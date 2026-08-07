from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def set_text(
    repo: TaskRepository, task_id: TaskId, content: str, description: str
) -> None:
    await repo.set_text(task_id, content, description)
