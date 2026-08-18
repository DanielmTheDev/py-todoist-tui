from collections.abc import Callable

import pytest
from textual.app import App
from textual.widgets import Input, OptionList

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.task import TaskId
from todoist_tui.tui.screens.parent_picker import ParentPickerScreen, ParentTarget


def _row(
    task_id: str,
    content: str,
    project_name: str | None = "Work",
    section_name: str | None = None,
) -> TaskRow:
    return TaskRow(
        id=TaskId(task_id),
        content=content,
        priority=Priority.P4,
        due=None,
        project_name=project_name,
        project_id="9",
        section_name=section_name,
    )


_ROWS = [
    _row("1", "Refactor the client"),
    _row("2", "Write docs", "Personal", "Later"),
]


class _Host(App[None]):
    def __init__(
        self,
        rows: list[TaskRow],
        on_result: Callable[[ParentTarget | None], None],
    ) -> None:
        super().__init__()
        self._rows = rows
        self._on_result = on_result

    def on_mount(self) -> None:
        self.push_screen(ParentPickerScreen(self._rows), self._on_result)


def _labels(host: _Host) -> list[str]:
    ol = host.screen.query_one(OptionList)
    return [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]


@pytest.mark.anyio
async def test_lists_the_top_level_entry_then_every_task_with_its_context() -> None:
    host = _Host(_ROWS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host) == [
            "1 — No parent (top level)",
            "2 Refactor the client — Work",
            "3 Write docs — Personal / Later",
        ]


@pytest.mark.anyio
async def test_typing_matches_task_content() -> None:
    host = _Host(_ROWS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d", "o", "c")
        await pilot.pause()
        assert _labels(host) == [
            "1 — No parent (top level)",
            "2 Write docs — Personal / Later",
        ]


@pytest.mark.anyio
async def test_typing_matches_the_project_context() -> None:
    host = _Host(_ROWS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l", "a", "t", "e", "r")
        await pilot.pause()
        assert _labels(host) == [
            "1 — No parent (top level)",
            "2 Write docs — Personal / Later",
        ]


@pytest.mark.anyio
async def test_un_parenting_stays_reachable_however_the_list_is_filtered() -> None:
    chosen: list[ParentTarget | None] = []
    host = _Host(_ROWS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("z", "z", "z")  # matches no task
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [ParentTarget(None)]


@pytest.mark.anyio
async def test_enter_dismisses_with_the_highlighted_task() -> None:
    chosen: list[ParentTarget | None] = []
    host = _Host(_ROWS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")  # top level -> first task
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [ParentTarget(_ROWS[0])]


@pytest.mark.anyio
async def test_escape_dismisses_with_none() -> None:
    chosen: list[ParentTarget | None] = []
    host = _Host(_ROWS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]


@pytest.mark.anyio
async def test_rows_are_numbered_from_the_top_level_entry_down() -> None:
    host = _Host(_ROWS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host) == [
            "1 — No parent (top level)",
            "2 Refactor the client — Work",
            "3 Write docs — Personal / Later",
        ]


@pytest.mark.anyio
async def test_a_digit_picks_that_row() -> None:
    chosen: list[ParentTarget | None] = []
    host = _Host(_ROWS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        assert chosen == [ParentTarget(_ROWS[1])]


@pytest.mark.anyio
async def test_the_first_digit_un_parents() -> None:
    chosen: list[ParentTarget | None] = []
    host = _Host(_ROWS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
        assert chosen == [ParentTarget(None)]


@pytest.mark.anyio
async def test_a_digit_never_reaches_the_filter() -> None:
    chosen: list[ParentTarget | None] = []
    host = _Host(_ROWS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d", "9", "o")  # the 9 numbers no row here
        await pilot.pause()
        assert chosen == []
        assert host.screen.query_one(Input).value == "do"
        assert _labels(host) == [
            "1 — No parent (top level)",
            "2 Write docs — Personal / Later",
        ]


@pytest.mark.anyio
async def test_the_list_fits_a_terminal_shorter_than_its_cap() -> None:
    """The filter box sits beside the list, and a percentage cap is measured
    against the screen alone — so the list's bottom fell off a short terminal."""
    host = _Host(_ROWS, lambda _t: None)
    async with host.run_test(size=(80, 5)) as pilot:
        await pilot.pause()
        options = host.screen.query_one(OptionList)
        assert options.region.bottom <= 5
        assert options.max_scroll_y > 0


def _title(host: _Host) -> str:
    return str(host.screen.query_one(Input).border_title)


@pytest.mark.anyio
async def test_a_pick_clears_the_due_dates_unless_told_otherwise() -> None:
    chosen: list[ParentTarget | None] = []
    host = _Host(_ROWS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        assert chosen == [ParentTarget(_ROWS[0], clear_due=True)]


@pytest.mark.anyio
async def test_the_toggle_keeps_the_due_dates() -> None:
    chosen: list[ParentTarget | None] = []
    host = _Host(_ROWS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.press("2")
        await pilot.pause()
        assert chosen == [ParentTarget(_ROWS[0], clear_due=False)]


@pytest.mark.anyio
async def test_the_toggle_flips_back() -> None:
    chosen: list[ParentTarget | None] = []
    host = _Host(_ROWS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t", "ctrl+t")
        await pilot.press("2")
        await pilot.pause()
        assert chosen == [ParentTarget(_ROWS[0], clear_due=True)]


@pytest.mark.anyio
async def test_the_filter_box_names_the_state_of_the_toggle() -> None:
    host = _Host(_ROWS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _title(host) == "clear due: ON · ctrl+t"
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert _title(host) == "clear due: OFF · ctrl+t"


@pytest.mark.anyio
async def test_the_toggle_never_reaches_the_filter() -> None:
    host = _Host(_ROWS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d", "o", "ctrl+t")
        await pilot.pause()
        assert host.screen.query_one(Input).value == "do"
