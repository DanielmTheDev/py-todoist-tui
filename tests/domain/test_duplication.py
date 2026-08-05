import datetime
import itertools
from collections.abc import Iterator

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.duplication import (
    build_project_duplicate,
    build_section_duplicate,
)
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId


def _temp_ids() -> Iterator[str]:
    return (f"tmp{i}" for i in itertools.count())


def _task(
    id: str,
    content: str = "x",
    *,
    project_id: str = "P",
    section_id: str | None = None,
    parent_id: str | None = None,
    priority: Priority = Priority.P4,
    due: Due | None = None,
    deadline: Deadline | None = None,
    labels: tuple[str, ...] = (),
    description: str = "",
) -> Task:
    return Task(
        id=TaskId(id),
        content=content,
        priority=priority,
        due=due,
        project_id=project_id,
        section_id=section_id,
        labels=labels,
        description=description,
        deadline=deadline,
        parent_id=parent_id,
    )


def test_project_duplicate_names_the_new_project() -> None:
    plan = build_project_duplicate(
        Project(id="P", name="Work"),
        sections=[],
        tasks=[],
        new_name="Work (copy)",
        temp_ids=_temp_ids(),
    )

    assert len(plan.projects) == 1
    assert plan.projects[0].name == "Work (copy)"
    assert plan.sections == ()
    assert plan.tasks == ()


def test_project_duplicate_recreates_sections_in_order() -> None:
    sections = [
        Section(id="s2", project_id="P", name="Later", order=2),
        Section(id="s1", project_id="P", name="Now", order=1),
    ]

    plan = build_project_duplicate(
        Project(id="P", name="Work"),
        sections=sections,
        tasks=[],
        new_name="Work (copy)",
        temp_ids=_temp_ids(),
    )

    proj_ref = plan.projects[0].temp_id
    assert [(s.name, s.order) for s in plan.sections] == [("Now", 1), ("Later", 2)]
    assert all(s.project_ref == proj_ref for s in plan.sections)
    assert len({s.temp_id for s in plan.sections}) == 2
    assert {s.temp_id for s in plan.sections}.isdisjoint({"s1", "s2"})


def test_project_duplicate_sectionless_task_points_at_new_project() -> None:
    task = _task("t1", content="loose")

    plan = build_project_duplicate(
        Project(id="P", name="Work"),
        sections=[],
        tasks=[task],
        new_name="Work (copy)",
        temp_ids=_temp_ids(),
    )

    nt = plan.tasks[0]
    assert nt.content == "loose"
    assert nt.section_ref is None
    assert nt.project_ref == plan.projects[0].temp_id
    assert nt.parent_ref is None


def test_project_duplicate_task_points_at_its_new_section() -> None:
    section = Section(id="s1", project_id="P", name="Now", order=1)
    task = _task("t1", section_id="s1")

    plan = build_project_duplicate(
        Project(id="P", name="Work"),
        sections=[section],
        tasks=[task],
        new_name="Work (copy)",
        temp_ids=_temp_ids(),
    )

    assert plan.tasks[0].section_ref == plan.sections[0].temp_id


def test_project_duplicate_carries_task_metadata() -> None:
    due = Due(date=datetime.date(2026, 7, 21), string="every day", is_recurring=True)
    deadline = Deadline(date=datetime.date(2026, 8, 1))
    task = _task(
        "t1",
        content="c",
        priority=Priority.P1,
        due=due,
        deadline=deadline,
        labels=("a", "b"),
        description="notes",
    )

    plan = build_project_duplicate(
        Project(id="P", name="Work"),
        sections=[],
        tasks=[task],
        new_name="W2",
        temp_ids=_temp_ids(),
    )

    nt = plan.tasks[0]
    assert nt.priority is Priority.P1
    assert nt.due is due
    assert nt.deadline is deadline
    assert nt.labels == ("a", "b")
    assert nt.description == "notes"


def test_project_duplicate_subtask_points_at_new_parent() -> None:
    section = Section(id="s1", project_id="P", name="Now", order=1)
    parent = _task("p", content="parent", section_id="s1")
    child = _task("c", content="child", section_id="s1", parent_id="p")

    plan = build_project_duplicate(
        Project(id="P", name="Work"),
        sections=[section],
        tasks=[parent, child],
        new_name="W2",
        temp_ids=_temp_ids(),
    )

    new_parent = next(t for t in plan.tasks if t.content == "parent")
    new_child = next(t for t in plan.tasks if t.content == "child")
    assert new_parent.parent_ref is None
    assert new_child.parent_ref == new_parent.temp_id
    assert new_child.section_ref == new_parent.section_ref


def test_project_duplicate_orphaned_subtask_becomes_root() -> None:
    task = _task("c", parent_id="not-in-set")

    plan = build_project_duplicate(
        Project(id="P", name="Work"),
        sections=[],
        tasks=[task],
        new_name="W2",
        temp_ids=_temp_ids(),
    )

    assert plan.tasks[0].parent_ref is None


def test_project_duplicate_orders_tasks_by_emission() -> None:
    plan = build_project_duplicate(
        Project(id="P", name="Work"),
        sections=[],
        tasks=[_task("a", content="a"), _task("b", content="b")],
        new_name="W2",
        temp_ids=_temp_ids(),
    )

    orders = [t.child_order for t in plan.tasks]
    assert orders == sorted(orders)
    assert len(set(orders)) == 2


def test_section_duplicate_creates_section_in_same_project() -> None:
    section = Section(id="s1", project_id="P", name="Now", order=1)
    task = _task("t1", section_id="s1")

    plan = build_section_duplicate(
        section,
        tasks=[task],
        new_name="Now (copy)",
        temp_ids=_temp_ids(),
    )

    assert plan.projects == ()
    assert len(plan.sections) == 1
    ns = plan.sections[0]
    assert (ns.name, ns.order, ns.project_ref) == ("Now (copy)", 1, "P")
    assert ns.temp_id != "s1"
    assert plan.tasks[0].section_ref == ns.temp_id
    assert plan.tasks[0].project_ref == "P"
