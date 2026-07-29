import pytest

from todoist_tui.application.complete import complete_task, uncomplete_task
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(self) -> None:
        self.completed: list[TaskId] = []
        self.uncompleted: list[TaskId] = []

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

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)

    async def uncomplete(self, task_id: TaskId) -> None:
        self.uncompleted.append(task_id)

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | None) -> None: ...

    async def set_project(self, task_id: TaskId, project_id: str) -> None: ...

    async def refresh(self) -> None: ...


@pytest.mark.anyio
async def test_complete_task_delegates_to_repo() -> None:
    repo = FakeRepository()

    await complete_task(repo, TaskId("6X4"))

    assert repo.completed == [TaskId("6X4")]


@pytest.mark.anyio
async def test_uncomplete_task_delegates_to_repo() -> None:
    repo = FakeRepository()

    await uncomplete_task(repo, TaskId("6X4"))

    assert repo.uncompleted == [TaskId("6X4")]
