"""Entities to create in one batched Sync trip.

Refs (`project_ref`/`section_ref`/`parent_ref`) hold either a `temp_id` of
another entity in this same plan or a real existing id — both are valid targets
in a batched Sync create. Pure: no I/O.
"""

from dataclasses import dataclass

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority


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
    due: Due | None
    deadline: Deadline | None
    labels: tuple[str, ...]
    description: str
    child_order: int
    project_ref: str
    section_ref: str | None
    parent_ref: str | None


@dataclass(frozen=True, slots=True)
class CreationPlan:
    projects: tuple[NewProject, ...]
    sections: tuple[NewSection, ...]
    tasks: tuple[NewTask, ...]
