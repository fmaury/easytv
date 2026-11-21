import asyncio
import logging
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from easytv.banner import channel_banner, message_banner, volume_banner
from easytv.config import SNOW_MAX_SECONDS
from easytv.player import (
    COMMAND_TIMEOUT,
    CONNECT_TIMEOUT,
    SNOW,
    EndOfFile,
    Layer,
    Message,
    MpvError,
    MpvPlayer,
    PlayerEvent,
    VideoError,
)


@pytest.fixture(scope="module")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("videos") / "clip.mp4"
    source = ["-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=3"]
    encode = ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    subprocess.run(["ffmpeg", "-loglevel", "error", *source, *encode, str(path)], check=True)
    return path


def run(
    scenario: Callable[[MpvPlayer], Awaitable[None]], audio: Sequence[str] = ("--ao=null",)
) -> None:
    async def main() -> None:
        player = MpvPlayer(keyboard=False, extra_args=["--vo=null", *audio, "--force-window=no"])
        await player.start()
        try:
            await asyncio.wait_for(scenario(player), timeout=15)
        finally:
            await player.close()

    asyncio.run(main())


async def next_event(player: MpvPlayer) -> PlayerEvent:
    return await asyncio.wait_for(player.events.get(), timeout=10)


async def wait_position(player: MpvPlayer, at_least: float) -> float:
    while (position := player.position) is None or position < at_least:
        await asyncio.sleep(0.05)
    return position


