import asyncio
import datetime

import pytest

from todoist_tui.application.views import (
    INBOX,
    TODAY,
    TaskRow,
    filter_view,
    load_view,
    project_view,
)
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(
        self,
        today: list[Task],
        inbox: list[Task],
        projects: list[Project],
        sections: list[Section] | None = None,
    ) -> None:
        self._today = today
        self._inbox = inbox
        self._projects = projects
        self._sections = sections or []

    async def today(self) -> list[Task]:
        return self._today

    async def inbox(self) -> list[Task]:
        return self._inbox

    async def by_project(self, project_id: str) -> list[Task]:
        return [t for t in self._today if t.project_id == project_id]

    async def filtered(self, query: str) -> list[Task]:
        return []

    async def refresh_filtered(self, query: str) -> list[Task]:
        return []

    async def projects(self) -> list[Project]:
        return self._projects

    async def sections(self) -> list[Section]:
        return self._sections

    async def filters(self) -> list[Filter]:
        return []

    async def complete(self, task_id: TaskId) -> None: ...

    async def uncomplete(self, task_id: TaskId) -> None: ...

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | None) -> None: ...

    async def set_deadline(
        self, task_id: TaskId, deadline: Deadline | None
    ) -> None: ...

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None: ...

    async def refresh(self) -> None: ...


def _task(content: str, project_id: str) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id=project_id,
    )


@pytest.mark.anyio
async def test_load_today_view_joins_project_name() -> None:
    repo = FakeRepository(
        [_task("Buy milk", "220")], [], [Project(id="220", name="Errands")]
    )

    rows = await load_view(repo, TODAY)

    assert rows == [
        TaskRow(
            id=TaskId("Buy milk"),
            content="Buy milk",
            priority=Priority.P2,
            due=Due(date=datetime.date(2026, 7, 21)),
            project_name="Errands",
            project_id="220",
        )
    ]


@pytest.mark.anyio
async def test_load_inbox_view_uses_inbox_tasks() -> None:
    repo = FakeRepository(
        [_task("Today thing", "220")],
        [_task("Inbox thing", "220")],
        [Project(id="220", name="Errands")],
    )

    rows = await load_view(repo, INBOX)

    assert [row.content for row in rows] == ["Inbox thing"]


@pytest.mark.anyio
async def test_load_view_resolves_section_name() -> None:
    task = Task(
        id=TaskId("x"),
        content="In a section",
        priority=Priority.P2,
        due=None,
        project_id="9",
        section_id="s1",
    )
    repo = FakeRepository(
        [task],
        [],
        [Project(id="9", name="Work")],
        [Section(id="s1", project_id="9", name="Planning")],
    )

    rows = await load_view(repo, TODAY)

    assert rows[0].section_name == "Planning"


@pytest.mark.anyio
async def test_load_view_no_section_yields_none_name() -> None:
    repo = FakeRepository([_task("Rootless", "9")], [], [Project(id="9", name="Work")])

    rows = await load_view(repo, TODAY)

    assert rows[0].section_name is None


@pytest.mark.anyio
async def test_load_view_carries_labels() -> None:
    tagged = Task(
        id=TaskId("x"),
        content="Tagged",
        priority=Priority.P2,
        due=None,
        project_id="220",
        labels=("home", "urgent"),
    )
    repo = FakeRepository([tagged], [], [Project(id="220", name="Errands")])

    rows = await load_view(repo, TODAY)

    assert rows[0].labels == ("home", "urgent")


@pytest.mark.anyio
async def test_load_view_carries_description() -> None:
    noted = Task(
        id=TaskId("x"),
        content="Noted",
        priority=Priority.P2,
        due=None,
        project_id="220",
        description="the full story",
    )
    repo = FakeRepository([noted], [], [Project(id="220", name="Errands")])

    rows = await load_view(repo, TODAY)

    assert rows[0].description == "the full story"


@pytest.mark.anyio
async def test_load_view_carries_parent_id() -> None:
    child = Task(
        id=TaskId("x"),
        content="A subtask",
        priority=Priority.P2,
        due=None,
        project_id="220",
        parent_id="p",
    )
    repo = FakeRepository([child], [], [Project(id="220", name="Errands")])

    rows = await load_view(repo, TODAY)

    assert rows[0].parent_id == "p"


