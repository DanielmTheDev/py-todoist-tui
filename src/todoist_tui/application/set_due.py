from collections.abc import Sequence
from dataclasses import replace

from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.reminder import (
    Reminder,
    default_reminder,
    wants_default_reminder,
)
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def set_due(
    repo: TaskRepository, task_id: TaskId, due: Due | DueText | None
) -> None:
    """Write a task's due and nothing else — what an undo restores."""
    _ = await repo.set_due(task_id, due)


async def schedule(
    repo: TaskRepository,
    task_id: TaskId,
    due: Due | DueText | None,
    reminders: Sequence[Reminder] = (),
) -> None:
    """Schedule a task the way the user asked, and give it the default reminder
    Todoist's own clients hang on a due time — the Sync API makes none, so a task
    scheduled here would otherwise stay silent.

    `reminders` are the ones the task already carries; one of its own means it
    needs no default. A due written as a phrase is only resolved server-side, so
    the decision reads the due as it landed. The reminder goes out behind the due
    it is relative to, which Todoist requires.
    """
    landed = await repo.set_due(task_id, due)
    if wants_default_reminder(landed, reminders):
        await repo.add_reminder(replace(default_reminder(), item_id=str(task_id)))