def test_play_from_start_position_until_end(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.play(video, start=1.5)
        assert await wait_position(player, 1.5) < 2.5
        assert await next_event(player) == EndOfFile()

    run(scenario)


def test_replacing_a_video_does_not_report_end_of_file(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.play(video, start=0)
        await wait_position(player, 0.2)
        await player.play(video, start=2.0)
        assert await wait_position(player, 0) >= 2.0
        assert await next_event(player) == EndOfFile()
        assert player.events.empty()

    run(scenario)


def test_script_messages_are_forwarded(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.send_message("easytv", "goto", "2")
        assert await next_event(player) == Message(("easytv", "goto", "2"))
        await player.show_banner(channel_banner(1, "01 - Test", "a.mp4"), 0.1)
        await player.show_banner(message_banner("Aucune chaîne"), None)
        await player.stop()

    run(scenario)


def test_has_started_once_the_video_really_plays(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.play(video, start=0)
        assert not player.has_started
        await wait_position(player, 1.0)
        assert player.has_started

    run(scenario)


def test_duration_of_the_current_video(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.play(video, start=0)
        while player.duration is None:
            await asyncio.sleep(0.05)
        assert abs(player.duration - 3.0) < 0.1
        await player.stop()
        assert player.duration is None

    run(scenario)


def test_unreadable_file_never_starts(tmp_path: Path) -> None:
    fake = tmp_path / "fake.mp4"
    fake.write_text("this is not a video", encoding="utf-8")

    async def scenario(player: MpvPlayer) -> None:
        await player.play(fake, start=0)
        event = await next_event(player)
        assert isinstance(event, VideoError | EndOfFile)
        assert not player.has_started

    run(scenario)


def test_banner_removal_is_accepted_by_mpv(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.show_banner(message_banner("hello"), None)
        await player._overlay(None)  # raises MpvError if mpv rejects the removal

    run(scenario)


def test_volume_is_accepted_by_mpv(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.set_volume(35, muted=True)
        assert await player._command("get_property", "volume") == 35
        assert await player._command("get_property", "mute") is True

    run(scenario)


def test_volume_gauge_and_banner_use_separate_layers(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.show_banner(message_banner("hello"), None)
        await player.show_banner(volume_banner(50, muted=False), 0.1, Layer.VOLUME)
        await asyncio.sleep(0.3)  # the gauge is removed, the banner stays
        await player._overlay(None, Layer.BANNER)

    run(scenario)


ALSA_CONFIG = Path("/usr/share/alsa/alsa.conf")


def test_sound_comes_back_after_the_audio_output_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Like an unplugged HDMI cable: the ALSA device is missing when the video starts.
    clip = tmp_path / "with-sound.mp4"
    source = ["-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=5"]
    sound = ["-f", "lavfi", "-i", "sine=duration=5"]
    encode = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", *source, *sound, *encode, str(clip)], check=True
    )
    extra = tmp_path / "asound.conf"
    extra.write_text("", encoding="utf-8")
    monkeypatch.setenv("ALSA_CONFIG_PATH", f"{ALSA_CONFIG}:{extra}")
    caplog.set_level(logging.INFO, logger="easytv.player")

    async def scenario(player: MpvPlayer) -> None:
        await player.play(clip, start=0)
        await wait_position(player, 1.0)
        assert player.audio_output is None
        await player.check_audio()  # still missing: mpv now deselects the audio track
        await asyncio.sleep(0.5)
        extra.write_text("pcm.easytv_test { type null }\n", encoding="utf-8")  # plugged back
        await player.check_audio()
        while player.audio_output is None:
            await asyncio.sleep(0.05)
        # The video played: it must not be reported as unreadable.
        assert await next_event(player) == EndOfFile()

    run(scenario, audio=["--ao=alsa", "--audio-device=alsa/easytv_test"])
    assert "Could not open/initialize audio device" in caplog.text
    assert "sound is back" in caplog.text


# An mpv that opens its IPC socket but never answers, except to quit.
SILENT_MPV = """\
import socket, sys
path = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--input-ipc-server="))
server = socket.socket(socket.AF_UNIX)
server.bind(path)
server.listen()
connection, _ = server.accept()
for line in connection.makefile("rb"):
    if b'"quit"' in line:
        break
"""


def fake_mpv(tmp_path: Path, body: str) -> str:
    script = tmp_path / "mpv"
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def slow_mpv(tmp_path: Path, delay: float) -> str:
    real = shutil.which("mpv")
    assert real is not None
    return fake_mpv(tmp_path, f'#!/bin/sh\nsleep {delay}\nexec {real} "$@"\n')


def test_default_timeouts_leave_room_for_a_busy_pi() -> None:
    # Measured on a Pi 3 (2026-11-21): no IPC socket after 5 s at boot, mpv silent for ~10 s
    # while the desktop handed the screen over; both crashed the TV with 5 s timeouts.
    assert CONNECT_TIMEOUT >= 30
    assert COMMAND_TIMEOUT >= 20


def test_waits_for_an_mpv_that_is_slow_to_start(tmp_path: Path) -> None:
    async def main() -> None:
        player = MpvPlayer(
            keyboard=False,
            extra_args=["--vo=null", "--ao=null", "--force-window=no"],
            mpv=slow_mpv(tmp_path, 1.0),
            connect_timeout=5,
        )
        try:
            await player.start()
            await player.set_volume(50, muted=False)
        finally:
            await player.close()

    asyncio.run(main())


def test_an_mpv_too_slow_to_start_is_a_clean_error(tmp_path: Path) -> None:
    async def main() -> None:
        player = MpvPlayer(
            keyboard=False,
            extra_args=["--vo=null", "--ao=null", "--force-window=no"],
            mpv=slow_mpv(tmp_path, 2.0),
            connect_timeout=0.3,
        )
        try:
            with pytest.raises(MpvError, match="IPC socket"):
                await player.start()
        finally:
            await player.close()

    asyncio.run(main())


def test_an_mpv_that_does_not_answer_is_a_clean_error(tmp_path: Path) -> None:
    async def main() -> None:
        player = MpvPlayer(
            keyboard=False,
            mpv=fake_mpv(tmp_path, f"#!{sys.executable}\n{SILENT_MPV}"),
            command_timeout=0.3,
        )
        try:
            # A TimeoutError would escape as a traceback; an MpvError is logged in one line.
            with pytest.raises(MpvError, match="did not answer"):
                await player.start()
        finally:
            await player.close()

    asyncio.run(main())


# --- Snow --------------------------------------------------------------------


async def mpv_path(player: MpvPlayer) -> str | None:
    try:
        path = await player._command("get_property", "path")
    except MpvError:  # nothing loaded
        return None
    return str(path)


async def wait_path(player: MpvPlayer, expected: Path) -> None:
    while await mpv_path(player) != str(expected):
        await asyncio.sleep(0.05)


def test_snow_clip_is_short_h264_with_sound() -> None:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name:format=duration",
            "-of",
            "default=noprint_wrappers=1",
            str(SNOW),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "codec_name=h264" in probe  # decoded in hardware on the Pi
    assert "codec_name=aac" in probe
    duration = float(probe.split("duration=")[1].split()[0])
    assert duration >= SNOW_MAX_SECONDS  # cut by mpv at snow_seconds


def test_snow_then_the_video_from_its_start_position(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.play(video, start=1.0, snow=True)
        assert await mpv_path(player) == str(SNOW)
        # While it snows, nothing is reported about the video to come.
        assert player.position is None
        assert not player.has_started
        await wait_path(player, video)
        assert await wait_position(player, 1.0) >= 1.0
        assert player.events.empty()  # the end of the snow is not an end of video

    run(scenario)


def test_zapping_again_during_the_snow_plays_only_the_last_channel(
    video: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other.mp4"
    other.write_bytes(video.read_bytes())

    async def scenario(player: MpvPlayer) -> None:
        await player.play(other, start=0, snow=True)
        await asyncio.sleep(0.3)
        await player.play(video, start=0, snow=True)
        await wait_path(player, video)
        await asyncio.sleep(1.0)
        assert await mpv_path(player) == str(video)

    run(scenario)


def test_stop_during_the_snow_plays_nothing(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.play(video, start=0, snow=True)
        await player.stop()
        await asyncio.sleep(1.5)  # longer than the snow
        assert await mpv_path(player) is None

    run(scenario)


def run_with(scenario: Callable[[MpvPlayer], Awaitable[None]], **options: Any) -> None:
    async def main() -> None:
        player = MpvPlayer(
            keyboard=False, extra_args=["--vo=null", "--ao=null", "--force-window=no"], **options
        )
        await player.start()
        try:
            await asyncio.wait_for(scenario(player), timeout=15)
        finally:
            await player.close()

    asyncio.run(main())


def test_snow_is_cut_at_its_duration_and_the_video_is_not(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        loop = asyncio.get_running_loop()
        began = loop.time()
        await player.play(video, start=0, snow=True)
        await wait_path(player, video)
        assert loop.time() - began < 1.5  # the clip lasts 2.2 s
        assert await wait_position(player, 1.0) >= 1.0  # no cut left on the video

    run_with(scenario, snow_seconds=0.3)


async def audio_filters(player: MpvPlayer) -> list[str]:
    filters = await player._command("get_property", "af")
    return [str(f.get("label")) for f in filters]


def test_snow_volume_applies_to_the_snow_only(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.play(video, start=0, snow=True)
        assert await audio_filters(player) == ["easytv-snow"]
        await wait_path(player, video)
        assert await audio_filters(player) == []

    run_with(scenario, snow_seconds=0.3, snow_volume=40)


def test_full_snow_volume_adds_no_filter(video: Path) -> None:
    async def scenario(player: MpvPlayer) -> None:
        await player.play(video, start=0, snow=True)
        assert await audio_filters(player) == []

    run_with(scenario)
