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
