"""When the TV goes to sleep by itself. Pure logic: the times are passed in."""

from datetime import datetime, time, timedelta

# Bedtime is checked every few seconds. A longer gap between two checks is a clock jump
# (the Pi has no clock: its time is set by the network after booting), not time passing.
MAX_GAP = 300.0


def bedtime_reached(previous: float, now: float, bedtime: time) -> bool:
    """Whether `bedtime` (local time) came between the checks at `previous` and `now`."""
    if not 0 < now - previous <= MAX_GAP:
        return False
    local = datetime.fromtimestamp(now)
    moment = datetime.combine(local.date(), bedtime)
    if moment > local:
        moment -= timedelta(days=1)
    return previous < moment.timestamp() <= now
