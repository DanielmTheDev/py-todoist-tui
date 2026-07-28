import datetime
from typing import Literal

from todoist_tui.domain.due import Due

QuickKind = Literal["today", "tomorrow", "next_week", "weekend", "clear"]

_SATURDAY = 5
_MONDAY = 0


def quick_due(kind: QuickKind, today: datetime.date) -> Due | None:
    """Resolve a quick-schedule choice against a reference date (all-day).

    `clear` means "remove the due date" and returns None.
    """
    if kind == "clear":
        return None
    if kind == "today":
        return Due(date=today)
    if kind == "tomorrow":
        return Due(date=today + datetime.timedelta(days=1))
    if kind == "weekend":
        days = (_SATURDAY - today.weekday()) % 7 or 7  # always the *next* Saturday
        return Due(date=today + datetime.timedelta(days=days))
    if kind == "next_week":
        offset = (_MONDAY - today.weekday()) % 7 or 7  # always the *next* Monday
        return Due(date=today + datetime.timedelta(days=offset))
    raise ValueError(f"unknown quick due kind: {kind!r}")
