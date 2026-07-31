from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def set_deadline(
    repo: TaskRepository, task_id: TaskId, deadline: Deadline | None
) -> None:
    await repo.set_deadline(task_id, deadline)
