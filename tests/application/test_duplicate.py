import itertools
from collections.abc import Iterator

import pytest

from todoist_tui.application.duplicate import duplicate_project, duplicate_section
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.duplication import (
    DuplicationPlan,
    build_project_duplicate,
    build_section_duplicate,
)
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId


def _temp_ids() -> Iterator[str]:
    return (f"t{i}" for i in itertools.count())


def _task(id: str, *, project_id: str, section_id: str | None = None) -> Task:
    return Task(
        id=TaskId(id),
        content=f"task {id}",
        priority=Priority.P4,
        due=None,
        project_id=project_id,
        section_id=section_id,
    )


class FakeRepository:
    def __init__(
        self,
        projects: list[Project],
        sections: list[Section],
        tasks: dict[str, list[Task]],
    ) -> None:
        self._projects = projects
        self._sections = sections
        self._tasks = tasks
        self.applied: list[DuplicationPlan] = []

    async def projects(self) -> list[Project]:
        return self._projects

    async def sections(self) -> list[Section]:
        return self._sections

    async def by_project(self, project_id: str) -> list[Task]:
        return self._tasks.get(project_id, [])

    async def apply_creation(self, plan: DuplicationPlan) -> None:
        self.applied.append(plan)

    async def today(self) -> list[Task]:
        return []

    async def inbox(self) -> list[Task]:
        return []

    async def filtered(self, query: str) -> list[Task]:
        return []

    async def refresh_filtered(self, query: str) -> list[Task]:
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

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | None) -> None: ...

    async def set_deadline(
        self, task_id: TaskId, deadline: Deadline | None
    ) -> None: ...

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None: ...

    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None: ...

    async def add_reminder(self, reminder: Reminder) -> None: ...

    async def delete_reminder(self, reminder_id: str) -> None: ...

    async def refresh(self) -> None: ...


@pytest.mark.anyio
async def test_duplicate_project_builds_plan_from_its_own_sections_and_tasks() -> None:
    project = Project(id="P", name="Work")
    sections = [
        Section(id="s1", project_id="P", name="Now", order=1),
        Section(id="other", project_id="Q", name="Elsewhere", order=1),
    ]
    tasks = [_task("a", project_id="P", section_id="s1"), _task("b", project_id="P")]
    repo = FakeRepository(
        [project, Project(id="Q", name="Other")], sections, {"P": tasks}
    )

    await duplicate_project(repo, "P", "Work (copy)", temp_ids=_temp_ids())

    expected = build_project_duplicate(
        project, [sections[0]], tasks, "Work (copy)", _temp_ids()
    )
    assert repo.applied == [expected]


@pytest.mark.anyio
async def test_duplicate_project_raises_when_project_missing() -> None:
    repo = FakeRepository([Project(id="P", name="Work")], [], {})

    with pytest.raises(LookupError):
        await duplicate_project(repo, "nope", "x", temp_ids=_temp_ids())


@pytest.mark.anyio
async def test_duplicate_section_builds_plan_from_that_sections_tasks() -> None:
    section = Section(id="s1", project_id="P", name="Now", order=2)
    in_section = _task("a", project_id="P", section_id="s1")
    elsewhere = _task("b", project_id="P", section_id="s2")
    repo = FakeRepository([], [section], {"P": [in_section, elsewhere]})

    await duplicate_section(repo, section, "Now (copy)", temp_ids=_temp_ids())

    expected = build_section_duplicate(section, [in_section], "Now (copy)", _temp_ids())
    assert repo.applied == [expected]
