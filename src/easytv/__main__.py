import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from easytv.app import App, StopReason
from easytv.config import Config, ConfigError, InputMode, load_config
from easytv.player import MpvError, MpvPlayer
from easytv.web import WebRemote

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(prog="easytv", description="Folders as TV channels.")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--debug", action="store_true", help="verbose logs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config)
    except ConfigError as e:
        logger.error("%s", e)
        sys.exit(2)

    logger.info("EasyTV starting with %s", args.config)
    try:
        reason = asyncio.run(_run(config, fullscreen=args.fullscreen))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("stopped")
        return
    except MpvError as e:
        logger.error("%s", e)
        sys.exit(1)
    if reason is StopReason.PLAYER_CLOSED:
        # Non-zero so that systemd restarts the TV.
        sys.exit(1)


async def _run(config: Config, *, fullscreen: bool) -> StopReason:
    # systemd stops the service with SIGTERM: stop like Ctrl+C, so the final state save runs.
    main_task = asyncio.current_task()
    assert main_task is not None
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, main_task.cancel)

    if config.input is InputMode.REMOTE and not config.web_port:
        logger.warning("remote control is not available yet and web_port = 0: no way to zap")
    player = MpvPlayer(
        keyboard=config.input is InputMode.KEYBOARD,
        fullscreen=fullscreen,
        extra_args=config.mpv_args,
    )
    await player.start()
    try:
        app = App(config, player)
        web = WebRemote(app.status, app.submit)
        if config.web_port:
            try:
                await web.start(config.web_port)
            except OSError as e:
                # The TV must keep working even if the web remote cannot start.
                logger.error("web remote disabled: port %d: %s", config.web_port, e)
        try:
            return await app.run()
        finally:
            await web.close()
    finally:
        await player.close()


if __name__ == "__main__":
    main()
