import pytest

from todoist_tui.application.complete import complete_task
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(self) -> None:
        self.completed: list[TaskId] = []

    async def today(self) -> list[Task]:
        return []

    async def projects(self) -> list[Project]:
        return []

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)


@pytest.mark.anyio
async def test_complete_task_delegates_to_repo() -> None:
    repo = FakeRepository()

    await complete_task(repo, TaskId("6X4"))

    assert repo.completed == [TaskId("6X4")]
