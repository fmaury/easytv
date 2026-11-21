import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, time
from pathlib import Path

import pytest

from easytv.app import NO_CHANNEL_TEXT, UNAVAILABLE_TEXT, App, StopReason
from easytv.banner import (
    BEDTIME_SUBTITLE,
    BEDTIME_TITLE,
    message_banner,
    sleep_screen,
    volume_banner,
)
from easytv.config import Config
from easytv.player import Closed, EndOfFile, Layer, Message, PlayerEvent, VideoError
from easytv.remote import Action, Command
from easytv.state import ChannelState, TvState, load_state, save_state
from easytv.web import Status

T0 = 1_000_000.0


@dataclass
class FakePlayer:
    events: asyncio.Queue[PlayerEvent] = field(default_factory=asyncio.Queue)
    position: float | None = None
    duration: float | None = None
    played: list[tuple[str, float]] = field(default_factory=list)
    banners: list[str] = field(default_factory=list)
    volume_banners: list[str] = field(default_factory=list)
    volume: tuple[int, bool] | None = None
    stopped: int = 0
    broken: set[str] = field(default_factory=set)  # file names that will not play
    has_started: bool = False
    snowed: list[str] = field(default_factory=list)  # videos played after the snow

    async def play(self, path: Path, start: float, *, snow: bool = False) -> None:
        self.played.append((f"{path.parent.name}/{path.name}", start))
        if snow:
            self.snowed.append(f"{path.parent.name}/{path.name}")
        self.position = None
        self.has_started = path.name not in self.broken

    async def show_banner(
        self, ass: str, seconds: float | None, layer: Layer = Layer.BANNER
    ) -> None:
        (self.banners if layer is Layer.BANNER else self.volume_banners).append(ass)

    async def set_volume(self, volume: int, muted: bool) -> None:
        self.volume = (volume, muted)

    async def check_audio(self) -> None:
        pass

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

    def run(self, scenario: Callable[[App], Awaitable[None]]) -> StopReason:
        async def main() -> StopReason:
            app = App(self.config, self.player, self.clock)
            task = asyncio.create_task(app.run())
            await asyncio.sleep(0)
            await scenario(app)
            await self.send(Message(("easytv", "quit")))
            return await asyncio.wait_for(task, timeout=2)

        return asyncio.run(main())


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

    assert env.run(scenario) is StopReason.QUIT
    assert env.player.played == [("1 - Cartoons/ep1.mp4", 0.0)]
    [banner] = env.player.banners
    assert "   Cartoons" in banner
    assert banner.endswith("ep1")


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
    async def main() -> StopReason:
        app = App(env.config, env.player, env.clock)
        await env.player.events.put(Closed())
        return await asyncio.wait_for(app.run(), timeout=2)

    assert asyncio.run(main()) is StopReason.PLAYER_CLOSED
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
    assert env.player.banners[0] == message_banner(NO_CHANNEL_TEXT)


def test_corrupted_state_does_not_prevent_start(env: Env) -> None:
    save_state(env.config.state_file, TvState(current_channel="2 - Docs"))
    env.config.state_file.write_text("{oops", encoding="utf-8")

    async def scenario(app: App) -> None:
        pass

    env.run(scenario)
    assert env.player.played == [("1 - Cartoons/ep1.mp4", 0.0)]


def test_info_shows_banner(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "info")))

    env.run(scenario)
    assert len(env.player.banners) == 2


def test_submitted_command_is_executed_and_status_follows(env: Env) -> None:
    async def scenario(app: App) -> None:
        assert app.status() == Status(["Cartoons", "Docs"], 1, "ep1", False, 100, False, False)
        app.submit(Command(Action.GOTO, 2))
        await env.send(Message(("easytv", "info")))  # let the app run
        assert app.status() == Status(["Cartoons", "Docs"], 2, "doc1", False, 100, False, False)

    env.run(scenario)
    assert [p for p, _ in env.player.played] == ["1 - Cartoons/ep1.mp4", "2 - Docs/doc1.mp4"]


