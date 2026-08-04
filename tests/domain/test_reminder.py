import datetime

import pytest

from todoist_tui.domain.due import Due
from todoist_tui.domain.reminder import Reminder


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


def test_to_api_emits_relative_args() -> None:
    reminder = Reminder(id="", item_id="t1", type="relative", minute_offset=30)

    assert reminder.to_api == {"type": "relative", "minute_offset": 30}


def test_to_api_absolute_without_due_raises() -> None:
    with pytest.raises(ValueError):
        _ = Reminder(id="", item_id="t1", type="absolute").to_api


def test_to_api_relative_without_offset_raises() -> None:
    with pytest.raises(ValueError):
        _ = Reminder(id="", item_id="t1", type="relative").to_api
