import datetime

import pytest

from todoist_tui.application.views import INBOX, TODAY, TaskRow, load_view
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(
        self,
        today: list[Task],
        inbox: list[Task],
        projects: list[Project],
    ) -> None:
        self._today = today
        self._inbox = inbox
        self._projects = projects

    async def today(self) -> list[Task]:
        return self._today

    async def inbox(self) -> list[Task]:
        return self._inbox

    async def projects(self) -> list[Project]:
        return self._projects

    async def complete(self, task_id: TaskId) -> None: ...


def _task(content: str, project_id: str) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id=project_id,
    )


@pytest.mark.anyio
async def test_load_today_view_joins_project_name() -> None:
    repo = FakeRepository(
        [_task("Buy milk", "220")], [], [Project(id="220", name="Errands")]
    )

    rows = await load_view(repo, TODAY)

    assert rows == [
        TaskRow(
            id=TaskId("Buy milk"),
            content="Buy milk",
            priority=Priority.P2,
            due=Due(date=datetime.date(2026, 7, 21)),
            project_name="Errands",
        )
    ]


@pytest.mark.anyio
async def test_load_inbox_view_uses_inbox_tasks() -> None:
    repo = FakeRepository(
        [_task("Today thing", "220")],
        [_task("Inbox thing", "220")],
        [Project(id="220", name="Errands")],
    )

    rows = await load_view(repo, INBOX)

    assert [row.content for row in rows] == ["Inbox thing"]


@pytest.mark.anyio
async def test_load_view_missing_project_yields_none_name() -> None:
    repo = FakeRepository(
        [_task("Orphan", "999")], [], [Project(id="220", name="Errands")]
    )

    rows = await load_view(repo, TODAY)

    assert rows[0].project_name is None


@pytest.mark.anyio
async def test_load_view_empty() -> None:
    repo = FakeRepository([], [], [])

    assert await load_view(repo, TODAY) == []


def test_view_titles() -> None:
    assert TODAY.title == "Today"
    assert INBOX.title == "Inbox"
