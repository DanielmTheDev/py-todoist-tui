import datetime

import pytest

from todoist_tui.application.add_task import add_task
from todoist_tui.domain.creation import CreationPlan, NewReminder, NewTask
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
    def __init__(self, projects: list[Project] | None = None) -> None:
        self._projects = projects or []
        self.applied: list[CreationPlan] = []

    async def projects(self) -> list[Project]:
        return self._projects

    async def apply_creation(self, plan: CreationPlan) -> None:
        self.applied.append(plan)

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

    async def sections(self) -> list[Section]:
        return []

    async def filters(self) -> list[Filter]:
        return []

    async def labels(self) -> list[Label]:
        return []

    async def reminders(self) -> list[Reminder]:
        return []

    async def complete(self, task_id: TaskId) -> None: ...

    async def uncomplete(self, task_id: TaskId) -> None: ...

    async def delete(self, task_id: TaskId) -> None: ...

    async def delete_section(self, section_id: str) -> None: ...

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | DueText | None) -> None: ...

    async def set_deadline(
        self, task_id: TaskId, deadline: Deadline | None
    ) -> None: ...

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None: ...

    async def set_parent(self, task_id: TaskId, parent_id: str) -> None: ...

    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None: ...

    async def set_text(
        self, task_id: TaskId, content: str, description: str
    ) -> None: ...

    async def add_reminder(self, reminder: Reminder) -> None: ...

    async def delete_reminder(self, reminder_id: str) -> None: ...

    async def refresh(self) -> None: ...


def _only_task(repo: FakeRepository) -> NewTask:
    assert len(repo.applied) == 1
    plan = repo.applied[0]
    assert plan.projects == () and plan.sections == ()
    assert len(plan.tasks) == 1
    return plan.tasks[0]


@pytest.mark.anyio
async def test_add_task_creates_one_task_where_it_was_asked_to() -> None:
    repo = FakeRepository()
    due = Due(date=datetime.date(2026, 8, 8))

    await add_task(
        repo,
        "Buy oat milk",
        description="2 cartons",
        project_id="P",
        section_id="s1",
        due=due,
        temp_ids=iter(["t-1"]),
    )

    assert _only_task(repo) == NewTask(
        temp_id="t-1",
        content="Buy oat milk",
        priority=Priority.P4,
        due=due,
        deadline=None,
        labels=(),
        description="2 cartons",
        child_order=None,  # Todoist appends it to the end of the list
        project_ref="P",
        section_ref="s1",
        parent_ref=None,
    )


@pytest.mark.anyio
async def test_add_task_under_a_parent_leaves_the_section_to_the_parent() -> None:
    repo = FakeRepository()

    await add_task(
        repo,
        "Rinse the jug",
        project_id="P",
        section_id="s1",
        parent_id="6X4",
        temp_ids=iter(["t-1"]),
    )

    task = _only_task(repo)
    assert (task.parent_ref, task.section_ref) == ("6X4", None)


@pytest.mark.anyio
async def test_add_task_without_a_project_lands_in_the_inbox() -> None:
    repo = FakeRepository(
        [Project(id="P", name="Work"), Project(id="I", name="Inbox", is_inbox=True)]
    )

    await add_task(repo, "Capture this", temp_ids=iter(["t-1"]))

    assert _only_task(repo).project_ref == "I"


@pytest.mark.anyio
async def test_add_task_raises_when_there_is_no_inbox() -> None:
    repo = FakeRepository([Project(id="P", name="Work")])

    with pytest.raises(LookupError):
        await add_task(repo, "Capture this", temp_ids=iter(["t-1"]))

    assert repo.applied == []


@pytest.mark.anyio
async def test_a_reminder_rides_along_in_the_creation_plan() -> None:
    """The task has no id yet, so its reminder points at the task's temp_id."""
    repo = FakeRepository(projects=[Project(id="220", name="Inbox", is_inbox=True)])

    await add_task(
        repo,
        "new",
        reminders=(Reminder("", "", "relative", minute_offset=30),),
        temp_ids=iter(["task", "rem"]),
    )

    plan = repo.applied[0]
    assert plan.reminders == (
        NewReminder("rem", "task", Reminder("", "", "relative", minute_offset=30)),
    )
