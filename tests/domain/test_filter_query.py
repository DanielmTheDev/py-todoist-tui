import datetime

import pytest

from todoist_tui.domain.due import Due
from todoist_tui.domain.filter_query import FilterQuery
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.task import Task, TaskId

TODAY = datetime.date(2026, 7, 23)


def _task(due: Due | None) -> Task:
    return Task(
        id=TaskId("x"),
        content="x",
        priority=Priority.P2,
        due=due,
        project_id="9",
    )


def test_today_matches_task_due_today() -> None:
    assert FilterQuery("today").matches(_task(Due(date=TODAY)), TODAY)


def test_today_matches_timed_task_due_today() -> None:
    due = Due(date=TODAY, time=datetime.time(9, 30))
    assert FilterQuery("today").matches(_task(due), TODAY)


def test_today_rejects_other_day() -> None:
    other = Due(date=datetime.date(2026, 7, 24))
    assert not FilterQuery("today").matches(_task(other), TODAY)


def test_today_rejects_task_without_due() -> None:
    assert not FilterQuery("today").matches(_task(None), TODAY)


def test_unsupported_query_raises() -> None:
    with pytest.raises(ValueError, match="unsupported filter query"):
        FilterQuery("p1").matches(_task(None), TODAY)
