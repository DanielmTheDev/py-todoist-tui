import datetime
from dataclasses import dataclass

from todoist_tui.domain.task import Task


@dataclass(frozen=True, slots=True)
class FilterQuery:
    """A Todoist filter expression evaluated over cached tasks. Today-only so far."""

    text: str

    def matches(self, task: Task, today: datetime.date) -> bool:
        if self.text == "today":
            return task.due is not None and task.due.date == today
        raise ValueError(f"unsupported filter query: {self.text!r}")
