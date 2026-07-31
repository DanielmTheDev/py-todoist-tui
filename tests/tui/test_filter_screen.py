from collections.abc import Callable

import pytest
from textual.app import App
from textual.widgets import OptionList

from todoist_tui.domain.filter import Filter
from todoist_tui.tui.screens.filters import FilterScreen

_FILTERS = [
    Filter(id="b", name="Second", query="overdue", order=2),
    Filter(id="a", name="First", query="today", order=1),
]


class _Host(App[None]):
    def __init__(
        self, filters: list[Filter], on_result: Callable[[Filter | None], None]
    ) -> None:
        super().__init__()
        self._choices = filters  # not self._filters: App owns that name
        self._on_result = on_result

    def on_mount(self) -> None:
        self.push_screen(FilterScreen(self._choices), self._on_result)


def _labels(host: _Host) -> list[str]:
    ol = host.screen.query_one(OptionList)
    return [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]


@pytest.mark.anyio
async def test_lists_filters_sorted_by_order() -> None:
    host = _Host(_FILTERS, lambda _f: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        options = host.screen.query_one(OptionList)
        ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
        assert ids == ["a", "b"]


@pytest.mark.anyio
async def test_typing_filters_by_name() -> None:
    host = _Host(_FILTERS, lambda _f: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("s", "e", "c")  # "sec" only in "Second"
        await pilot.pause()
        assert _labels(host) == ["Second"]


@pytest.mark.anyio
async def test_enter_dismisses_with_highlighted_filter() -> None:
    chosen: list[Filter | None] = []
    host = _Host(_FILTERS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_FILTERS[1]]  # "a", first after sort


@pytest.mark.anyio
async def test_down_then_enter_selects_next() -> None:
    chosen: list[Filter | None] = []
    host = _Host(_FILTERS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")  # First -> Second
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_FILTERS[0]]  # "b", second after sort


@pytest.mark.anyio
async def test_enter_with_no_match_is_a_noop() -> None:
    chosen: list[Filter | None] = []
    host = _Host(_FILTERS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("z", "z", "z")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == []  # nothing highlighted, so nothing dismissed
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]


@pytest.mark.anyio
async def test_click_dismisses_with_that_filter() -> None:
    chosen: list[Filter | None] = []
    host = _Host(_FILTERS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.click(OptionList, offset=(3, 1))  # first row inside the border
        await pilot.pause()
        assert chosen == [_FILTERS[1]]  # "a", first after sort


@pytest.mark.anyio
async def test_escape_dismisses_with_none() -> None:
    chosen: list[Filter | None] = []
    host = _Host(_FILTERS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]
