import asyncio
import logging
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import pytest

from easytv.banner import channel_banner, message_banner, volume_banner
from easytv.player import EndOfFile, Layer, Message, MpvPlayer, PlayerEvent, VideoError

pytestmark = pytest.mark.skipif(
    shutil.which("mpv") is None or shutil.which("ffmpeg") is None,
    reason="integration tests need mpv and ffmpeg",
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


@pytest.mark.skipif(not ALSA_CONFIG.exists(), reason="needs ALSA")
def test_sound_comes_back_after_the_audio_output_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Like an unplugged HDMI cable: the ALSA device is missing when the video starts.
    clip = tmp_path / "with-sound.mp4"
    source = ["-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=4"]
    sound = ["-f", "lavfi", "-i", "sine=duration=4"]
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
        await player.check_audio()  # still missing: nothing breaks
        extra.write_text("pcm.easytv_test { type null }\n", encoding="utf-8")  # plugged back
        await player.check_audio()
        while player.audio_output is None:
            await asyncio.sleep(0.05)
        # The video played: it must not be reported as unreadable.
        assert await next_event(player) == EndOfFile()

    run(scenario, audio=["--ao=alsa", "--audio-device=alsa/easytv_test"])
    assert "Could not open/initialize audio device" in caplog.text
    assert "sound is back" in caplog.text
