from datetime import time
from pathlib import Path

import pytest

from easytv.config import DEFAULT_VIDEO_EXTENSIONS, ConfigError, InputMode, load_config


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
        input = "keyboard"
        mpv_args = ["--hwdec=v4l2m2m", "--ao=alsa"]
        web_port = 0
        """,
    )
    config = load_config(path)
    assert config.channels_dir == Path("/media/tv")
    assert config.state_file == Path("/var/lib/easytv/state.json")
    assert config.resume_timeout == 7200
    assert config.save_interval == 2.5
    assert config.rescan_interval == 60
    assert config.video_extensions == {".mp4", ".mkv"}
    assert config.input is InputMode.KEYBOARD
    assert config.mpv_args == ("--hwdec=v4l2m2m", "--ao=alsa")
    assert config.web_port == 0


def test_defaults(tmp_path: Path) -> None:
    path = write(tmp_path, 'channels_dir = "/media/tv"\nstate_file = "/tmp/state.json"\n')
    config = load_config(path)
    assert config.resume_timeout == 3600
    assert config.save_interval == 5
    assert config.rescan_interval == 30
    assert config.video_extensions == DEFAULT_VIDEO_EXTENSIONS
    assert config.input is InputMode.REMOTE
    assert config.mpv_args == ()
    assert config.web_port == 8080


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


@pytest.mark.parametrize("value", ['"telecommande"', "1"])
def test_invalid_input_mode(tmp_path: Path, value: str) -> None:
    path = write(tmp_path, f'channels_dir = "/tv"\nstate_file = "/s.json"\ninput = {value}\n')
    with pytest.raises(ConfigError, match='input must be one of "keyboard", "remote"'):
        load_config(path)


def test_example_config_is_valid() -> None:
    config = load_config(Path(__file__).parent.parent / "config.example.toml")
    assert config.input is InputMode.REMOTE


@pytest.mark.parametrize("value", ['"--hwdec=v4l2m2m"', "[1]", '[""]'])
def test_invalid_mpv_args(tmp_path: Path, value: str) -> None:
    path = write(tmp_path, f'channels_dir = "/tv"\nstate_file = "/s.json"\nmpv_args = {value}\n')
    with pytest.raises(ConfigError, match="mpv_args"):
        load_config(path)


@pytest.mark.parametrize("value", ['"8080"', "-1", "65536", "80.5", "true"])
def test_invalid_web_port(tmp_path: Path, value: str) -> None:
    path = write(tmp_path, f'channels_dir = "/tv"\nstate_file = "/s.json"\nweb_port = {value}\n')
    with pytest.raises(ConfigError, match="web_port"):
        load_config(path)


def test_bedtime(tmp_path: Path) -> None:
    base = 'channels_dir = "/tv"\nstate_file = "/s.json"\n'
    assert load_config(write(tmp_path, base)).bedtime is None
    assert load_config(write(tmp_path, base + 'bedtime = ""')).bedtime is None
    assert load_config(write(tmp_path, base + 'bedtime = "00:00"')).bedtime == time(0, 0)
    assert load_config(write(tmp_path, base + "bedtime = 20:30:00")).bedtime == time(20, 30)


@pytest.mark.parametrize("value", ['"minuit"', '"25:00"', "2000", "true"])
def test_invalid_bedtime(tmp_path: Path, value: str) -> None:
    path = write(tmp_path, f'channels_dir = "/tv"\nstate_file = "/s.json"\nbedtime = {value}')
    with pytest.raises(ConfigError, match="bedtime"):
        load_config(path)


def test_snow(tmp_path: Path) -> None:
    base = 'channels_dir = "/tv"\nstate_file = "/s.json"\n'
    assert load_config(write(tmp_path, base)).snow is True
    assert load_config(write(tmp_path, base + "snow = false")).snow is False


@pytest.mark.parametrize("value", ['"yes"', "1", '""'])
def test_invalid_snow(tmp_path: Path, value: str) -> None:
    path = write(tmp_path, f'channels_dir = "/tv"\nstate_file = "/s.json"\nsnow = {value}')
    with pytest.raises(ConfigError, match="snow"):
        load_config(path)


def test_snow_duration_and_volume(tmp_path: Path) -> None:
    base = 'channels_dir = "/tv"\nstate_file = "/s.json"\n'
    config = load_config(write(tmp_path, base))
    assert (config.snow_seconds, config.snow_volume) == (0.4, 100)
    config = load_config(write(tmp_path, base + "snow_seconds = 1\nsnow_volume = 0"))
    assert (config.snow_seconds, config.snow_volume) == (1.0, 0)


@pytest.mark.parametrize("value", ["0", "-1", "2.5", "true", '"0.4"'])
def test_invalid_snow_seconds(tmp_path: Path, value: str) -> None:
    path = write(tmp_path, f'channels_dir = "/tv"\nstate_file = "/s.json"\nsnow_seconds = {value}')
    with pytest.raises(ConfigError, match="snow_seconds"):
        load_config(path)


@pytest.mark.parametrize("value", ["-1", "101", "50.5", "true", '"50"'])
def test_invalid_snow_volume(tmp_path: Path, value: str) -> None:
    path = write(tmp_path, f'channels_dir = "/tv"\nstate_file = "/s.json"\nsnow_volume = {value}')
    with pytest.raises(ConfigError, match="snow_volume"):
        load_config(path)


def test_mix(tmp_path: Path) -> None:
    base = 'channels_dir = "/tv"\nstate_file = "/s.json"\n'
    assert load_config(write(tmp_path, base)).mix is None
    assert load_config(write(tmp_path, base + 'mix = ""')).mix is None
    assert load_config(write(tmp_path, base + 'mix = "Doodingue"')).mix == "Doodingue"


@pytest.mark.parametrize("value", ["true", "1", '"a/b"'])
def test_invalid_mix(tmp_path: Path, value: str) -> None:
    path = write(tmp_path, f'channels_dir = "/tv"\nstate_file = "/s.json"\nmix = {value}')
    with pytest.raises(ConfigError, match="mix"):
        load_config(path)
