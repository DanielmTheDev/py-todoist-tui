import datetime

from todoist_tui.domain.due import Due


def test_from_api_date_only() -> None:
    due = Due.from_api({"date": "2026-07-21", "is_recurring": False})

    assert due.date == datetime.date(2026, 7, 21)
    assert due.time is None
    assert due.is_recurring is False


def test_from_api_datetime_extracts_time() -> None:
    due = Due.from_api({"date": "2026-07-21T09:30:00", "is_recurring": False})

    assert due.date == datetime.date(2026, 7, 21)
    assert due.time == datetime.time(9, 30)


def test_from_api_prefers_datetime_key_when_present() -> None:
    due = Due.from_api(
        {"date": "2026-07-21", "datetime": "2026-07-21T18:00:00", "is_recurring": True}
    )

    assert due.time == datetime.time(18, 0)
    assert due.is_recurring is True


def test_from_api_handles_trailing_z() -> None:
    due = Due.from_api({"date": "2026-07-21T09:30:00Z"})

    assert due.date == datetime.date(2026, 7, 21)
    assert due.time == datetime.time(9, 30)


def test_to_api_all_day_emits_date_only() -> None:
    due = Due(date=datetime.date(2026, 7, 21))

    assert due.to_api == {"date": "2026-07-21"}


def test_to_api_timed_emits_datetime() -> None:
    due = Due(date=datetime.date(2026, 7, 21), time=datetime.time(9, 30))

    assert due.to_api == {"datetime": "2026-07-21T09:30:00"}


def test_from_api_captures_recurrence_string_and_lang() -> None:
    due = Due.from_api(
        {
            "date": "2026-07-21",
            "is_recurring": True,
            "string": "every day",
            "lang": "en",
        }
    )

    assert due.is_recurring is True
    assert due.string == "every day"
    assert due.lang == "en"


def test_from_api_leaves_string_none_when_absent() -> None:
    due = Due.from_api({"date": "2026-07-21"})

    assert due.string is None
    assert due.lang is None


def test_to_api_recurring_includes_string_and_lang() -> None:
    due = Due(
        date=datetime.date(2026, 7, 21),
        is_recurring=True,
        string="every day",
        lang="en",
    )

    assert due.to_api == {"date": "2026-07-21", "string": "every day", "lang": "en"}


def test_to_api_non_recurring_omits_string_even_if_present() -> None:
    due = Due(date=datetime.date(2026, 7, 21), string="every day")

    assert due.to_api == {"date": "2026-07-21"}
