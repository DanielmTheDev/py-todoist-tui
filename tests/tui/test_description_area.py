import datetime
from collections.abc import Callable
from typing import ClassVar

import pytest
from rich.style import Style
from textual.app import App
from textual.binding import Binding, BindingType
from textual.widgets import TextArea

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.project import Project
from todoist_tui.domain.section import Section
from todoist_tui.tui.screens.description import DescriptionArea
from todoist_tui.tui.screens.draft import TaskDraft
from todoist_tui.tui.screens.edit import Catalog, TaskEditScreen

TODAY = datetime.date(2026, 8, 19)


async def _no_targets() -> tuple[list[Project], list[Section]]:
    return [], []


async def _no_parents() -> list[TaskRow]:
    return []


async def _no_labels() -> list[str]:
    return []


EMPTY = Catalog(_no_targets, _no_parents, _no_labels)


class _Host(App[None]):
    """Stands in for the task list: it holds a bare-letter binding of its own, so
    a key the description eats in normal mode must never reach it."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("x", "intercepted", "Select", show=False),
        Binding("a", "intercepted", "Add", show=False),
    ]

    def __init__(
        self, description: str, on_result: Callable[[TaskDraft | None], None]
    ) -> None:
        super().__init__()
        self._description = description
        self._on_result = on_result
        self.intercepted = 0

    def on_mount(self) -> None:
        draft = TaskDraft("Buy milk", self._description)
        self.push_screen(TaskEditScreen(draft, TODAY, EMPTY), self._on_result)

    def action_intercepted(self) -> None:
        self.intercepted += 1


def _area(host: _Host) -> DescriptionArea:
    return host.screen.query_one(DescriptionArea)


def _mode(host: _Host) -> str:
    return str(_area(host).border_title)


def _host(description: str = "one\ntwo\nthree") -> _Host:
    return _Host(description, lambda _result: None)


def _styles_around_the_cursor(host: _Host) -> tuple[Style, Style]:
    """What the screen paints on the cursor's own cell and on the one after it,
    which carries the line's own colours."""
    area = _area(host)
    area.cursor_blink = False  # else the cell is only styled half the time
    row, column = area.cursor_location
    region = area.content_region
    at = host.screen.get_style_at
    return at(region.x + column, region.y + row), at(
        region.x + column + 1, region.y + row
    )


@pytest.mark.anyio
async def test_the_field_starts_in_insert_so_typing_works_as_before() -> None:
    host = _host("oat")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        assert _mode(host) == "INSERT"
        await pilot.press("!")
        assert _area(host).text == "oat!"


@pytest.mark.anyio
async def test_escape_leaves_insert_instead_of_closing_the_editor() -> None:
    dismissed: list[TaskDraft | None] = []
    host = _Host("oat", dismissed.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape")
        assert _mode(host) == "NORMAL"
        assert dismissed == []
        await pilot.press("j")  # a command now, not a character
        assert _area(host).text == "oat"


@pytest.mark.anyio
async def test_a_second_escape_closes_the_editor() -> None:
    dismissed: list[TaskDraft | None] = []
    host = _Host("oat", dismissed.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "escape")
        await pilot.pause()
        assert dismissed == [None]


@pytest.mark.anyio
async def test_escape_drops_a_half_typed_command_before_it_drops_the_edit() -> None:
    dismissed: list[TaskDraft | None] = []
    host = _Host("one\ntwo", dismissed.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "d", "escape")
        await pilot.pause()
        assert dismissed == []
        assert _area(host).text == "one\ntwo"
        await pilot.press("escape")
        await pilot.pause()
        assert dismissed == [None]


@pytest.mark.anyio
async def test_i_goes_back_to_insert() -> None:
    host = _host("oat")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "i", "!")
        assert _mode(host) == "INSERT"
        assert _area(host).text == "oa!t"


@pytest.mark.anyio
async def test_A_appends_at_the_end_of_the_line() -> None:
    host = _host("one\ntwo")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "g", "g", "A", "!")
        assert _area(host).text == "one!\ntwo"


@pytest.mark.anyio
async def test_dd_deletes_a_line_and_u_brings_it_back() -> None:
    host = _host()
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "g", "g", "d", "d")
        assert _area(host).text == "two\nthree"
        await pilot.press("u")
        assert _area(host).text == "one\ntwo\nthree"
        await pilot.press("ctrl+r")
        assert _area(host).text == "two\nthree"


@pytest.mark.anyio
async def test_x_deletes_the_character_under_the_cursor() -> None:
    host = _host("oat")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "0", "x")
        assert _area(host).text == "at"


