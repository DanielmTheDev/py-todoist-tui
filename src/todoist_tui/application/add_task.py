"""Create a single task, optionally under a parent. Todoist takes a create as a
batched Sync command, so the work is one `CreationPlan` holding one task."""

import uuid
from collections.abc import Iterator

from todoist_tui.domain.creation import CreationPlan, NewReminder, NewTask
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reminder import Reminder
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
    temp_ids: Iterator[str] | None = None,
) -> None:
    """Add `content` to `project_id`, falling back to the Inbox when it is None.

    A subtask (`parent_id` set) inherits its parent's section, so the section is
    left out rather than sent alongside. A label Todoist doesn't know yet is
    registered by the create itself, so no separate step declares it.
    """
    ids = temp_ids or _uuid_temp_ids()
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
    await repo.apply_creation(
        CreationPlan(
            (),
            (),
            (task,),
            tuple(
                NewReminder(next(ids), task.temp_id, reminder) for reminder in reminders
            ),
        )
    )


async def _inbox_id(repo: TaskRepository) -> str:
    inbox = next((p for p in await repo.projects() if p.is_inbox), None)
    if inbox is None:
        raise LookupError("no inbox project found")
    return inbox.id
