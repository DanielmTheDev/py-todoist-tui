from dataclasses import dataclass
from typing import Protocol

from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId


class TaskRepository(Protocol):
    """Port to the task backend. Adapters live in the `api`/`store` layers."""

    async def today(self) -> list[Task]: ...

    async def inbox(self) -> list[Task]: ...

    async def projects(self) -> list[Project]: ...

    async def complete(self, task_id: TaskId) -> None: ...


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One /sync trip's worth of state: all projects and tasks."""

    projects: list[Project]
    tasks: list[Task]


class SnapshotSource(Protocol):
    """Fetches a full account snapshot in a single trip."""

    async def snapshot(self) -> Snapshot: ...
