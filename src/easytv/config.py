import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

DEFAULT_VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts"})


class ConfigError(Exception):
    pass


class InputMode(StrEnum):
    KEYBOARD = "keyboard"  # keys pressed in the mpv window (development on a PC)
    REMOTE = "remote"  # input devices read with evdev: TV remote via CEC, USB remote (Pi)


@dataclass(frozen=True)
class Config:
    channels_dir: Path
    state_file: Path
    resume_timeout: float = 3600
    save_interval: float = 5
    rescan_interval: float = 30
    video_extensions: frozenset[str] = DEFAULT_VIDEO_EXTENSIONS
    input: InputMode = InputMode.REMOTE
    mpv_args: tuple[str, ...] = ()


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e

    defaults = Config(channels_dir=Path(), state_file=Path())
    return Config(
        channels_dir=_path(data, "channels_dir"),
        state_file=_path(data, "state_file"),
        resume_timeout=_seconds(data, "resume_timeout", defaults.resume_timeout),
        save_interval=_seconds(data, "save_interval", defaults.save_interval),
        rescan_interval=_seconds(data, "rescan_interval", defaults.rescan_interval),
        video_extensions=_extensions(data, defaults.video_extensions),
        input=_input_mode(data, defaults.input),
        mpv_args=_mpv_args(data),
    )


def _path(data: dict[str, Any], key: str) -> Path:
    if key not in data:
        raise ConfigError(f"missing required key: {key}")
    value = data[key]
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a non-empty string")
    return Path(value).expanduser()


def _seconds(data: dict[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    # bool is a subclass of int: reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ConfigError(f"{key} must be a positive number of seconds")
    return float(value)


def _extensions(data: dict[str, Any], default: frozenset[str]) -> frozenset[str]:
    value = data.get("video_extensions")
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError("video_extensions must be a list of strings")
    return frozenset(v.lower() if v.startswith(".") else f".{v.lower()}" for v in value)


def _input_mode(data: dict[str, Any], default: InputMode) -> InputMode:
    value = data.get("input", default)
    try:
        return InputMode(value)
    except ValueError as e:
        choices = ", ".join(f'"{m}"' for m in InputMode)
        raise ConfigError(f"input must be one of {choices}") from e


def _mpv_args(data: dict[str, Any]) -> tuple[str, ...]:
    value = data.get("mpv_args", [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError("mpv_args must be a list of strings")
    return tuple(value)
