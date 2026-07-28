from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from todoist_tui.domain.arrange import Arrangement
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId

if TYPE_CHECKING:
    from todoist_tui.domain.sync_delta import SyncDelta


class TaskRepository(Protocol):
    """Port to the task backend. Adapters live in the `api`/`store` layers."""

    async def today(self) -> list[Task]: ...

    async def inbox(self) -> list[Task]: ...

    async def filtered(self, query: str) -> list[Task]: ...

    async def refresh_filtered(self, query: str) -> list[Task]: ...

    async def projects(self) -> list[Project]: ...

    async def filters(self) -> list[Filter]: ...

    async def complete(self, task_id: TaskId) -> None: ...

    async def uncomplete(self, task_id: TaskId) -> None: ...

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def refresh(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One /sync trip's worth of state: projects, tasks, saved filters, token."""

    projects: list[Project]
    tasks: list[Task]
    sync_token: str
    filters: list[Filter] = field(default_factory=list[Filter])


class SnapshotSource(Protocol):
    """Fetches account changes in a single /sync trip.

    `since=None` requests a full sync; a token requests only the changes made
    since it. Imported lazily to keep the delta type out of the port module.
    """

    async def delta(self, since: str | None) -> "SyncDelta": ...


class SnapshotCache(Protocol):
    """Persists the latest snapshot across restarts. `load` returns None when cold."""

    async def load(self) -> Snapshot | None: ...

    async def save(self, snapshot: Snapshot) -> None: ...


class ArrangementStore(Protocol):
    """Persists each view's group/sort arrangement. `get` is empty when unset."""

    async def get(self, view_key: str) -> Arrangement: ...

    async def save(self, view_key: str, arrangement: Arrangement) -> None: ...
