import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from easytv.app import NO_CHANNEL_TEXT, App
from easytv.config import Config
from easytv.player import Closed, EndOfFile, Message, PlayerEvent, VideoError
from easytv.state import ChannelState, TvState, load_state, save_state

T0 = 1_000_000.0


@dataclass
class FakePlayer:
    events: asyncio.Queue[PlayerEvent] = field(default_factory=asyncio.Queue)
    position: float | None = None
    played: list[tuple[str, float]] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    stopped: int = 0

    async def play(self, path: Path, start: float) -> None:
        self.played.append((f"{path.parent.name}/{path.name}", start))
        self.position = None

    async def show_text(self, text: str, seconds: float) -> None:
        self.texts.append(text)

    async def stop(self) -> None:
        self.stopped += 1
        self.position = None


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


@dataclass
class Env:
    root: Path
    config: Config
    player: FakePlayer
    clock: Clock

    def make(self, *files: str) -> None:
        for name in files:
            path = self.root / "tv" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def state(self) -> TvState:
        return load_state(self.config.state_file)

    async def send(self, event: PlayerEvent) -> None:
        await self.player.events.put(event)
        for _ in range(10):  # let the app process the event
            await asyncio.sleep(0)

    def run(self, scenario: Callable[[App], Awaitable[None]]) -> None:
        async def main() -> None:
            app = App(self.config, self.player, self.clock)
            task = asyncio.create_task(app.run())
            await asyncio.sleep(0)
            await scenario(app)
            await self.send(Message(("easytv", "quit")))
            await asyncio.wait_for(task, timeout=2)

        asyncio.run(main())


@pytest.fixture
def env(tmp_path: Path) -> Env:
    config = Config(
        channels_dir=tmp_path / "tv",
        state_file=tmp_path / "state.json",
        save_interval=1000,  # timers are triggered by hand in tests
        rescan_interval=1000,
    )
    e = Env(tmp_path, config, FakePlayer(), Clock())
    e.make("1 - Cartoons/ep1.mp4", "1 - Cartoons/ep2.mp4", "2 - Docs/doc1.mp4")
    return e


def test_start_plays_first_channel_with_banner(env: Env) -> None:
    async def scenario(app: App) -> None:
        pass

    env.run(scenario)
    assert env.player.played == [("1 - Cartoons/ep1.mp4", 0.0)]
    assert env.player.texts == ["1. 1 - Cartoons\nep1.mp4"]


def test_zap_saves_exact_position_and_resumes_later(env: Env) -> None:
    async def scenario(app: App) -> None:
        env.player.position = 42.0
        env.clock.now += 42
        await env.send(Message(("easytv", "next_channel")))
        assert env.state().channels["1 - Cartoons"] == ChannelState("ep1.mp4", 42.0, T0 + 42)
        env.clock.now += 600
        await env.send(Message(("easytv", "prev_channel")))

    env.run(scenario)
    assert env.player.played == [
        ("1 - Cartoons/ep1.mp4", 0.0),
        ("2 - Docs/doc1.mp4", 0.0),
        ("1 - Cartoons/ep1.mp4", 42.0),
    ]


def test_goto_and_unknown_messages(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "goto", "2")))
        await env.send(Message(("easytv", "goto", "9")))
        await env.send(Message(("other", "thing")))

    env.run(scenario)
    assert [p for p, _ in env.player.played] == ["1 - Cartoons/ep1.mp4", "2 - Docs/doc1.mp4"]


def test_end_of_file_and_error_play_next_video(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(EndOfFile())
        await env.send(VideoError("broken"))

    env.run(scenario)
    assert [p for p, _ in env.player.played] == [
        "1 - Cartoons/ep1.mp4",
        "1 - Cartoons/ep2.mp4",
        "1 - Cartoons/ep1.mp4",
    ]


def test_quit_saves_state_and_restart_resumes(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "goto", "2")))
        env.player.position = 30.0
        env.clock.now += 30

    env.run(scenario)
    assert env.state().current_channel == "2 - Docs"

    env.player = FakePlayer()
    env.clock.now += 300

    async def after_restart(app: App) -> None:
        pass

    env.run(after_restart)
    assert env.player.played == [("2 - Docs/doc1.mp4", 30.0)]


def test_closed_player_stops_the_app(env: Env) -> None:
    async def main() -> None:
        app = App(env.config, env.player, env.clock)
        await env.player.events.put(Closed())
        await asyncio.wait_for(app.run(), timeout=2)

    asyncio.run(main())
    assert env.state().current_channel == "1 - Cartoons"


def test_rescan_switches_when_current_video_is_deleted(env: Env) -> None:
    async def scenario(app: App) -> None:
        (env.root / "tv" / "1 - Cartoons" / "ep1.mp4").unlink()
        await app.rescan()

    env.run(scenario)
    assert [p for p, _ in env.player.played] == ["1 - Cartoons/ep1.mp4", "1 - Cartoons/ep2.mp4"]


def test_no_channels(env: Env, tmp_path: Path) -> None:
    env.config = Config(channels_dir=tmp_path / "empty", state_file=tmp_path / "s.json")

    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "next_channel")))

    env.run(scenario)
    assert env.player.played == []
    assert env.player.stopped >= 1
    assert env.player.texts[0] == NO_CHANNEL_TEXT


def test_corrupted_state_does_not_prevent_start(env: Env) -> None:
    save_state(env.config.state_file, TvState(current_channel="2 - Docs"))
    env.config.state_file.write_text("{oops", encoding="utf-8")

    async def scenario(app: App) -> None:
        pass

    env.run(scenario)
    assert env.player.played == [("1 - Cartoons/ep1.mp4", 0.0)]
