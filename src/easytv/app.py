import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from easytv.config import Config
from easytv.library import Channel, scan
from easytv.player import Closed, EndOfFile, Message, Player, PlayerEvent, VideoError
from easytv.remote import Action, Command, parse_message
from easytv.state import load_state, save_state
from easytv.tuner import Playback, Tuner

logger = logging.getLogger(__name__)

BANNER_SECONDS = 3.0
NO_CHANNEL_TEXT = "Aucune chaîne"


class App:
    def __init__(
        self, config: Config, player: Player, clock: Callable[[], float] = time.time
    ) -> None:
        self._config = config
        self._player = player
        self._clock = clock
        self._tuner = Tuner(self._scan(), load_state(config.state_file), config.resume_timeout)

    async def run(self) -> None:
        await self._show(self._tuner.start(self._clock()))
        timers = [
            asyncio.create_task(self._every(self._config.save_interval, self.save)),
            asyncio.create_task(self._every(self._config.rescan_interval, self.rescan)),
        ]
        try:
            while await self._handle(await self._player.events.get()):
                pass
        finally:
            for timer in timers:
                timer.cancel()
            await asyncio.gather(*timers, return_exceptions=True)
            await self.save()

    async def save(self) -> None:
        position = self._player.position
        if position is not None:
            self._tuner.report_position(position, self._clock())
        try:
            save_state(self._config.state_file, self._tuner.state)
        except OSError as e:
            logger.error("could not save state to %s: %s", self._config.state_file, e)

    async def rescan(self) -> None:
        await self.save()
        playback = self._tuner.update_channels(self._scan(), self._clock())
        if playback is not None:
            await self._show(playback)
        elif self._tuner.current is None:
            await self._show(None)

    async def _handle(self, event: PlayerEvent) -> bool:
        """Process one player event. Returns False when the app must stop."""
        match event:
            case Message(args):
                command = parse_message(args)
                return command is None or await self._execute(command)
            case EndOfFile():
                await self._show(self._tuner.next_video(self._clock()), banner=False)
            case VideoError(message):
                logger.error("cannot play video: %s", message)
                await self._show(self._tuner.next_video(self._clock()), banner=False)
            case Closed():
                logger.info("player closed")
                return False
        return True

    async def _execute(self, command: Command) -> bool:
        if command.action is Action.QUIT:
            return False
        if command.action is Action.INFO:
            await self._banner()
            return True

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
        if playback is not None:
            await self._show(playback)
            await self.save()
        return True

    async def _show(self, playback: Playback | None, *, banner: bool = True) -> None:
        if playback is None:
            if self._tuner.current is None:
                await self._player.stop()
                await self._player.show_text(NO_CHANNEL_TEXT, 3600)
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
            await self._player.show_text(NO_CHANNEL_TEXT, BANNER_SECONDS)
            return
        number = self._tuner.channels.index(channel) + 1
        video = self._tuner.state.channels[channel.name].video
        await self._player.show_text(f"{number}. {channel.name}\n{video}", BANNER_SECONDS)

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
