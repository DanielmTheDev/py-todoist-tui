"""Relative, human-readable date labels (Today / Tomorrow / weekday / date).

Pure domain logic. Weekday and month names are hardcoded English so the output
is deterministic regardless of the host locale.
"""

import datetime

_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)  # indexed by date.weekday()

_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)  # indexed by month - 1


def humanize_date(d: datetime.date, today: datetime.date) -> str:
    """Todoist-style label for `d` relative to `today`.

    Today / Tomorrow / Yesterday, the full weekday name for the next 2..6 days,
    otherwise a compact `3 Aug` (with a 2-digit year suffix when the year
    differs). Time-of-day, when any, is appended by the caller.
    """
    delta = (d - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    if 2 <= delta <= 6:
        return _WEEKDAYS[d.weekday()]
    compact = f"{d.day} {_MONTHS[d.month - 1]}"
    if d.year != today.year:
        compact += f" {d.year % 100:02d}"
    return compact
