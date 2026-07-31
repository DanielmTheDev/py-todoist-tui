from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def move_task(
    repo: TaskRepository,
    task_id: TaskId,
    project_id: str,
    section_id: str | None = None,
) -> None:
    await repo.set_project(task_id, project_id, section_id)
