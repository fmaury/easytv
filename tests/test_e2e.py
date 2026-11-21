"""End to end: a real EasyTV (real mpv, without picture or sound) driven like the phone page does.

Each command goes through HTTP → web server → App → mpv; its effect is checked on mpv itself,
through its IPC socket (`easytv.ctl`), and on /api/status.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from easytv.ctl import CtlError, MpvConnection, find_socket

TIMEOUT = 10.0


@dataclass
class Tv:
    port: int
    mpv: MpvConnection
    process: subprocess.Popen[bytes]

    def command(self, action: str, **extra: Any) -> None:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/command",
            data=json.dumps({"action": action, **extra}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            assert response.status == 202

    def status(self) -> dict[str, Any]:
        url = f"http://127.0.0.1:{self.port}/api/status"
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            data: dict[str, Any] = json.load(response)
            return data

    def get(self, name: str) -> Any:
        """An mpv property, or None while it is unavailable (e.g. `path` once stopped)."""
        try:
            return self.mpv.command("get_property", name)
        except CtlError:
            return None

    def playing(self) -> str | None:
        """'<channel folder>/<video file>' as mpv plays it."""
        path = self.get("path")
        return None if path is None else "/".join(Path(path).parts[-2:])


def wait_until(probe: Callable[[], object], expected: object) -> None:
    """Commands are queued, not applied before the HTTP reply: poll until they take effect."""
    deadline = time.monotonic() + TIMEOUT
    while (value := probe()) != expected:
        if time.monotonic() > deadline:
            pytest.fail(f"expected {expected!r}, still {value!r}")
        time.sleep(0.05)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture(scope="module")
def channels(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two channels of two clips, long enough not to end during the test."""
    root = tmp_path_factory.mktemp("channels")
    clip = root / "clip.mp4"
    source = ["-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=120"]
    encode = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    subprocess.run(["ffmpeg", "-loglevel", "error", *source, *encode, str(clip)], check=True)
    for channel in ["01 - Alpha", "02 - Beta"]:
        (root / channel).mkdir()
        for video in ["ep1.mp4", "ep2.mp4"]:
            shutil.copy(clip, root / channel / video)
    clip.unlink()
    return root


@pytest.fixture
def tv(channels: Path, tmp_path: Path) -> Iterator[Tv]:
    port = free_port()
    config = tmp_path / "config.toml"
    config.write_text(
        f"""
channels_dir = "{channels}"
input = "remote"
state_file = "{tmp_path / "state.json"}"
web_port = {port}
mpv_args = ["--vo=null", "--ao=null", "--force-window=no"]
"""
    )
    # TMPDIR: mpv's socket lands in tmp_path, so find_socket cannot pick another EasyTV's.
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    log = (tmp_path / "easytv.log").open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "easytv", "--config", str(config)],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    mpv: MpvConnection | None = None
    try:
        tv = Tv(port, _connect(tmp_path, process), process)
        mpv = tv.mpv
        wait_until(lambda: _status_or_none(tv, "current"), 1)
        yield tv
    finally:
        if mpv is not None:
            mpv.close()
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        log.close()
        sys.stdout.write((tmp_path / "easytv.log").read_text())  # shown by pytest on failure


def _connect(tmp_path: Path, process: subprocess.Popen[bytes]) -> MpvConnection:
    deadline = time.monotonic() + TIMEOUT
    while True:
        try:
            return MpvConnection(find_socket(tmp_path))
        except CtlError:
            if process.poll() is not None or time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def _status_or_none(tv: Tv, key: str) -> Any:
    try:
        return tv.status()[key]
    except OSError:  # web server not listening yet
        return None


def test_starts_on_the_first_channel(tv: Tv) -> None:
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    status = tv.status()
    assert status["channels"] == ["Alpha", "Beta"]
    assert (status["current"], status["video"], status["stopped"]) == (1, "ep1", False)


def test_channel_buttons(tv: Tv) -> None:
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    tv.command("next_channel")
    wait_until(tv.playing, "02 - Beta/ep1.mp4")
    assert tv.status()["current"] == 2
    tv.command("prev_channel")
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    tv.command("prev_channel")  # wraps around to the last channel
    wait_until(tv.playing, "02 - Beta/ep1.mp4")


def test_goto_from_the_channel_list(tv: Tv) -> None:
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    tv.command("goto", number=2)
    wait_until(tv.playing, "02 - Beta/ep1.mp4")
    tv.command("goto", number=1)
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")


def test_video_buttons(tv: Tv) -> None:
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    tv.command("next_video")
    wait_until(tv.playing, "01 - Alpha/ep2.mp4")
    assert tv.status()["video"] == "ep2"
    tv.command("prev_video")
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")


def test_volume_buttons(tv: Tv) -> None:
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    start = tv.status()["volume"]
    tv.command("volume_down")
    wait_until(lambda: tv.get("volume"), start - 5)
    assert tv.status()["volume"] == start - 5
    tv.command("volume_up")
    wait_until(lambda: tv.get("volume"), start)


def test_mute_button(tv: Tv) -> None:
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    tv.command("mute")
    wait_until(lambda: tv.get("mute"), True)
    assert tv.status()["muted"] is True
    tv.command("mute")
    wait_until(lambda: tv.get("mute"), False)


def test_power_button(tv: Tv) -> None:
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    tv.command("stop")
    wait_until(tv.playing, None)
    assert tv.status()["stopped"] is True
    tv.command("play")
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    assert tv.status()["stopped"] is False


def test_info_button_keeps_playing(tv: Tv) -> None:
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    tv.command("info")
    time.sleep(0.3)
    assert tv.playing() == "01 - Alpha/ep1.mp4"


def test_stops_cleanly(tv: Tv) -> None:
    wait_until(tv.playing, "01 - Alpha/ep1.mp4")
    tv.process.send_signal(signal.SIGTERM)
    assert tv.process.wait(timeout=TIMEOUT) == 0
