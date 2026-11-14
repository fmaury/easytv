import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_VERSION = 1


@dataclass
class ChannelState:
    video: str
    position: float
    left_at: float  # Unix timestamp of the last update while watching


@dataclass
class TvState:
    current_channel: str | None = None
    channels: dict[str, ChannelState] = field(default_factory=dict)


def load_state(path: Path) -> TvState:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _parse(data)
    except FileNotFoundError:
        return TvState()
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        # A broken state must never prevent the TV from starting.
        logger.error("ignoring unreadable state file %s: %s", path, e)
        return TvState()


def save_state(path: Path, state: TvState) -> None:
    """Write atomically so a power cut never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": STATE_VERSION, **asdict(state)}
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _parse(data: Any) -> TvState:
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        raise ValueError("unsupported state format")
    current = data["current_channel"]
    if current is not None and not isinstance(current, str):
        raise TypeError("current_channel must be a string")
    channels = {
        str(name): ChannelState(
            video=str(entry["video"]),
            position=float(entry["position"]),
            left_at=float(entry["left_at"]),
        )
        for name, entry in data["channels"].items()
    }
    return TvState(current_channel=current, channels=channels)
