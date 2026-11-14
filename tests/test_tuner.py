from pathlib import Path

from easytv.library import Channel
from easytv.state import ChannelState, TvState
from easytv.tuner import Playback, Tuner

ROOT = Path("/tv")
T0 = 1_000_000.0
MINUTE = 60.0
HOUR = 3600.0


def channel(name: str, *videos: str) -> Channel:
    return Channel(name=name, path=ROOT / name, videos=videos)


CARTOONS = channel("1 - Cartoons", "ep1.mp4", "ep2.mp4", "ep3.mp4")
DOCS = channel("2 - Docs", "doc1.mp4", "doc2.mp4")
FILMS = channel("3 - Films", "film.mkv")
ALL = [CARTOONS, DOCS, FILMS]


def play(ch: Channel, video: str, start: float = 0.0) -> Playback:
    return Playback(channel=ch.name, video_path=ch.path / video, start=start)


def tuner(state: TvState | None = None, channels: list[Channel] = ALL) -> Tuner:
    return Tuner(channels, state or TvState(), resume_timeout=HOUR)


def saved(ch: Channel, video: str, position: float, left_at: float) -> TvState:
    return TvState(
        current_channel=ch.name,
        channels={ch.name: ChannelState(video=video, position=position, left_at=left_at)},
    )


# --- Startup and resume rule -------------------------------------------------


def test_first_start_plays_first_video_of_first_channel() -> None:
    t = tuner()
    assert t.start(T0) == play(CARTOONS, "ep1.mp4")
    assert t.state.current_channel == CARTOONS.name


def test_resume_at_same_position_within_timeout() -> None:
    t = tuner(saved(DOCS, "doc2.mp4", 754.0, T0))
    assert t.start(T0 + 59 * MINUTE) == play(DOCS, "doc2.mp4", 754.0)


def test_restart_video_from_beginning_at_timeout() -> None:
    t = tuner(saved(DOCS, "doc2.mp4", 754.0, T0))
    assert t.start(T0 + HOUR) == play(DOCS, "doc2.mp4")


def test_restart_video_from_beginning_after_timeout() -> None:
    t = tuner(saved(DOCS, "doc2.mp4", 754.0, T0))
    assert t.start(T0 + 2 * HOUR) == play(DOCS, "doc2.mp4")


def test_start_on_deleted_channel_goes_to_first_channel() -> None:
    t = tuner(saved(channel("9 - Gone", "x.mp4"), "x.mp4", 10.0, T0))
    assert t.start(T0) == play(CARTOONS, "ep1.mp4")


def test_each_channel_has_its_own_resume_timer() -> None:
    t = tuner()
    t.start(T0)  # 20:00 cartoons
    t.report_position(12 * MINUTE, T0 + 12 * MINUTE)
    t.zap(+1, T0 + 12 * MINUTE)  # leave cartoons at 20:12
    t.report_position(40 * MINUTE, T0 + 52 * MINUTE)
    t.zap(+1, T0 + 52 * MINUTE)  # leave docs at 20:52, watch films

    # 21:22: docs left 30 min ago -> exact position
    assert t.goto(2, T0 + 82 * MINUTE) == play(DOCS, "doc1.mp4", 40 * MINUTE)
    # 21:22: cartoons left 1 h 10 ago -> same video from the beginning
    assert t.goto(1, T0 + 82 * MINUTE) == play(CARTOONS, "ep1.mp4")


def test_power_cut_resumes_from_last_reported_position() -> None:
    t = tuner()
    t.start(T0)
    t.report_position(300.0, T0 + 300)
    # The process dies here; the saved state is reloaded at reboot.
    rebooted = tuner(t.state)
    assert rebooted.start(T0 + 300 + 10 * MINUTE) == play(CARTOONS, "ep1.mp4", 300.0)


# --- Zapping -----------------------------------------------------------------


def test_zap_wraps_both_ways() -> None:
    t = tuner()
    t.start(T0)
    assert t.zap(-1, T0) == play(FILMS, "film.mkv")
    assert t.zap(+1, T0) == play(CARTOONS, "ep1.mp4")
    assert t.zap(+1, T0) == play(DOCS, "doc1.mp4")


def test_zap_records_departure_time_and_position() -> None:
    t = tuner()
    t.start(T0)
    t.report_position(100.0, T0 + 100)
    t.zap(+1, T0 + 130)
    assert t.state.channels[CARTOONS.name] == ChannelState("ep1.mp4", 100.0, T0 + 130)
    assert t.state.current_channel == DOCS.name


