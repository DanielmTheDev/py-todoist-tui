"""Duplicate a whole project (as a new top-level project) or a single section
(within its project), copying active tasks and their metadata. Todoist has no
server-side duplicate, so the work is: read the source, build a creation plan,
apply it as one batched Sync create."""

import uuid
from collections.abc import Iterator

from todoist_tui.domain.duplication import (
    build_project_duplicate,
    build_section_duplicate,
)
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.section import Section


def _uuid_temp_ids() -> Iterator[str]:
    while True:
        yield str(uuid.uuid4())


async def duplicate_project(
    repo: TaskRepository,
    project_id: str,
    new_name: str,
    temp_ids: Iterator[str] | None = None,
) -> None:
    project = next((p for p in await repo.projects() if p.id == project_id), None)
    if project is None:
        raise LookupError(f"no project {project_id!r}")
    sections = [s for s in await repo.sections() if s.project_id == project_id]
    tasks = await repo.by_project(project_id)
    plan = build_project_duplicate(
        project, sections, tasks, new_name, temp_ids or _uuid_temp_ids()
    )
    await repo.apply_creation(plan)


async def duplicate_section(
    repo: TaskRepository,
    section: Section,
    new_name: str,
    temp_ids: Iterator[str] | None = None,
) -> None:
    tasks = [
        t
        for t in await repo.by_project(section.project_id)
        if t.section_id == section.id
    ]
    plan = build_section_duplicate(
        section, tasks, new_name, temp_ids or _uuid_temp_ids()
    )
    await repo.apply_creation(plan)
