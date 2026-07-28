from collections.abc import Callable

import pytest
from textual.app import App

from todoist_tui.domain.filter import Filter
from todoist_tui.tui.screens.filters import FilterList, FilterScreen

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


@pytest.mark.anyio
async def test_lists_filters_sorted_by_order() -> None:
    host = _Host(_FILTERS, lambda _f: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        options = host.screen.query_one(FilterList)
        ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
        assert ids == ["a", "b"]


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
async def test_j_moves_down_then_enter_selects_next() -> None:
    chosen: list[Filter | None] = []
    host = _Host(_FILTERS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_FILTERS[0]]  # "b", second after sort


@pytest.mark.anyio
async def test_escape_dismisses_with_none() -> None:
    chosen: list[Filter | None] = []
    host = _Host(_FILTERS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]
