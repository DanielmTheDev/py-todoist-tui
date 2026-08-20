"""Entities to create in one batched Sync trip.

Refs (`project_ref`/`section_ref`/`parent_ref`) hold either a `temp_id` of
another entity in this same plan or a real existing id — both are valid targets
in a batched Sync create. Pure: no I/O.
"""

from dataclasses import dataclass

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reminder import Reminder


@dataclass(frozen=True, slots=True)
class NewProject:
    temp_id: str
    name: str


@dataclass(frozen=True, slots=True)
class NewSection:
    temp_id: str
    name: str
    order: int
    project_ref: str


@dataclass(frozen=True, slots=True)
class NewTask:
    temp_id: str
    content: str
    priority: Priority
    due: Due | DueText | None  # a phrase is Todoist's to parse
    deadline: Deadline | None
    labels: tuple[str, ...]
    description: str
    child_order: int | None  # None lets Todoist append it to the end of its list
    project_ref: str
    section_ref: str | None
    parent_ref: str | None


@dataclass(frozen=True, slots=True)
class NewReminder:
    """A reminder for a task the same plan creates. `reminder`'s own `id` and
    `item_id` say nothing here — the plan's refs place it — but its payload rule
    is the one every reminder is written with."""

    temp_id: str
    item_ref: str
    reminder: Reminder


@dataclass(frozen=True, slots=True)
class CreationPlan:
    projects: tuple[NewProject, ...]
    sections: tuple[NewSection, ...]
    tasks: tuple[NewTask, ...]
    reminders: tuple[NewReminder, ...] = ()
