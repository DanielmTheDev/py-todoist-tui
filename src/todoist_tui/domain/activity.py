import datetime
from dataclasses import dataclass
from enum import StrEnum


class EventKind(StrEnum):
    """What happened to a task, as Todoist's activity log names it."""

    ADDED = "added"
    UPDATED = "updated"
    COMPLETED = "completed"
    UNCOMPLETED = "uncompleted"
    MOVED = "moved"
    DELETED = "deleted"
    OTHER = "other"

    @classmethod
    def _missing_(cls, value: object) -> "EventKind":
        # a verb this client doesn't know still belongs in the feed
        return cls.OTHER


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    """One entry of the activity log: a task changed, at a time, somehow."""

    id: str
    at: datetime.datetime
    kind: EventKind
    content: str
    task_id: str
    project_id: str | None


@dataclass(frozen=True, slots=True)
class ActivityPage:
    """One page of the log. `next_cursor` is `None` at the end of history."""

    events: tuple[ActivityEvent, ...]
    next_cursor: str | None
