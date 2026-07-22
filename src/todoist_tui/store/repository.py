import asyncio

from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot, SnapshotSource, TaskRepository
from todoist_tui.domain.task import Task, TaskId


class SnapshotTaskRepository:
    """Serves projects()/inbox() from one memoized /sync snapshot.

    today() stays on the server filter via `inner`; complete() forwards then
    invalidates the snapshot so the next read re-syncs.
    """

    def __init__(self, inner: TaskRepository, source: SnapshotSource) -> None:
        self._inner = inner
        self._source = source
        self._snapshot: Snapshot | None = None
        self._lock = asyncio.Lock()

    async def _snapshot_now(self) -> Snapshot:
        if self._snapshot is None:
            async with self._lock:
                if self._snapshot is None:
                    self._snapshot = await self._source.snapshot()
        return self._snapshot

    async def projects(self) -> list[Project]:
        return (await self._snapshot_now()).projects

    async def inbox(self) -> list[Task]:
        snapshot = await self._snapshot_now()
        inbox = next((p for p in snapshot.projects if p.is_inbox), None)
        if inbox is None:
            raise LookupError("no inbox project found")
        return [task for task in snapshot.tasks if task.project_id == inbox.id]

    async def today(self) -> list[Task]:
        return await self._inner.today()

    async def complete(self, task_id: TaskId) -> None:
        await self._inner.complete(task_id)
        self._snapshot = None
