import datetime
from collections.abc import Sequence

import pytest

from todoist_tui.application.set_due import set_due
from todoist_tui.domain.activity import ActivityPage, EventKind
from todoist_tui.domain.creation import CreationPlan
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(self) -> None:
        self.dues: list[tuple[TaskId, Due | DueText | None]] = []

    async def today(self) -> list[Task]:
        return []

    async def inbox(self) -> list[Task]:
        return []

    async def by_project(self, project_id: str) -> list[Task]:
        return []

    async def all_tasks(self) -> list[Task]:
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

    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        return ActivityPage(events=(), next_cursor=None)

    async def complete(self, task_id: TaskId) -> None: ...

    async def uncomplete(self, task_id: TaskId) -> None: ...

    async def delete(self, task_id: TaskId) -> None: ...

    async def delete_section(self, section_id: str) -> None: ...

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | DueText | None) -> None:
        self.dues.append((task_id, due))

    async def set_deadline(
        self, task_id: TaskId, deadline: Deadline | None
    ) -> None: ...

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None: ...

    async def set_parent(self, task_id: TaskId, parent_id: str) -> None: ...

    async def reorder(self, items: Sequence[tuple[TaskId, int]]) -> None: ...

    async def set_day_orders(self, items: Sequence[tuple[TaskId, int]]) -> None: ...

    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None: ...

    async def set_text(
        self, task_id: TaskId, content: str, description: str
    ) -> None: ...

    async def refresh(self) -> None: ...

    async def apply_creation(self, plan: CreationPlan) -> None: ...

    async def reminders(self) -> list[Reminder]:
        return []

    async def add_reminder(self, reminder: Reminder) -> None: ...

    async def delete_reminder(self, reminder_id: str) -> None: ...


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


@pytest.mark.anyio
async def test_set_due_passes_natural_language_through() -> None:
    repo = FakeRepository()
    text = DueText("every mon until Dec 31")

    await set_due(repo, TaskId("6X4"), text)

    assert repo.dues == [(TaskId("6X4"), text)]
