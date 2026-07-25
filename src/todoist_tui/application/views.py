import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
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
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class View:
    """A named list of tasks and how to fetch it from the repository.

    `key` is a stable identity used to persist this view's arrangement.
    """

    title: str
    key: str
    fetch: Callable[[TaskRepository], Awaitable[list[Task]]]


TODAY = View("Today", "today", lambda repo: repo.today())
INBOX = View("Inbox", "inbox", lambda repo: repo.inbox())


def filter_view(f: Filter) -> View:
    """A view backed by a saved filter, evaluated server-side by its query."""
    return View(f.name, f"filter:{f.id}", lambda repo: repo.filtered(f.query))


async def load_view(repo: TaskRepository, view: View) -> list[TaskRow]:
    tasks, projects = await asyncio.gather(view.fetch(repo), repo.projects())
    names = {project.id: project.name for project in projects}
    return [
        TaskRow(
            id=task.id,
            content=task.content,
            priority=task.priority,
            due=task.due,
            project_name=names.get(task.project_id),
            labels=task.labels,
        )
        for task in tasks
    ]
