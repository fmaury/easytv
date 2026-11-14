import argparse
import asyncio
import logging
import sys
from pathlib import Path

from easytv.app import App, StopReason
from easytv.config import Config, ConfigError, InputMode, load_config
from easytv.player import MpvError, MpvPlayer

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
    except KeyboardInterrupt:
        logger.info("stopped")
        return
    except MpvError as e:
        logger.error("%s", e)
        sys.exit(1)
    if reason is StopReason.PLAYER_CLOSED:
        # Non-zero so that systemd restarts the TV.
        sys.exit(1)


async def _run(config: Config, *, fullscreen: bool) -> StopReason:
    if config.input is InputMode.REMOTE:
        logger.warning("remote control is not available yet: zapping is disabled")
    player = MpvPlayer(keyboard=config.input is InputMode.KEYBOARD, fullscreen=fullscreen)
    await player.start()
    try:
        return await App(config, player).run()
    finally:
        await player.close()


if __name__ == "__main__":
    main()
