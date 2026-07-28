from todoist_tui.domain.priority import Priority
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def set_priority(
    repo: TaskRepository, task_id: TaskId, priority: Priority
) -> None:
    await repo.set_priority(task_id, priority)
