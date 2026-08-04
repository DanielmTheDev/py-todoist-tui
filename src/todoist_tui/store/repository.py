import asyncio

from todoist_tui.domain.clock import Clock
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.filter_query import FilterQuery
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import (
    Snapshot,
    SnapshotCache,
    SnapshotSource,
    TaskRepository,
)
from todoist_tui.domain.section import Section
from todoist_tui.domain.sync_delta import merge
from todoist_tui.domain.task import Task, TaskId


class SnapshotTaskRepository:
    """Serves projects()/inbox() from a memoized /sync snapshot, cache-first.

    First read prefers the persisted cache (instant, offline cold start);
    on a miss it syncs from `source` and writes through to the cache.
    `refresh()` force-resyncs from the network. today() is evaluated client-side
    over the snapshot via a `FilterQuery`. complete() marks the snapshot dirty so
    the next read bypasses the now-stale cache and re-syncs.
    """

    def __init__(
        self,
        inner: TaskRepository,
        source: SnapshotSource,
        cache: SnapshotCache,
        clock: Clock,
    ) -> None:
        self._inner = inner
        self._source = source
        self._cache = cache
        self._clock = clock
        self._snapshot: Snapshot | None = None
        self._dirty = False
        self._filter_cache: dict[str, list[Task]] = {}
        self._lock = asyncio.Lock()

    async def _snapshot_now(self) -> Snapshot:
        if self._snapshot is not None:
            return self._snapshot
        async with self._lock:
            if self._snapshot is not None:
                return self._snapshot
            if not self._dirty:
                cached = await self._cache.load()
                if cached is not None:
                    self._snapshot = cached
                    return cached
            self._snapshot = await self._sync()
            return self._snapshot

    async def _sync(self) -> Snapshot:
        prior = self._snapshot or await self._cache.load()
        delta = await self._source.delta(prior.sync_token if prior else None)
        merged = merge(prior, delta)
        await self._cache.save(merged)
        self._dirty = False
        return merged

    async def refresh(self) -> None:
        async with self._lock:
            self._snapshot = await self._sync()

    async def projects(self) -> list[Project]:
        return (await self._snapshot_now()).projects

    async def sections(self) -> list[Section]:
        return (await self._snapshot_now()).sections

    async def inbox(self) -> list[Task]:
        snapshot = await self._snapshot_now()
        inbox = next((p for p in snapshot.projects if p.is_inbox), None)
        if inbox is None:
            raise LookupError("no inbox project found")
        return [task for task in snapshot.tasks if task.project_id == inbox.id]

    async def by_project(self, project_id: str) -> list[Task]:
        snapshot = await self._snapshot_now()
        return [task for task in snapshot.tasks if task.project_id == project_id]

    async def today(self) -> list[Task]:
        snapshot = await self._snapshot_now()
        today = self._clock.today()
        query = FilterQuery("today")
        return [task for task in snapshot.tasks if query.matches(task, today)]

    async def filtered(self, query: str) -> list[Task]:
        if query not in self._filter_cache:  # cache-first; refresh happens in bg
            self._filter_cache[query] = await self._inner.filtered(query)
        return self._filter_cache[query]

    async def refresh_filtered(self, query: str) -> list[Task]:
        result = await self._inner.filtered(query)  # server-side eval, live
        self._filter_cache[query] = result
        return result

    async def filters(self) -> list[Filter]:
        return (await self._snapshot_now()).filters

    async def labels(self) -> list[Label]:
        return (await self._snapshot_now()).labels

    async def complete(self, task_id: TaskId) -> None:
        await self._inner.complete(task_id)
        await self._invalidate()

    async def uncomplete(self, task_id: TaskId) -> None:
        await self._inner.uncomplete(task_id)
        await self._invalidate()

    async def delete(self, task_id: TaskId) -> None:
        await self._inner.delete(task_id)
        await self._invalidate()

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None:
        await self._inner.set_priority(task_id, priority)
        await self._invalidate()

    async def set_due(self, task_id: TaskId, due: Due | None) -> None:
        await self._inner.set_due(task_id, due)
        await self._invalidate()

    async def set_deadline(self, task_id: TaskId, deadline: Deadline | None) -> None:
        await self._inner.set_deadline(task_id, deadline)
        await self._invalidate()

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        await self._inner.set_project(task_id, project_id, section_id)
        await self._invalidate()

    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None:
        await self._inner.set_labels(task_id, labels, create)
        await self._invalidate()

    async def _invalidate(self) -> None:
        async with self._lock:  # a concurrent reader must not re-cache stale state
            self._snapshot = None
            self._dirty = True
            self._filter_cache = {}  # a mutation changes what filters match
