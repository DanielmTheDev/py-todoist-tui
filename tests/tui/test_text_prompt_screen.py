from collections.abc import Callable

import pytest
from textual.app import App
from textual.widgets import Input

from todoist_tui.tui.screens.text_prompt import TextPromptScreen


class _Host(App[None]):
    def __init__(
        self,
        prompt: str,
        initial: str,
        on_result: Callable[[str | None], None],
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._initial = initial
        self._on_result = on_result

    def on_mount(self) -> None:
        self.push_screen(TextPromptScreen(self._prompt, self._initial), self._on_result)


@pytest.mark.anyio
async def test_enter_returns_the_prefilled_value() -> None:
    chosen: list[str | None] = []
    host = _Host("Name the copy", "Work (copy)", chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == ["Work (copy)"]


@pytest.mark.anyio
async def test_prefilled_value_is_selected_for_overtyping() -> None:
    chosen: list[str | None] = []
    host = _Host("Name the copy", "Work (copy)", chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("N", "e", "w")  # replaces the selected prefill
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == ["New"]


@pytest.mark.anyio
async def test_escape_returns_none() -> None:
    chosen: list[str | None] = []
    host = _Host("Name the copy", "Work (copy)", chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]


@pytest.mark.anyio
async def test_blank_name_does_not_dismiss() -> None:
    chosen: list[str | None] = []
    host = _Host("Name the copy", "", chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")  # nothing typed: stay open
        await pilot.pause()
        assert chosen == []
        host.screen.query_one(Input)  # still mounted
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]
