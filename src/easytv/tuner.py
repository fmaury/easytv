from dataclasses import dataclass
from pathlib import Path

from easytv.library import Channel
from easytv.state import MAX_VOLUME, ChannelState, TvState


@dataclass(frozen=True)
class Playback:
    """What the player must play: a video of a channel, from a given position."""

    channel: str
    video_path: Path
    start: float


class Tuner:
    """Decides what to play. Pure logic: the current time is always passed in."""

    def __init__(self, channels: list[Channel], state: TvState, resume_timeout: float) -> None:
        self._channels = list(channels)
        self.state = state
        self._resume_timeout = resume_timeout
        self._index: int | None = None
        self.stopped = False

    @property
    def channels(self) -> list[Channel]:
        return list(self._channels)

    @property
    def current(self) -> Channel | None:
        return None if self._index is None else self._channels[self._index]

    def start(self, now: float) -> Playback | None:
        if not self._channels:
            return None
        index = self._find(self.state.current_channel)
        return self._tune(0 if index is None else index, now)

    def report_position(self, position: float, now: float) -> None:
        channel = self.current
        if channel is not None:
            entry = self.state.channels[channel.name]
            entry.position = position
            entry.left_at = now

    def stop(self, position: float | None, now: float) -> None:
        """Stop watching: like leaving the current channel, without tuning another one."""
        if self.stopped:
            return
        if position is not None:
            self.report_position(position, now)
        else:
            self._leave(now)
        self.stopped = True

    def resume(self, now: float) -> Playback | None:
        """Watch again after `stop`: the current channel, under the resume rule."""
        self.stopped = False
        if self._index is None:
            return self.start(now)
        return self._tune(self._index, now)

    def zap(self, step: int, now: float) -> Playback | None:
        self._leave(now)
        self.stopped = False
        if self._index is None:
            return self.start(now)
        return self._tune((self._index + step) % len(self._channels), now)

    def goto(self, number: int, now: float) -> Playback | None:
        """Tune to channel `number` (1-based). Out of range or current channel: no change,
        unless stopped: the current channel then plays again."""
        index = number - 1
        if not 0 <= index < len(self._channels):
            return None
        if index == self._index:
            return self.resume(now) if self.stopped else None
        self._leave(now)
        self.stopped = False
        return self._tune(index, now)

    def next_video(self, now: float) -> Playback | None:
        return self._step_video(+1, now)

    def prev_video(self, now: float) -> Playback | None:
        """The previous video from its start; before the first one comes the last one."""
        return self._step_video(-1, now)

    def _step_video(self, step: int, now: float) -> Playback | None:
        channel = self.current
        if channel is None:
            return None
        self.stopped = False
        current = self.state.channels[channel.name].video
        if current in channel.videos:
            i = channel.videos.index(current)
            video = channel.videos[(i + step) % len(channel.videos)]
        elif step > 0:
            video = _next_after(channel, current)
        else:
            video = _prev_before(channel, current)
        return self._play(channel, video, 0.0, now)

    def change_volume(self, delta: int) -> None:
        """Like a TV: changing the volume also unmutes."""
        self.state.volume = max(0, min(MAX_VOLUME, self.state.volume + delta))
        self.state.muted = False

    def toggle_mute(self) -> None:
        self.state.muted = not self.state.muted

    def update_channels(self, channels: list[Channel], now: float) -> Playback | None:
        """Apply a rescan. Returns a new playback only if what was playing is gone.

        When no channel is left, `current` becomes None and the caller must stop playback.
        `stopped` is kept: when stopped, the caller must not play the returned playback.
        """
        playing = self.current
        self._channels = list(channels)
        self._index = None
        if playing is None:
            return self.start(now)
        if not self._channels:
            return None

        index = self._find(playing.name)
        if index is None:
            return self._tune(0, now)
        self._index = index
        channel = self._channels[index]
        video = self.state.channels[channel.name].video
        if video in channel.videos:
            return None
        return self._play(channel, _next_after(channel, video), 0.0, now)

    def _find(self, name: str | None) -> int | None:
        for i, channel in enumerate(self._channels):
            if channel.name == name:
                return i
        return None

    def _leave(self, now: float) -> None:
        channel = self.current
        # When stopped, the channel was already left at the time of the stop.
        if channel is not None and not self.stopped:
            self.state.channels[channel.name].left_at = now

    def _tune(self, index: int, now: float) -> Playback:
        channel = self._channels[index]
        self._index = index
        self.state.current_channel = channel.name
        video, start = self._resume_point(channel, now)
        return self._play(channel, video, start, now)

    def _resume_point(self, channel: Channel, now: float) -> tuple[str, float]:
        saved = self.state.channels.get(channel.name)
        if saved is None:
            return channel.videos[0], 0.0
        if saved.video not in channel.videos:
            return _next_after(channel, saved.video), 0.0
        if now - saved.left_at < self._resume_timeout:
            return saved.video, saved.position
        return saved.video, 0.0

    def _play(self, channel: Channel, video: str, start: float, now: float) -> Playback:
        self.state.channels[channel.name] = ChannelState(video=video, position=start, left_at=now)
        return Playback(channel=channel.name, video_path=channel.path / video, start=start)


def _next_after(channel: Channel, missing: str) -> str:
    """The video sorting right after a vanished one, wrapping to the first."""
    key = channel.key(missing)
    return next((v for v in channel.videos if channel.key(v) > key), channel.videos[0])


def _prev_before(channel: Channel, missing: str) -> str:
    """The video sorting right before a vanished one, wrapping to the last."""
    key = channel.key(missing)
    return next((v for v in reversed(channel.videos) if channel.key(v) < key), channel.videos[-1])
