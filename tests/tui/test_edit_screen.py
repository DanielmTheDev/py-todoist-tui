from collections.abc import Callable

import pytest
from textual import events
from textual.app import App
from textual.widgets import Input, Static, TextArea

from todoist_tui.tui.screens.edit import TaskEditScreen, TaskText


def _paste(app: App[None], text: str) -> None:
    """A bracketed paste, as the terminal delivers it: to the app, which forwards
    it to whichever field has focus."""
    app.post_message(events.Paste(text))


def _link_hint(app: App[None]) -> str:
    return str(app.screen.query_one("#link", Static).content)


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
async def test_ctrl_backspace_in_the_title_deletes_the_word_to_the_left() -> None:
    edited: list[TaskText | None] = []
    host = _Host("Buy oat milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+backspace")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskText("Buy oat", "")]


@pytest.mark.anyio
async def test_ctrl_shift_a_in_the_description_selects_all_so_typing_replaces() -> None:
    edited: list[TaskText | None] = []
    host = _Host("Buy milk", "oat\nand 2x", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.press("ctrl+shift+a")
        await pilot.press("s", "o", "y")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskText("Buy milk", "soy")]


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


@pytest.mark.anyio
async def test_a_url_pasted_onto_a_title_makes_the_title_the_link() -> None:
    host = _Host("review the PR", "", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, "https://example.com/pr/9")
        await pilot.pause()
        assert (
            host.screen.query_one(Input).value
            == "[review the PR](https://example.com/pr/9)"
        )
        assert _link_hint(host) == ""


@pytest.mark.anyio
async def test_a_url_pasted_onto_an_empty_title_waits_for_the_title() -> None:
    edited: list[TaskText | None] = []
    host = _Host("", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, "https://example.com/pr/9")
        await pilot.pause()
        assert host.screen.query_one(Input).value == ""
        assert _link_hint(host) == "↳ link: https://example.com/pr/9"
        await pilot.press("p", "r")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskText("[pr](https://example.com/pr/9)", "")]


@pytest.mark.anyio
async def test_the_newest_pasted_url_replaces_a_waiting_one() -> None:
    edited: list[TaskText | None] = []
    host = _Host("", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, "https://example.com/old")
        await pilot.pause()
        _paste(host, "https://example.com/new")
        await pilot.pause()
        await pilot.press("p", "r")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskText("[pr](https://example.com/new)", "")]


@pytest.mark.anyio
async def test_a_url_pasted_onto_an_already_linked_title_stays_bare() -> None:
    host = _Host("[a](https://example.com/a)", "", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, "https://example.com/b")
        await pilot.pause()
        assert (
            host.screen.query_one(Input).value
            == "[a](https://example.com/a) https://example.com/b"
        )


@pytest.mark.anyio
async def test_pasted_text_that_is_not_a_url_is_inserted_as_typed() -> None:
    host = _Host("Buy", "", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, " oat milk")
        await pilot.pause()
        assert host.screen.query_one(Input).value == "Buy oat milk"
        assert _link_hint(host) == ""


@pytest.mark.anyio
async def test_a_url_pasted_into_the_description_stays_a_plain_paste() -> None:
    host = _Host("Buy milk", "", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        _paste(host, "https://example.com/x")
        await pilot.pause()
        assert host.screen.query_one(TextArea).text == "https://example.com/x"
        assert _link_hint(host) == ""
