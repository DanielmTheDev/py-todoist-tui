import asyncio
import datetime
from collections.abc import Sequence

import pytest

from todoist_tui.application.views import (
    ALL,
    INBOX,
    TODAY,
    TaskRow,
    all_views,
    filter_view,
    load_view,
    project_view,
    prune,
    query_for_key,
    search_view,
    section_view,
    view_from_key,
    with_subtrees,
)
from todoist_tui.domain.activity import ActivityPage, EventKind
from todoist_tui.domain.arrange import Arrangement, Field
from todoist_tui.domain.comment import Attachment, Comment
from todoist_tui.domain.creation import CreationPlan
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.search import SearchTerm, parse_search
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
        all_tasks: list[Task] | None = None,
    ) -> None:
        self._today = today
        self._inbox = inbox
        self._projects = projects
        self._sections = sections or []
        self._reminders = reminders or []
        self._all_tasks = all_tasks if all_tasks is not None else [*today, *inbox]

    async def today(self) -> list[Task]:
        return self._today

    async def all_tasks(self) -> list[Task]:
        return self._all_tasks

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

    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        return ActivityPage(events=(), next_cursor=None)

    async def comments(self, task_id: TaskId) -> list[Comment]:
        return []

    async def add_comment(
        self, task_id: TaskId, content: str, attachment: Attachment | None = None
    ) -> None: ...

    async def delete_comment(self, comment_id: str) -> None: ...

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

    async def refresh(self) -> None: ...

    async def apply_creation(self, plan: CreationPlan) -> None: ...

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
async def test_load_all_view_uses_every_open_task() -> None:
    repo = FakeRepository(
        [_task("Today thing", "220")],
        [_task("Inbox thing", "9")],
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
    )

    rows = await load_view(repo, ALL)

    assert [(row.content, row.project_name) for row in rows] == [
        ("Today thing", "Errands"),
        ("Inbox thing", "Work"),
    ]


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
async def test_load_view_carries_child_order() -> None:
    """Manual ordering needs the task's place among its siblings on the row."""
    task = Task(
        id=TaskId("x"),
        content="Third",
        priority=Priority.P2,
        due=None,
        project_id="9",
        child_order=3,
    )
    repo = FakeRepository([task], [], [Project(id="9", name="Work")])

    rows = await load_view(repo, TODAY)

    assert rows[0].child_order == 3


@pytest.mark.anyio
async def test_load_view_carries_day_order() -> None:
    """A day-scoped view orders across projects, so the row needs day_order too."""
    task = Task(
        id=TaskId("x"),
        content="Second today",
        priority=Priority.P2,
        due=None,
        project_id="9",
        day_order=2,
    )
    repo = FakeRepository([task], [], [Project(id="9", name="Work")])

    rows = await load_view(repo, TODAY)

    assert rows[0].day_order == 2


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


def _subtask(content: str, parent_id: str, project_id: str = "220") -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P2,
        due=None,
        project_id=project_id,
        parent_id=parent_id,
    )


@pytest.mark.anyio
async def test_load_view_pulls_in_subtasks_of_a_match() -> None:
    parent = _task("Buy milk", "220")
    child = _subtask("Find the shop", parent_id="Buy milk")
    repo = FakeRepository(
        [parent], [], [Project(id="220", name="Errands")], all_tasks=[parent, child]
    )

    rows = await load_view(repo, TODAY)

    assert [(row.content, row.matched) for row in rows] == [
        ("Buy milk", True),
        ("Find the shop", False),
    ]


@pytest.mark.anyio
async def test_load_view_leaves_a_matching_subtask_a_member() -> None:
    parent = _task("Buy milk", "220")
    child = _subtask("Find the shop", parent_id="Buy milk")
    repo = FakeRepository(
        [parent, child],
        [],
        [Project(id="220", name="Errands")],
        all_tasks=[parent, child],
    )

    rows = await load_view(repo, TODAY)

    assert all(row.matched for row in rows)


def _pulled_in(content: str, parent_id: str) -> TaskRow:
    return TaskRow(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=None,
        project_name="Work",
        parent_id=parent_id,
        matched=False,
    )


def _member(content: str, parent_id: str | None = None) -> TaskRow:
    return TaskRow(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=None,
        project_name="Work",
        parent_id=parent_id,
    )


def test_prune_drops_the_members_that_left() -> None:
    rows = [_member("stays"), _member("goes")]

    assert prune(rows, lambda row: row.content == "goes") == [_member("stays")]


def test_prune_never_evicts_a_pulled_in_subtask_on_its_own() -> None:
    # its own fields don't decide membership: the parent's do
    rows = [_member("parent"), _pulled_in("sub", "parent")]

    assert prune(rows, lambda row: row.content == "sub") == rows


def test_prune_takes_pulled_in_subtasks_out_with_their_parent() -> None:
    rows = [_member("parent"), _pulled_in("sub", "parent"), _member("other")]

    assert prune(rows, lambda row: row.content == "parent") == [_member("other")]


def test_prune_takes_out_a_whole_pulled_in_subtree() -> None:
    rows = [
        _member("parent"),
        _pulled_in("sub", "parent"),
        _pulled_in("subsub", "sub"),
    ]

    assert prune(rows, lambda row: row.content == "parent") == []


def test_prune_keeps_a_matching_subtask_whose_parent_left() -> None:
    # it matched on its own, so it stays — flat, as an orphan
    rows = [_member("parent"), _member("sub", parent_id="parent")]

    assert prune(rows, lambda row: row.content == "parent") == [
        _member("sub", parent_id="parent")
    ]


