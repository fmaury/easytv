from pathlib import Path

import pytest

from easytv.config import DEFAULT_VIDEO_EXTENSIONS, ConfigError, load_config


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_full_config(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
        channels_dir = "/media/tv"
        state_file = "/var/lib/easytv/state.json"
        resume_timeout = 7200
        save_interval = 2.5
        rescan_interval = 60
        video_extensions = [".MP4", "mkv"]
        """,
    )
    config = load_config(path)
    assert config.channels_dir == Path("/media/tv")
    assert config.state_file == Path("/var/lib/easytv/state.json")
    assert config.resume_timeout == 7200
    assert config.save_interval == 2.5
    assert config.rescan_interval == 60
    assert config.video_extensions == {".mp4", ".mkv"}


def test_defaults(tmp_path: Path) -> None:
    path = write(tmp_path, 'channels_dir = "/media/tv"\nstate_file = "/tmp/state.json"\n')
    config = load_config(path)
    assert config.resume_timeout == 3600
    assert config.save_interval == 5
    assert config.rescan_interval == 30
    assert config.video_extensions == DEFAULT_VIDEO_EXTENSIONS


def test_home_is_expanded(tmp_path: Path) -> None:
    path = write(tmp_path, 'channels_dir = "~/tv"\nstate_file = "~/state.json"\n')
    config = load_config(path)
    assert config.channels_dir == Path.home() / "tv"
    assert config.state_file == Path.home() / "state.json"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(write(tmp_path, "channels_dir = "))


def test_missing_required_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="state_file"):
        load_config(write(tmp_path, 'channels_dir = "/media/tv"\n'))


@pytest.mark.parametrize("value", ['"1h"', "0", "-5", "true"])
def test_invalid_timeout(tmp_path: Path, value: str) -> None:
    path = write(
        tmp_path, f'channels_dir = "/tv"\nstate_file = "/s.json"\nresume_timeout = {value}\n'
    )
    with pytest.raises(ConfigError, match="resume_timeout"):
        load_config(path)


def test_invalid_extensions(tmp_path: Path) -> None:
    path = write(
        tmp_path, 'channels_dir = "/tv"\nstate_file = "/s.json"\nvideo_extensions = ".mp4"\n'
    )
    with pytest.raises(ConfigError, match="video_extensions"):
        load_config(path)
