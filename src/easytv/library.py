import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DIGITS = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Channel:
    name: str
    path: Path
    videos: tuple[str, ...]


def sort_key(name: str) -> tuple[tuple[int, int | str], ...]:
    """Natural, case-insensitive key: "ep2" sorts before "ep10"."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in _DIGITS.split(name.casefold())
        if part
    )


def scan(channels_dir: Path, extensions: frozenset[str]) -> list[Channel]:
    if not channels_dir.is_dir():
        logger.warning("channels directory not found: %s", channels_dir)
        return []

    channels = []
    for folder in channels_dir.iterdir():
        if folder.name.startswith(".") or not folder.is_dir():
            continue
        videos = sorted(
            (
                f.name
                for f in folder.iterdir()
                if not f.name.startswith(".") and f.suffix.lower() in extensions and f.is_file()
            ),
            key=sort_key,
        )
        if videos:
            channels.append(Channel(name=folder.name, path=folder, videos=tuple(videos)))
    channels.sort(key=lambda c: sort_key(c.name))
    return channels
