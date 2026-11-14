from pathlib import Path

from easytv.config import DEFAULT_VIDEO_EXTENSIONS
from easytv.library import scan, sort_key


def make(root: Path, *files: str) -> None:
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def test_natural_sort() -> None:
    names = ["ep10.mp4", "Ep2.mp4", "ep1.mp4", "bonus.mp4"]
    assert sorted(names, key=sort_key) == ["bonus.mp4", "ep1.mp4", "Ep2.mp4", "ep10.mp4"]


def test_channels_and_videos_are_sorted(tmp_path: Path) -> None:
    make(
        tmp_path,
        "10 - Films/b.mkv",
        "2 - Docs/doc10.mp4",
        "2 - Docs/doc2.mp4",
        "1 - Cartoons/ep1.mp4",
    )
    channels = scan(tmp_path, DEFAULT_VIDEO_EXTENSIONS)
    assert [c.name for c in channels] == ["1 - Cartoons", "2 - Docs", "10 - Films"]
    assert channels[1].videos == ("doc2.mp4", "doc10.mp4")
    assert channels[1].path == tmp_path / "2 - Docs"


def test_ignores_hidden_and_non_video_files(tmp_path: Path) -> None:
    make(
        tmp_path,
        "tv/a.MP4",
        "tv/.hidden.mp4",
        "tv/notes.txt",
        "tv/cover.jpg",
        ".trash/x.mp4",
    )
    channels = scan(tmp_path, DEFAULT_VIDEO_EXTENSIONS)
    assert [(c.name, c.videos) for c in channels] == [("tv", ("a.MP4",))]


def test_ignores_empty_channels_root_files_and_subfolders(tmp_path: Path) -> None:
    make(tmp_path, "loose.mp4", "empty/readme.txt", "nested/season1/ep1.mp4")
    assert scan(tmp_path, DEFAULT_VIDEO_EXTENSIONS) == []


def test_missing_channels_dir(tmp_path: Path) -> None:
    assert scan(tmp_path / "nope", DEFAULT_VIDEO_EXTENSIONS) == []