@pytest.mark.anyio
async def test_cw_changes_a_word_and_opens_insert() -> None:
    host = _host("one two")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "0", "c", "w", "X")
        assert _area(host).text == "X two"
        assert _mode(host) == "INSERT"


@pytest.mark.anyio
async def test_ciw_changes_the_word_the_cursor_sits_in() -> None:
    """`i` also starts insert, so this proves the operator holds the buffer open
    for the object rather than the widget acting on the key as it arrives."""
    host = _host("one two")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "0", "l", "c", "i", "w", "X")
        assert _area(host).text == "X two"
        assert _mode(host) == "INSERT"


@pytest.mark.anyio
async def test_a_count_repeats_a_motion() -> None:
    host = _host("one\ntwo\nthree\nfour")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "g", "g", "3", "j")
        assert _area(host).cursor_location == (3, 0)


@pytest.mark.anyio
async def test_dollar_then_j_keeps_hugging_the_line_end() -> None:
    host = _host("alpha\nhi\nomega")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "g", "g", "$", "j", "j")
        assert _area(host).cursor_location == (2, 4)


@pytest.mark.anyio
async def test_the_editor_keys_still_work_from_normal_mode() -> None:
    saved: list[TaskDraft | None] = []
    host = _Host("oat", saved.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "ctrl+s")
        await pilot.pause()
        assert saved == [TaskDraft("Buy milk", "oat")]


@pytest.mark.anyio
async def test_tab_still_leaves_the_field_from_normal_mode() -> None:
    host = _host("oat")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "tab")
        assert not _area(host).has_focus


@pytest.mark.anyio
async def test_normal_mode_keys_never_reach_the_list_bindings() -> None:
    """`x` selects and `a` adds a task in the list; inside the field they are
    vim commands and must not escape to the app."""
    host = _host("oat")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "x", "a")
        assert host.intercepted == 0
        assert isinstance(host.screen, TaskEditScreen)


@pytest.mark.anyio
async def test_enter_and_backspace_do_not_edit_in_normal_mode() -> None:
    host = _host("one\ntwo")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "enter", "backspace")
        assert _area(host).text == "one\ntwo"


@pytest.mark.anyio
async def test_leaving_and_returning_starts_in_insert_again() -> None:
    host = _host("oat")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "tab")
        _area(host).focus()
        await pilot.pause()
        assert _mode(host) == "INSERT"


@pytest.mark.anyio
async def test_the_cursor_steps_back_off_the_line_end_when_insert_ends() -> None:
    host = _host("oat")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        assert _area(host).cursor_location == (0, 3)
        await pilot.press("escape")
        assert _area(host).cursor_location == (0, 2)


@pytest.mark.anyio
async def test_the_description_is_still_a_plain_text_area_to_the_editor() -> None:
    host = _host("oat")
    async with host.run_test() as pilot:
        await pilot.pause()
        assert isinstance(host.screen.query_one(TextArea), DescriptionArea)


@pytest.mark.anyio
async def test_the_arrows_are_the_motions_they_stand_for() -> None:
    """Left/right otherwise fall through to TextArea, which would park the
    cursor past the last character and keep the `$` memory alive."""
    host = _host("alpha\nhi\nomega")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "g", "g", "$", "right")
        assert _area(host).cursor_location == (0, 4)
        await pilot.press("down")
        assert _area(host).cursor_location == (1, 1)  # the `$` memory is gone
        await pilot.press("d", "down")
        assert _area(host).text == "alpha"


@pytest.mark.anyio
async def test_undo_forgets_the_line_end_the_cursor_was_hugging() -> None:
    """Otherwise the next j/k hugs the end of a line the user never sent it to."""
    host = _host("ab\nwxyz")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "g", "g", "x", "$", "u", "j")
        assert _area(host).cursor_location == (1, 0)


@pytest.mark.anyio
async def test_a_command_with_nothing_to_do_leaves_the_text_alone() -> None:
    host = _host("first\n\nthird")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab", "escape", "g", "g", "j", "x")  # x on a blank line
        assert _area(host).text == "first\n\nthird"


@pytest.mark.anyio
async def test_the_cursor_underlines_in_insert_and_fills_the_cell_in_normal() -> None:
    """A terminal cursor cannot be a thin bar here — Textual paints its own on a
    whole cell — so insert underlines the cell instead of filling it."""
    host = _host("oat")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        insert, line = _styles_around_the_cursor(host)
        assert insert.underline
        assert insert.bgcolor == line.bgcolor  # underlined, not filled

        await pilot.press("escape")
        await pilot.pause()
        normal, line = _styles_around_the_cursor(host)
        assert not normal.underline
        assert normal.bgcolor != line.bgcolor  # a block filling the cell
