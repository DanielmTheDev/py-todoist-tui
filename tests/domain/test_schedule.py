import datetime

import pytest

from todoist_tui.domain.due import Due
from todoist_tui.domain.schedule import quick_due

_TUESDAY = datetime.date(2026, 7, 28)


def test_today_returns_reference_date() -> None:
    assert quick_due("today", _TUESDAY) == Due(date=_TUESDAY)


def test_tomorrow_is_next_day() -> None:
    assert quick_due("tomorrow", _TUESDAY) == Due(date=datetime.date(2026, 7, 29))


def test_next_week_is_the_coming_monday() -> None:
    assert quick_due("next_week", _TUESDAY) == Due(date=datetime.date(2026, 8, 3))


def test_next_week_from_a_monday_skips_to_the_following_monday() -> None:
    monday = datetime.date(2026, 8, 3)
    assert quick_due("next_week", monday) == Due(date=datetime.date(2026, 8, 10))


def test_weekend_is_the_coming_saturday() -> None:
    assert quick_due("weekend", _TUESDAY) == Due(date=datetime.date(2026, 8, 1))


def test_weekend_on_a_saturday_jumps_to_next_saturday() -> None:
    saturday = datetime.date(2026, 8, 1)
    assert quick_due("weekend", saturday) == Due(date=datetime.date(2026, 8, 8))


def test_weekend_on_a_sunday_is_next_saturday() -> None:
    sunday = datetime.date(2026, 8, 2)
    assert quick_due("weekend", sunday) == Due(date=datetime.date(2026, 8, 8))


def test_clear_returns_none() -> None:
    assert quick_due("clear", _TUESDAY) is None


def test_quick_due_produces_all_day_dues() -> None:
    due = quick_due("today", _TUESDAY)
    assert due is not None
    assert due.time is None
    assert due.is_recurring is False


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValueError, match="quick due"):
        quick_due("someday", _TUESDAY)  # type: ignore[arg-type]
