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
    query_for_key,
    search_view,
    view_from_key,
)
from todoist_tui.domain.arrange import Arrangement, Field
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.search import SearchTerm
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId


class FakeRepository:
    def __init__(
        self,
        today: list[Task],
        inbox: list[Task],
        projects: list[Project],
        sections: list[Section] | None = None,
        reminders: list[Reminder] | None = None,
    ) -> None:
        self._today = today
        self._inbox = inbox
        self._projects = projects
        self._sections = sections or []
        self._reminders = reminders or []

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

    async def labels(self) -> list[Label]:
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

    async def refresh(self) -> None: ...

    async def reminders(self) -> list[Reminder]:
        return self._reminders

    async def add_reminder(self, reminder: Reminder) -> None: ...

    async def delete_reminder(self, reminder_id: str) -> None: ...


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
async def test_load_view_joins_reminders_by_item_id() -> None:
    repo = FakeRepository(
        [_task("Buy milk", "220"), _task("Call", "220")],
        [],
        [Project(id="220", name="Errands")],
        reminders=[
            Reminder(id="r1", item_id="Buy milk", type="relative", minute_offset=30),
            Reminder(id="r2", item_id="Buy milk", type="relative", minute_offset=0),
        ],
    )

    rows = await load_view(repo, TODAY)

    by_content = {row.content: row for row in rows}
    assert [r.id for r in by_content["Buy milk"].reminders] == ["r1", "r2"]
    assert by_content["Call"].reminders == ()


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
async def test_load_view_resolves_section_order() -> None:
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
        [Section(id="s1", project_id="9", name="Planning", order=3)],
    )

    rows = await load_view(repo, TODAY)

    assert rows[0].section_order == 3


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


def test_project_view_defaults_to_grouping_by_section() -> None:
    view = project_view(Project(id="9", name="Work"))
    assert view.default_arrangement == Arrangement(group_by=(Field.SECTION,))


def test_today_view_has_no_default_grouping() -> None:
    assert TODAY.default_arrangement == Arrangement()


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


@pytest.mark.anyio
async def test_search_view_titled_by_term_fetches_via_search_query() -> None:
    repo = RecordingRepository([_task("hit", "220")])
    view = search_view(SearchTerm("milk"))

    tasks = await view.fetch(repo)

    assert view.title == "Search: milk"
    assert view.key == "search:milk"
    assert repo.queries == ["search: milk"]
    assert [str(t.id) for t in tasks] == ["hit"]


_PROJECTS = [Project(id="9", name="Work"), Project(id="220", name="Errands")]
_FILTERS = [Filter(id="f1", name="Work P1", query="@work & p1", order=1)]


def test_view_from_key_resolves_today() -> None:
    view = view_from_key("today", _PROJECTS, _FILTERS)
    assert view is TODAY


def test_view_from_key_resolves_inbox() -> None:
    view = view_from_key("inbox", _PROJECTS, _FILTERS)
    assert view is INBOX


def test_view_from_key_resolves_project() -> None:
    view = view_from_key("project:9", _PROJECTS, _FILTERS)
    assert view is not None
    assert view.key == "project:9"
    assert view.title == "Work"


def test_view_from_key_resolves_filter() -> None:
    view = view_from_key("filter:f1", _PROJECTS, _FILTERS)
    assert view is not None
    assert view.key == "filter:f1"
    assert view.title == "Work P1"


def test_view_from_key_resolves_search() -> None:
    view = view_from_key("search:milk", _PROJECTS, _FILTERS)
    assert view is not None
    assert view.key == "search:milk"
    assert view.title == "Search: milk"


def test_view_from_key_keeps_a_colon_inside_the_search_term() -> None:
    view = view_from_key("search:a:b", _PROJECTS, _FILTERS)
    assert view is not None
    assert view.title == "Search: a:b"


@pytest.mark.parametrize("key", ["search:", "search:m", "search:a&b"])
def test_view_from_key_unsearchable_term_is_none(key: str) -> None:
    # a stale or hand-edited home key must not be able to provoke a 400
    assert view_from_key(key, _PROJECTS, _FILTERS) is None


def test_query_for_key_reads_a_saved_filters_query() -> None:
    assert query_for_key("filter:f1", _FILTERS) == "@work & p1"


def test_query_for_key_rebuilds_a_search_query() -> None:
    assert query_for_key("search:milk", _FILTERS) == "search: milk"


@pytest.mark.parametrize("key", ["today", "inbox", "project:9", "search:a&b"])
def test_keys_evaluated_without_the_server_have_no_query(key: str) -> None:
    assert query_for_key(key, _FILTERS) is None


def test_view_from_key_unknown_project_is_none() -> None:
    assert view_from_key("project:999", _PROJECTS, _FILTERS) is None


def test_view_from_key_unknown_filter_is_none() -> None:
    assert view_from_key("filter:gone", _PROJECTS, _FILTERS) is None


@pytest.mark.parametrize("key", ["", "garbage", "project:", "unknown:9"])
def test_view_from_key_malformed_is_none(key: str) -> None:
    assert view_from_key(key, _PROJECTS, _FILTERS) is None


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

    async def labels(self) -> list[Label]:
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

    async def refresh(self) -> None: ...

    async def reminders(self) -> list[Reminder]:
        return []

    async def add_reminder(self, reminder: Reminder) -> None: ...

    async def delete_reminder(self, reminder_id: str) -> None: ...


@pytest.mark.anyio
async def test_load_view_fetches_tasks_and_projects_concurrently() -> None:
    rows = await asyncio.wait_for(load_view(BarrierRepository(), TODAY), timeout=1.0)

    assert [row.content for row in rows] == ["Buy milk"]
