import datetime

import pytest

from todoist_tui.application.set_deadline import set_deadline
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(self) -> None:
        self.deadlines: list[tuple[TaskId, Deadline | None]] = []

    async def today(self) -> list[Task]:
        return []

    async def inbox(self) -> list[Task]:
        return []

    async def by_project(self, project_id: str) -> list[Task]:
        return []

    async def filtered(self, query: str) -> list[Task]:
        return []

    async def refresh_filtered(self, query: str) -> list[Task]:
        return []

    async def projects(self) -> list[Project]:
        return []

    async def sections(self) -> list[Section]:
        return []

    async def filters(self) -> list[Filter]:
        return []

    async def labels(self) -> list[Label]:
        return []

    async def complete(self, task_id: TaskId) -> None: ...

    async def uncomplete(self, task_id: TaskId) -> None: ...

    async def delete(self, task_id: TaskId) -> None: ...

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | None) -> None: ...

    async def set_deadline(self, task_id: TaskId, deadline: Deadline | None) -> None:
        self.deadlines.append((task_id, deadline))

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None: ...

    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None: ...

    async def refresh(self) -> None: ...


@pytest.mark.anyio
async def test_set_deadline_delegates_to_repo() -> None:
    repo = FakeRepository()
    deadline = Deadline(date=datetime.date(2026, 8, 15))

    await set_deadline(repo, TaskId("6X4"), deadline)

    assert repo.deadlines == [(TaskId("6X4"), deadline)]


@pytest.mark.anyio
async def test_set_deadline_clear_passes_none() -> None:
    repo = FakeRepository()

    await set_deadline(repo, TaskId("6X4"), None)

    assert repo.deadlines == [(TaskId("6X4"), None)]
