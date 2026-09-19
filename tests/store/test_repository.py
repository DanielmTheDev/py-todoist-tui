import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, time

import pytest

from todoist_tui.domain.activity import ActivityPage, EventKind
from todoist_tui.domain.comment import Attachment, Comment
from todoist_tui.domain.creation import CreationPlan, NewProject
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.section import Section
from todoist_tui.domain.sync_delta import SyncDelta
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.store.repository import FILTER_CACHE_LIMIT, SnapshotTaskRepository


class FakeClock:
    def __init__(self, today: date) -> None:
        self._today = today

    def today(self) -> date:
        return self._today


_TODAY = date(2026, 7, 23)
_CLOCK = FakeClock(_TODAY)


def _full_delta(snapshot: Snapshot) -> SyncDelta:
    return SyncDelta(
        projects=snapshot.projects,
        tasks=snapshot.tasks,
        deleted_project_ids=frozenset(),
        deleted_task_ids=frozenset(),
        sync_token=snapshot.sync_token,
        full_sync=True,
        filters=snapshot.filters,
        sections=snapshot.sections,
    )


def _task(task_id: str, project_id: str, due: Due | None = None) -> Task:
    return Task(
        id=TaskId(task_id),
        content=task_id,
        priority=Priority.P2,
        due=due,
        project_id=project_id,
    )


class FakeInner:
    """Backs today()/complete()/filtered(); the snapshot repo serves the rest."""

    def __init__(self, filtered_result: list[Task] | None = None) -> None:
        self.today_calls = 0
        self.completed: list[TaskId] = []
        self.uncompleted: list[TaskId] = []
        self.deleted: list[TaskId] = []
        self.deleted_sections: list[str] = []
        self.priorities: list[tuple[TaskId, Priority]] = []
        self.dues: list[tuple[TaskId, Due | DueText | None]] = []
        self.landed_due: Due | None = None
        self.deadlines: list[tuple[TaskId, Deadline | None]] = []
        self.moves: list[tuple[TaskId, str, str | None]] = []
        self.parents: list[tuple[TaskId, str]] = []
        self.reorders: list[list[tuple[TaskId, int]]] = []
        self.section_reorders: list[list[tuple[str, int]]] = []
        self.day_orders: list[list[tuple[TaskId, int]]] = []
        self.label_edits: list[tuple[TaskId, tuple[str, ...], tuple[str, ...]]] = []
        self.text_edits: list[tuple[TaskId, str, str]] = []
        self.applied: list[CreationPlan] = []
        self.filtered_queries: list[str] = []
        self.activity_calls: list[tuple[EventKind | None, str | None]] = []
        self.comment_calls: list[TaskId] = []
        self.posted_comments: list[tuple[TaskId, str, Attachment | None]] = []
        self.deleted_comments: list[str] = []
        self._filtered_result = filtered_result or []

    async def today(self) -> list[Task]:
        self.today_calls += 1
        return []

    async def filtered(self, query: str) -> list[Task]:
        self.filtered_queries.append(query)
        return self._filtered_result

    async def refresh_filtered(  # pragma: no cover - wrapper uses filtered()
        self, query: str
    ) -> list[Task]:
        raise AssertionError("refresh_filtered() is served by the snapshot repo")

    async def inbox(self) -> list[Task]:  # pragma: no cover - must not be called
        raise AssertionError("inbox() must be served from the snapshot")

    async def by_project(  # pragma: no cover - must not be called
        self, project_id: str
    ) -> list[Task]:
        raise AssertionError("by_project() must be served from the snapshot")

    async def all_tasks(self) -> list[Task]:  # pragma: no cover - must not be called
        raise AssertionError("all_tasks() must be served from the snapshot")

    async def projects(self) -> list[Project]:  # pragma: no cover
        raise AssertionError("projects() must be served from the snapshot")

    async def sections(self) -> list[Section]:  # pragma: no cover
        raise AssertionError("sections() must be served from the snapshot")

    async def filters(self) -> list[Filter]:  # pragma: no cover
        raise AssertionError("filters() must be served from the snapshot")

    async def labels(self) -> list[Label]:  # pragma: no cover
        raise AssertionError("labels() must be served from the snapshot")

    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        self.activity_calls.append((event_type, cursor))
        return ActivityPage(events=(), next_cursor="next")

    async def comments(self, task_id: TaskId) -> list[Comment]:
        self.comment_calls.append(task_id)
        return []

    async def add_comment(
        self, task_id: TaskId, content: str, attachment: Attachment | None = None
    ) -> None:
        self.posted_comments.append((task_id, content, attachment))

    async def delete_comment(self, comment_id: str) -> None:
        self.deleted_comments.append(comment_id)

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)

    async def uncomplete(self, task_id: TaskId) -> None:
        self.uncompleted.append(task_id)

    async def delete(self, task_id: TaskId) -> None:
        self.deleted.append(task_id)

    async def delete_section(self, section_id: str) -> None:
        self.deleted_sections.append(section_id)

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None:
        self.priorities.append((task_id, priority))

    async def set_due(self, task_id: TaskId, due: Due | DueText | None) -> Due | None:
        self.dues.append((task_id, due))
        return self.landed_due

    async def set_deadline(self, task_id: TaskId, deadline: Deadline | None) -> None:
        self.deadlines.append((task_id, deadline))

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        self.moves.append((task_id, project_id, section_id))

    async def set_parent(self, task_id: TaskId, parent_id: str) -> None:
        self.parents.append((task_id, parent_id))

    async def reorder(self, items: Sequence[tuple[TaskId, int]]) -> None:
        self.reorders.append(list(items))

    async def reorder_sections(self, sections: Sequence[tuple[str, int]]) -> None:
        self.section_reorders.append(list(sections))

    async def set_day_orders(self, items: Sequence[tuple[TaskId, int]]) -> None:
        self.day_orders.append(list(items))

    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None:
        self.label_edits.append((task_id, labels, create))

    async def set_text(self, task_id: TaskId, content: str, description: str) -> None:
        self.text_edits.append((task_id, content, description))

    async def apply_creation(self, plan: CreationPlan) -> None:
        self.applied.append(plan)

    async def refresh(self) -> None:  # pragma: no cover - must not be called
        raise AssertionError("refresh() is served by the snapshot repo")

    async def reminders(self) -> list[Reminder]:
        return []

    async def add_reminder(self, reminder: Reminder) -> None: ...

    async def delete_reminder(self, reminder_id: str) -> None: ...


