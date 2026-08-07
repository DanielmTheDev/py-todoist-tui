from collections.abc import Callable

import pytest
from textual.app import App
from textual.widgets import Input, TextArea

from todoist_tui.tui.screens.edit import TaskEditScreen, TaskText


class _Host(App[None]):
    def __init__(
        self,
        content: str,
        description: str,
        on_result: Callable[[TaskText | None], None],
    ) -> None:
        super().__init__()
        self._content = content
        self._description = description
        self._on_result = on_result

    def on_mount(self) -> None:
        self.push_screen(
            TaskEditScreen(self._content, self._description), self._on_result
        )


@pytest.mark.anyio
async def test_both_fields_are_prefilled() -> None:
    host = _Host("Buy milk", "oat, 2x", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.screen.query_one(Input).value == "Buy milk"
        assert host.screen.query_one(TextArea).text == "oat, 2x"


@pytest.mark.anyio
async def test_ctrl_s_returns_both_edited_values() -> None:
    edited: list[TaskText | None] = []
    host = _Host("Buy milk", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("!")  # appends to the title, does not replace it
        await pilot.press("tab")
        await pilot.press("2", "x")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskText("Buy milk!", "oat2x")]


@pytest.mark.anyio
async def test_typing_appends_instead_of_wiping_the_prefilled_title() -> None:
    edited: list[TaskText | None] = []
    host = _Host("Buy milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("s")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskText("Buy milks", "")]


@pytest.mark.anyio
async def test_tab_moves_focus_to_the_description() -> None:
    host = _Host("Buy milk", "oat", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.focused is host.screen.query_one(Input)
        await pilot.press("tab")
        await pilot.pause()
        assert host.focused is host.screen.query_one(TextArea)


@pytest.mark.anyio
async def test_enter_in_the_title_saves() -> None:
    edited: list[TaskText | None] = []
    host = _Host("Buy milk", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert edited == [TaskText("Buy milk", "oat")]


@pytest.mark.anyio
async def test_enter_in_the_description_adds_a_line() -> None:
    edited: list[TaskText | None] = []
    host = _Host("Buy milk", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.press("enter", "2", "x")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskText("Buy milk", "oat\n2x")]


@pytest.mark.anyio
async def test_escape_returns_none() -> None:
    edited: list[TaskText | None] = []
    host = _Host("Buy milk", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("x")
        await pilot.press("escape")
        await pilot.pause()
        assert edited == [None]


@pytest.mark.anyio
async def test_surrounding_whitespace_is_trimmed() -> None:
    edited: list[TaskText | None] = []
    host = _Host("  Buy milk  ", "  oat  ", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskText("Buy milk", "oat")]


@pytest.mark.anyio
async def test_blank_title_does_not_dismiss() -> None:
    edited: list[TaskText | None] = []
    host = _Host("", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == []
        host.screen.query_one(Input)  # still mounted
        await pilot.press("escape")
        await pilot.pause()
        assert edited == [None]
