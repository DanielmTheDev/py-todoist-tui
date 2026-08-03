from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def delete_task(repo: TaskRepository, task_id: TaskId) -> None:
    await repo.delete(task_id)
