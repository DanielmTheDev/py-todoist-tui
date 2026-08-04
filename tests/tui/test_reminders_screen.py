import datetime
from collections.abc import Callable

import pytest
from textual.app import App

from todoist_tui.domain.reminder import Reminder
from todoist_tui.tui.screens.reminders import Mode, ReminderRequest, RemindersScreen

_TODAY = datetime.date(2026, 8, 4)

_R1 = Reminder(id="r1", item_id="t1", type="relative", minute_offset=30)


class _Host(App[None]):
    def __init__(
        self,
        on_result: Callable[[ReminderRequest | None], None],
        existing: tuple[Reminder, ...],
        allow_relative: bool,
        mode: Mode,
    ) -> None:
        super().__init__()
        self._on_result = on_result
        self._existing = existing
        self._allow_relative = allow_relative
        self._mode: Mode = mode

    def on_mount(self) -> None:
        self.push_screen(
            RemindersScreen(_TODAY, self._existing, self._allow_relative, self._mode),
            self._on_result,
        )


async def _press(
    *keys: str,
    existing: tuple[Reminder, ...] = (),
    allow_relative: bool = True,
    mode: Mode = "manage",
) -> ReminderRequest | None:
    results: list[ReminderRequest | None] = []
    host = _Host(results.append, existing, allow_relative, mode)
    async with host.run_test() as pilot:
        await pilot.pause()
        for key in keys:
            await pilot.press(key)
        await pilot.pause()
    (result,) = results
    return result


@pytest.mark.anyio
async def test_delete_highlighted_reminder() -> None:
    assert await _press("d", existing=(_R1,)) == ReminderRequest(delete_id="r1")


@pytest.mark.anyio
async def test_cursor_moves_before_delete() -> None:
    two = (_R1, Reminder(id="r2", item_id="t1", type="relative", minute_offset=60))
    assert await _press("j", "d", existing=two) == ReminderRequest(delete_id="r2")


@pytest.mark.anyio
async def test_escape_from_menu_cancels() -> None:
    assert await _press("escape", existing=(_R1,)) is None


@pytest.mark.anyio
async def test_add_absolute_from_menu() -> None:
    assert await _press("a", "a") == ReminderRequest(add_absolute=True)


@pytest.mark.anyio
async def test_add_relative_typed_minutes() -> None:
    assert await _press("a", "r", "4", "5", "enter") == ReminderRequest(add_relative=45)


@pytest.mark.anyio
async def test_add_relative_preset() -> None:
    assert await _press("a", "r", "h") == ReminderRequest(add_relative=60)


@pytest.mark.anyio
async def test_relative_enter_without_input_stays_open() -> None:
    # empty buffer + enter must not dismiss; a preset then still works
    assert await _press("a", "r", "enter", "t") == ReminderRequest(add_relative=0)


@pytest.mark.anyio
async def test_escape_from_type_returns_to_menu() -> None:
    # a -> type, escape -> back to menu, escape -> cancel
    assert await _press("a", "escape", "escape", existing=(_R1,)) is None


@pytest.mark.anyio
async def test_relative_unavailable_when_no_due_time() -> None:
    # r is ignored without a due time; a still reaches absolute
    assert await _press("a", "r", "a", allow_relative=False) == ReminderRequest(
        add_absolute=True
    )


@pytest.mark.anyio
async def test_add_mode_starts_at_type_and_escape_cancels() -> None:
    assert await _press("escape", mode="add") is None
