from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from todoist_tui.domain.due import Due, DueText

ReminderType = Literal["absolute", "relative"]

DEFAULT_REMINDER_OFFSET = 0  # the account's `auto_reminder`: fire at the due time


@dataclass(frozen=True, slots=True)
class Reminder:
    """A task reminder. `absolute` fires at `due`'s datetime — recurring when
    its rule does, a `DueText` phrase until the server parses one; `relative`
    fires `minute_offset` minutes before the task's own due time. Location
    reminders are not modelled — the TUI has no way to enter them."""

    id: str
    item_id: str
    type: ReminderType
    due: Due | DueText | None = None
    minute_offset: int | None = None
    notify_uid: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Reminder":
        if "id" not in data or "item_id" not in data:
            raise ValueError(f"reminder missing id/item_id: {data!r}")
        raw_due = data.get("due")
        offset = data.get("minute_offset")
        return cls(
            id=str(data["id"]),
            item_id=str(data["item_id"]),
            type="relative" if data.get("type") == "relative" else "absolute",
            due=Due.from_api(raw_due) if raw_due else None,
            minute_offset=int(offset) if offset is not None else None,
            notify_uid=(
                str(data["notify_uid"]) if data.get("notify_uid") is not None else None
            ),
        )

    @property
    def to_api(self) -> dict[str, Any]:
        """`reminder_add` args for this reminder, minus `item_id` (the client
        supplies it). `notify_uid` is omitted — Todoist defaults it to the task's
        owner for a personal task."""
        if self.type == "absolute":
            if self.due is None:
                raise ValueError("absolute reminder needs a due")
            return {"type": "absolute", "due": self.due.to_api}
        if self.minute_offset is None:
            raise ValueError("relative reminder needs a minute_offset")
        return {"type": "relative", "minute_offset": self.minute_offset}


def default_reminder() -> Reminder:
    """The reminder Todoist's own clients hang on a task due at a time. The Sync
    API leaves it to the client, so a task scheduled here would otherwise never
    notify."""
    return Reminder(
        id="", item_id="", type="relative", minute_offset=DEFAULT_REMINDER_OFFSET
    )


def wants_default_reminder(due: Due | None, reminders: Sequence[Reminder]) -> bool:
    """Whether a task due at a time has nothing to remind about it yet.

    A due written as a phrase is parsed server-side, so pass the due as it
    landed — not the phrase. Todoist refuses a relative reminder on an all-day
    task, which is why only a due time earns one.
    """
    return due is not None and due.time is not None and not reminders
