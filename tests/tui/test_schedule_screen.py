import datetime
from collections.abc import Callable

import pytest
from textual.app import App

from todoist_tui.domain.due import Due
from todoist_tui.tui.screens.schedule import DueResult, ScheduleScreen

_TUESDAY = datetime.date(2026, 7, 28)


class _Host(App[None]):
    def __init__(
        self, today: datetime.date, on_result: Callable[[DueResult | None], None]
    ) -> None:
        super().__init__()
        self._today = today
        self._on_result = on_result

    def on_mount(self) -> None:
        self.push_screen(ScheduleScreen(self._today), self._on_result)


async def _press(key: str, today: datetime.date = _TUESDAY) -> DueResult | None:
    results: list[DueResult | None] = []
    host = _Host(today, results.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
    (result,) = results
    return result


@pytest.mark.anyio
async def test_today_key_sets_today() -> None:
    assert await _press("t") == DueResult(Due(date=_TUESDAY))


@pytest.mark.anyio
async def test_tomorrow_key_sets_next_day() -> None:
    assert await _press("m") == DueResult(Due(date=datetime.date(2026, 7, 29)))


@pytest.mark.anyio
async def test_next_week_key_sets_coming_monday() -> None:
    assert await _press("w") == DueResult(Due(date=datetime.date(2026, 8, 3)))


@pytest.mark.anyio
async def test_weekend_key_sets_coming_saturday() -> None:
    assert await _press("e") == DueResult(Due(date=datetime.date(2026, 8, 1)))


@pytest.mark.anyio
async def test_clear_key_dismisses_with_none_due() -> None:
    assert await _press("x") == DueResult(None)


@pytest.mark.anyio
async def test_escape_cancels_with_none_result() -> None:
    assert await _press("escape") is None
