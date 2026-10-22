import calendar
import datetime
from dataclasses import dataclass
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


def parse_time_digits(digits: str) -> datetime.time | None:
    """Length-based 24h parse of typed digits. '' -> None (all-day);
    1-2 digits = hour, 3-4 = H(H)MM. Raises ValueError on non-digits,
    >4 digits, or an out-of-range hour/minute."""
    if not digits:
        return None
    if not digits.isdigit() or len(digits) > 4:
        raise ValueError(f"not a time: {digits!r}")
    if len(digits) <= 2:
        hour, minute = int(digits), 0
    else:
        hour, minute = int(digits[:-2]), int(digits[-2:])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {digits!r}")
    return datetime.time(hour, minute)


def reschedule(original: Due | None, picked: Due | None) -> Due | None:
    """Apply a picked date to a task, preserving recurrence.

    The picker only ever yields a plain date. For a recurring task we graft that
    date onto the existing rule (keeping its `string`/`lang` and time-of-day) so
    the update moves the next occurrence without dropping the recurrence. A
    cleared pick removes the due date and thus the recurrence.
    """
    if picked is None:
        return None
    if original is not None and original.is_recurring:
        return Due(
            date=picked.date,
            time=picked.time or original.time,
            is_recurring=True,
            string=original.string,
            lang=original.lang,
        )
    return picked


# "in X" offsets the picker's +/- walk: fine steps near now, coarse further out
POSTPONE_LADDER: tuple[datetime.timedelta, ...] = tuple(
    datetime.timedelta(minutes=m) for m in (15, 30, 45, 60, 90, 120, 180, 240, 360, 480)
)
_GRID = datetime.timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class Postpone:
    """ "In X": `by` after the task's own due time, or after `now` when it has
    no time or that time has passed (an overdue task should land in the future).
    Applied per task, so a selection each shifts from its own time."""

    by: datetime.timedelta
    now: datetime.datetime

    def applied_to(self, original: Due | None) -> Due:
        base = self.now
        if original is not None and original.time is not None:
            base = max(base, datetime.datetime.combine(original.date, original.time))
        target = _ceil_to_grid(base + self.by)
        picked = Due(date=target.date(), time=target.time())
        return reschedule(original, picked) or picked


def _ceil_to_grid(moment: datetime.datetime) -> datetime.datetime:
    floor = datetime.datetime.combine(moment.date(), datetime.time())
    return floor + -((floor - moment) // _GRID) * _GRID


def shift_month(day: datetime.date, months: int) -> datetime.date:
    """Move `day` by whole months, clamping to the target month's last day."""
    index = day.month - 1 + months
    year = max(datetime.MINYEAR, min(datetime.MAXYEAR, day.year + index // 12))
    month = index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(day.day, last))


def month_weeks(year: int, month: int) -> list[list[datetime.date | None]]:
    """`month` laid out as weeks of 7 cells (Mon..Sun); None pads other months."""
    weeks = calendar.Calendar(firstweekday=_MONDAY).monthdatescalendar(year, month)
    return [[d if d.month == month else None for d in week] for week in weeks]
