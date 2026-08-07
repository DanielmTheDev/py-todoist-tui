from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def delete_task(repo: TaskRepository, task_id: TaskId) -> None:
    await repo.delete(task_id)


async def delete_section(repo: TaskRepository, section_id: str) -> None:
    await repo.delete_section(section_id)
