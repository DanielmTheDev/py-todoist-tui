"""A task's attributes as the editor holds them, mid-edit.

One draft serves both an add (seeded with defaults) and an edit (seeded from the
row), so the two flows can never drift apart. `*_name` fields are what the strip
shows; the ids are what the save applies.
"""

import datetime
from collections.abc import Iterable
from dataclasses import dataclass

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reminder import Reminder
from todoist_tui.tui.format import (
    format_deadline,
    format_due,
    format_labels,
    format_reminder,
)

_UNSET = "—"


@dataclass(frozen=True, slots=True)
class Subtask:
    """A subtask as the editor holds it: a draft of its own, plus the row it came
    from — None for one the save has yet to create. `done` is a completion the
    save applies, so it can be taken back until then."""

    draft: "TaskDraft"
    row: TaskRow | None = None
    done: bool = False

    @property
    def content(self) -> str:
        return self.draft.content


@dataclass(frozen=True, slots=True)
class TaskDraft:
    content: str
    description: str
    priority: Priority = Priority.P4
    due: Due | DueText | None = None
    deadline: Deadline | None = None
    labels: tuple[str, ...] = ()
    # names the picker offered to create, which the save registers as it goes
    new_labels: tuple[str, ...] = ()
    project_id: str | None = None
    project_name: str = ""
    section_id: str | None = None
    section_name: str | None = None
    parent_id: str | None = None
    # the parent as picked here, carrying what an optimistic re-parent needs. A
    # task already nested when the editor opened has the id without the row.
    parent: TaskRow | None = None
    subtasks: tuple[Subtask, ...] = ()
    reminders: tuple[Reminder, ...] = ()


def draft_of(
    row: TaskRow,
    parent: TaskRow | None = None,
    children: Iterable[TaskRow] = (),
) -> TaskDraft:
    """The task as it stands, ready to be edited."""
    return TaskDraft(
        content=row.content,
        description=row.description,
        priority=row.priority,
        due=row.due,
        deadline=row.deadline,
        labels=row.labels,
        project_id=row.project_id,
        project_name=row.project_name or "",
        section_id=row.section_id,
        section_name=row.section_name,
        parent_id=row.parent_id,
        parent=parent,
        subtasks=tuple(Subtask(draft_of(child), child) for child in children),
        reminders=row.reminders,
    )


def attribute_strip(draft: TaskDraft, today: datetime.date) -> str:
    """One line naming every attribute the draft carries, in the detail card's
    wording so the two read the same."""
    return " · ".join(
        f"{name} {value or _UNSET}"
        for name, value in (
            ("Due", _due(draft.due, today)),
            ("Deadline", format_deadline(draft.deadline, today)),
            ("Project", _project(draft)),
            ("Parent", _parent(draft)),
            ("Subtasks", _subtasks(draft)),
            ("Reminders", _reminders(draft, today)),
            ("Labels", format_labels(draft.labels)),
            ("Priority", draft.priority.label),
        )
    )


def _parent(draft: TaskDraft) -> str:
    if draft.parent is not None:
        return draft.parent.content
    return "(a task)" if draft.parent_id else ""


def _subtasks(draft: TaskDraft) -> str:
    return str(len(draft.subtasks)) if draft.subtasks else ""


def _due(due: Due | DueText | None, today: datetime.date) -> str:
    # a typed phrase is Todoist's to parse, so it is shown as written
    return due.text if isinstance(due, DueText) else format_due(due, today)


def _project(draft: TaskDraft) -> str:
    if draft.section_name is None:
        return draft.project_name
    return f"{draft.project_name} / {draft.section_name}"


def _reminders(draft: TaskDraft, today: datetime.date) -> str:
    return ", ".join(format_reminder(r, today) for r in draft.reminders)
