import pytest
from textual.binding import Binding
from textual.widgets import Static

from tests.tui.test_app import FakeRepository
from todoist_tui.tui.app import TodoistApp, as_binding, shortcut_rows
from todoist_tui.tui.screens.help import HelpScreen


def test_shortcut_rows_flattens_both_lists_dropping_help_and_blank() -> None:
    rows = shortcut_rows(
        [("e", "complete", "Complete"), Binding("question_mark", "help", "Help")],
        [Binding("j", "cursor_down", "Down", show=False), Binding("x", "noop", "")],
    )
    assert ("e", "Complete") in rows
    assert ("j", "Down") in rows
    assert all(desc != "Help" for _, desc in rows)  # help binding dropped
    assert all(desc for _, desc in rows)  # blank descriptions dropped


def test_app_bindings_hide_everything_but_help() -> None:
    shown = [b for b in map(as_binding, TodoistApp.BINDINGS) if b.show]
    assert [b.action for b in shown] == ["help"]


@pytest.mark.anyio
async def test_question_mark_opens_help_listing_all_shortcuts() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        shown = str(app.screen.query_one("#help", Static).render())
        assert "Complete" in shown  # visible app action
        assert "Down" in shown  # table nav, hidden from the footer
        assert "P1" in shown  # priority binding, hidden from the footer


@pytest.mark.anyio
async def test_escape_closes_help() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


@pytest.mark.anyio
async def test_help_does_not_stack() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        app.action_help()  # re-entry while already open
        await pilot.pause()
        assert sum(isinstance(s, HelpScreen) for s in app.screen_stack) == 1
