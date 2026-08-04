from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def set_labels(
    repo: TaskRepository,
    task_id: TaskId,
    labels: tuple[str, ...],
    create: tuple[str, ...] = (),
) -> None:
    await repo.set_labels(task_id, labels, create)
