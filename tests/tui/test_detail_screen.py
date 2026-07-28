import datetime

import pytest
from textual.app import App
from textual.widgets import Static

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.task import TaskId
from todoist_tui.tui.screens.detail import TaskDetailScreen

_DUE = Due(date=datetime.date(2026, 7, 29), time=datetime.time(9, 0))


def _row(
    content: str = "Buy milk",
    due: Due | None = _DUE,
    priority: Priority = Priority.P1,
    project_name: str | None = "Errands",
    labels: tuple[str, ...] = ("home", "errand"),
    description: str = "2% from the corner store",
) -> TaskRow:
    return TaskRow(
        id=TaskId("6X4"),
        content=content,
        priority=priority,
        due=due,
        project_name=project_name,
        labels=labels,
        description=description,
    )


class _Host(App[None]):
    def __init__(self, row: TaskRow, dismissed: list[bool]) -> None:
        super().__init__()
        self._row = row
        self._dismissed = dismissed

    def on_mount(self) -> None:
        self.push_screen(
            TaskDetailScreen(self._row), lambda _result: self._dismissed.append(True)
        )


async def _shown(row: TaskRow) -> str:
    host = _Host(row, [])
    async with host.run_test() as pilot:
        await pilot.pause()
        return str(host.screen.query_one("#detail", Static).render())


async def _dismisses_on(row: TaskRow, key: str) -> bool:
    dismissed: list[bool] = []
    host = _Host(row, dismissed)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
    return dismissed == [True]


@pytest.mark.anyio
async def test_renders_title_and_all_fields() -> None:
    shown = await _shown(_row())

    assert "Buy milk" in shown
    assert "2026-07-29 09:00" in shown
    assert "P1" in shown
    assert "Errands" in shown
    assert "@home" in shown
    assert "@errand" in shown
    assert "2% from the corner store" in shown


@pytest.mark.anyio
async def test_recurring_due_shows_the_rule() -> None:
    due = Due(date=datetime.date(2026, 7, 29), is_recurring=True, string="every day")

    shown = await _shown(_row(due=due))

    assert "every day" in shown


@pytest.mark.anyio
async def test_missing_description_shows_placeholder() -> None:
    shown = await _shown(_row(description=""))

    assert "No description" in shown


@pytest.mark.anyio
async def test_no_project_and_no_labels_render_a_dash() -> None:
    shown = await _shown(_row(project_name=None, labels=()))

    assert "@" not in shown  # no labels rendered
    assert "—" in shown


@pytest.mark.anyio
async def test_no_due_renders_a_dash() -> None:
    shown = await _shown(_row(due=None))

    assert "Due" in shown
    assert "—" in shown


@pytest.mark.anyio
@pytest.mark.parametrize("key", ["escape", "enter", "q"])
async def test_escape_enter_and_q_close_the_view(key: str) -> None:
    assert await _dismisses_on(_row(), key)
