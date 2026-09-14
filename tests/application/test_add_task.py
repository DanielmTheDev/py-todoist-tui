import datetime
from collections.abc import Sequence

import pytest

from todoist_tui.application.add_task import add_task
from todoist_tui.domain.activity import ActivityPage, EventKind
from todoist_tui.domain.creation import (
    CreationPlan,
    NewChild,
    NewReminder,
    NewTask,
)
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder, default_reminder
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

    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        return ActivityPage(events=(), next_cursor=None)

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

    async def reorder(self, items: Sequence[tuple[TaskId, int]]) -> None: ...

    async def reorder_sections(self, sections: Sequence[tuple[str, int]]) -> None: ...

    async def set_day_orders(self, items: Sequence[tuple[TaskId, int]]) -> None: ...

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


@pytest.mark.anyio
async def test_a_due_time_earns_the_default_reminder() -> None:
    repo = FakeRepository(projects=[Project(id="220", name="Inbox", is_inbox=True)])

    await add_task(
        repo,
        "new",
        due=Due(date=datetime.date(2030, 1, 1), time=datetime.time(9, 0)),
        temp_ids=iter(["task", "rem"]),
    )

    assert repo.applied[0].reminders == (
        NewReminder("rem", "task", default_reminder()),
    )


@pytest.mark.anyio
async def test_an_all_day_due_earns_no_reminder() -> None:
    repo = FakeRepository(projects=[Project(id="220", name="Inbox", is_inbox=True)])

    await add_task(
        repo, "new", due=Due(date=datetime.date(2030, 1, 1)), temp_ids=iter(["task"])
    )

    assert repo.applied[0].reminders == ()


@pytest.mark.anyio
async def test_a_chosen_reminder_beats_the_default() -> None:
    repo = FakeRepository(projects=[Project(id="220", name="Inbox", is_inbox=True)])
    chosen = Reminder("", "", "relative", minute_offset=30)

    await add_task(
        repo,
        "new",
        due=Due(date=datetime.date(2030, 1, 1), time=datetime.time(9, 0)),
        reminders=(chosen,),
        temp_ids=iter(["task", "rem"]),
    )

    assert repo.applied[0].reminders == (NewReminder("rem", "task", chosen),)


@pytest.mark.anyio
async def test_subtasks_ride_in_the_same_plan_under_the_new_task() -> None:
    """The parent has no id yet, so each subtask points at its temp_id."""
    repo = FakeRepository()

    await add_task(
        repo,
        "Ship release",
        project_id="P",
        section_id="s1",
        subtasks=(NewChild("tag version"), NewChild("write changelog")),
        temp_ids=iter(["parent", "kid-1", "kid-2"]),
    )

    plan = repo.applied[0]
    parent, *children = plan.tasks
    assert parent.temp_id == "parent"
    assert [(c.temp_id, c.content, c.parent_ref, c.section_ref) for c in children] == [
        ("kid-1", "tag version", "parent", None),
        ("kid-2", "write changelog", "parent", None),
    ]
    assert {c.project_ref for c in children} == {"P"}


@pytest.mark.anyio
async def test_a_subtask_carries_its_own_attributes_into_the_batch() -> None:
    repo = FakeRepository()
    due = Due(date=datetime.date(2026, 8, 8))
    deadline = Deadline(date=datetime.date(2026, 8, 9))

    await add_task(
        repo,
        "Ship release",
        project_id="P",
        subtasks=(
            NewChild(
                "tag version",
                description="annotated",
                priority=Priority.P1,
                due=due,
                deadline=deadline,
                labels=("work",),
            ),
        ),
        temp_ids=iter(["parent", "kid-1"]),
    )

    child = repo.applied[0].tasks[1]
    assert (child.due, child.deadline, child.labels, child.description) == (
        due,
        deadline,
        ("work",),
        "annotated",
    )
    assert child.priority is Priority.P1


@pytest.mark.anyio
async def test_a_subtask_keeps_the_parents_place_but_not_its_attributes() -> None:
    repo = FakeRepository()

    await add_task(
        repo,
        "Ship release",
        description="the 2.1 cut",
        project_id="P",
        due=Due(date=datetime.date(2026, 8, 8)),
        priority=Priority.P1,
        labels=("work",),
        subtasks=(NewChild("tag version"),),
        temp_ids=iter(["parent", "kid-1"]),
    )

    child = repo.applied[0].tasks[1]
    assert (child.due, child.labels, child.description, child.priority) == (
        None,
        (),
        "",
        Priority.P4,
    )


@pytest.mark.anyio
async def test_a_subtasks_own_reminder_points_at_the_subtask() -> None:
    repo = FakeRepository()

    await add_task(
        repo,
        "Ship release",
        project_id="P",
        subtasks=(
            NewChild(
                "tag version",
                reminders=(Reminder("", "", "relative", minute_offset=30),),
            ),
        ),
        temp_ids=iter(["parent", "kid-1", "rem"]),
    )

    assert repo.applied[0].reminders == (
        NewReminder("rem", "kid-1", Reminder("", "", "relative", minute_offset=30)),
    )


@pytest.mark.anyio
async def test_a_reminder_still_points_at_the_parent_past_its_subtasks() -> None:
    repo = FakeRepository(projects=[Project(id="220", name="Inbox", is_inbox=True)])

    await add_task(
        repo,
        "Ship release",
        reminders=(Reminder("", "", "relative", minute_offset=30),),
        subtasks=(NewChild("tag version"),),
        temp_ids=iter(["parent", "rem", "kid-1"]),
    )

    assert repo.applied[0].reminders[0] == NewReminder(
        "rem", "parent", Reminder("", "", "relative", minute_offset=30)
    )