class FakeSource:
    def __init__(self, delta: SyncDelta) -> None:
        self._delta = delta
        self.since: list[str | None] = []

    @property
    def snapshot_calls(self) -> int:
        return len(self.since)

    async def delta(self, since: str | None) -> SyncDelta:
        await asyncio.sleep(0)  # yield so concurrent readers actually interleave
        self.since.append(since)
        return self._delta


class FakeCache:
    def __init__(self, stored: Snapshot | None = None) -> None:
        self._stored = stored
        self.saved: list[Snapshot] = []
        self.load_calls = 0

    async def load(self) -> Snapshot | None:
        self.load_calls += 1
        return self._stored

    async def save(self, snapshot: Snapshot) -> None:
        self.saved.append(snapshot)
        self._stored = snapshot


def _snapshot(sync_token: str = "tok") -> Snapshot:
    return Snapshot(
        projects=[
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
        ],
        tasks=[_task("a", "220"), _task("b", "9"), _task("c", "220")],
        sync_token=sync_token,
    )


@pytest.mark.anyio
async def test_projects_and_inbox_share_one_sync() -> None:
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(FakeInner(), source, FakeCache(), _CLOCK)

    projects = await repo.projects()
    inbox = await repo.inbox()

    assert [p.id for p in projects] == ["220", "9"]
    assert [t.id for t in inbox] == [TaskId("a"), TaskId("c")]
    assert source.snapshot_calls == 1


@pytest.mark.anyio
async def test_by_project_served_from_snapshot() -> None:
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(FakeInner(), source, FakeCache(), _CLOCK)

    tasks = await repo.by_project("9")

    assert [str(t.id) for t in tasks] == ["b"]
    assert source.snapshot_calls == 1


@pytest.mark.anyio
async def test_all_tasks_served_from_snapshot() -> None:
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(FakeInner(), source, FakeCache(), _CLOCK)

    tasks = await repo.all_tasks()

    assert [str(t.id) for t in tasks] == ["a", "b", "c"]
    assert source.snapshot_calls == 1


@pytest.mark.anyio
async def test_inbox_raises_when_no_inbox_project() -> None:
    snapshot = Snapshot(
        projects=[Project(id="9", name="Work")], tasks=[], sync_token="tok"
    )
    repo = SnapshotTaskRepository(
        FakeInner(), FakeSource(_full_delta(snapshot)), FakeCache(), _CLOCK
    )

    with pytest.raises(LookupError, match="inbox"):
        await repo.inbox()