def test_status_without_channels(env: Env, tmp_path: Path) -> None:
    env.config = Config(channels_dir=tmp_path / "empty", state_file=tmp_path / "s.json")

    async def scenario(app: App) -> None:
        assert app.status() == Status([], None, None, False, 100, False, False)

    env.run(scenario)


# --- Unreadable videos -------------------------------------------------------


def test_one_unreadable_video_is_skipped(env: Env) -> None:
    env.make("1 - Cartoons/ep3.mp4")
    env.player.broken = {"ep2.mp4"}

    async def scenario(app: App) -> None:
        await env.send(EndOfFile())  # ep1 ends normally
        await env.send(VideoError("broken"))  # ep2 cannot be read
        await env.send(EndOfFile())  # ep3 ends normally
        await env.send(EndOfFile())

    env.run(scenario)
    assert [p for p, _ in env.player.played] == [
        "1 - Cartoons/ep1.mp4",
        "1 - Cartoons/ep2.mp4",
        "1 - Cartoons/ep3.mp4",
        "1 - Cartoons/ep1.mp4",
        "1 - Cartoons/ep2.mp4",
    ]
    assert not any(UNAVAILABLE_TEXT in b for b in env.player.banners)


def test_fully_broken_channel_stops_instead_of_looping(env: Env) -> None:
    env.player.broken = {"ep1.mp4", "ep2.mp4"}

    async def scenario(app: App) -> None:
        await env.send(VideoError("broken"))
        await env.send(EndOfFile())  # ended instantly, never played
        assert app.status().unavailable

    env.run(scenario)
    assert [p for p, _ in env.player.played] == ["1 - Cartoons/ep1.mp4", "1 - Cartoons/ep2.mp4"]
    assert env.player.stopped == 1
    assert env.player.banners[-1].startswith(message_banner(UNAVAILABLE_TEXT))
    assert "Cartoons" in env.player.banners[-1]


def test_zapping_still_works_after_broken_channel(env: Env) -> None:
    env.player.broken = {"ep1.mp4", "ep2.mp4"}

    async def scenario(app: App) -> None:
        await env.send(VideoError("broken"))
        await env.send(VideoError("broken"))
        await env.send(Message(("easytv", "next_channel")))
        await env.send(Message(("easytv", "info")))

    env.run(scenario)
    assert env.player.played[-1] == ("2 - Docs/doc1.mp4", 0.0)
    assert "Docs" in env.player.banners[-1]


def test_rescan_retries_broken_channel_when_videos_change(env: Env) -> None:
    env.player.broken = {"ep1.mp4", "ep2.mp4"}

    async def scenario(app: App) -> None:
        await env.send(VideoError("broken"))
        await env.send(VideoError("broken"))
        await app.rescan()  # nothing changed: stays unavailable
        env.player.broken = set()
        env.make("1 - Cartoons/ep3.mp4")
        await app.rescan()

    env.run(scenario)
    assert [p for p, _ in env.player.played] == [
        "1 - Cartoons/ep1.mp4",
        "1 - Cartoons/ep2.mp4",
        "1 - Cartoons/ep3.mp4",
    ]


# --- Volume -------------------------------------------------------------------


def test_volume_changes_show_gauge_and_are_remembered(env: Env) -> None:
    async def scenario(app: App) -> None:
        assert env.player.volume == (100, False)  # applied at startup
        await env.send(Message(("easytv", "volume_down")))
        await env.send(Message(("easytv", "volume_down")))
        assert env.player.volume == (90, False)
        await env.send(Message(("easytv", "mute")))
        assert env.player.volume == (90, True)
        assert app.status().muted

    env.run(scenario)
    assert env.player.volume_banners[-1] == volume_banner(90, muted=True)
    assert len(env.player.banners) == 1  # the channel banner is left alone
    assert env.player.played == [("1 - Cartoons/ep1.mp4", 0.0)]  # no zapping
    state = env.state()
    assert (state.volume, state.muted) == (90, True)

    env.player = FakePlayer()

    async def after_restart(app: App) -> None:
        assert env.player.volume == (90, True)

    env.run(after_restart)


