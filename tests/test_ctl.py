import json
import os
import socketserver
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from easytv.ctl import TIMEOUT, CtlError, MpvConnection, find_socket, main

PROPERTIES: dict[str, Any] = {"path": "/media/tv/Pingu/01 - Pingu.avi", "time-pos": 12.5}


class FakeMpv(socketserver.StreamRequestHandler):
    """Answers like mpv, with an event sent before each reply."""

    received: list[list[str]]

    def handle(self) -> None:
        for line in self.rfile:
            request = json.loads(line)
            command = request["command"]
            self.received.append(command)
            self._send({"event": "property-change", "name": "time-pos"})
            reply: dict[str, Any] = {"request_id": request["request_id"]}
            if command[0] == "get_property" and command[1] in PROPERTIES:
                reply |= {"error": "success", "data": PROPERTIES[command[1]]}
            elif command[0] == "get_property":
                reply["error"] = "property unavailable"
            else:
                reply["error"] = "success"
            self._send(reply)

    def _send(self, message: dict[str, Any]) -> None:
        self.wfile.write(json.dumps(message).encode() + b"\n")


@pytest.fixture
def mpv(tmp_path: Path) -> Iterator[tuple[Path, list[list[str]]]]:
    path = tmp_path / "easytv-abc" / "mpv.sock"
    path.parent.mkdir()
    received: list[list[str]] = []
    handler = type("Handler", (FakeMpv,), {"received": received})
    with socketserver.ThreadingUnixStreamServer(str(path), handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield path, received
        server.shutdown()


def test_get_prints_properties_and_skips_events(
    mpv: tuple[Path, list[list[str]]], capsys: pytest.CaptureFixture[str]
) -> None:
    path, _ = mpv
    assert main(["--socket", str(path), "get", "path", "time-pos"]) == 0
    assert capsys.readouterr().out == "path=/media/tv/Pingu/01 - Pingu.avi\ntime-pos=12.5\n"


def test_get_unavailable_property_fails_but_prints_the_others(
    mpv: tuple[Path, list[list[str]]], capsys: pytest.CaptureFixture[str]
) -> None:
    path, _ = mpv
    assert main(["--socket", str(path), "get", "hwdec-current", "path"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "hwdec-current=<get_property hwdec-current: property unavailable>"
    assert out[1] == "path=/media/tv/Pingu/01 - Pingu.avi"


def test_cmd_sends_the_command(mpv: tuple[Path, list[list[str]]]) -> None:
    path, received = mpv
    assert main(["--socket", str(path), "cmd", "script-message", "easytv", "quit"]) == 0
    assert received == [["disable_event", "all"], ["script-message", "easytv", "quit"]]


def test_no_socket_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--socket", str(tmp_path / "missing.sock"), "get", "path"]) == 1
    assert "cannot connect" in capsys.readouterr().err


def test_find_socket_picks_the_newest(tmp_path: Path) -> None:
    with pytest.raises(CtlError):
        find_socket(tmp_path)
    for name, mtime in [("easytv-old", 1000), ("easytv-new", 2000), ("easytv-mid", 1500)]:
        sock = tmp_path / name / "mpv.sock"
        sock.parent.mkdir()
        sock.touch()
        os.utime(sock, (mtime, mtime))
    assert find_socket(tmp_path) == tmp_path / "easytv-new" / "mpv.sock"


class SlowMpv(socketserver.StreamRequestHandler):
    """Answers after a delay, like mpv writing a screenshot on a Pi 3."""

    delay = 0.5

    def handle(self) -> None:
        for line in self.rfile:
            time.sleep(self.delay)
            reply = {"request_id": json.loads(line)["request_id"], "error": "success"}
            self.wfile.write(json.dumps(reply).encode() + b"\n")


@pytest.fixture
def slow_mpv(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "mpv.sock"
    with socketserver.ThreadingUnixStreamServer(str(path), SlowMpv) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield path
        server.shutdown()


def test_default_timeout_leaves_room_for_a_screenshot_on_the_pi() -> None:
    # A 1080p PNG screenshot took more than 5 s on a Pi 3 (2026-11-21): ctl gave up meanwhile.
    assert TIMEOUT >= 20


def test_waits_for_a_slow_answer(slow_mpv: Path) -> None:
    assert main(["--socket", str(slow_mpv), "cmd", "screenshot-to-file", "/tmp/x.jpg"]) == 0


def test_an_answer_slower_than_the_timeout_is_an_error(slow_mpv: Path) -> None:
    with pytest.raises(CtlError, match="timed out"):
        MpvConnection(slow_mpv, timeout=0.1)
