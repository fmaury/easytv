import asyncio
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from easytv.player import EndOfFile, Message, MpvPlayer, PlayerEvent

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


def run(scenario: Callable[[MpvPlayer], Awaitable[None]]) -> None:
    async def main() -> None:
        player = MpvPlayer(
            keyboard=False, extra_args=["--vo=null", "--ao=null", "--force-window=no"]
        )
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
        await player.show_text("hello", 1)
        await player.stop()

    run(scenario)
