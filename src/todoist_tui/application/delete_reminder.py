from todoist_tui.domain.repository import TaskRepository


async def delete_reminder(repo: TaskRepository, reminder_id: str) -> None:
    await repo.delete_reminder(reminder_id)
