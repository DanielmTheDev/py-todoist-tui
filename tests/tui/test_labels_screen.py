from collections.abc import Callable

import pytest
from rich.text import Text
from textual.app import App
from textual.widgets import OptionList

from todoist_tui.tui.screens.labels import LabelsScreen

_LABELS = ["home", "urgent", "work"]


class _Host(App[None]):
    def __init__(
        self,
        labels: list[str],
        current: tuple[str, ...],
        on_result: Callable[[tuple[str, ...] | None], None],
    ) -> None:
        super().__init__()
        self._labels = labels
        self._current = current
        self._on_result = on_result

    def on_mount(self) -> None:
        self.push_screen(LabelsScreen(self._labels, self._current), self._on_result)


def _prompts(host: _Host) -> list[str]:
    ol = host.screen.query_one(OptionList)
    return [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]


@pytest.mark.anyio
async def test_lists_all_labels_sorted_with_current_checked() -> None:
    host = _Host(_LABELS, ("work",), lambda _r: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _prompts(host) == ["[ ] home", "[ ] urgent", "[x] work"]


@pytest.mark.anyio
async def test_checkbox_prompts_are_plain_text_not_rich_markup() -> None:
    # "[x]" as a markup string would be parsed and swallowed by Rich, hiding the
    # box; a Text prompt renders the brackets literally.
    host = _Host(_LABELS, ("work",), lambda _r: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        ol = host.screen.query_one(OptionList)
        checked = ol.get_option_at_index(2).prompt  # "work", pre-checked
        assert isinstance(checked, Text)
        assert checked.plain == "[x] work"


@pytest.mark.anyio
async def test_space_toggles_the_highlighted_label() -> None:
    host = _Host(_LABELS, (), lambda _r: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")  # highlight starts on "home"
        await pilot.pause()
        assert _prompts(host)[0] == "[x] home"
        await pilot.press("space")  # toggle back off
        await pilot.pause()
        assert _prompts(host)[0] == "[ ] home"


@pytest.mark.anyio
async def test_down_moves_the_cursor_before_toggling() -> None:
    chosen: list[tuple[str, ...] | None] = []
    host = _Host(_LABELS, (), chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")  # home -> urgent
        await pilot.press("down")  # urgent -> work
        await pilot.press("up")  # work -> urgent
        await pilot.press("space")  # toggle "urgent"
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [("urgent",)]


@pytest.mark.anyio
async def test_enter_confirms_the_selected_set() -> None:
    chosen: list[tuple[str, ...] | None] = []
    host = _Host(_LABELS, ("work",), chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")  # add "home"
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [("home", "work")]


@pytest.mark.anyio
async def test_escape_dismisses_with_none() -> None:
    chosen: list[tuple[str, ...] | None] = []
    host = _Host(_LABELS, ("work",), chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]


@pytest.mark.anyio
async def test_typing_filters_labels() -> None:
    host = _Host(_LABELS, (), lambda _r: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("w", "o")  # matches "work" only
        await pilot.pause()
        assert _prompts(host) == ["[ ] work"]


@pytest.mark.anyio
async def test_no_match_offers_a_create_row_that_adds_the_typed_name() -> None:
    chosen: list[tuple[str, ...] | None] = []
    host = _Host(_LABELS, (), chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f", "r", "e", "s", "h")  # no existing match
        await pilot.pause()
        assert _prompts(host) == ["[+] create @fresh"]
        await pilot.press("space")  # create + select "fresh", clears filter
        await pilot.pause()
        assert _prompts(host) == [
            "[ ] home",
            "[ ] urgent",
            "[ ] work",
            "[x] fresh",
        ]
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [("fresh",)]


@pytest.mark.anyio
async def test_backspace_edits_the_filter() -> None:
    host = _Host(_LABELS, (), lambda _r: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("w", "o", "r", "k", "k")  # "workk" matches nothing
        await pilot.pause()
        assert _prompts(host) == ["[+] create @workk"]
        await pilot.press("backspace")  # back to "work"
        await pilot.pause()
        assert _prompts(host) == ["[ ] work"]


@pytest.mark.anyio
async def test_current_label_absent_from_catalog_is_shown_checked() -> None:
    host = _Host(_LABELS, ("orphan",), lambda _r: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert "[x] orphan" in _prompts(host)
