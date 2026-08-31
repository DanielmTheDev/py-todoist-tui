from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from todoist_tui.domain.activity import ActivityPage, EventKind
from todoist_tui.domain.arrange import Arrangement, GroupPath
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.domain.view_slots import ViewSlots

if TYPE_CHECKING:
    from todoist_tui.domain.creation import CreationPlan
    from todoist_tui.domain.sync_delta import SyncDelta


class TaskRepository(Protocol):
    """Port to the task backend. Adapters live in the `api`/`store` layers."""

    async def today(self) -> list[Task]: ...

    async def inbox(self) -> list[Task]: ...

    async def by_project(self, project_id: str) -> list[Task]: ...

    async def filtered(self, query: str) -> list[Task]: ...

    async def refresh_filtered(self, query: str) -> list[Task]: ...

    async def all_tasks(self) -> list[Task]:
        """Every open task, whatever view it belongs to — the pool a view draws
        the subtasks of its matches from."""
        ...

    async def projects(self) -> list[Project]: ...

    async def sections(self) -> list[Section]: ...

    async def filters(self) -> list[Filter]: ...

    async def labels(self) -> list[Label]: ...

    async def reminders(self) -> list[Reminder]: ...

    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        """One page of the task activity log, newest first."""
        ...

    async def complete(self, task_id: TaskId) -> None: ...

    async def uncomplete(self, task_id: TaskId) -> None: ...

    async def delete(self, task_id: TaskId) -> None: ...

    async def delete_section(self, section_id: str) -> None:
        """Delete a section and, server-side, every task inside it."""
        ...

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None: ...

    async def set_due(self, task_id: TaskId, due: Due | DueText | None) -> None:
        """A `DueText` hands Todoist the phrase to parse instead of a date."""
        ...

    async def set_deadline(
        self, task_id: TaskId, deadline: Deadline | None
    ) -> None: ...

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None: ...

    async def set_parent(self, task_id: TaskId, parent_id: str) -> None: ...

    async def reorder(self, items: Sequence[tuple[TaskId, int]]) -> None:
        """Set each task's `child_order` — its place among its siblings."""
        ...

    async def set_day_orders(self, items: Sequence[tuple[TaskId, int]]) -> None:
        """Set each task's `day_order` — its place in a day-scoped list."""
        ...

    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None: ...

    async def set_text(self, task_id: TaskId, content: str, description: str) -> None:
        """Replace both prose fields; an empty description clears it."""
        ...

    async def add_reminder(self, reminder: Reminder) -> None: ...

    async def delete_reminder(self, reminder_id: str) -> None: ...

    async def apply_creation(self, plan: "CreationPlan") -> None: ...

    async def refresh(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One /sync trip's worth of state: projects, tasks, saved filters, token."""

    projects: list[Project]
    tasks: list[Task]
    sync_token: str
    filters: list[Filter] = field(default_factory=list[Filter])
    sections: list[Section] = field(default_factory=list[Section])
    labels: list[Label] = field(default_factory=list[Label])
    reminders: list[Reminder] = field(default_factory=list[Reminder])


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
    """Persists each view's group/sort arrangement.

    `get` returns `default` only when the view was never saved; a saved (even
    empty) arrangement always wins, so clearing a view's grouping sticks.
    """

    async def get(
        self, view_key: str, default: Arrangement | None = None
    ) -> Arrangement: ...

    async def save(self, view_key: str, arrangement: Arrangement) -> None: ...


class FoldStore(Protocol):
    """Persists which of a view's groups are unfolded.

    An unknown view has nothing open, which is how a group starts: folded.
    """

    async def get(self, view_key: str) -> frozenset[GroupPath]: ...

    async def save(self, view_key: str, open_groups: frozenset[GroupPath]) -> None: ...


class ViewSlotStore(Protocol):
    """Persists the keys that jump to a view, and which view opens on startup.

    `save` replaces the whole set — the slots are edited as one value object.
    """

    async def get(self) -> ViewSlots: ...

    async def save(self, slots: ViewSlots) -> None: ...
