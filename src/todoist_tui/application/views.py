import asyncio
import datetime
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
    project_id: str | None = None
    section_id: str | None = None
    section_name: str | None = None
    labels: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True, slots=True)
class View:
    """A named list of tasks and how to fetch it from the repository.

    `key` is a stable identity used to persist this view's arrangement.
    `keeps` client-side tests whether a (possibly just-edited) row still belongs
    in this view, so an edit can drop the row without waiting for a resync. None
    when membership is fixed (Inbox) or only the server can decide (saved filters).
    """

    title: str
    key: str
    fetch: Callable[[TaskRepository], Awaitable[list[Task]]]
    keeps: Callable[[TaskRow, datetime.date], bool] | None = None


def _due_today(row: TaskRow, today: datetime.date) -> bool:
    # mirrors FilterQuery("today"): a task belongs to Today iff due on `today`
    return row.due is not None and row.due.date == today


TODAY = View("Today", "today", lambda repo: repo.today(), keeps=_due_today)
INBOX = View("Inbox", "inbox", lambda repo: repo.inbox())


def filter_view(f: Filter) -> View:
    """A view backed by a saved filter, evaluated server-side by its query."""
    return View(f.name, f"filter:{f.id}", lambda repo: repo.filtered(f.query))


async def load_view(repo: TaskRepository, view: View) -> list[TaskRow]:
    tasks, projects, sections = await asyncio.gather(
        view.fetch(repo), repo.projects(), repo.sections()
    )
    names = {project.id: project.name for project in projects}
    section_names = {section.id: section.name for section in sections}
    return [
        TaskRow(
            id=task.id,
            content=task.content,
            priority=task.priority,
            due=task.due,
            project_name=names.get(task.project_id),
            project_id=task.project_id,
            section_id=task.section_id,
            section_name=(
                section_names.get(task.section_id) if task.section_id else None
            ),
            labels=task.labels,
            description=task.description,
        )
        for task in tasks
    ]
