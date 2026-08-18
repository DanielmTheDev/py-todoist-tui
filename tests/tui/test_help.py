import datetime

import pytest
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from tests.tui.test_app import FakeRepository
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.tui.app import TodoistApp, as_binding, card_rows, shortcut_rows
from todoist_tui.tui.screens.detail import TaskDetailScreen
from todoist_tui.tui.screens.help import HelpScreen

_TASK = Task(
    id=TaskId("t1"),
    content="t1",
    priority=Priority.P4,
    due=Due(date=datetime.date(2026, 7, 21)),
    project_id="220",
)


def test_shortcut_rows_flattens_both_lists_dropping_help_and_blank() -> None:
    rows = shortcut_rows(
        [("e", "complete", "Complete"), Binding("question_mark", "help", "Help")],
        [Binding("j", "cursor_down", "Down", show=False), Binding("x", "noop", "")],
    )
    assert ("e", "Complete") in rows
    assert ("j", "Down") in rows
    assert all(desc != "Help" for _, desc in rows)  # help binding dropped
    assert all(desc for _, desc in rows)  # blank descriptions dropped


def test_shortcut_rows_print_the_key_the_user_presses() -> None:
    """Textual names them `at`/`asterisk`; nobody has those keys."""
    rows = shortcut_rows(
        [
            Binding("at", "set_labels", "Labels"),
            Binding("asterisk", "select_all", "Select all"),
        ]
    )
    assert rows == [("@", "Labels"), ("*", "Select all")]


def test_card_rows_print_the_key_the_user_presses() -> None:
    assert ("@", "Labels") in card_rows(TodoistApp.BINDINGS)


def test_shortcut_rows_spells_out_a_multi_key_binding() -> None:
    rows = shortcut_rows([Binding("h,left", "collapse", "Collapse", show=False)])
    assert rows == [("h / left", "Collapse")]


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
        assert "Open link" not in shown  # a card key; the card's help owns it


@pytest.mark.anyio
async def test_typing_filters_the_shortcut_list() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press(*"complete")
        await pilot.pause()
        shown = str(app.screen.query_one("#help", Static).render())
        assert "Complete" in shown  # matching row survives
        assert "Down" not in shown  # non-matching row filtered out


@pytest.mark.anyio
async def test_filter_matches_against_the_key_too() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("j")  # the vim-down key; "Down" label has no 'j'
        await pilot.pause()
        shown = str(app.screen.query_one("#help", Static).render())
        assert "Down" in shown  # matched by key, not description


@pytest.mark.anyio
async def test_clearing_the_filter_restores_all_rows() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press(*"complete")
        await pilot.pause()
        app.screen.query_one(Input).value = ""
        await pilot.pause()
        shown = str(app.screen.query_one("#help", Static).render())
        assert "Complete" in shown
        assert "Down" in shown


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
        await app.action_help()  # re-entry while already open
        await pilot.pause()
        assert sum(isinstance(s, HelpScreen) for s in app.screen_stack) == 1


def test_card_rows_group_the_keys_that_reach_one_action() -> None:
    rows = card_rows(TodoistApp.BINDINGS)

    assert ("v", "Move") in rows
    assert ("a / A", "Add subtask") in rows  # the card takes both
    assert ("1", "P1") in rows
    assert ("5-9", "Open link") in rows  # card-only
    assert all("Views" not in desc for _, desc in rows)  # list-only, unreachable


@pytest.mark.anyio
async def test_question_mark_on_the_card_lists_the_cards_own_keys() -> None:
    repo = FakeRepository([_TASK], [])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, TaskDetailScreen)
        await pilot.press("question_mark")
        await pilot.pause()

        assert isinstance(app.screen, HelpScreen)
        shown = str(app.screen.query_one("#help", Static).render())
        assert "Open link" in shown
        assert "Move" in shown
        assert "Views" not in shown  # the list's own keys do not reach the card


@pytest.mark.anyio
async def test_leaving_the_cards_help_returns_to_the_card() -> None:
    repo = FakeRepository([_TASK], [])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app.screen, TaskDetailScreen)  # the card never closed


@pytest.mark.anyio
async def test_a_help_list_taller_than_the_terminal_scrolls() -> None:
    """The list outgrew the modal, and the rows past the fold were simply gone."""
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()

        scroll = app.screen.query_one(VerticalScroll)
        assert scroll.max_scroll_y > 0  # the tail is reachable, not clipped
        assert scroll.region.height <= 24


@pytest.mark.anyio
async def test_the_help_box_fits_a_terminal_shorter_than_its_cap() -> None:
    """The filter box sits beside the list, and a percentage cap is measured
    against the screen alone — so the box's bottom fell off a short terminal."""
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()

        scroll = app.screen.query_one(VerticalScroll)
        assert scroll.region.bottom <= 10
        assert scroll.max_scroll_y > 0


@pytest.mark.anyio
async def test_shrinking_the_terminal_refits_the_open_help_box() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.resize_terminal(80, 8)
        await pilot.pause()

        assert app.screen.query_one(VerticalScroll).region.bottom <= 8


@pytest.mark.anyio
async def test_the_help_list_scrolls_by_key() -> None:
    """The filter box holds focus, so the list needs keys of its own."""
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("down", "down", "down")
        await pilot.pause()

        assert app.screen.query_one(VerticalScroll).scroll_y > 0
