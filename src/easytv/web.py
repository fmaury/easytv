"""Web remote: a page served to phones on the home network, to zap without the TV remote."""

import asyncio
import json
import logging
import socket
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib import resources

from easytv.remote import Action, Command

logger = logging.getLogger(__name__)

# Quitting from a phone would only make systemd restart the TV: not offered.
WEB_ACTIONS = frozenset(Action) - {Action.QUIT}

_MAX_BODY = 1024
_MAX_HEADERS = 50
_READ_TIMEOUT = 10.0
_REASONS = {
    200: "OK",
    202: "Accepted",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Content Too Large",
    415: "Unsupported Media Type",
    500: "Internal Server Error",
}


@dataclass(frozen=True)
class Status:
    channels: list[str]  # display names, in channel order
    current: int | None  # 1-based number of the current channel
    video: str | None  # title of the current video
    unavailable: bool  # no readable video on the current channel
    volume: int  # 0-100
    muted: bool


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = b""
    content_type: str = "application/json"


def parse_command(body: bytes) -> Command | None:
    """Turn a JSON body such as {"action": "goto", "number": 2} into a command."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("action"), str):
        return None
    try:
        action = Action(data["action"])
    except ValueError:
        return None
    if action not in WEB_ACTIONS:
        return None
    if action is not Action.GOTO:
        return Command(action)
    number = data.get("number")
    # bool is a subclass of int: reject it explicitly.
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        return None
    return Command(action, number)


def lan_address() -> str | None:
    """This machine's address on the local network, to print the page's URL."""
    try:
        # Connecting a UDP socket sends nothing: it only selects the outgoing interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))
            address: str = s.getsockname()[0]
            return address
    except OSError as e:
        logger.debug("no network address: %s", e)
        return None


class WebRemote:
    def __init__(self, status: Callable[[], Status], submit: Callable[[Command], None]) -> None:
        self._status = status
        self._submit = submit
        self._page = resources.files("easytv").joinpath("web.html").read_bytes()
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.Task[None]] = set()

    @property
    def port(self) -> int:
        assert self._server is not None
        port: int = self._server.sockets[0].getsockname()[1]
        return port

    async def start(self, port: int, host: str | None = None) -> None:
        """Listen on all interfaces by default. Port 0 picks a free port (tests)."""
        self._server = await asyncio.start_server(self._serve, host=host, port=port)
        address = lan_address() or "<adresse-de-la-pi>"
        logger.info("web remote: http://%s:%d", address, self.port)

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        # Browsers open connections in advance and may never use them: drop them now rather
        # than wait for their read timeout, so stopping the TV is never delayed.
        for client in self._clients:
            client.cancel()
        await asyncio.gather(*self._clients, return_exceptions=True)
        await self._server.wait_closed()

    def handle(self, method: str, path: str, body: bytes = b"", content_type: str = "") -> Response:
        match path.split("?", 1)[0]:
            case "/":
                if method != "GET":
                    return _error(405, "method not allowed")
                return Response(200, self._page, "text/html; charset=utf-8")
            case "/api/status":
                if method != "GET":
                    return _error(405, "method not allowed")
                return _json(200, asdict(self._status()))
            case "/api/command":
                if method != "POST":
                    return _error(405, "method not allowed")
                # Requiring JSON makes browsers ask permission (CORS preflight) before a POST
                # from another site, which this server never grants: other sites cannot zap.
                if content_type.split(";", 1)[0].strip().lower() != "application/json":
                    return _error(415, "expected application/json")
                command = parse_command(body)
                if command is None:
                    logger.warning("invalid web command: %r", body[:100])
                    return _error(400, "invalid command")
                logger.debug("web command: %s", command)
                self._submit(command)
                return _json(202, {"ok": True})
            case _:
                return _error(404, "not found")

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._clients.add(task)
        try:
            writer.write(_encode(await self._respond(reader)))
            await writer.drain()
        except ConnectionError as e:
            logger.debug("web client went away: %s", e)
        finally:
            self._clients.discard(task)
            writer.close()

    async def _respond(self, reader: asyncio.StreamReader) -> Response:
        try:
            request = await asyncio.wait_for(_read_request(reader), _READ_TIMEOUT)
        except (TimeoutError, asyncio.IncompleteReadError, ValueError) as e:
            logger.debug("bad HTTP request: %s", e)
            return _error(400, "bad request")
        if isinstance(request, Response):
            return request
        try:
            return self.handle(*request)
        except Exception:
            logger.exception("web request failed")
            return _error(500, "internal error")


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, str, bytes, str] | Response:
    """Read one HTTP/1.1 request: (method, path, body, content type), or an error response."""
    parts = (await reader.readline()).decode("latin-1").split()
    if len(parts) != 3:
        raise ValueError(f"malformed request line: {parts}")
    method, path, _ = parts
    length = 0
    content_type = ""
    for _ in range(_MAX_HEADERS):
        line = (await reader.readline()).decode("latin-1").strip()
        if not line:
            break
        name, _, value = line.partition(":")
        match name.strip().lower():
            case "content-length":
                length = int(value)
            case "content-type":
                content_type = value.strip()
    else:
        raise ValueError("too many headers")
    if length < 0:
        raise ValueError(f"negative content length: {length}")
    if length > _MAX_BODY:
        return _error(413, "body too large")
    return method, path, await reader.readexactly(length), content_type


def _json(status: int, data: object) -> Response:
    return Response(status, json.dumps(data, ensure_ascii=False).encode())


def _error(status: int, message: str) -> Response:
    return _json(status, {"error": message})


def _encode(response: Response) -> bytes:
    head = (
        f"HTTP/1.1 {response.status} {_REASONS.get(response.status, '')}\r\n"
        f"Content-Type: {response.content_type}\r\n"
        f"Content-Length: {len(response.body)}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    return head.encode("latin-1") + response.body
