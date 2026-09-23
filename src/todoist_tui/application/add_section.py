"""Create a section in a project, at a place of the caller's choosing."""

import uuid

from todoist_tui.domain.creation import CreationPlan, NewSection
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.section import Section, section_insert_plan


async def add_section(
    repo: TaskRepository,
    project_id: str,
    name: str,
    sections: list[Section],
    after_id: str | None,
    temp_id: str | None = None,
) -> None:
    """Add `name` to `project_id`, following the section `after_id` names.

    `sections` is what the caller has on screen, project-wide or not; only the
    target project's own sections decide the order. The sections the new one
    pushes down are renumbered first, so it never lands sharing an order.
    """
    order, moved = section_insert_plan(
        [section for section in sections if section.project_id == project_id], after_id
    )
    if moved:
        await repo.reorder_sections(moved)
    await repo.apply_creation(
        CreationPlan(
            (),
            (NewSection(temp_id or str(uuid.uuid4()), name, order, project_id),),
            (),
        )
    )