@pytest.mark.anyio
async def test_today_served_from_snapshot() -> None:
    snapshot = Snapshot(
        projects=[Project(id="9", name="Work")],
        tasks=[
            _task("due-today", "9", due=Due(date=_TODAY)),
            _task("due-tomorrow", "9", due=Due(date=date(2026, 7, 24))),
            _task("no-due", "9"),
        ],
        sync_token="tok",
    )
    inner = FakeInner()
    source = FakeSource(_full_delta(snapshot))
    repo = SnapshotTaskRepository(inner, source, FakeCache(), _CLOCK)

    result = await repo.today()

    assert [str(t.id) for t in result] == ["due-today"]
    assert inner.today_calls == 0  # today comes from the snapshot, not the server
    assert source.snapshot_calls == 1


@pytest.mark.anyio
async def test_filtered_delegates_to_inner_server_side() -> None:
    inner = FakeInner(filtered_result=[_task("hit", "9")])
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(inner, source, FakeCache(), _CLOCK)

    result = await repo.filtered("@work & p1")

    assert [str(t.id) for t in result] == ["hit"]
    assert inner.filtered_queries == ["@work & p1"]
    assert source.snapshot_calls == 0  # results are live, not from the snapshot


@pytest.mark.anyio
async def test_filtered_caches_result_per_query() -> None:
    inner = FakeInner(filtered_result=[_task("hit", "9")])
    repo = SnapshotTaskRepository(
        inner, FakeSource(_full_delta(_snapshot())), FakeCache(), _CLOCK
    )

    await repo.filtered("a")
    await repo.filtered("a")  # served from cache
    await repo.filtered("b")

    assert inner.filtered_queries == ["a", "b"]


@pytest.mark.anyio
async def test_refresh_filtered_bypasses_then_updates_cache() -> None:
    inner = FakeInner(filtered_result=[_task("hit", "9")])
    repo = SnapshotTaskRepository(
        inner, FakeSource(_full_delta(_snapshot())), FakeCache(), _CLOCK
    )

    await repo.filtered("a")
    await repo.refresh_filtered("a")  # forces a fresh fetch
    await repo.filtered("a")  # now served from the refreshed cache

    assert inner.filtered_queries == ["a", "a"]


def _delegating_repo(inner: FakeInner) -> SnapshotTaskRepository:
    """A repo whose reads are never exercised, so a write can be watched alone."""
    return SnapshotTaskRepository(
        inner, FakeSource(_full_delta(_snapshot())), FakeCache(), _CLOCK
    )


@pytest.mark.anyio
async def test_complete_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.complete(TaskId("x"))

    assert inner.completed == [TaskId("x")]


@pytest.mark.anyio
async def test_uncomplete_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.uncomplete(TaskId("x"))

    assert inner.uncompleted == [TaskId("x")]


@pytest.mark.anyio
async def test_delete_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.delete(TaskId("x"))

    assert inner.deleted == [TaskId("x")]


@pytest.mark.anyio
async def test_delete_section_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.delete_section("6S1")

    assert inner.deleted_sections == ["6S1"]


@pytest.mark.anyio
async def test_set_priority_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.set_priority(TaskId("x"), Priority.P1)

    assert inner.priorities == [(TaskId("x"), Priority.P1)]


@pytest.mark.anyio
async def test_set_due_delegates_to_the_api_and_answers_with_what_landed() -> None:
    inner = FakeInner()
    inner.landed_due = Due(date=_TODAY, time=time(10, 0))
    repo = _delegating_repo(inner)

    landed = await repo.set_due(TaskId("x"), DueText("tod 10:00"))

    assert inner.dues == [(TaskId("x"), DueText("tod 10:00"))]
    assert landed == Due(date=_TODAY, time=time(10, 0))


@pytest.mark.anyio
async def test_set_project_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.set_project(TaskId("x"), "9")

    assert inner.moves == [(TaskId("x"), "9", None)]


@pytest.mark.anyio
async def test_set_parent_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.set_parent(TaskId("x"), "p")

    assert inner.parents == [(TaskId("x"), "p")]


@pytest.mark.anyio
async def test_set_day_orders_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.set_day_orders([(TaskId("x"), 2), (TaskId("y"), 1)])

    assert inner.day_orders == [[(TaskId("x"), 2), (TaskId("y"), 1)]]


@pytest.mark.anyio
async def test_reorder_sections_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.reorder_sections([("s1", 2), ("s2", 1)])

    assert inner.section_reorders == [[("s1", 2), ("s2", 1)]]


@pytest.mark.anyio
async def test_reorder_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.reorder([(TaskId("x"), 2), (TaskId("y"), 1)])

    assert inner.reorders == [[(TaskId("x"), 2), (TaskId("y"), 1)]]


@pytest.mark.anyio
async def test_set_labels_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.set_labels(TaskId("x"), ("home",), ("home",))

    assert inner.label_edits == [(TaskId("x"), ("home",), ("home",))]