def test_zap_before_start_starts() -> None:
    assert tuner().zap(+1, T0) == play(CARTOONS, "ep1.mp4")


def test_goto() -> None:
    t = tuner()
    t.start(T0)
    assert t.goto(3, T0) == play(FILMS, "film.mkv")
    assert t.goto(3, T0) is None  # already there
    assert t.goto(0, T0) is None
    assert t.goto(4, T0) is None
    assert t.current == FILMS


def test_report_position_before_start_is_ignored() -> None:
    t = tuner()
    t.report_position(10.0, T0)
    assert t.state == TvState()


# --- Continuous playback -----------------------------------------------------


def test_next_video_and_wrap_around() -> None:
    t = tuner(saved(CARTOONS, "ep2.mp4", 500.0, T0))
    t.start(T0)
    assert t.next_video(T0 + 10) == play(CARTOONS, "ep3.mp4")
    assert t.next_video(T0 + 20) == play(CARTOONS, "ep1.mp4")
    assert t.state.channels[CARTOONS.name] == ChannelState("ep1.mp4", 0.0, T0 + 20)


def test_single_video_channel_replays_it() -> None:
    t = tuner()
    t.start(T0)
    t.goto(3, T0)
    assert t.next_video(T0) == play(FILMS, "film.mkv")


# --- Vanished content --------------------------------------------------------


def test_deleted_video_resumes_on_next_one() -> None:
    t = tuner(saved(CARTOONS, "ep2b.mp4", 500.0, T0))
    assert t.start(T0) == play(CARTOONS, "ep3.mp4")


def test_deleted_last_video_wraps_to_first() -> None:
    t = tuner(saved(CARTOONS, "ep9.mp4", 500.0, T0))
    assert t.start(T0) == play(CARTOONS, "ep1.mp4")


def test_rescan_without_change_keeps_playing() -> None:
    t = tuner()
    t.start(T0)
    t.zap(+1, T0)
    assert t.update_channels([*ALL, channel("4 - New", "n.mp4")], T0) is None
    assert t.current == DOCS


def test_rescan_with_current_video_deleted() -> None:
    t = tuner(saved(CARTOONS, "ep2.mp4", 500.0, T0))
    t.start(T0)
    shrunk = channel(CARTOONS.name, "ep1.mp4", "ep3.mp4")
    assert t.update_channels([shrunk, DOCS], T0 + 5) == play(CARTOONS, "ep3.mp4")


def test_rescan_with_current_channel_deleted_goes_to_first() -> None:
    t = tuner()
    t.start(T0)
    t.goto(2, T0)
    assert t.update_channels([CARTOONS, FILMS], T0) == play(CARTOONS, "ep1.mp4")
    assert t.current == CARTOONS


def test_deleted_channel_state_is_kept() -> None:
    t = tuner()
    t.start(T0)
    t.goto(2, T0)
    t.report_position(42.0, T0 + 42)
    t.update_channels([CARTOONS], T0 + 50)
    assert t.update_channels(ALL, T0 + 60) is None
    assert t.goto(2, T0 + 70) == play(DOCS, "doc1.mp4", 42.0)


# --- No channels -------------------------------------------------------------


def test_no_channels() -> None:
    t = tuner(channels=[])
    assert t.start(T0) is None
    assert t.zap(+1, T0) is None
    assert t.goto(1, T0) is None
    assert t.next_video(T0) is None
    assert t.current is None


def test_channels_appearing_after_empty_start() -> None:
    t = tuner(channels=[])
    t.start(T0)
    assert t.update_channels([DOCS], T0) == play(DOCS, "doc1.mp4")


def test_all_channels_removed_stops_playback() -> None:
    t = tuner()
    t.start(T0)
    assert t.update_channels([], T0) is None
    assert t.current is None


def test_volume_is_clamped_and_unmutes() -> None:
    t = tuner(TvState(volume=97, muted=True))
    t.change_volume(+5)
    assert (t.state.volume, t.state.muted) == (100, False)
    t.change_volume(-150)
    assert t.state.volume == 0


def test_toggle_mute_keeps_volume() -> None:
    t = tuner(TvState(volume=40))
    t.toggle_mute()
    assert (t.state.volume, t.state.muted) == (40, True)
    t.toggle_mute()
    assert (t.state.volume, t.state.muted) == (40, False)
