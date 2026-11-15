from datetime import datetime, time

from easytv.bedtime import MAX_GAP, bedtime_reached

MIDNIGHT = time(0, 0)


def at(text: str) -> float:
    """Timestamp of a local date and time such as "2026-11-15 23:59:50"."""
    return datetime.fromisoformat(text).timestamp()


def test_reached_when_crossing_midnight() -> None:
    assert bedtime_reached(at("2026-11-15 23:59:50"), at("2026-11-16 00:00:05"), MIDNIGHT)


def test_reached_exactly_at_bedtime() -> None:
    assert bedtime_reached(at("2026-11-15 23:59:50"), at("2026-11-16 00:00:00"), MIDNIGHT)


def test_not_reached_before_or_after() -> None:
    assert not bedtime_reached(at("2026-11-15 23:59:30"), at("2026-11-15 23:59:45"), MIDNIGHT)
    assert not bedtime_reached(at("2026-11-16 00:00:00"), at("2026-11-16 00:00:15"), MIDNIGHT)


def test_evening_bedtime() -> None:
    bedtime = time(20, 30)
    assert bedtime_reached(at("2026-11-15 20:29:55"), at("2026-11-15 20:30:10"), bedtime)
    assert not bedtime_reached(at("2026-11-15 20:31:00"), at("2026-11-15 20:31:15"), bedtime)


def test_clock_jump_is_ignored() -> None:
    # Boot with a clock in 1970, then the network sets the real time.
    assert not bedtime_reached(0.0, at("2026-11-16 00:00:05"), MIDNIGHT)
    gap = at("2026-11-16 00:00:05") - MAX_GAP - 1
    assert not bedtime_reached(gap, at("2026-11-16 00:00:05"), MIDNIGHT)


def test_clock_going_back_is_ignored() -> None:
    assert not bedtime_reached(at("2026-11-16 00:00:05"), at("2026-11-15 23:59:50"), MIDNIGHT)
