import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any

import pytest

from easytv.__main__ import main
from easytv.player import Closed, PlayerEvent


def test_invalid_config_exits_with_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("sys.argv", ["easytv", "--config", str(tmp_path / "missing.toml")])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    assert "config file not found" in caplog.text


class ClosingPlayer:
    """A player whose window is closed right away."""

    def __init__(self, **_: Any) -> None:
        self.events: asyncio.Queue[PlayerEvent] = asyncio.Queue()
        self.position: float | None = None
        self.has_started = False

    async def start(self) -> None:
        await self.events.put(Closed())

    async def close(self) -> None:
        pass

    async def play(self, path: Path, start: float) -> None:
        pass

    async def show_banner(self, ass: str, seconds: float | None) -> None:
        pass

    async def stop(self) -> None:
        pass


def test_exit_code_1_when_player_closes_by_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'channels_dir = "{tmp_path}"\nstate_file = "{tmp_path}/s.json"\ninput = "keyboard"\n'
    )
    monkeypatch.setattr("easytv.__main__.MpvPlayer", ClosingPlayer)
    monkeypatch.setattr("sys.argv", ["easytv", "--config", str(config)])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1


class TerminatedPlayer(ClosingPlayer):
    """A player playing at 42 s when systemd sends SIGTERM."""

    async def start(self) -> None:
        self.position = 42.0
        asyncio.get_running_loop().call_later(0.2, os.kill, os.getpid(), signal.SIGTERM)


def test_sigterm_saves_the_position(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tv" / "news").mkdir(parents=True)
    (tmp_path / "tv" / "news" / "a.mp4").touch()
    config = tmp_path / "config.toml"
    config.write_text(f'channels_dir = "{tmp_path}/tv"\nstate_file = "{tmp_path}/s.json"\n')
    monkeypatch.setattr("easytv.__main__.MpvPlayer", TerminatedPlayer)
    monkeypatch.setattr("sys.argv", ["easytv", "--config", str(config)])
    main()  # returns normally: no exit code, no crash
    state = json.loads((tmp_path / "s.json").read_text())
    assert state["channels"]["news"]["position"] == 42.0