def test_volume_up_unmutes(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "volume_down")))
        await env.send(Message(("easytv", "mute")))
        await env.send(Message(("easytv", "volume_up")))
        assert env.player.volume == (100, False)

    env.run(scenario)


# --- Stop and play -----------------------------------------------------------


def test_stop_then_play_resumes_where_it_stopped(env: Env) -> None:
    async def scenario(app: App) -> None:
        env.player.position = 42.0
        env.clock.now += 42
        await env.send(Message(("easytv", "stop")))
        assert env.player.stopped == 1
        assert env.player.banners[-1] == sleep_screen()
        assert app.status().stopped
        await env.send(Message(("easytv", "info")))  # the sleep screen stays
        assert env.player.banners[-1] == sleep_screen()
        assert env.state().channels["1 - Cartoons"] == ChannelState("ep1.mp4", 42.0, T0 + 42)

        await env.send(Message(("easytv", "stop")))  # a second phone presses too
        assert env.player.stopped == 1

        env.clock.now += 600
        await env.send(Message(("easytv", "play")))
        assert not app.status().stopped
        await env.send(Message(("easytv", "play")))  # already playing: nothing

    env.run(scenario)
    assert env.player.played == [("1 - Cartoons/ep1.mp4", 0.0), ("1 - Cartoons/ep1.mp4", 42.0)]


def test_zap_while_stopped_plays(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "stop")))
        await env.send(Message(("easytv", "next_channel")))
        assert not app.status().stopped

    env.run(scenario)
    assert [p for p, _ in env.player.played] == ["1 - Cartoons/ep1.mp4", "2 - Docs/doc1.mp4"]


def test_rescan_while_stopped_plays_nothing(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "stop")))
        (env.root / "tv" / "1 - Cartoons" / "ep1.mp4").unlink()
        await app.rescan()
        assert len(env.player.played) == 1
        await env.send(Message(("easytv", "play")))

    env.run(scenario)
    assert [p for p, _ in env.player.played] == ["1 - Cartoons/ep1.mp4", "1 - Cartoons/ep2.mp4"]


def test_play_after_all_channels_vanished(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "stop")))
        for video in (env.root / "tv").rglob("*.mp4"):
            video.unlink()
        await app.rescan()
        await env.send(Message(("easytv", "play")))
        assert not app.status().stopped

    env.run(scenario)
    assert env.player.banners[-1] == message_banner(NO_CHANNEL_TEXT)


def test_prev_video_shows_the_banner(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "prev_video")))

    env.run(scenario)
    assert env.player.played == [("1 - Cartoons/ep1.mp4", 0.0), ("1 - Cartoons/ep2.mp4", 0.0)]
    assert env.player.banners[-1].endswith("ep2")


# --- Bedtime and progress ----------------------------------------------------


def bedtime_around(env: Env) -> tuple[time, float]:
    """A bedtime one minute after now (local time), and its timestamp."""
    moment = datetime.fromtimestamp(env.clock.now + 60).replace(second=0, microsecond=0)
    return moment.time(), moment.timestamp()


def test_bedtime_puts_the_tv_to_sleep_once(env: Env) -> None:
    bedtime, at = bedtime_around(env)
    env.config = Config(**{**env.config.__dict__, "bedtime": bedtime})

    async def scenario(app: App) -> None:
        env.clock.now = at - 10
        await app.check_bedtime()
        assert not app.status().stopped
        env.player.position = 30.0
        env.clock.now = at + 5
        await app.check_bedtime()
        assert app.status().stopped
        assert app.status().sleep_text == BEDTIME_TITLE
        assert env.player.banners[-1] == sleep_screen(BEDTIME_TITLE, BEDTIME_SUBTITLE)

        await env.send(Message(("easytv", "play")))  # turned on again after bedtime
        env.clock.now = at + 20
        await app.check_bedtime()
        assert not app.status().stopped

    env.run(scenario)
    assert env.player.played[-1] == ("1 - Cartoons/ep1.mp4", 30.0)


