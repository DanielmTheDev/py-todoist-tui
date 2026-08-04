import asyncio
import datetime
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from todoist_tui.domain.arrange import Arrangement, Field
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.search import SearchTerm, parse_search
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
    section_order: int = 0
    labels: tuple[str, ...] = ()
    description: str = ""
    deadline: Deadline | None = None
    parent_id: str | None = None


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
    # applied until the user saves an arrangement for this view
    default_arrangement: Arrangement = field(default_factory=Arrangement)


def _due_today(row: TaskRow, today: datetime.date) -> bool:
    # mirrors FilterQuery("today"): a task belongs to Today iff due on `today`
    return row.due is not None and row.due.date == today


TODAY = View("Today", "today", lambda repo: repo.today(), keeps=_due_today)
INBOX = View("Inbox", "inbox", lambda repo: repo.inbox())


def filter_view(f: Filter) -> View:
    """A view backed by a saved filter, evaluated server-side by its query."""
    return View(f.name, f"filter:{f.id}", lambda repo: repo.filtered(f.query))


def search_view(term: SearchTerm) -> View:
    """A view of every task matching free text, evaluated server-side."""
    return View(
        f"Search: {term.text}",
        f"search:{term.text}",
        lambda repo: repo.filtered(term.query),
    )


def project_view(p: Project) -> View:
    """A view of one project's tasks; a move drops the row without a resync."""
    return View(
        p.name,
        f"project:{p.id}",
        lambda repo: repo.by_project(p.id),
        keeps=lambda row, _today: row.project_id == p.id,
        default_arrangement=Arrangement(group_by=(Field.SECTION,)),  # like Todoist
    )


def view_from_key(
    key: str, projects: list[Project], filters: list[Filter]
) -> View | None:
    """Rebuild the View a stored key names, or None if its target is gone.

    Inverse of the `View.key` the factories above emit. `None` lets the caller
    fall back (e.g. to TODAY) when a saved project/filter has since vanished.
    """
    if key == TODAY.key:
        return TODAY
    if key == INBOX.key:
        return INBOX
    if key.startswith("project:"):
        target = key[len("project:") :]
        project = next((p for p in projects if p.id == target), None)
        return project_view(project) if project is not None else None
    if key.startswith("filter:"):
        target = key[len("filter:") :]
        found = next((f for f in filters if f.id == target), None)
        return filter_view(found) if found is not None else None
    if key.startswith("search:"):
        term = parse_search(key[len("search:") :])
        # a hand-edited or stale key must not be able to provoke a 400
        return search_view(term) if isinstance(term, SearchTerm) else None
    return None


def query_for_key(key: str, filters: list[Filter]) -> str | None:
    """The server-side query a stored key's view re-runs to stay live, if any.

    Companion to `view_from_key`, so knowledge of the key format stays here.
    """
    if key.startswith("search:"):
        term = parse_search(key[len("search:") :])
        return term.query if isinstance(term, SearchTerm) else None
    return next((f.query for f in filters if f"filter:{f.id}" == key), None)


async def load_view(repo: TaskRepository, view: View) -> list[TaskRow]:
    tasks, projects, sections = await asyncio.gather(
        view.fetch(repo), repo.projects(), repo.sections()
    )
    names = {project.id: project.name for project in projects}
    sections_by_id = {section.id: section for section in sections}
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
                sections_by_id[task.section_id].name
                if task.section_id and task.section_id in sections_by_id
                else None
            ),
            section_order=(
                sections_by_id[task.section_id].order
                if task.section_id and task.section_id in sections_by_id
                else 0
            ),
            labels=task.labels,
            description=task.description,
            deadline=task.deadline,
            parent_id=task.parent_id,
        )
        for task in tasks
    ]
