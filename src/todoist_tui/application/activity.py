import asyncio
from dataclasses import dataclass

from todoist_tui.domain.activity import ActivityEvent, EventKind
from todoist_tui.domain.repository import TaskRepository


@dataclass(frozen=True, slots=True)
class ActivityRow:
    """An event plus the project name the feed shows next to it."""

    event: ActivityEvent
    project_name: str | None


async def load_activity(
    repo: TaskRepository,
    event_type: EventKind | None = None,
    cursor: str | None = None,
) -> tuple[tuple[ActivityRow, ...], str | None]:
    """One page of activity, ready to render, plus the cursor for the next."""
    page, projects = await asyncio.gather(
        repo.activity(event_type, cursor), repo.projects()
    )
    names = {project.id: project.name for project in projects}
    rows = tuple(
        ActivityRow(event=event, project_name=names.get(event.project_id or ""))
        for event in page.events
    )
    return rows, page.next_cursor
