import pytest

from easytv.__main__ import main


def test_main_logs_startup(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        main()
    assert "EasyTV starting" in caplog.text
