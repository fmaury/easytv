import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DIGITS = re.compile(r"(\d+)")

SortKey = tuple[tuple[int, int | str], ...]


@dataclass(frozen=True)
class Channel:
    name: str
    path: Path
    videos: tuple[str, ...]  # file names; "<channel folder>/<file>" for the mix channel
    shuffled: bool = False  # videos in the mix's fixed random order instead of by name

    def key(self, video: str) -> SortKey:
        """Where `video` sits in this channel's order, even if it no longer exists."""
        return shuffle_key(video) if self.shuffled else sort_key(video)


def shuffle_key(video: str) -> SortKey:
    """A random-looking but fixed rank: the mix keeps its order across rescans and restarts,
    and a new video lands at a random place without moving the others."""
    return ((1, hashlib.sha256(video.encode()).hexdigest()),)


def sort_key(name: str) -> SortKey:
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


def mix(channels: list[Channel], name: str, channels_dir: Path) -> Channel | None:
    """A channel of every video of every channel, shuffled. None for fewer than two channels,
    or when a real channel already has this name (their memories would mix up)."""
    if len(channels) < 2:
        return None
    if any(c.name == name for c in channels):
        logger.warning("no mix channel: a folder is already named %r", name)
        return None
    videos = sorted((f"{c.name}/{v}" for c in channels for v in c.videos), key=shuffle_key)
    return Channel(name=name, path=channels_dir, videos=tuple(videos), shuffled=True)