@pytest.mark.anyio
async def test_load_view_missing_project_yields_none_name() -> None:
    repo = FakeRepository(
        [_task("Orphan", "999")], [], [Project(id="220", name="Errands")]
    )

    rows = await load_view(repo, TODAY)

    assert rows[0].project_name is None


@pytest.mark.anyio
async def test_load_view_empty() -> None:
    repo = FakeRepository([], [], [])

    assert await load_view(repo, TODAY) == []


def test_view_titles() -> None:
    assert TODAY.title == "Today"
    assert INBOX.title == "Inbox"


def test_view_keys_are_stable_identities() -> None:
    assert TODAY.key == "today"
    assert INBOX.key == "inbox"
    assert (
        filter_view(Filter(id="f1", name="Work", query="@work", order=1)).key
        == "filter:f1"
    )
    assert project_view(Project(id="9", name="Work")).key == "project:9"


@pytest.mark.anyio
async def test_project_view_titled_by_name_fetches_its_tasks() -> None:
    repo = FakeRepository(
        [_task("mine", "9"), _task("other", "220")], [], [Project(id="9", name="Work")]
    )
    view = project_view(Project(id="9", name="Work"))

    tasks = await view.fetch(repo)

    assert view.title == "Work"
    assert [str(t.id) for t in tasks] == ["mine"]


def test_project_view_keeps_only_matching_rows() -> None:
    view = project_view(Project(id="9", name="Work"))
    assert view.keeps is not None
    mine = TaskRow(
        id=TaskId("x"),
        content="x",
        priority=Priority.P2,
        due=None,
        project_name="Work",
        project_id="9",
    )
    moved = TaskRow(
        id=TaskId("y"),
        content="y",
        priority=Priority.P2,
        due=None,
        project_name="Errands",
        project_id="220",
    )
    today = datetime.date(2026, 7, 31)
    assert view.keeps(mine, today) is True
    assert view.keeps(moved, today) is False


class RecordingRepository(FakeRepository):
    def __init__(self, result: list[Task]) -> None:
        super().__init__([], [], [])
        self.queries: list[str] = []
        self._result = result

    async def filtered(self, query: str) -> list[Task]:
        self.queries.append(query)
        return self._result


@pytest.mark.anyio
async def test_filter_view_titled_by_name_fetches_via_query() -> None:
    repo = RecordingRepository([_task("hit", "220")])
    view = filter_view(Filter(id="f1", name="Work P1", query="@work & p1", order=1))

    tasks = await view.fetch(repo)

    assert view.title == "Work P1"
    assert repo.queries == ["@work & p1"]
    assert [str(t.id) for t in tasks] == ["hit"]


class BarrierRepository:
    """Each fetch waits for the other to start — deadlocks unless run concurrently."""

    def __init__(self) -> None:
        self._today_started = asyncio.Event()
        self._projects_started = asyncio.Event()

    async def today(self) -> list[Task]:
        self._today_started.set()
        await self._projects_started.wait()
        return [_task("Buy milk", "220")]

    async def inbox(self) -> list[Task]:
        return []

    async def by_project(self, project_id: str) -> list[Task]:
        return []

    async def projects(self) -> list[Project]:
        self._projects_started.set()
        await self._today_started.wait()
        return [Project(id="220", name="Errands")]

    async def sections(self) -> list[Section]:
        return []

    async def filtered(self, query: str) -> list[Task]:
        return []

    async def refresh_filtered(self, query: str) -> list[Task]:
        return []

    async def filters(self) -> list[Filter]:
        return []

    async def complete(self, task_id: TaskId) -> None: ...

    async def uncomplete(self, task_id: TaskId) -> None: ...

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | None) -> None: ...

    async def set_deadline(
        self, task_id: TaskId, deadline: Deadline | None
    ) -> None: ...

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None: ...

    async def refresh(self) -> None: ...


@pytest.mark.anyio
async def test_load_view_fetches_tasks_and_projects_concurrently() -> None:
    rows = await asyncio.wait_for(load_view(BarrierRepository(), TODAY), timeout=1.0)

    assert [row.content for row in rows] == ["Buy milk"]
