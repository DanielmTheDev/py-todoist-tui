import asyncio

from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import Task, TaskId


class CachingTaskRepository:
    """Session-memoizes projects(); other calls delegate to the wrapped repo."""

    def __init__(self, inner: TaskRepository) -> None:
        self._inner = inner
        self._projects: list[Project] | None = None
        self._lock = asyncio.Lock()

    async def projects(self) -> list[Project]:
        if self._projects is None:
            async with self._lock:
                if self._projects is None:
                    self._projects = await self._inner.projects()
        return self._projects

    async def today(self) -> list[Task]:
        return await self._inner.today()

    async def inbox(self) -> list[Task]:
        return await self._inner.inbox()

    async def complete(self, task_id: TaskId) -> None:
        await self._inner.complete(task_id)
