import asyncio
from datetime import date

import pytest

from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.sync_delta import SyncDelta
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.store.repository import SnapshotTaskRepository


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
        self.priorities: list[tuple[TaskId, Priority]] = []
        self.dues: list[tuple[TaskId, Due | None]] = []
        self.moves: list[tuple[TaskId, str]] = []
        self.filtered_queries: list[str] = []
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

    async def projects(self) -> list[Project]:  # pragma: no cover
        raise AssertionError("projects() must be served from the snapshot")

    async def filters(self) -> list[Filter]:  # pragma: no cover
        raise AssertionError("filters() must be served from the snapshot")

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)

    async def uncomplete(self, task_id: TaskId) -> None:
        self.uncompleted.append(task_id)

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None:
        self.priorities.append((task_id, priority))

    async def set_due(self, task_id: TaskId, due: Due | None) -> None:
        self.dues.append((task_id, due))

    async def set_project(self, task_id: TaskId, project_id: str) -> None:
        self.moves.append((task_id, project_id))

    async def refresh(self) -> None:  # pragma: no cover - must not be called
        raise AssertionError("refresh() is served by the snapshot repo")


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


@pytest.mark.anyio
async def test_complete_invalidates_filter_cache() -> None:
    inner = FakeInner(filtered_result=[_task("hit", "9")])
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(
        inner, FakeSource(_incremental("next", "a")), cache, _CLOCK
    )

    await repo.filtered("a")
    await repo.complete(TaskId("x"))  # a mutation invalidates cached results
    await repo.filtered("a")

    assert inner.filtered_queries == ["a", "a"]


@pytest.mark.anyio
async def test_set_priority_delegates_then_invalidates_filter_cache() -> None:
    inner = FakeInner(filtered_result=[_task("hit", "9")])
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(
        inner, FakeSource(_incremental("next", "a")), cache, _CLOCK
    )

    await repo.filtered("a")
    await repo.set_priority(TaskId("x"), Priority.P1)  # mutation invalidates cache
    await repo.filtered("a")

    assert inner.priorities == [(TaskId("x"), Priority.P1)]
    assert inner.filtered_queries == ["a", "a"]


@pytest.mark.anyio
async def test_set_due_delegates_then_invalidates_filter_cache() -> None:
    inner = FakeInner(filtered_result=[_task("hit", "9")])
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(
        inner, FakeSource(_incremental("next", "a")), cache, _CLOCK
    )

    await repo.filtered("a")
    await repo.set_due(TaskId("x"), Due(date=_TODAY))  # mutation invalidates cache
    await repo.filtered("a")

    assert inner.dues == [(TaskId("x"), Due(date=_TODAY))]
    assert inner.filtered_queries == ["a", "a"]


@pytest.mark.anyio
async def test_set_project_delegates_then_invalidates_filter_cache() -> None:
    inner = FakeInner(filtered_result=[_task("hit", "9")])
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(
        inner, FakeSource(_incremental("next", "a")), cache, _CLOCK
    )

    await repo.filtered("a")
    await repo.set_project(TaskId("x"), "9")  # mutation invalidates cache
    await repo.filtered("a")

    assert inner.moves == [(TaskId("x"), "9")]
    assert inner.filtered_queries == ["a", "a"]


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
async def test_complete_then_read_syncs_incrementally_and_drops_the_task() -> None:
    inner = FakeInner()
    source = FakeSource(_incremental("after", deleted_task="a"))
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(inner, source, cache, _CLOCK)

    await repo.projects()  # served from cache
    await repo.complete(TaskId("a"))
    inbox = await repo.inbox()  # dirty -> incremental resync from the cached token

    assert inner.completed == [TaskId("a")]
    assert source.since == ["cached"]
    assert [str(t.id) for t in inbox] == ["c"]


@pytest.mark.anyio
async def test_uncomplete_then_read_syncs_incrementally_and_restores_the_task() -> None:
    inner = FakeInner()
    source = FakeSource(_full_delta(_snapshot("after")))
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(inner, source, cache, _CLOCK)

    await repo.projects()  # served from cache
    await repo.uncomplete(TaskId("a"))
    inbox = await repo.inbox()  # dirty -> resync from the cached token

    assert inner.uncompleted == [TaskId("a")]
    assert source.since == ["cached"]
    assert [str(t.id) for t in inbox] == ["a", "c"]


@pytest.mark.anyio
async def test_concurrent_first_fetch_shares_single_sync() -> None:
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(FakeInner(), source, FakeCache(), _CLOCK)

    await asyncio.gather(repo.projects(), repo.inbox())

    assert source.snapshot_calls == 1