def test_no_bedtime_on_a_clock_jump(env: Env) -> None:
    # The Pi boots with a wrong clock, then the network sets it: not a passing bedtime.
    bedtime, at = bedtime_around(env)
    env.config = Config(**{**env.config.__dict__, "bedtime": bedtime})

    async def scenario(app: App) -> None:
        env.clock.now = at - 86_400 * 30
        await app.check_bedtime()
        env.clock.now = at + 5
        await app.check_bedtime()
        assert not app.status().stopped

    env.run(scenario)


def test_status_has_progress_while_playing(env: Env) -> None:
    async def scenario(app: App) -> None:
        env.player.position, env.player.duration = 12.5, 600.0
        status = app.status()
        assert (status.position, status.duration, status.sleep_text) == (12.5, 600.0, None)
        await env.send(Message(("easytv", "stop")))
        status = app.status()
        assert (status.position, status.duration) == (None, None)
        assert status.sleep_text == "La télé fait dodo"

    env.run(scenario)


# --- Snow --------------------------------------------------------------------


def test_snow_when_the_channel_changes_and_when_the_tv_comes_on(env: Env) -> None:
    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "next_channel")))  # 2 - Docs
        await env.send(Message(("easytv", "goto", "1")))
        await env.send(Message(("easytv", "next_video")))  # same channel: no snow
        await env.send(Message(("easytv", "prev_video")))
        await env.send(EndOfFile())  # end of an episode: no snow
        await env.send(Message(("easytv", "stop")))
        await env.send(Message(("easytv", "play")))  # the TV comes on

    env.run(scenario)
    assert [p for p, _ in env.player.played] == [
        "1 - Cartoons/ep1.mp4",  # start
        "2 - Docs/doc1.mp4",
        "1 - Cartoons/ep1.mp4",
        "1 - Cartoons/ep2.mp4",
        "1 - Cartoons/ep1.mp4",
        "1 - Cartoons/ep2.mp4",
        "1 - Cartoons/ep2.mp4",  # play after stop
    ]
    assert env.player.snowed == [
        "1 - Cartoons/ep1.mp4",
        "2 - Docs/doc1.mp4",
        "1 - Cartoons/ep1.mp4",
        "1 - Cartoons/ep2.mp4",
    ]


def test_no_snow_when_disabled(env: Env) -> None:
    env.config = replace(env.config, snow=False)

    async def scenario(app: App) -> None:
        await env.send(Message(("easytv", "next_channel")))
        await env.send(Message(("easytv", "stop")))
        await env.send(Message(("easytv", "play")))

    env.run(scenario)
    assert len(env.player.played) == 3
    assert env.player.snowed == []


# --- Mix channel -------------------------------------------------------------


def test_mix_is_channel_1_and_plays_videos_of_every_channel(env: Env) -> None:
    env.config = replace(env.config, mix="Doodingue")
    statuses: list[Status] = []

    async def scenario(app: App) -> None:
        statuses.append(app.status())
        for _ in range(2):
            await env.send(Message(("easytv", "next_video")))
        await env.send(Message(("easytv", "next_channel")))

    env.run(scenario)
    status = statuses[0]
    assert status.channels == ["Doodingue", "Cartoons", "Docs"]
    assert status.current == 1
    mixed = [p for p, _ in env.player.played[:3]]
    assert sorted(mixed) == ["1 - Cartoons/ep1.mp4", "1 - Cartoons/ep2.mp4", "2 - Docs/doc1.mp4"]
    assert env.player.played[3] == ("1 - Cartoons/ep1.mp4", 0.0)  # channel 2: Cartoons
    assert " · " in env.player.banners[0]  # the mix shows where the episode comes from


def test_no_mix_with_a_single_channel(env: Env, tmp_path: Path) -> None:
    env.config = replace(env.config, mix="Doodingue", channels_dir=tmp_path / "one")
    (tmp_path / "one" / "Only").mkdir(parents=True)
    (tmp_path / "one" / "Only" / "a.mp4").touch()
    statuses: list[Status] = []

    async def scenario(app: App) -> None:
        statuses.append(app.status())

    env.run(scenario)
    assert statuses[0].channels == ["Only"]
