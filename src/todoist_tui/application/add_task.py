"""Create a single task, optionally under a parent. Todoist takes a create as a
batched Sync command, so the work is one `CreationPlan` holding one task."""

import uuid
from collections.abc import Iterator

from todoist_tui.domain.creation import (
    CreationPlan,
    NewChild,
    NewReminder,
    NewTask,
)
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reminder import (
    Reminder,
    default_reminder,
    wants_default_reminder,
)
from todoist_tui.domain.repository import TaskRepository


def _uuid_temp_ids() -> Iterator[str]:
    while True:
        yield str(uuid.uuid4())


async def add_task(
    repo: TaskRepository,
    content: str,
    description: str = "",
    project_id: str | None = None,
    section_id: str | None = None,
    parent_id: str | None = None,
    due: Due | DueText | None = None,
    deadline: Deadline | None = None,
    priority: Priority = Priority.P4,
    labels: tuple[str, ...] = (),
    reminders: tuple[Reminder, ...] = (),
    subtasks: tuple[NewChild, ...] = (),
    temp_ids: Iterator[str] | None = None,
) -> None:
    """Add `content` to `project_id`, falling back to the Inbox when it is None.

    A subtask (`parent_id` set) inherits its parent's section, so the section is
    left out rather than sent alongside. A label Todoist doesn't know yet is
    registered by the create itself, so no separate step declares it. A due time
    with no reminder of its own earns the default one, as Todoist's own clients
    give it.

    `subtasks` are nested under the new task and created in the same batch — the
    parent has no id yet, so each points at its temp_id instead.
    """
    ids = temp_ids or _uuid_temp_ids()
    if wants_default_reminder(None, due, reminders):
        reminders = (default_reminder(),)
    task = NewTask(
        temp_id=next(ids),
        content=content,
        priority=priority,
        due=due,
        deadline=deadline,
        labels=labels,
        description=description,
        child_order=None,  # let Todoist append it to the end of its list
        project_ref=project_id or await _inbox_id(repo),
        section_ref=None if parent_id else section_id,
        parent_ref=parent_id,
    )
    # the task has no id until the batch lands, so its reminders ride along in it
    alerts = [NewReminder(next(ids), task.temp_id, reminder) for reminder in reminders]
    children: list[NewTask] = []
    for child in subtasks:
        born = _under(task, child, next(ids))
        children.append(born)
        alerts += [
            NewReminder(next(ids), born.temp_id, reminder)
            for reminder in _wanted(child)
        ]
    await repo.apply_creation(CreationPlan((), (), (task, *children), tuple(alerts)))


def _wanted(child: NewChild) -> tuple[Reminder, ...]:
    if wants_default_reminder(None, child.due, child.reminders):
        return (default_reminder(),)
    return child.reminders


def _under(parent: NewTask, child: NewChild, temp_id: str) -> NewTask:
    """A subtask of `parent`: its own attributes, in its parent's project and
    section — a subtask inherits where it goes, nothing else."""
    return NewTask(
        temp_id=temp_id,
        content=child.content,
        priority=child.priority,
        due=child.due,
        deadline=child.deadline,
        labels=child.labels,
        description=child.description,
        child_order=None,  # Todoist appends, so the batch's order is the list's
        project_ref=parent.project_ref,
        section_ref=None,
        parent_ref=parent.temp_id,
    )


async def _inbox_id(repo: TaskRepository) -> str:
    inbox = next((p for p in await repo.projects() if p.is_inbox), None)
    if inbox is None:
        raise LookupError("no inbox project found")
    return inbox.id
