import datetime
from collections.abc import Sequence

import pytest

from todoist_tui.application.set_due import schedule, set_due
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
        self.added: list[Reminder] = []
        self.calls: list[str] = []
        self.landed_due: Due | None = None

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

    async def set_due(self, task_id: TaskId, due: Due | DueText | None) -> Due | None:
        self.dues.append((task_id, due))
        self.calls.append("set_due")
        return self.landed_due

    async def set_deadline(
        self, task_id: TaskId, deadline: Deadline | None
    ) -> None: ...

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None: ...

    async def set_parent(self, task_id: TaskId, parent_id: str) -> None: ...

    async def reorder(self, items: Sequence[tuple[TaskId, int]]) -> None: ...

    async def reorder_sections(self, sections: Sequence[tuple[str, int]]) -> None: ...

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

    async def add_reminder(self, reminder: Reminder) -> None:
        self.added.append(reminder)
        self.calls.append("add_reminder")

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


@pytest.mark.anyio
async def test_schedule_gives_a_timed_task_the_default_reminder() -> None:
    """Todoist's Sync API never makes one, so a task scheduled here would stay
    silent at its due time."""
    repo = FakeRepository()
    repo.landed_due = Due(date=datetime.date(2026, 9, 7), time=datetime.time(10, 0))

    await schedule(repo, TaskId("6X4"), DueText("tod 10:00"))

    assert repo.added == [
        Reminder(id="", item_id="6X4", type="relative", minute_offset=0)
    ]


@pytest.mark.anyio
async def test_schedule_leaves_an_all_day_task_without_a_reminder() -> None:
    repo = FakeRepository()
    repo.landed_due = Due(date=datetime.date(2026, 9, 7))

    await schedule(repo, TaskId("6X4"), DueText("today"))

    assert repo.added == []


@pytest.mark.anyio
async def test_schedule_adds_no_reminder_when_the_task_already_has_one() -> None:
    repo = FakeRepository()
    repo.landed_due = Due(date=datetime.date(2026, 9, 7), time=datetime.time(10, 0))
    own = Reminder(id="r1", item_id="6X4", type="relative", minute_offset=30)

    await schedule(repo, TaskId("6X4"), DueText("tod 10:00"), (own,))

    assert repo.added == []


@pytest.mark.anyio
async def test_schedule_adds_the_reminder_after_the_due_it_needs() -> None:
    """Todoist refuses a relative reminder on a task with no due time, so the
    order of the two commands is the behaviour, not an implementation detail."""
    repo = FakeRepository()
    repo.landed_due = Due(date=datetime.date(2026, 9, 7), time=datetime.time(10, 0))

    await schedule(repo, TaskId("6X4"), DueText("tod 10:00"))

    assert repo.calls == ["set_due", "add_reminder"]


@pytest.mark.anyio
async def test_set_due_alone_adds_no_reminder() -> None:
    """The plain write is what an undo restores; it must create nothing."""
    repo = FakeRepository()
    repo.landed_due = Due(date=datetime.date(2026, 9, 7), time=datetime.time(10, 0))

    await set_due(repo, TaskId("6X4"), DueText("tod 10:00"))

    assert repo.added == []
