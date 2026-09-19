import datetime
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from todoist_tui.domain.task import Task


@dataclass(frozen=True, slots=True)
class Attachment:
    """A file hanging off a comment. Todoist serves a resized copy of an image
    under `tn_*`; the full file is `file_url`. Both need the account's token —
    an unauthenticated fetch answers a login page, not an error."""

    file_name: str
    file_type: str
    file_url: str
    file_size: int = 0
    image_width: int | None = None
    image_height: int | None = None
    thumbnail_url: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Attachment":
        # each tn_* is [url, width, height]; the medium one is the preview size
        thumbnail = data.get("tn_m") or data.get("tn_l") or data.get("tn_s")
        width, height = data.get("image_width"), data.get("image_height")
        return cls(
            file_name=str(data.get("file_name") or "attachment"),
            file_type=str(data.get("file_type") or ""),
            file_url=str(data.get("file_url") or ""),
            file_size=int(data.get("file_size") or 0),
            image_width=int(width) if width is not None else None,
            image_height=int(height) if height is not None else None,
            thumbnail_url=str(thumbnail[0]) if thumbnail else None,
        )

    @property
    def to_api(self) -> dict[str, Any]:
        """The `file_attachment` a comment is posted with. Todoist hands this
        dict back on upload and takes it again verbatim; the thumbnails it adds
        later are its own business, not something to send."""
        return {
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_url": self.file_url,
            "file_size": self.file_size,
            "image_width": self.image_width,
            "image_height": self.image_height,
        }

    @property
    def is_image(self) -> bool:
        return self.file_type.startswith("image/")

    @property
    def preview_url(self) -> str:
        """What to fetch for the inline preview: the resized copy when Todoist
        has made one, else the file itself — a just-uploaded image has no
        thumbnail yet, and showing it full-size beats showing nothing."""
        return self.thumbnail_url or self.file_url


@dataclass(frozen=True, slots=True)
class Comment:
    """One comment on a task, with the file it carries, if any."""

    id: str
    task_id: str
    content: str
    posted_at: datetime.datetime
    attachment: Attachment | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Comment":
        if "id" not in data:
            raise ValueError(f"comment missing id: {data!r}")
        attachment = data.get("file_attachment")
        return cls(
            id=str(data["id"]),
            task_id=str(data.get("item_id") or data.get("task_id") or ""),
            content=str(data.get("content") or ""),
            posted_at=_posted_at(data.get("posted_at")),
            attachment=Attachment.from_api(attachment) if attachment else None,
        )


def _posted_at(raw: object) -> datetime.datetime:
    """Todoist stamps comments in UTC with a trailing `Z`, which `fromisoformat`
    only learned in 3.11 — and an undated comment still has to sort somewhere."""
    if not isinstance(raw, str) or not raw:
        return datetime.datetime.min.replace(tzinfo=datetime.UTC)
    parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)


def with_note_counts(tasks: Iterable[Task], notes: Mapping[str, str]) -> list[Task]:
    """Stamp each task with how many comments `notes` (comment id -> task id)
    holds for it.

    The count cannot come off the task: Todoist fills `note_count` only in a full
    sync and never re-sends the item when a comment is added, so counting the
    comments we were sent is the only reading that stays true.
    """
    counts = Counter(notes.values())
    return [replace(task, note_count=counts[str(task.id)]) for task in tasks]
