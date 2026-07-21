import datetime

import pytest
from textual.widgets import DataTable, Static

from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.tui.app import TodoistApp


class FakeRepository:
    def __init__(self, tasks: list[Task], projects: list[Project]) -> None:
        self._tasks = tasks
        self._projects = projects

    async def today(self) -> list[Task]:
        return self._tasks

    async def projects(self) -> list[Project]:
        return self._projects


@pytest.mark.anyio
async def test_mount_renders_today_tasks_in_table() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21), time=datetime.time(9, 30)),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], [Project(id="220", name="Errands")]))

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[str])
        assert table.row_count == 1
        row = table.get_row_at(0)
        assert row == ["P2", "09:30", "Buy milk", "Errands"]


@pytest.mark.anyio
async def test_all_day_task_has_blank_time() -> None:
    task = Task(
        id=TaskId("1"),
        content="Someday",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], [Project(id="220", name="Errands")]))

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(DataTable[str]).get_row_at(0)[1] == ""


@pytest.mark.anyio
async def test_empty_shows_status_message() -> None:
    app = TodoistApp(FakeRepository([], []))

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(DataTable[str]).row_count == 0
        assert "No tasks due today" in str(app.query_one("#status", Static).render())
