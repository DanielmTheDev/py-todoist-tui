import asyncio

import pytest

from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.sync_delta import SyncDelta
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.store.repository import SnapshotTaskRepository


def _full_delta(snapshot: Snapshot) -> SyncDelta:
    return SyncDelta(
        projects=snapshot.projects,
        tasks=snapshot.tasks,
        deleted_project_ids=frozenset(),
        deleted_task_ids=frozenset(),
        sync_token=snapshot.sync_token,
        full_sync=True,
    )


def _task(task_id: str, project_id: str) -> Task:
    return Task(
        id=TaskId(task_id),
        content=task_id,
        priority=Priority.P2,
        due=None,
        project_id=project_id,
    )


class FakeInner:
    """Backs today()/complete(); the snapshot repo must never call the rest."""

    def __init__(self, today: list[Task] | None = None) -> None:
        self._today = today or []
        self.today_calls = 0
        self.completed: list[TaskId] = []

    async def today(self) -> list[Task]:
        self.today_calls += 1
        return self._today

    async def inbox(self) -> list[Task]:  # pragma: no cover - must not be called
        raise AssertionError("inbox() must be served from the snapshot")

    async def projects(self) -> list[Project]:  # pragma: no cover
        raise AssertionError("projects() must be served from the snapshot")

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)

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
    repo = SnapshotTaskRepository(FakeInner(), source, FakeCache())

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
        FakeInner(), FakeSource(_full_delta(snapshot)), FakeCache()
    )

    with pytest.raises(LookupError, match="inbox"):
        await repo.inbox()


@pytest.mark.anyio
async def test_today_delegates_to_inner_without_syncing() -> None:
    inner = FakeInner(today=[_task("t", "9")])
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(inner, source, FakeCache())

    assert [t.id for t in await repo.today()] == [TaskId("t")]
    assert inner.today_calls == 1
    assert source.snapshot_calls == 0


@pytest.mark.anyio
async def test_cold_start_serves_from_cache_without_network() -> None:
    source = FakeSource(_full_delta(_snapshot("net")))
    cache = FakeCache(stored=_snapshot("cached"))
    repo = SnapshotTaskRepository(FakeInner(), source, cache)

    projects = await repo.projects()

    assert [p.id for p in projects] == ["220", "9"]
    assert source.snapshot_calls == 0
    assert cache.load_calls == 1


@pytest.mark.anyio
async def test_cache_miss_syncs_and_writes_through() -> None:
    snapshot = _snapshot("net")
    source = FakeSource(_full_delta(snapshot))
    cache = FakeCache()
    repo = SnapshotTaskRepository(FakeInner(), source, cache)

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
    repo = SnapshotTaskRepository(FakeInner(), source, cache)

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
    repo = SnapshotTaskRepository(inner, source, cache)

    await repo.projects()  # served from cache
    await repo.complete(TaskId("a"))
    inbox = await repo.inbox()  # dirty -> incremental resync from the cached token

    assert inner.completed == [TaskId("a")]
    assert source.since == ["cached"]
    assert [str(t.id) for t in inbox] == ["c"]


@pytest.mark.anyio
async def test_concurrent_first_fetch_shares_single_sync() -> None:
    source = FakeSource(_full_delta(_snapshot()))
    repo = SnapshotTaskRepository(FakeInner(), source, FakeCache())

    await asyncio.gather(repo.projects(), repo.inbox())

    assert source.snapshot_calls == 1
