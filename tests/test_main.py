from pathlib import Path

import pytest

from easytv.__main__ import main


def test_invalid_config_exits_with_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("sys.argv", ["easytv", "--config", str(tmp_path / "missing.toml")])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    assert "config file not found" in caplog.text
