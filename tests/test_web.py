import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from importlib import resources

import pytest

from easytv.remote import Action, Command
from easytv.web import WEB_ACTIONS, Response, Status, WebRemote, parse_command

STATUS = Status(
    channels=["Cartoons", "Docs"],
    current=2,
    video="doc1",
    unavailable=False,
    volume=60,
    muted=False,
    stopped=False,
)
JSON = "application/json"


@pytest.fixture
def submitted() -> list[Command]:
    return []


@pytest.fixture
def web(submitted: list[Command]) -> WebRemote:
    return WebRemote(lambda: STATUS, submitted.append)


def body(response: Response) -> object:
    return json.loads(response.body)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"action": "next_channel"}, Command(Action.NEXT_CHANNEL)),
        ({"action": "prev_channel"}, Command(Action.PREV_CHANNEL)),
        ({"action": "next_video"}, Command(Action.NEXT_VIDEO)),
        ({"action": "prev_video"}, Command(Action.PREV_VIDEO)),
        ({"action": "info"}, Command(Action.INFO)),
        ({"action": "volume_up"}, Command(Action.VOLUME_UP)),
        ({"action": "volume_down"}, Command(Action.VOLUME_DOWN)),
        ({"action": "mute"}, Command(Action.MUTE)),
        ({"action": "stop"}, Command(Action.STOP)),
        ({"action": "play"}, Command(Action.PLAY)),
        ({"action": "goto", "number": 3}, Command(Action.GOTO, 3)),
    ],
)
def test_parse_valid_command(data: object, expected: Command) -> None:
    assert parse_command(json.dumps(data).encode()) == expected


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{oops",
        b"\xff\xfe",
        b"[]",
        b'"next_channel"',
        b"{}",
        b'{"action": "quit"}',
        b'{"action": "explode"}',
        b'{"action": null}',
        b'{"action": "goto"}',
        b'{"action": "goto", "number": 0}',
        b'{"action": "goto", "number": "2"}',
        b'{"action": "goto", "number": 2.5}',
        b'{"action": "goto", "number": true}',
    ],
)
def test_parse_invalid_command(raw: bytes) -> None:
    assert parse_command(raw) is None


def test_quit_is_the_only_action_not_offered() -> None:
    assert set(Action) - WEB_ACTIONS == {Action.QUIT}


def test_page_offers_every_action_with_known_names() -> None:
    """A typo in a button's action would make it silently do nothing."""
    page = resources.files("easytv").joinpath("web.html").read_text()
    buttons = set(re.findall(r'data-action="(\w+)"', page))
    # The power button toggles between stop and play; the channel list sends goto.
    power = re.search(r'power\.dataset\.action = status\.stopped \? "(\w+)" : "(\w+)"', page)
    goto = re.search(r'send\(\{ action: "(\w+)", number \}\)', page)
    assert power is not None and goto is not None
    offered = buttons | set(power.groups()) | {goto[1]}
    assert offered == {action.value for action in WEB_ACTIONS}


def test_page(web: WebRemote) -> None:
    response = web.handle("GET", "/")
    assert response.status == 200
    assert response.content_type.startswith("text/html")
    assert b"<title>EasyTV</title>" in response.body


def test_status(web: WebRemote) -> None:
    response = web.handle("GET", "/api/status?t=1")
    assert response.status == 200
    assert body(response) == {
        "channels": ["Cartoons", "Docs"],
        "current": 2,
        "video": "doc1",
        "unavailable": False,
        "volume": 60,
        "muted": False,
        "stopped": False,
        "position": None,
        "duration": None,
        "sleep_text": None,
    }


def test_command_is_submitted(web: WebRemote, submitted: list[Command]) -> None:
    response = web.handle("POST", "/api/command", b'{"action": "goto", "number": 1}', JSON)
    assert response.status == 202
    assert submitted == [Command(Action.GOTO, 1)]


def test_command_accepts_json_with_charset(web: WebRemote, submitted: list[Command]) -> None:
    content_type = "application/json; charset=utf-8"
    response = web.handle("POST", "/api/command", b'{"action": "info"}', content_type)
    assert response.status == 202
    assert submitted == [Command(Action.INFO)]


def test_invalid_command_is_rejected(web: WebRemote, submitted: list[Command]) -> None:
    response = web.handle("POST", "/api/command", b'{"action": "quit"}', JSON)
    assert response.status == 400
    assert submitted == []


