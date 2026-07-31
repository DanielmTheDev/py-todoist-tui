import datetime
from collections.abc import Callable

import pytest
from textual.app import App
from textual.widgets import Static

from todoist_tui.domain.due import Due
from todoist_tui.tui.screens.schedule import DueResult, ScheduleScreen

_TUESDAY = datetime.date(2026, 7, 28)


class _Host(App[None]):
    def __init__(
        self,
        today: datetime.date,
        on_result: Callable[[DueResult | None], None],
        current: datetime.date | None = None,
        current_time: datetime.time | None = None,
    ) -> None:
        super().__init__()
        self._today = today
        self._on_result = on_result
        self._current = current
        self._current_time = current_time

    def on_mount(self) -> None:
        self.push_screen(
            ScheduleScreen(self._today, self._current, self._current_time),
            self._on_result,
        )


async def _press(
    *keys: str,
    today: datetime.date = _TUESDAY,
    current: datetime.date | None = None,
    current_time: datetime.time | None = None,
) -> DueResult | None:
    results: list[DueResult | None] = []
    host = _Host(today, results.append, current, current_time)
    async with host.run_test() as pilot:
        await pilot.pause()
        for key in keys:
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


@pytest.mark.anyio
async def test_enter_picks_the_cursor_which_starts_at_today() -> None:
    assert await _press("enter") == DueResult(Due(date=_TUESDAY))


@pytest.mark.anyio
async def test_cursor_starts_at_current_due_when_given() -> None:
    current = datetime.date(2026, 9, 10)
    assert await _press("enter", current=current) == DueResult(Due(date=current))


@pytest.mark.anyio
async def test_right_and_left_move_by_one_day() -> None:
    assert await _press("l", "enter") == DueResult(Due(date=datetime.date(2026, 7, 29)))
    assert await _press("h", "enter") == DueResult(Due(date=datetime.date(2026, 7, 27)))


@pytest.mark.anyio
async def test_down_and_up_move_by_one_week() -> None:
    assert await _press("j", "enter") == DueResult(Due(date=datetime.date(2026, 8, 4)))
    assert await _press("k", "enter") == DueResult(Due(date=datetime.date(2026, 7, 21)))


@pytest.mark.anyio
async def test_bracket_keys_move_by_one_month() -> None:
    assert await _press("]", "enter") == DueResult(Due(date=datetime.date(2026, 8, 28)))
    assert await _press("[", "enter") == DueResult(Due(date=datetime.date(2026, 6, 28)))


@pytest.mark.anyio
async def test_month_step_clamps_to_shorter_month() -> None:
    result = await _press("]", "enter", current=datetime.date(2026, 1, 31))
    assert result == DueResult(Due(date=datetime.date(2026, 2, 28)))


@pytest.mark.anyio
async def test_typed_digits_set_time_on_enter() -> None:
    assert await _press("9", "3", "0", "enter") == DueResult(
        Due(date=_TUESDAY, time=datetime.time(9, 30))
    )


@pytest.mark.anyio
async def test_empty_time_buffer_stays_all_day() -> None:
    assert await _press("enter") == DueResult(Due(date=_TUESDAY))


@pytest.mark.anyio
async def test_backspace_edits_the_time_buffer() -> None:
    # 1430 -> backspace -> 143 (H:MM = 1:43)
    assert await _press("1", "4", "3", "0", "backspace", "enter") == DueResult(
        Due(date=_TUESDAY, time=datetime.time(1, 43))
    )


@pytest.mark.anyio
async def test_quick_key_ignores_typed_time() -> None:
    assert await _press("9", "3", "0", "t") == DueResult(Due(date=_TUESDAY))


@pytest.mark.anyio
async def test_r_removes_time_keeping_the_date() -> None:
    result = await _press(
        "9", "3", "0", "r", "enter", current=datetime.date(2026, 9, 10)
    )
    assert result == DueResult(Due(date=datetime.date(2026, 9, 10)))


@pytest.mark.anyio
async def test_r_clears_a_prefilled_time() -> None:
    result = await _press("r", "enter", current_time=datetime.time(9, 30))
    assert result == DueResult(Due(date=_TUESDAY))


@pytest.mark.anyio
async def test_current_time_prefills_the_buffer() -> None:
    # Pre-filled 09:30; enter without typing keeps it.
    result = await _press("enter", current_time=datetime.time(9, 30))
    assert result == DueResult(Due(date=_TUESDAY, time=datetime.time(9, 30)))


@pytest.mark.anyio
async def test_invalid_time_keeps_modal_open_then_recovers() -> None:
    results: list[DueResult | None] = []
    host = _Host(_TUESDAY, results.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("2", "5", "enter")  # hour 25 -> invalid
        await pilot.pause()
        assert results == []  # not dismissed
        assert isinstance(host.screen, ScheduleScreen)
        rendered = str(host.screen.query_one("#schedule", Static).render())
        assert "25" in rendered  # buffer preserved, shown with an error
        await pilot.press("backspace", "backspace", "9", "enter")  # fix to 09:00
        await pilot.pause()
    assert results == [DueResult(Due(date=_TUESDAY, time=datetime.time(9, 0)))]


@pytest.mark.anyio
async def test_calendar_renders_the_cursor_month_label() -> None:
    results: list[DueResult | None] = []
    host = _Host(_TUESDAY, results.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        rendered = str(host.screen.query_one("#schedule", Static).render())
        assert "July 2026" in rendered
