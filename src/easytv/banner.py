"""TV-style on-screen banners, as ASS text for mpv's osd-overlay (1920x1080 reference)."""

import re
from pathlib import PurePath

WIDTH = 1920
HEIGHT = 1080

_ORDER_PREFIX = re.compile(r"^\d+\s*[-._]?\s*")

# ASS colors are &HBBGGRR&; alpha &H00& is opaque, &HFF& transparent.
_BAR = (
    r"{\an7\pos(0,830)\bord0\shad0\1c&H000000&\1a&H50&\p1}"
    r"m 0 0 l 1920 0 1920 250 0 250{\p0}"
)
_TEXT_STYLE = r"\an1\pos(90,1035)\bord3\shad0\3c&H000000&"


def display_name(folder: str) -> str:
    """Channel name without its ordering prefix: "01 - Dessins animés" -> "Dessins animés"."""
    return _ORDER_PREFIX.sub("", folder) or folder


def video_title(filename: str) -> str:
    return PurePath(filename).stem.replace("_", " ")


def escape_ass(text: str) -> str:
    """Make arbitrary text safe inside ASS: braces start override tags, backslash escapes."""
    return text.replace("\\", "\\⁠").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def channel_banner(number: int, channel: str, video: str) -> str:
    name = escape_ass(display_name(channel))
    title = escape_ass(video_title(video))
    text = (
        f"{{{_TEXT_STYLE}\\fs120\\b1\\1c&H00D7FF&}}{number}"
        f"{{\\fs80\\1c&HFFFFFF&}}   {name}"
        f"\\N{{\\fs52\\b0\\1c&HDDDDDD&}}{title}"
    )
    return f"{_BAR}\n{text}"


def volume_banner(volume: int, muted: bool) -> str:
    """A TV-style volume gauge in the top right corner."""
    x, y, width, height = 1400, 110, 420, 24
    filled = 0 if muted else round(width * volume / 100)
    label = "Son coupé" if muted else f"Volume  {volume}"
    parts = [
        rf"{{\an7\pos({x - 30},30)\bord0\shad0\1c&H000000&\1a&H50&\p1}}"
        rf"m 0 0 l {width + 60} 0 {width + 60} 134 0 134{{\p0}}",
        rf"{{\an7\pos({x},42)\fs50\b1\bord3\shad0\1c&HFFFFFF&\3c&H000000&}}{label}",
        rf"{{\an7\pos({x},{y})\bord0\shad0\1c&H606060&\p1}}"
        rf"m 0 0 l {width} 0 {width} {height} 0 {height}{{\p0}}",
    ]
    if filled:
        parts.append(
            rf"{{\an7\pos({x},{y})\bord0\shad0\1c&H00D7FF&\p1}}"
            rf"m 0 0 l {filled} 0 {filled} {height} 0 {height}{{\p0}}"
        )
    return "\n".join(parts)


def message_banner(text: str) -> str:
    return (
        f"{{\\an5\\pos({WIDTH // 2},{HEIGHT // 2})\\fs90\\b1\\bord4\\shad0"
        f"\\1c&HFFFFFF&\\3c&H000000&}}{escape_ass(text)}"
    )
