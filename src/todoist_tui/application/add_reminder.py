from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.repository import TaskRepository


async def add_reminder(repo: TaskRepository, reminder: Reminder) -> None:
    await repo.add_reminder(reminder)