def test_command_without_json_content_type_is_rejected(
    web: WebRemote, submitted: list[Command]
) -> None:
    # What a form or a "simple" cross-site request from another web page would send.
    response = web.handle("POST", "/api/command", b'{"action": "info"}', "text/plain")
    assert response.status == 415
    assert submitted == []


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("POST", "/", 405),
        ("POST", "/api/status", 405),
        ("GET", "/api/command", 405),
        ("GET", "/nope", 404),
        ("GET", "/../etc/passwd", 404),
    ],
)
def test_routing_errors(web: WebRemote, method: str, path: str, status: int) -> None:
    assert web.handle(method, path).status == status


def serve(web: WebRemote, scenario: Callable[[int], Awaitable[None]]) -> None:
    async def main() -> None:
        await web.start(0, host="127.0.0.1")
        try:
            await scenario(web.port)
        finally:
            await web.close()

    asyncio.run(main())


async def exchange(port: int, request: bytes) -> tuple[str, bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    response = await asyncio.wait_for(reader.read(), timeout=5)
    writer.close()
    await writer.wait_closed()
    head, _, payload = response.partition(b"\r\n\r\n")
    return head.decode("latin-1").split("\r\n")[0], payload


def test_http_server(web: WebRemote, submitted: list[Command]) -> None:
    async def scenario(port: int) -> None:
        line, payload = await exchange(port, b"GET /api/status HTTP/1.1\r\nHost: tv\r\n\r\n")
        assert line == "HTTP/1.1 200 OK"
        assert json.loads(payload)["current"] == 2

        command = b'{"action":"next_channel"}'
        line, _ = await exchange(
            port,
            b"POST /api/command HTTP/1.1\r\nHost: tv\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(command)}\r\n\r\n".encode()
            + command,
        )
        assert line == "HTTP/1.1 202 Accepted"

        line, _ = await exchange(port, b"GET / HTTP/1.1\r\n\r\n")
        assert line == "HTTP/1.1 200 OK"

    serve(web, scenario)
    assert submitted == [Command(Action.NEXT_CHANNEL)]


@pytest.mark.parametrize(
    ("request_bytes", "status_line"),
    [
        (b"garbage\r\n\r\n", "HTTP/1.1 400 Bad Request"),
        (b"", "HTTP/1.1 400 Bad Request"),
        (b"POST /api/command HTTP/1.1\r\nContent-Length: abc\r\n\r\n", "HTTP/1.1 400 Bad Request"),
        (b"POST /api/command HTTP/1.1\r\nContent-Length: -5\r\n\r\n", "HTTP/1.1 400 Bad Request"),
        (
            b"POST /api/command HTTP/1.1\r\nContent-Length: 999999\r\n\r\n",
            "HTTP/1.1 413 Content Too Large",
        ),
        (
            b"GET / HTTP/1.1\r\n" + b"X-Header: 1\r\n" * 100 + b"\r\n",
            "HTTP/1.1 400 Bad Request",
        ),
    ],
)
def test_http_server_rejects_bad_requests(
    web: WebRemote, submitted: list[Command], request_bytes: bytes, status_line: str
) -> None:
    async def scenario(port: int) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(request_bytes)
        writer.write_eof()
        response = await asyncio.wait_for(reader.read(), timeout=5)
        writer.close()
        await writer.wait_closed()
        assert response.decode("latin-1").split("\r\n")[0] == status_line

    serve(web, scenario)
    assert submitted == []


def test_http_server_survives_a_failing_handler(submitted: list[Command]) -> None:
    def broken_status() -> Status:
        raise RuntimeError("bug")

    web = WebRemote(broken_status, submitted.append)

    async def scenario(port: int) -> None:
        line, _ = await exchange(port, b"GET /api/status HTTP/1.1\r\n\r\n")
        assert line == "HTTP/1.1 500 Internal Server Error"
        line, _ = await exchange(port, b"GET / HTTP/1.1\r\n\r\n")
        assert line == "HTTP/1.1 200 OK"

    serve(web, scenario)


def test_close_does_not_wait_for_idle_connections(web: WebRemote) -> None:
    async def main() -> None:
        await web.start(0, host="127.0.0.1")
        # A browser's speculative connection: opened, nothing sent.
        _, writer = await asyncio.open_connection("127.0.0.1", web.port)
        await asyncio.sleep(0.1)
        loop = asyncio.get_running_loop()
        started = loop.time()
        await asyncio.wait_for(web.close(), timeout=2)
        assert loop.time() - started < 1
        writer.close()

    asyncio.run(main())
