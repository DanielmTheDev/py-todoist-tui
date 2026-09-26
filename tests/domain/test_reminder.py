import datetime

import pytest

from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.reminder import (
    Reminder,
    default_reminder,
    wants_default_reminder,
)


def test_from_api_reads_an_absolute_reminder() -> None:
    reminder = Reminder.from_api(
        {
            "id": "r1",
            "item_id": "t1",
            "type": "absolute",
            "due": {"date": "2030-01-01T08:30:00"},
            "notify_uid": "52617323",
        }
    )

    assert reminder.id == "r1"
    assert reminder.item_id == "t1"
    assert reminder.type == "absolute"
    assert reminder.due == Due(
        date=datetime.date(2030, 1, 1), time=datetime.time(8, 30)
    )
    assert reminder.minute_offset is None
    assert reminder.notify_uid == "52617323"


def test_from_api_reads_a_relative_reminder() -> None:
    reminder = Reminder.from_api(
        {"id": "r2", "item_id": "t1", "type": "relative", "minute_offset": 30}
    )

    assert reminder.type == "relative"
    assert reminder.minute_offset == 30
    assert reminder.due is None


def test_from_api_coerces_numeric_ids_to_str() -> None:
    reminder = Reminder.from_api(
        {"id": 7, "item_id": 42, "type": "relative", "minute_offset": 0}
    )

    assert reminder.id == "7"
    assert reminder.item_id == "42"


def test_from_api_missing_id_raises() -> None:
    with pytest.raises(ValueError):
        Reminder.from_api({"item_id": "t1", "type": "relative", "minute_offset": 0})


def test_to_api_emits_absolute_args() -> None:
    reminder = Reminder(
        id="",
        item_id="t1",
        type="absolute",
        due=Due(date=datetime.date(2030, 1, 1), time=datetime.time(8, 30)),
    )

    assert reminder.to_api == {
        "type": "absolute",
        "due": {"date": "2030-01-01T08:30:00"},
    }


def test_to_api_sends_a_phrase_for_the_server_to_parse() -> None:
    reminder = Reminder(
        id="", item_id="t1", type="absolute", due=DueText("every day at 9am")
    )

    assert reminder.to_api == {
        "type": "absolute",
        "due": {"string": "every day at 9am"},
    }


def test_from_api_keeps_a_recurring_rule() -> None:
    reminder = Reminder.from_api(
        {
            "id": "r1",
            "item_id": "t1",
            "type": "absolute",
            "due": {
                "date": "2026-09-28T18:00:00",
                "is_recurring": True,
                "string": "every mon 18:00",
                "lang": "en",
            },
        }
    )

    assert reminder.due == Due(
        date=datetime.date(2026, 9, 28),
        time=datetime.time(18, 0),
        is_recurring=True,
        string="every mon 18:00",
        lang="en",
    )


def test_to_api_emits_relative_args() -> None:
    reminder = Reminder(id="", item_id="t1", type="relative", minute_offset=30)

    assert reminder.to_api == {"type": "relative", "minute_offset": 30}


def test_to_api_absolute_without_due_raises() -> None:
    with pytest.raises(ValueError):
        _ = Reminder(id="", item_id="t1", type="absolute").to_api


def test_to_api_relative_without_offset_raises() -> None:
    with pytest.raises(ValueError):
        _ = Reminder(id="", item_id="t1", type="relative").to_api


def test_default_reminder_fires_at_the_due_time() -> None:
    reminder = default_reminder()

    assert reminder.type == "relative"
    assert reminder.minute_offset == 0
    assert reminder.id == ""
    assert reminder.item_id == ""


def test_wants_the_default_for_a_task_due_at_a_time() -> None:
    timed = Due(date=datetime.date(2030, 1, 1), time=datetime.time(9, 0))

    assert wants_default_reminder(timed, ())


def test_wants_no_default_for_an_all_day_due() -> None:
    """Todoist refuses a relative reminder on a task with no due time."""
    assert not wants_default_reminder(Due(date=datetime.date(2030, 1, 1)), ())


def test_wants_no_default_when_a_reminder_already_exists() -> None:
    timed = Due(date=datetime.date(2030, 1, 1), time=datetime.time(9, 0))
    existing = Reminder(id="r1", item_id="t1", type="relative", minute_offset=30)

    assert not wants_default_reminder(timed, (existing,))


def test_wants_the_default_when_only_the_time_changed() -> None:
    """A task moved from one time to another still earns it: what matters is
    that it now has a time and nothing reminds about it."""
    timed = Due(date=datetime.date(2030, 1, 1), time=datetime.time(10, 0))

    assert wants_default_reminder(timed, ())


def test_wants_no_default_when_the_due_is_cleared() -> None:
    assert not wants_default_reminder(None, ())