@pytest.mark.anyio
async def test_set_text_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)

    await repo.set_text(TaskId("x"), "New title", "New note")

    assert inner.text_edits == [(TaskId("x"), "New title", "New note")]


@pytest.mark.anyio
async def test_apply_creation_delegates_to_the_api() -> None:
    inner = FakeInner()
    repo = _delegating_repo(inner)
    plan = CreationPlan(
        projects=(NewProject(temp_id="tp", name="Work (copy)"),), sections=(), tasks=()
    )

    await repo.apply_creation(plan)

    assert inner.applied == [plan]


@pytest.mark.anyio
async def test_set_project_forwards_section_id() -> None:
    inner = FakeInner()
    repo = SnapshotTaskRepository(
        inner, FakeSource(_full_delta(_snapshot())), FakeCache(), _CLOCK
    )

    await repo.set_project(TaskId("x"), "9", "77")

    assert inner.moves == [(TaskId("x"), "9", "77")]


@pytest.mark.anyio
async def test_sections_served_from_snapshot() -> None:
    snapshot = Snapshot(
        projects=[],
        tasks=[],
        sync_token="tok",
        sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
    )
    repo = SnapshotTaskRepository(
        FakeInner(), FakeSource(_full_delta(snapshot)), FakeCache(), _CLOCK
    )

    (s,) = await repo.sections()

    assert (s.id, s.name) == ("s1", "Planning")


@pytest.mark.anyio
async def test_filters_served_from_snapshot() -> None:
    snapshot = Snapshot(
        projects=[],
        tasks=[],
        sync_token="tok",
        filters=[Filter(id="f1", name="P1", query="p1", order=1)],
    )
    repo = SnapshotTaskRepository(
        FakeInner(), FakeSource(_full_delta(snapshot)), FakeCache(), _CLOCK
    )

    (f,) = await repo.filters()

    assert (f.id, f.name) == ("f1", "P1")


@pytest.mark.anyio
async def test_cold_start_serves_from_cache_without_network() -> None:
    source = FakeSource(_full_delta(_snapshot("net")))
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(FakeInner(), source, cache, _CLOCK)

    projects = await repo.projects()

    assert [p.id for p in projects] == ["220", "9"]
    assert source.snapshot_calls == 0
    assert cache.load_calls == 1


@pytest.mark.anyio
async def test_cache_miss_syncs_and_writes_through() -> None:
    snapshot = _snapshot("net")
    source = FakeSource(_full_delta(snapshot))
    cache = FakeCache()
    repo = SnapshotTaskRepository(FakeInner(), source, cache, _CLOCK)

    await repo.projects()

    assert source.snapshot_calls == 1
    assert cache.saved == [snapshot]


def _incremental(sync_token: str, deleted_task: str) -> SyncDelta:
    return SyncDelta(
        projects=[],
        tasks=[],
        deleted_project_ids=frozenset(),
        deleted_task_ids=frozenset({deleted_task}),
        sync_token=sync_token,
        full_sync=False,
    )


@pytest.mark.anyio
async def test_refresh_syncs_incrementally_from_stored_token_and_merges() -> None:
    source = FakeSource(_incremental("fresh", deleted_task="a"))
    cache = FakeCache(stored=_snapshot("stale"))
    repo = SnapshotTaskRepository(FakeInner(), source, cache, _CLOCK)

    await repo.refresh()

    assert source.since == ["stale"]  # reuses the cached token, not a full sync
    (saved,) = cache.saved
    assert saved.sync_token == "fresh"
    assert [str(t.id) for t in saved.tasks] == ["b", "c"]  # "a" folded out
    assert [str(t.id) for t in await repo.inbox()] == ["c"]  # served from memo


@pytest.mark.anyio
async def test_concurrent_first_fetch_shares_single_sync() -> None:
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(FakeInner(), source, FakeCache(), _CLOCK)

    await asyncio.gather(repo.projects(), repo.inbox())

    assert source.snapshot_calls == 1


@pytest.mark.anyio
async def test_a_read_after_a_mutation_serves_the_memoized_snapshot() -> None:
    source = FakeSource(_incremental("after", deleted_task="a"))
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(FakeInner(), source, cache, _CLOCK)

    await repo.projects()  # memoizes the cached snapshot
    await repo.set_priority(TaskId("a"), Priority.P1)
    inbox = await repo.inbox()

    assert source.snapshot_calls == 0  # no network stall before the caller resyncs
    assert [str(t.id) for t in inbox] == ["a", "c"]  # stale, and the outbox knows


