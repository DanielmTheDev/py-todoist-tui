import datetime

import pytest

from todoist_tui.application.today import TodayRow, load_today
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(self, tasks: list[Task], projects: list[Project]) -> None:
        self._tasks = tasks
        self._projects = projects

    async def today(self) -> list[Task]:
        return self._tasks

    async def projects(self) -> list[Project]:
        return self._projects


def _task(content: str, project_id: str) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id=project_id,
    )


@pytest.mark.anyio
async def test_load_today_joins_project_name() -> None:
    repo = FakeRepository(
        [_task("Buy milk", "220")], [Project(id="220", name="Errands")]
    )

    rows = await load_today(repo)

    assert rows == [
        TodayRow(
            content="Buy milk",
            priority=Priority.P2,
            due=Due(date=datetime.date(2026, 7, 21)),
            project_name="Errands",
        )
    ]


@pytest.mark.anyio
async def test_load_today_missing_project_yields_none_name() -> None:
    repo = FakeRepository([_task("Orphan", "999")], [Project(id="220", name="Errands")])

    rows = await load_today(repo)

    assert rows[0].project_name is None


@pytest.mark.anyio
async def test_load_today_empty() -> None:
    repo = FakeRepository([], [])

    assert await load_today(repo) == []
