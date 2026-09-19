from collections.abc import Callable

import pytest
from textual.app import App

from todoist_tui.tui.screens.compose import ComposeCommentScreen


class _Host(App[None]):
    def __init__(self, on_result: Callable[[str | None], None]) -> None:
        super().__init__()
        self._on_result = on_result

    def on_mount(self) -> None:
        self.push_screen(ComposeCommentScreen(), self._on_result)


async def _written(*keys: str) -> list[str | None]:
    """What the screen dismissed with, if it dismissed at all."""
    results: list[str | None] = []
    host = _Host(results.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        for key in keys:
            await pilot.press(key)
        await pilot.pause()
    return results


@pytest.mark.anyio
async def test_typing_then_ctrl_s_posts_what_was_written() -> None:
    assert await _written("s", "h", "i", "p", "ctrl+s") == ["ship"]


@pytest.mark.anyio
async def test_the_field_opens_in_insert_mode_as_the_editor_does() -> None:
    """Coming in and typing must work without pressing `i` first."""
    assert await _written("h", "i", "ctrl+s") == ["hi"]


@pytest.mark.anyio
async def test_escape_leaves_insert_before_it_leaves_the_comment() -> None:
    """The first escape is vim's; only the second abandons the comment."""
    assert await _written("h", "i", "escape") == []  # still open, insert left
    assert await _written("h", "i", "escape", "escape") == [None]


@pytest.mark.anyio
async def test_an_empty_comment_is_not_worth_posting() -> None:
    assert await _written("ctrl+s") == []  # stays open rather than posting nothing


@pytest.mark.anyio
async def test_whitespace_around_the_comment_is_dropped() -> None:
    assert await _written(" ", "h", "i", " ", "ctrl+s") == ["hi"]


@pytest.mark.anyio
async def test_a_comment_can_run_over_several_lines() -> None:
    assert await _written("a", "enter", "b", "ctrl+s") == ["a\nb"]
