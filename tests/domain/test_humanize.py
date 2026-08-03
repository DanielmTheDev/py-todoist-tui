import datetime

from todoist_tui.domain.humanize import humanize_date

_TODAY = datetime.date(2026, 8, 3)  # a Monday


def test_today() -> None:
    assert humanize_date(_TODAY, _TODAY) == "Today"


def test_tomorrow() -> None:
    assert humanize_date(datetime.date(2026, 8, 4), _TODAY) == "Tomorrow"


def test_yesterday() -> None:
    assert humanize_date(datetime.date(2026, 8, 2), _TODAY) == "Yesterday"


def test_weekday_within_next_six_days() -> None:
    # +2 .. +6 render as the full weekday name
    assert humanize_date(datetime.date(2026, 8, 5), _TODAY) == "Wednesday"
    assert humanize_date(datetime.date(2026, 8, 9), _TODAY) == "Sunday"


def test_seventh_day_falls_through_to_compact() -> None:
    assert humanize_date(datetime.date(2026, 8, 10), _TODAY) == "10 Aug"


def test_overdue_beyond_yesterday_is_compact_date() -> None:
    assert humanize_date(datetime.date(2026, 7, 31), _TODAY) == "31 Jul"


def test_future_compact_date() -> None:
    assert humanize_date(datetime.date(2026, 12, 25), _TODAY) == "25 Dec"


def test_year_suffix_when_year_differs() -> None:
    assert humanize_date(datetime.date(2027, 1, 3), _TODAY) == "3 Jan 27"
    assert humanize_date(datetime.date(2025, 8, 3), _TODAY) == "3 Aug 25"
