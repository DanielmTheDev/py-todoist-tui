from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import Task, TaskId


@dataclass(frozen=True, slots=True)
class TaskRow:
    """A task ready to render: project resolved to its name."""

    id: TaskId
    content: str
    priority: Priority
    due: Due | None
    project_name: str | None


@dataclass(frozen=True, slots=True)
class View:
    """A named list of tasks and how to fetch it from the repository."""

    title: str
    fetch: Callable[[TaskRepository], Awaitable[list[Task]]]


TODAY = View("Today", lambda repo: repo.today())
INBOX = View("Inbox", lambda repo: repo.inbox())


async def load_view(repo: TaskRepository, view: View) -> list[TaskRow]:
    tasks = await view.fetch(repo)
    names = {project.id: project.name for project in await repo.projects()}
    return [
        TaskRow(
            id=task.id,
            content=task.content,
            priority=task.priority,
            due=task.due,
            project_name=names.get(task.project_id),
        )
        for task in tasks
    ]
