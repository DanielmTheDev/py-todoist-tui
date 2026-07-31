from dataclasses import dataclass
from typing import NewType

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority

TaskId = NewType("TaskId", str)


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
