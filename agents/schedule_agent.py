# Agent: Schedule | Role: Enforce active time windows before any outbound message

"""Schedule agent — determines whether the bot should be active right now.

Uses SCHEDULE_WINDOWS from config.py and timezone-aware datetimes (FIXES.md Gotcha #8).
"""

import functools
import logging
from datetime import datetime, timedelta
from typing import Callable

import pytz

from config import SCHEDULE_WINDOWS, TIMEZONE

logger = logging.getLogger(__name__)

_tz = pytz.timezone(TIMEZONE)


def _now_ct() -> datetime:
    """Return current Central Time as a timezone-aware datetime."""
    return datetime.now(_tz)


def is_active_now() -> bool:
    """Return True if the bot should send messages right now."""
    now = _now_ct()
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    window = SCHEDULE_WINDOWS.get(weekday, {"active": False})

    if not window["active"]:
        return False

    start_h, start_m = map(int, window["start"].split(":"))
    end_h, end_m = map(int, window["end"].split(":"))

    start_time = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end_time = now.replace(hour=end_h, minute=end_m, second=59, microsecond=999999)

    return start_time <= now <= end_time


def next_active_window() -> datetime:
    """Return the datetime when the next active window starts."""
    now = _now_ct()

    for offset in range(8):
        candidate = now + timedelta(days=offset)
        weekday = candidate.weekday()
        window = SCHEDULE_WINDOWS.get(weekday, {"active": False})

        if not window["active"]:
            continue

        start_h, start_m = map(int, window["start"].split(":"))
        start_dt = candidate.replace(
            hour=start_h, minute=start_m, second=0, microsecond=0
        )

        if offset == 0 and start_dt <= now:
            # We're past today's start — check if still within window
            end_h, end_m = map(int, window["end"].split(":"))
            end_dt = candidate.replace(
                hour=end_h, minute=end_m, second=59, microsecond=999999
            )
            if now <= end_dt:
                return now  # Already active
            continue  # Today's window is over

        return start_dt

    # Shouldn't reach here — return tomorrow as fallback
    return now + timedelta(days=1)


def should_send(func: Callable) -> Callable:
    """Decorator that checks is_active_now() before executing a send function.

    Returns None without calling the wrapped function if outside active window.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not is_active_now():
            logger.info("Outside active window — skipping send for %s", func.__name__)
            return None
        return func(*args, **kwargs)
    return wrapper
