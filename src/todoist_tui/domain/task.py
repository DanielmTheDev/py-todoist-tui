from dataclasses import dataclass
from typing import NewType

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority

TaskId = NewType("TaskId", str)

UNSET_DAY_ORDER = -1
"""What Todoist reports until something places a task in a day-scoped list."""


@dataclass(frozen=True, slots=True)
class Task:
    id: TaskId
    content: str
    priority: Priority
    due: Due | None
    project_id: str
    section_id: str | None = None
    labels: tuple[str, ...] = ()
    description: str = ""
    deadline: Deadline | None = None
    parent_id: str | None = None
    child_order: int = 0  # place among its siblings; Todoist's own manual order
    day_order: int = UNSET_DAY_ORDER  # place in a day list, across projects
