"""Build a plan for recreating a project or section under new IDs.

Todoist has no server-side duplicate command, so a copy is made by recreating
the source as fresh entities. Pure: no I/O.
"""

import itertools
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator

from todoist_tui.domain.creation import CreationPlan, NewProject, NewSection, NewTask
from todoist_tui.domain.project import Project
from todoist_tui.domain.section import Section, sorted_sections
from todoist_tui.domain.task import Task


def build_project_duplicate(
    project: Project,
    sections: Iterable[Section],
    tasks: Iterable[Task],
    new_name: str,
    temp_ids: Iterator[str],
) -> CreationPlan:
    new_project = NewProject(temp_id=next(temp_ids), name=new_name)
    new_sections: list[NewSection] = []
    section_ref: dict[str, str] = {}
    for section in sorted_sections(list(sections)):
        temp_id = next(temp_ids)
        section_ref[section.id] = temp_id
        new_sections.append(
            NewSection(
                temp_id=temp_id,
                name=section.name,
                order=section.order,
                project_ref=new_project.temp_id,
            )
        )
    new_tasks = _rebuild_tasks(
        tasks,
        temp_ids,
        project_ref=new_project.temp_id,
        section_ref_of=lambda task: section_ref.get(task.section_id or ""),
    )
    return CreationPlan((new_project,), tuple(new_sections), new_tasks)


def build_section_duplicate(
    section: Section,
    tasks: Iterable[Task],
    new_name: str,
    temp_ids: Iterator[str],
) -> CreationPlan:
    new_section = NewSection(
        temp_id=next(temp_ids),
        name=new_name,
        order=section.order,
        project_ref=section.project_id,
    )
    new_tasks = _rebuild_tasks(
        tasks,
        temp_ids,
        project_ref=section.project_id,
        section_ref_of=lambda _task: new_section.temp_id,
    )
    return CreationPlan((), (new_section,), new_tasks)


def _rebuild_tasks(
    tasks: Iterable[Task],
    temp_ids: Iterator[str],
    project_ref: str,
    section_ref_of: Callable[[Task], str | None],
) -> tuple[NewTask, ...]:
    source = list(tasks)
    temp_of = {task.id: next(temp_ids) for task in source}
    children: dict[str | None, list[Task]] = defaultdict(list)
    for task in source:
        parent = task.parent_id if task.parent_id in temp_of else None
        children[parent].append(task)

    order = itertools.count()
    result: list[NewTask] = []

    def add(task: Task, parent_ref: str | None, section: str | None) -> None:
        temp_id = temp_of[task.id]
        result.append(
            NewTask(
                temp_id=temp_id,
                content=task.content,
                priority=task.priority,
                due=task.due,
                deadline=task.deadline,
                labels=task.labels,
                description=task.description,
                child_order=next(order),
                project_ref=project_ref,
                section_ref=section,
                parent_ref=parent_ref,
            )
        )
        # a subtask inherits its parent's section, not its own record's
        for child in children[task.id]:
            add(child, temp_id, section)

    for root in children[None]:
        add(root, None, section_ref_of(root))
    return tuple(result)
