"""A task's attributes as the editor holds them, mid-edit.

One draft serves both an add (seeded with defaults) and an edit (seeded from the
row), so the two flows can never drift apart. `*_name` fields are what the strip
shows; the ids are what the save applies.
"""

import datetime
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text

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
    priority_dot,
)
from todoist_tui.tui.theme import Tier

# Nerd Font (nf-md) glyphs standing in for the field names
DUE_ICON = "\U000f00ed"  # calendar
DEADLINE_ICON = "\U000f00f0"  # calendar-clock
PROJECT_ICON = "\U000f024b"  # folder
PARENT_ICON = "\U000f005d"  # arrow-up
SUBTASKS_ICON = "\U000f0645"  # file-tree
REMINDERS_ICON = "\U000f009a"  # bell
LABELS_ICON = "\U000f04f9"  # tag
_SEPARATOR = " · "


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


def attribute_strip(
    draft: TaskDraft,
    today: datetime.date,
    tiers: Mapping[Tier, Style],
    priorities: Mapping[Priority, Style],
) -> Text:
    """One line of icon-marked runs for the attributes the draft carries; an
    unset field drops out entirely, since f1 help names them all. A `Text` so
    a title's own brackets never read as Rich markup."""
    icon, value = tiers[Tier.MUTED], tiers[Tier.PRIMARY]
    text = Text()
    for glyph, shown in (
        (DUE_ICON, _due(draft.due, today)),
        (DEADLINE_ICON, format_deadline(draft.deadline, today)),
        (PROJECT_ICON, _project(draft)),
        (PARENT_ICON, _parent(draft)),
        (SUBTASKS_ICON, _subtasks(draft)),
        (REMINDERS_ICON, _reminders(draft, today)),
        (LABELS_ICON, format_labels(draft.labels)),
    ):
        if not shown:
            continue
        text.append(f"{glyph} ", style=icon)
        text.append(shown, style=value)
        text.append(_SEPARATOR, style=icon)
    dot = priority_dot(draft.priority)
    if dot:
        text.append(f"{dot} ", style=priorities[draft.priority])
    text.append(draft.priority.label, style=value)
    return text


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
