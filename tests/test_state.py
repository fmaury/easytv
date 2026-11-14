from pathlib import Path

import pytest

from easytv.state import ChannelState, TvState, load_state, save_state


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = TvState(
        current_channel="02 - Docs",
        channels={
            "01 - Dessins animés": ChannelState("ep02.mp4", 754.3, 1_763_150_000.0),
            "02 - Docs": ChannelState("doc05.mp4", 128.0, 1_763_155_400.0),
        },
    )
    save_state(path, state)
    assert load_state(path) == state


def test_missing_file_gives_empty_state(tmp_path: Path) -> None:
    assert load_state(tmp_path / "state.json") == TvState()


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '{"version": 99, "current_channel": null, "channels": {}}',
        '{"version": 1, "current_channel": 3, "channels": {}}',
        '{"version": 1, "current_channel": null, "channels": []}',
        '{"version": 1, "current_channel": null, "channels": {"a": {"video": "x"}}}',
        '{"version": 1, "current_channel": null, "channels": {"a": {"video": "x", '
        '"position": "oops", "left_at": 0}}}',
    ],
)
def test_corrupted_file_gives_empty_state(
    tmp_path: Path, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    assert load_state(path) == TvState()
    assert "ignoring unreadable state file" in caplog.text


def test_save_creates_parent_and_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "dir" / "state.json"
    save_state(path, TvState())
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]


def test_save_overwrites_previous_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(path, TvState(current_channel="a"))
    save_state(path, TvState(current_channel="b"))
    assert load_state(path).current_channel == "b"