@pytest.mark.anyio
async def test_a_mutation_keeps_the_filter_cache_until_the_resync() -> None:
    inner = FakeInner(filtered_result=[_task("hit", "9")])
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(
        inner, FakeSource(_incremental("next", "a")), cache, _CLOCK
    )

    await repo.filtered("a")
    await repo.complete(TaskId("x"))
    await repo.filtered("a")

    assert inner.filtered_queries == ["a"]  # still served from cache


@pytest.mark.anyio
async def test_refresh_after_a_mutation_pulls_the_change() -> None:
    inner = FakeInner()
    source = FakeSource(_incremental("after", deleted_task="a"))
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(inner, source, cache, _CLOCK)

    await repo.projects()
    await repo.complete(TaskId("a"))
    await repo.refresh()

    assert source.since == ["cached"]  # incremental, from the memoized token
    assert [str(t.id) for t in await repo.inbox()] == ["c"]


@pytest.mark.anyio
async def test_a_mutation_before_any_read_bypasses_the_stale_disk_cache() -> None:
    source = FakeSource(_incremental("after", deleted_task="a"))
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(FakeInner(), source, cache, _CLOCK)

    await repo.complete(TaskId("a"))
    inbox = await repo.inbox()  # nothing memoized yet, so the disk copy is stale

    assert source.snapshot_calls == 1
    assert [str(t.id) for t in inbox] == ["c"]


@pytest.mark.anyio
async def test_the_filter_cache_keeps_only_the_most_recent_queries() -> None:
    inner = FakeInner(filtered_result=[_task("hit", "9")])
    repo = SnapshotTaskRepository(
        inner, FakeSource(_full_delta(_snapshot())), FakeCache(), _CLOCK
    )

    for i in range(FILTER_CACHE_LIMIT + 1):
        await repo.filtered(f"q{i}")
    fetched = len(inner.filtered_queries)
    await repo.filtered(f"q{FILTER_CACHE_LIMIT}")  # the newest: still cached
    await repo.filtered("q0")  # the oldest: evicted by the one that followed it

    assert inner.filtered_queries[fetched:] == ["q0"]


@pytest.mark.anyio
async def test_activity_goes_straight_to_the_backend() -> None:
    inner = FakeInner()
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(inner, source, FakeCache(), _CLOCK)

    page = await repo.activity(event_type=EventKind.COMPLETED, cursor="abc")

    assert page.next_cursor == "next"
    assert inner.activity_calls == [(EventKind.COMPLETED, "abc")]


@pytest.mark.anyio
async def test_comments_go_straight_to_the_backend() -> None:
    """A thread is read for one task on demand, so the snapshot never carries
    one — as with the activity log."""
    inner = FakeInner()
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(inner, source, FakeCache(), _CLOCK)

    assert await repo.comments(TaskId("t1")) == []
    assert inner.comment_calls == [TaskId("t1")]


@pytest.mark.anyio
async def test_a_filter_result_carries_the_comment_counts_too() -> None:
    """A saved filter is evaluated server-side, where the task's own note_count
    is never filled — the snapshot's notes supply it."""
    inner = FakeInner(filtered_result=[_task("t1", "9")])
    snapshot = _snapshot()
    source = FakeSource(replace(_full_delta(snapshot), notes={"n1": "t1", "n2": "t1"}))
    repo = SnapshotTaskRepository(inner, source, FakeCache(), _CLOCK)
    await repo.projects()  # as a view does: the snapshot is loaded alongside

    (task,) = await repo.filtered("today")

    assert task.note_count == 2


@pytest.mark.anyio
async def test_a_comment_written_before_any_read_leaves_the_disk_copy_behind() -> None:
    """A comment changes the count the marker reads, so it marks the snapshot
    stale like any other mutation: the disk copy is skipped, and a read syncs."""
    inner = FakeInner()
    source = FakeSource(_incremental("after", deleted_task="a"))
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(inner, source, cache, _CLOCK)

    await repo.add_comment(TaskId("t1"), "ship it")
    inbox = await repo.inbox()

    assert inner.posted_comments == [(TaskId("t1"), "ship it", None)]
    assert source.snapshot_calls == 1
    assert [str(t.id) for t in inbox] == ["c"]


@pytest.mark.anyio
async def test_deleting_a_comment_marks_the_snapshot_stale_too() -> None:
    inner = FakeInner()
    source = FakeSource(_incremental("after", deleted_task="a"))
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(inner, source, cache, _CLOCK)

    await repo.delete_comment("c1")
    await repo.inbox()

    assert inner.deleted_comments == ["c1"]
    assert source.snapshot_calls == 1  # the disk copy no longer speaks for the count
