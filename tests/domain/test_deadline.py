import datetime

import pytest

from todoist_tui.domain.deadline import Deadline


def test_from_api_reads_date() -> None:
    deadline = Deadline.from_api({"date": "2026-08-15", "lang": "en"})

    assert deadline.date == datetime.date(2026, 8, 15)


def test_from_api_missing_date_raises() -> None:
    with pytest.raises(ValueError):
        Deadline.from_api({"lang": "en"})


def test_to_api_emits_date_only() -> None:
    deadline = Deadline(date=datetime.date(2026, 8, 15))

    assert deadline.to_api == {"date": "2026-08-15"}
