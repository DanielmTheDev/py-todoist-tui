import datetime

import pytest

from todoist_tui.application.set_due import set_due
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(self) -> None:
        self.dues: list[tuple[TaskId, Due | None]] = []

    async def today(self) -> list[Task]:
        return []

    async def inbox(self) -> list[Task]:
        return []

    async def filtered(self, query: str) -> list[Task]:
        return []

    async def refresh_filtered(self, query: str) -> list[Task]:
        return []

    async def projects(self) -> list[Project]:
        return []

    async def filters(self) -> list[Filter]:
        return []

    async def complete(self, task_id: TaskId) -> None: ...

    async def uncomplete(self, task_id: TaskId) -> None: ...

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | None) -> None:
        self.dues.append((task_id, due))

    async def set_project(self, task_id: TaskId, project_id: str) -> None: ...

    async def refresh(self) -> None: ...


@pytest.mark.anyio
async def test_set_due_delegates_to_repo() -> None:
    repo = FakeRepository()
    due = Due(date=datetime.date(2026, 7, 29))

    await set_due(repo, TaskId("6X4"), due)

    assert repo.dues == [(TaskId("6X4"), due)]


@pytest.mark.anyio
async def test_set_due_clear_passes_none() -> None:
    repo = FakeRepository()

    await set_due(repo, TaskId("6X4"), None)

    assert repo.dues == [(TaskId("6X4"), None)]
