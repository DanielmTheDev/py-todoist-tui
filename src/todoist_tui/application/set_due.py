from todoist_tui.domain.due import Due
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def set_due(repo: TaskRepository, task_id: TaskId, due: Due | None) -> None:
    await repo.set_due(task_id, due)
