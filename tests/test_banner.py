import pytest

from easytv.banner import (
    channel_banner,
    display_name,
    escape_ass,
    message_banner,
    video_title,
)


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("01 - Dessins animés", "Dessins animés"),
        ("1.Docs", "Docs"),
        ("10_Films", "Films"),
        ("3 Séries", "Séries"),
        ("Musique", "Musique"),
        ("2024", "2024"),
        ("007 James Bond", "James Bond"),
    ],
)
def test_display_name(folder: str, expected: str) -> None:
    assert display_name(folder) == expected


def test_video_title() -> None:
    assert video_title("ep_02.mp4") == "ep 02"
    assert video_title("Le.Film.mkv") == "Le.Film"


def test_escape_ass_neutralizes_tags() -> None:
    escaped = escape_ass(r"a{\b1}b\Nc" + "\nd")
    assert "{" not in escaped.replace("\\{", "")
    assert "}" not in escaped.replace("\\}", "")
    assert "\\N" not in escaped
    assert "\n" not in escaped


def test_channel_banner_contains_number_name_and_title() -> None:
    ass = channel_banner(2, "02 - Docs", "doc_1.mp4")
    assert "}2{" in ass
    assert "   Docs" in ass
    assert ass.endswith("doc 1")
    assert "02 - Docs" not in ass


def test_message_banner_is_centered() -> None:
    ass = message_banner("Aucune chaîne")
    assert ass.startswith("{\\an5")
    assert ass.endswith("Aucune chaîne")
