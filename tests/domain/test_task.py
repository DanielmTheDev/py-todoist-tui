import datetime

from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId


def test_task_holds_identity_and_fields() -> None:
    due = Due(date=datetime.date(2026, 7, 21), time=None, is_recurring=False)
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P3,
        due=due,
        project_id="220",
    )

    assert task.id == TaskId("6X4")
    assert task.content == "Buy milk"
    assert task.priority is Priority.P3
    assert task.due is due
    assert task.project_id == "220"


def test_task_due_optional() -> None:
    task = Task(
        id=TaskId("1"),
        content="Someday",
        priority=Priority.P4,
        due=None,
        project_id="220",
    )

    assert task.due is None


def test_task_labels_default_empty() -> None:
    task = Task(
        id=TaskId("1"),
        content="No labels",
        priority=Priority.P4,
        due=None,
        project_id="220",
    )

    assert task.labels == ()


def test_task_holds_labels() -> None:
    task = Task(
        id=TaskId("2"),
        content="Tagged",
        priority=Priority.P4,
        due=None,
        project_id="220",
        labels=("home", "urgent"),
    )

    assert task.labels == ("home", "urgent")


def test_task_description_defaults_empty() -> None:
    task = Task(
        id=TaskId("1"),
        content="No notes",
        priority=Priority.P4,
        due=None,
        project_id="220",
    )

    assert task.description == ""


def test_task_holds_description() -> None:
    task = Task(
        id=TaskId("2"),
        content="With notes",
        priority=Priority.P4,
        due=None,
        project_id="220",
        description="Get 2% from the corner store",
    )

    assert task.description == "Get 2% from the corner store"


def test_project_holds_id_and_name() -> None:
    project = Project(id="220", name="Inbox")

    assert project.id == "220"
    assert project.name == "Inbox"
