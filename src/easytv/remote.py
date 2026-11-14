import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)

MESSAGE_PREFIX = "easytv"


class Action(StrEnum):
    NEXT_CHANNEL = "next_channel"
    PREV_CHANNEL = "prev_channel"
    GOTO = "goto"
    NEXT_VIDEO = "next_video"
    INFO = "info"
    QUIT = "quit"


@dataclass(frozen=True)
class Command:
    action: Action
    number: int | None = None  # channel number for GOTO (1-based)


def parse_message(args: Sequence[str]) -> Command | None:
    """Turn an mpv script message such as ("easytv", "goto", "2") into a command."""
    if len(args) < 2 or args[0] != MESSAGE_PREFIX:
        return None
    try:
        action = Action(args[1])
    except ValueError:
        logger.warning("unknown command: %s", " ".join(args[1:]))
        return None
    if action is not Action.GOTO:
        return Command(action)
    if len(args) == 3 and args[2].isdigit() and int(args[2]) > 0:
        return Command(action, int(args[2]))
    logger.warning("invalid goto command: %s", " ".join(args[1:]))
    return None
