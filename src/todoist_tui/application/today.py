from dataclasses import dataclass

from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.repository import TaskRepository


@dataclass(frozen=True, slots=True)
class TodayRow:
    """A task due today, ready to render: project resolved to its name."""

    content: str
    priority: Priority
    due: Due | None
    project_name: str | None


async def load_today(repo: TaskRepository) -> list[TodayRow]:
    tasks = await repo.today()
    names = {project.id: project.name for project in await repo.projects()}
    return [
        TodayRow(
            content=task.content,
            priority=task.priority,
            due=task.due,
            project_name=names.get(task.project_id),
        )
        for task in tasks
    ]
