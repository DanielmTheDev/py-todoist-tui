from collections.abc import Callable

import pytest
from textual.app import App
from textual.widgets import OptionList

from todoist_tui.domain.project import Project
from todoist_tui.tui.screens.project_picker import ProjectPickerScreen

# orders deliberately differ from alphabetical, so the sort is by Todoist order
_PROJECTS = [
    Project(id="220", name="Errands", order=1),
    Project(id="5", name="Personal", order=2),
    Project(id="9", name="Work", order=0),
]
_WORK = Project(id="9", name="Work", order=0)
_ERRANDS = Project(id="220", name="Errands", order=1)
_PERSONAL = Project(id="5", name="Personal", order=2)


class _Host(App[None]):
    def __init__(
        self,
        projects: list[Project],
        on_result: Callable[[Project | None], None],
        current: str | None = None,
    ) -> None:
        super().__init__()
        self._choices = projects  # not self._projects: keep off App-owned names
        self._on_result = on_result
        self._current = current

    def on_mount(self) -> None:
        self.push_screen(
            ProjectPickerScreen(self._choices, current=self._current), self._on_result
        )


def _options(host: _Host) -> list[str | None]:
    ol = host.screen.query_one(OptionList)
    return [ol.get_option_at_index(i).id for i in range(ol.option_count)]


@pytest.mark.anyio
async def test_lists_all_projects_in_todoist_order() -> None:
    host = _Host(_PROJECTS, lambda _p: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _options(host) == ["9", "220", "5"]  # by order: Work, Errands, Personal


@pytest.mark.anyio
async def test_typing_narrows_the_list() -> None:
    host = _Host(_PROJECTS, lambda _p: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("w", "o")
        await pilot.pause()
        assert _options(host) == ["9"]  # only "Work" contains "wo"


@pytest.mark.anyio
async def test_enter_dismisses_with_highlighted_project() -> None:
    chosen: list[Project | None] = []
    host = _Host(_PROJECTS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_WORK]  # first in Todoist order


@pytest.mark.anyio
async def test_typing_then_enter_selects_the_match() -> None:
    chosen: list[Project | None] = []
    host = _Host(_PROJECTS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("w", "o")
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_WORK]


@pytest.mark.anyio
async def test_down_arrow_then_enter_selects_next() -> None:
    chosen: list[Project | None] = []
    host = _Host(_PROJECTS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_ERRANDS]  # second in Todoist order


@pytest.mark.anyio
async def test_down_then_up_arrow_returns_to_first() -> None:
    chosen: list[Project | None] = []
    host = _Host(_PROJECTS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("up")
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_WORK]  # back to first


@pytest.mark.anyio
async def test_current_project_is_preselected() -> None:
    chosen: list[Project | None] = []
    host = _Host(_PROJECTS, chosen.append, current="5")  # Personal sorts last
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_PERSONAL]  # current wins over sort order


@pytest.mark.anyio
async def test_escape_dismisses_with_none() -> None:
    chosen: list[Project | None] = []
    host = _Host(_PROJECTS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]


@pytest.mark.anyio
async def test_enter_with_no_match_is_a_noop() -> None:
    chosen: list[Project | None] = []
    host = _Host(_PROJECTS, chosen.append)
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
