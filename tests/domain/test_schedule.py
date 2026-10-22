import datetime

import pytest

from todoist_tui.domain.due import Due
from todoist_tui.domain.schedule import (
    POSTPONE_LADDER,
    Postpone,
    month_weeks,
    parse_time_digits,
    quick_due,
    reschedule,
    shift_month,
)

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


def test_reschedule_recurring_keeps_rule_moves_date() -> None:
    original = Due(date=_TUESDAY, is_recurring=True, string="every day", lang="en")
    picked = Due(date=datetime.date(2026, 8, 3))

    result = reschedule(original, picked)

    assert result == Due(
        date=datetime.date(2026, 8, 3),
        is_recurring=True,
        string="every day",
        lang="en",
    )


def test_reschedule_recurring_keeps_original_time_of_day() -> None:
    original = Due(
        date=_TUESDAY,
        time=datetime.time(9, 0),
        is_recurring=True,
        string="every day at 9am",
    )
    picked = Due(date=datetime.date(2026, 8, 3))  # picker yields all-day

    result = reschedule(original, picked)

    assert result is not None
    assert result.time == datetime.time(9, 0)


def test_reschedule_non_recurring_returns_picked_unchanged() -> None:
    original = Due(date=_TUESDAY)
    picked = Due(date=datetime.date(2026, 8, 3))

    assert reschedule(original, picked) == picked


def test_reschedule_none_original_returns_picked() -> None:
    picked = Due(date=datetime.date(2026, 8, 3))

    assert reschedule(None, picked) == picked


def test_reschedule_clear_drops_recurrence() -> None:
    original = Due(date=_TUESDAY, is_recurring=True, string="every day")

    assert reschedule(original, None) is None


def test_parse_time_empty_is_all_day() -> None:
    assert parse_time_digits("") is None


@pytest.mark.parametrize(
    ("digits", "expected"),
    [
        ("4", datetime.time(4, 0)),
        ("9", datetime.time(9, 0)),
        ("16", datetime.time(16, 0)),
        ("930", datetime.time(9, 30)),
        ("1430", datetime.time(14, 30)),
        ("2359", datetime.time(23, 59)),
        ("0000", datetime.time(0, 0)),
    ],
)
def test_parse_time_length_based(digits: str, expected: datetime.time) -> None:
    assert parse_time_digits(digits) == expected


@pytest.mark.parametrize("digits", ["25", "99", "999", "1260", "12345", "9a", "12:30"])
def test_parse_time_rejects_invalid(digits: str) -> None:
    with pytest.raises(ValueError):
        parse_time_digits(digits)


def test_shift_month_forward() -> None:
    assert shift_month(_TUESDAY, 1) == datetime.date(2026, 8, 28)


def test_shift_month_back() -> None:
    assert shift_month(_TUESDAY, -1) == datetime.date(2026, 6, 28)


def test_shift_month_crosses_year_boundary() -> None:
    assert shift_month(datetime.date(2026, 12, 15), 1) == datetime.date(2027, 1, 15)


def test_shift_month_clamps_to_shorter_month() -> None:
    assert shift_month(datetime.date(2026, 1, 31), 1) == datetime.date(2026, 2, 28)


def test_shift_month_clamps_to_leap_february() -> None:
    assert shift_month(datetime.date(2028, 1, 31), 1) == datetime.date(2028, 2, 29)


def test_shift_month_clamps_within_dates_year_range() -> None:
    assert shift_month(_TUESDAY, 10**6).year == 9999
    assert shift_month(_TUESDAY, -(10**6)).year == 1


def test_month_weeks_are_seven_cells_wide() -> None:
    weeks = month_weeks(2026, 7)
    assert all(len(week) == 7 for week in weeks)


def test_month_weeks_cover_every_day_once_with_none_padding() -> None:
    weeks = month_weeks(2026, 2)  # 28 days
    days = [cell for week in weeks for cell in week if cell is not None]
    assert [d.day for d in days] == list(range(1, 29))
    assert all(d.month == 2 for d in days)


def test_month_weeks_start_on_monday() -> None:
    # 1 July 2026 is a Wednesday: the first row pads Mon/Tue with None
    first_week = month_weeks(2026, 7)[0]
    assert first_week[0] is None and first_week[1] is None
    assert first_week[2] == datetime.date(2026, 7, 1)


_NOW = datetime.datetime(2026, 7, 28, 14, 27, 30)
_HOUR = datetime.timedelta(hours=1)


def _at(day: int, hour: int, minute: int) -> Due:
    return Due(date=datetime.date(2026, 7, day), time=datetime.time(hour, minute))


def test_postpone_counts_from_now_when_there_is_no_due() -> None:
    by = datetime.timedelta(minutes=30)
    assert Postpone(by, _NOW).applied_to(None) == _at(28, 15, 0)  # 14:57:30 rounds up


def test_postpone_keeps_a_time_already_on_the_five_minute_grid() -> None:
    now = datetime.datetime(2026, 7, 28, 14, 25)
    by = datetime.timedelta(minutes=5)
    assert Postpone(by, now).applied_to(None) == _at(28, 14, 30)


def test_postpone_counts_from_a_future_due_time() -> None:
    assert Postpone(_HOUR, _NOW).applied_to(_at(28, 18, 0)) == _at(28, 19, 0)


def test_postpone_counts_from_now_when_the_due_time_is_past() -> None:
    assert Postpone(_HOUR, _NOW).applied_to(_at(27, 18, 0)) == _at(28, 15, 30)


def test_postpone_counts_from_now_for_an_all_day_due() -> None:
    all_day = Due(date=datetime.date(2026, 7, 30))
    assert Postpone(_HOUR, _NOW).applied_to(all_day) == _at(28, 15, 30)


def test_postpone_crosses_midnight() -> None:
    now = datetime.datetime(2026, 7, 28, 23, 50)
    by = datetime.timedelta(minutes=30)
    assert Postpone(by, now).applied_to(None) == _at(29, 0, 20)


def test_postpone_keeps_a_recurring_rule() -> None:
    daily = Due(
        date=datetime.date(2026, 7, 28),
        time=datetime.time(18, 0),
        is_recurring=True,
        string="every day at 18:00",
    )
    assert Postpone(_HOUR, _NOW).applied_to(daily) == Due(
        date=datetime.date(2026, 7, 28),
        time=datetime.time(19, 0),
        is_recurring=True,
        string="every day at 18:00",
    )


def test_postpone_ladder_climbs_from_a_quarter_hour_to_hours() -> None:
    assert POSTPONE_LADDER[0] == datetime.timedelta(minutes=15)
    assert list(POSTPONE_LADDER) == sorted(POSTPONE_LADDER)
