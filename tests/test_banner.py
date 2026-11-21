import pytest

from easytv.banner import (
    BEDTIME_SUBTITLE,
    BEDTIME_TITLE,
    SLEEP_TITLE,
    channel_banner,
    display_name,
    escape_ass,
    message_banner,
    sleep_screen,
    video_title,
    volume_banner,
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


def test_volume_banner_gauge_width() -> None:
    full = volume_banner(100, muted=False)
    assert "Volume  100" in full
    assert "m 0 0 l 420 0 420 24 0 24" in full  # gauge fully filled
    half = volume_banner(50, muted=False)
    assert "m 0 0 l 210 0 210 24 0 24" in half


def test_volume_banner_muted_has_empty_gauge() -> None:
    muted = volume_banner(80, muted=True)
    assert "Son coupé" in muted
    assert "&H00D7FF&" not in muted  # no yellow fill
    assert volume_banner(0, muted=False).count("\\p1") == 2  # panel and empty gauge only


def test_sleep_screen_is_drawn_without_emoji_font() -> None:
    screen = sleep_screen()
    assert SLEEP_TITLE in screen
    assert r"\p1" in screen  # the face is a drawing
    assert all(ord(char) < 0x2000 for char in screen)  # no emoji: the Pi has no emoji font


def test_bedtime_screen_has_its_own_text() -> None:
    screen = sleep_screen(BEDTIME_TITLE, BEDTIME_SUBTITLE)
    assert BEDTIME_TITLE in screen
    assert SLEEP_TITLE not in screen


def test_video_title_in_the_mix_names_its_channel() -> None:
    assert video_title("01 - Pingu/02 - Pingu helps.avi") == "Pingu · 02 - Pingu helps"
