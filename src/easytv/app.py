import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from enum import Enum

from easytv.banner import (
    channel_banner,
    display_name,
    message_banner,
    video_title,
    volume_banner,
)
from easytv.config import Config
from easytv.library import Channel, scan
from easytv.player import Closed, EndOfFile, Layer, Message, Player, PlayerEvent, VideoError
from easytv.remote import Action, Command, parse_message
from easytv.state import load_state, save_state
from easytv.tuner import Playback, Tuner
from easytv.web import Status

logger = logging.getLogger(__name__)

BANNER_SECONDS = 4.0
VOLUME_SECONDS = 2.5
VOLUME_STEP = 5
NO_CHANNEL_TEXT = "Aucune chaîne"
UNAVAILABLE_TEXT = "Chaîne indisponible"


class StopReason(Enum):
    QUIT = "quit"
    PLAYER_CLOSED = "player closed"


class App:
    def __init__(
        self, config: Config, player: Player, clock: Callable[[], float] = time.time
    ) -> None:
        self._config = config
        self._player = player
        self._clock = clock
        self._tuner = Tuner(self._scan(), load_state(config.state_file), config.resume_timeout)
        self._failures = 0  # consecutive unreadable videos on the current channel
        self._unavailable: tuple[str, ...] | None = None  # videos of a fully broken channel

    async def run(self) -> StopReason:
        logger.info(
            "%d channel(s) found in %s", len(self._tuner.channels), self._config.channels_dir
        )
        await self._apply_volume()
        await self._show(self._tuner.start(self._clock()))
        timers = [
            asyncio.create_task(self._every(self._config.save_interval, self.save)),
            asyncio.create_task(self._every(self._config.rescan_interval, self.rescan)),
        ]
        try:
            while True:
                reason = await self._handle(await self._player.events.get())
                if reason is not None:
                    logger.info("stopping: %s", reason.value)
                    return reason
        finally:
            for timer in timers:
                timer.cancel()
            await asyncio.gather(*timers, return_exceptions=True)
            await self.save()

    def submit(self, command: Command) -> None:
        """Queue a command from another source (web remote), handled like a remote key."""
        self._player.events.put_nowait(Message(command.message_args()))

    def status(self) -> Status:
        channels = self._tuner.channels
        current = self._tuner.current
        state = self._tuner.state
        return Status(
            channels=[display_name(c.name) for c in channels],
            current=None if current is None else channels.index(current) + 1,
            video=None if current is None else video_title(state.channels[current.name].video),
            unavailable=self._unavailable is not None,
            volume=state.volume,
            muted=state.muted,
        )

    async def save(self) -> None:
        position = self._player.position
        if position is not None:
            self._tuner.report_position(position, self._clock())
        try:
            save_state(self._config.state_file, self._tuner.state)
            logger.debug("state saved to %s", self._config.state_file)
        except OSError as e:
            logger.error("could not save state to %s: %s", self._config.state_file, e)

    async def rescan(self) -> None:
        await self.save()
        before = {c.name for c in self._tuner.channels}
        playback = self._tuner.update_channels(self._scan(), self._clock())
        after = {c.name for c in self._tuner.channels}
        for name in sorted(after - before):
            logger.info("channel added: %s", name)
        for name in sorted(before - after):
            logger.info("channel removed: %s", name)

        current = self._tuner.current
        if playback is not None:
            await self._show(playback, reset=True)
        elif current is None:
            await self._show(None)
        elif self._unavailable is not None and current.videos != self._unavailable:
            logger.info("videos changed on %s, retrying", current.name)
            await self._show(self._tuner.next_video(self._clock()), reset=True)

    async def _handle(self, event: PlayerEvent) -> StopReason | None:
        match event:
            case Message(args):
                command = parse_message(args)
                if command is not None:
                    logger.debug("command: %s", command)
                    return await self._execute(command)
            case EndOfFile() if self._player.has_started:
                self._failures = 0
                await self._show(self._tuner.next_video(self._clock()), banner=False)
            case EndOfFile():
                logger.error("video ended without playing: %s", self._current_video())
                await self._on_failure()
            case VideoError(message):
                logger.error("cannot play %s: %s", self._current_video(), message)
                await self._on_failure()
            case Closed():
                return StopReason.PLAYER_CLOSED
        return None

    async def _execute(self, command: Command) -> StopReason | None:
        if command.action is Action.QUIT:
            return StopReason.QUIT
        if command.action is Action.INFO:
            await self._banner()
            return None
        if command.action in (Action.VOLUME_UP, Action.VOLUME_DOWN, Action.MUTE):
            if command.action is Action.MUTE:
                self._tuner.toggle_mute()
            else:
                step = VOLUME_STEP if command.action is Action.VOLUME_UP else -VOLUME_STEP
                self._tuner.change_volume(step)
            logger.info(
                "volume %d%s", self._tuner.state.volume, " (muted)" * self._tuner.state.muted
            )
            await self._apply_volume()
            state = self._tuner.state
            await self._player.show_banner(
                volume_banner(state.volume, state.muted), VOLUME_SECONDS, Layer.VOLUME
            )
            return None

        position = self._player.position
        now = self._clock()
        if position is not None:
            # Record the exact position of the channel we are leaving.
            self._tuner.report_position(position, now)
        match command.action:
            case Action.NEXT_CHANNEL:
                playback = self._tuner.zap(+1, now)
            case Action.PREV_CHANNEL:
                playback = self._tuner.zap(-1, now)
            case Action.GOTO:
                assert command.number is not None
                playback = self._tuner.goto(command.number, now)
            case Action.NEXT_VIDEO:
                playback = self._tuner.next_video(now)
            case _:
                return None
        if playback is not None:
            await self._show(playback, reset=command.action is not Action.NEXT_VIDEO)
            await self.save()
        return None

    async def _apply_volume(self) -> None:
        await self._player.set_volume(self._tuner.state.volume, self._tuner.state.muted)

    async def _on_failure(self) -> None:
        """Skip an unreadable video, without looping forever on a fully broken channel."""
        channel = self._tuner.current
        if channel is None:
            return
        self._failures += 1
        if self._failures < len(channel.videos):
            await self._show(self._tuner.next_video(self._clock()), banner=False)
            return
        logger.error("no readable video on %s", channel.name)
        self._unavailable = channel.videos
        await self._player.stop()
        await self._banner()

    async def _show(
        self, playback: Playback | None, *, banner: bool = True, reset: bool = False
    ) -> None:
        if reset:
            self._failures = 0
            self._unavailable = None
        if playback is None:
            if self._tuner.current is None:
                await self._player.stop()
                await self._player.show_banner(message_banner(NO_CHANNEL_TEXT), None)
            return
        logger.info(
            "playing %s / %s from %.1fs",
            playback.channel,
            playback.video_path.name,
            playback.start,
        )
        await self._player.play(playback.video_path, playback.start)
        if banner:
            await self._banner()

    async def _banner(self) -> None:
        channel = self._tuner.current
        if channel is None:
            await self._player.show_banner(message_banner(NO_CHANNEL_TEXT), None)
        else:
            number = self._tuner.channels.index(channel) + 1
            video = self._tuner.state.channels[channel.name].video
            banner = channel_banner(number, channel.name, video)
            if self._unavailable is None:
                await self._player.show_banner(banner, BANNER_SECONDS)
            else:
                unavailable = f"{message_banner(UNAVAILABLE_TEXT)}\n{banner}"
                await self._player.show_banner(unavailable, None)

    def _current_video(self) -> str:
        channel = self._tuner.current
        if channel is None:
            return "?"
        return f"{channel.name}/{self._tuner.state.channels[channel.name].video}"

    def _scan(self) -> list[Channel]:
        return scan(self._config.channels_dir, self._config.video_extensions)

    @staticmethod
    async def _every(seconds: float, action: Callable[[], Awaitable[None]]) -> None:
        while True:
            await asyncio.sleep(seconds)
            try:
                await action()
            except Exception:
                logger.exception("periodic task failed")
