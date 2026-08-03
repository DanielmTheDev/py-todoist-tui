import pytest

from todoist_tui.application.move_task import move_task
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(self) -> None:
        self.moves: list[tuple[TaskId, str, str | None]] = []

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

    async def complete(self, task_id: TaskId) -> None: ...

    async def uncomplete(self, task_id: TaskId) -> None: ...

    async def delete(self, task_id: TaskId) -> None: ...

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | None) -> None: ...

    async def set_deadline(
        self, task_id: TaskId, deadline: Deadline | None
    ) -> None: ...

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        self.moves.append((task_id, project_id, section_id))

    async def refresh(self) -> None: ...


@pytest.mark.anyio
async def test_move_task_delegates_to_repo() -> None:
    repo = FakeRepository()

    await move_task(repo, TaskId("6X4"), "220")

    assert repo.moves == [(TaskId("6X4"), "220", None)]


@pytest.mark.anyio
async def test_move_task_forwards_section_id() -> None:
    repo = FakeRepository()

    await move_task(repo, TaskId("6X4"), "220", "77")

    assert repo.moves == [(TaskId("6X4"), "220", "77")]