def test_with_subtrees_returns_the_ids_it_was_given() -> None:
    rows = [_member("alone"), _member("other")]

    assert with_subtrees(rows, {"alone"}) == {"alone"}


def test_with_subtrees_reaches_the_whole_subtree() -> None:
    rows = [
        _member("parent"),
        _member("sub", parent_id="parent"),
        _pulled_in("subsub", "sub"),
        _member("other"),
    ]

    assert with_subtrees(rows, {"parent"}) == {"parent", "sub", "subsub"}


def test_with_subtrees_covers_every_root_it_is_given() -> None:
    rows = [
        _member("one"),
        _pulled_in("one-sub", "one"),
        _member("two"),
        _pulled_in("two-sub", "two"),
    ]

    assert with_subtrees(rows, {"one", "two"}) == {"one", "one-sub", "two", "two-sub"}


def test_with_subtrees_terminates_on_a_parent_cycle() -> None:
    rows = [_member("a", parent_id="b"), _member("b", parent_id="a")]

    assert with_subtrees(rows, {"a"}) == {"a", "b"}


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

    async def all_tasks(self) -> list[Task]:
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

    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        return ActivityPage(events=(), next_cursor=None)

    async def comments(self, task_id: TaskId) -> list[Comment]:
        return []

    async def add_comment(
        self, task_id: TaskId, content: str, attachment: Attachment | None = None
    ) -> None: ...

    async def delete_comment(self, comment_id: str) -> None: ...

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

    async def refresh(self) -> None: ...

    async def apply_creation(self, plan: CreationPlan) -> None: ...

    async def reminders(self) -> list[Reminder]:
        return []

    async def add_reminder(self, reminder: Reminder) -> None: ...

    async def delete_reminder(self, reminder_id: str) -> None: ...


@pytest.mark.anyio
async def test_load_view_fetches_tasks_and_projects_concurrently() -> None:
    rows = await asyncio.wait_for(load_view(BarrierRepository(), TODAY), timeout=1.0)

    assert [row.content for row in rows] == ["Buy milk"]


def test_all_views_lists_filters_then_projects_then_today_and_inbox() -> None:
    views = all_views(
        [
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
            Project(id="7", name="Home"),
        ],
        [Filter(id="f1", name="Next", query="p1", order=1)],
        [],
    )

    assert [(v.title, v.key) for v in views] == [
        ("Next", "filter:f1"),
        ("Work", "project:9"),
        ("Home", "project:7"),
        ("Today", "today"),
        ("Inbox", "inbox"),
    ]


def test_all_views_without_projects_or_filters_still_offers_today_and_inbox() -> None:
    assert [v.key for v in all_views([], [], [])] == ["today", "inbox"]


def test_all_views_keys_round_trip_back_through_view_from_key() -> None:
    """Every bindable view must be storable as a slot, i.e. rebuildable from its key."""
    projects = [Project(id="9", name="Work")]
    filters = [Filter(id="f1", name="Next", query="p1", order=1)]
    sections = [Section(id="s1", project_id="9", name="Planning", order=1)]

    for view in all_views(projects, filters, sections):
        rebuilt = view_from_key(view.key, projects, filters)
        assert rebuilt is not None
        if view.land_section is None:
            assert rebuilt.title == view.title


def test_section_view_opens_its_project_view_at_the_section() -> None:
    project = Project(id="9", name="Work")
    section = Section(id="s1", project_id="9", name="Planning", order=1)

    view = section_view(project, section)

    assert view.title == "Work / Planning"
    assert view.key == "project:9"
    assert view.land_section == "Planning"
    assert view.project_id == "9"
    assert view.default_arrangement == Arrangement(group_by=(Field.SECTION,))


def test_all_views_lists_each_section_after_its_project() -> None:
    views = all_views(
        [Project(id="9", name="Work"), Project(id="7", name="Home")],
        [],
        [
            Section(id="s2", project_id="9", name="Backlog", order=2),
            Section(id="s3", project_id="7", name="Errands", order=1),
            Section(id="s1", project_id="9", name="Planning", order=1),
        ],
    )

    assert [v.title for v in views] == [
        "Work",
        "Work / Planning",
        "Work / Backlog",
        "Home",
        "Home / Errands",
        "Today",
        "Inbox",
    ]


def test_all_views_skips_the_inbox_projects_sections() -> None:
    views = all_views(
        [Project(id="220", name="Eingang", is_inbox=True)],
        [],
        [Section(id="s1", project_id="220", name="Later", order=1)],
    )

    assert [v.key for v in views] == ["today", "inbox"]


def test_a_section_row_rebuilds_as_its_project_view() -> None:
    """A section takes no slot of its own: its key names the project view."""
    projects = [Project(id="9", name="Work")]
    section = Section(id="s1", project_id="9", name="Planning", order=1)

    row = section_view(projects[0], section)
    rebuilt = view_from_key(row.key, projects, [])

    assert rebuilt is not None
    assert rebuilt.title == "Work"
    assert rebuilt.land_section is None


def test_views_that_span_projects_are_day_ordered() -> None:
    """child_order only orders one sibling set, so a mixed view cannot use it."""
    assert TODAY.day_ordered
    assert filter_view(Filter(id="f1", name="GTD", query="today", order=1)).day_ordered
    term = parse_search("milk")
    assert isinstance(term, SearchTerm)
    assert search_view(term).day_ordered


def test_views_that_are_one_project_keep_the_sibling_order() -> None:
    assert not INBOX.day_ordered
    assert not ALL.day_ordered
    assert not project_view(Project(id="9", name="Work")).day_ordered
