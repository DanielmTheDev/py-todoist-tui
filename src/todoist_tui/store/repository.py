import asyncio
from collections.abc import Sequence

from todoist_tui.domain.activity import ActivityPage, EventKind
from todoist_tui.domain.clock import Clock
from todoist_tui.domain.creation import CreationPlan
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.filter_query import FilterQuery
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.repository import (
    Snapshot,
    SnapshotCache,
    SnapshotSource,
    TaskRepository,
)
from todoist_tui.domain.section import Section
from todoist_tui.domain.sync_delta import merge
from todoist_tui.domain.task import Task, TaskId

# Nothing wipes the per-query cache any more, so it keeps only the queries a
# session is still moving between — enough for the saved filters plus a few
# searches, without holding every phrase ever typed.
FILTER_CACHE_LIMIT = 16


class SnapshotTaskRepository:
    """Serves projects()/inbox() from a memoized /sync snapshot, cache-first.

    First read prefers the persisted cache (instant, offline cold start);
    on a miss it syncs from `source` and writes through to the cache.
    `refresh()` force-resyncs from the network. today() is evaluated client-side
    over the snapshot via a `FilterQuery`.

    A mutation only marks the snapshot stale — it never drops it. Reads stay
    instant, so an action never leaves the next one waiting on the network, and
    the caller resyncs behind it (the outbox does so as soon as its queue
    drains). What the user changed is theirs to replay on top; a stale read can
    only lack a change they already see. `_dirty` matters just for a mutation
    made before anything was read, where the disk copy predates it.
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

    async def all_tasks(self) -> list[Task]:
        return (await self._snapshot_now()).tasks

    async def today(self) -> list[Task]:
        snapshot = await self._snapshot_now()
        today = self._clock.today()
        query = FilterQuery("today")
        return [task for task in snapshot.tasks if query.matches(task, today)]

    async def filtered(self, query: str) -> list[Task]:
        if query not in self._filter_cache:  # cache-first; refresh happens in bg
            self._remember(query, await self._inner.filtered(query))
        return self._filter_cache[query]

    async def refresh_filtered(self, query: str) -> list[Task]:
        result = await self._inner.filtered(query)  # server-side eval, live
        self._remember(query, result)
        return result

    def _remember(self, query: str, tasks: list[Task]) -> None:
        self._filter_cache.pop(query, None)  # re-insert, so it counts as the newest
        self._filter_cache[query] = tasks
        for stale in list(self._filter_cache)[:-FILTER_CACHE_LIMIT]:
            del self._filter_cache[stale]

    async def filters(self) -> list[Filter]:
        return (await self._snapshot_now()).filters

    async def labels(self) -> list[Label]:
        return (await self._snapshot_now()).labels

    async def reminders(self) -> list[Reminder]:
        return (await self._snapshot_now()).reminders

    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        # history is append-only and outside the sync token: always live
        return await self._inner.activity(event_type, cursor)

    async def complete(self, task_id: TaskId) -> None:
        await self._inner.complete(task_id)
        self._mark_stale()

    async def uncomplete(self, task_id: TaskId) -> None:
        await self._inner.uncomplete(task_id)
        self._mark_stale()

    async def delete(self, task_id: TaskId) -> None:
        await self._inner.delete(task_id)
        self._mark_stale()

    async def delete_section(self, section_id: str) -> None:
        await self._inner.delete_section(section_id)
        self._mark_stale()

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None:
        await self._inner.set_priority(task_id, priority)
        self._mark_stale()

    async def set_due(self, task_id: TaskId, due: Due | DueText | None) -> Due | None:
        landed = await self._inner.set_due(task_id, due)
        self._mark_stale()
        return landed

    async def set_deadline(self, task_id: TaskId, deadline: Deadline | None) -> None:
        await self._inner.set_deadline(task_id, deadline)
        self._mark_stale()

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        await self._inner.set_project(task_id, project_id, section_id)
        self._mark_stale()

    async def set_parent(self, task_id: TaskId, parent_id: str) -> None:
        await self._inner.set_parent(task_id, parent_id)
        self._mark_stale()

    async def reorder(self, items: Sequence[tuple[TaskId, int]]) -> None:
        await self._inner.reorder(items)
        self._mark_stale()

    async def set_day_orders(self, items: Sequence[tuple[TaskId, int]]) -> None:
        await self._inner.set_day_orders(items)
        self._mark_stale()

    async def reorder_sections(self, sections: Sequence[tuple[str, int]]) -> None:
        await self._inner.reorder_sections(sections)
        self._mark_stale()

    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None:
        await self._inner.set_labels(task_id, labels, create)
        self._mark_stale()

    async def set_text(self, task_id: TaskId, content: str, description: str) -> None:
        await self._inner.set_text(task_id, content, description)
        self._mark_stale()

    async def add_reminder(self, reminder: Reminder) -> None:
        await self._inner.add_reminder(reminder)
        self._mark_stale()

    async def delete_reminder(self, reminder_id: str) -> None:
        await self._inner.delete_reminder(reminder_id)
        self._mark_stale()

    async def apply_creation(self, plan: CreationPlan) -> None:
        await self._inner.apply_creation(plan)
        self._mark_stale()

    def _mark_stale(self) -> None:
        self._dirty = True
