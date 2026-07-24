from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def complete_task(repo: TaskRepository, task_id: TaskId) -> None:
    await repo.complete(task_id)


async def uncomplete_task(repo: TaskRepository, task_id: TaskId) -> None:
    await repo.uncomplete(task_id)
