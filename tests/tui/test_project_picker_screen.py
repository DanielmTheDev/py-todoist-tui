from collections.abc import Callable

import pytest
from textual.app import App
from textual.widgets import OptionList

from todoist_tui.domain.project import Project
from todoist_tui.domain.section import Section
from todoist_tui.tui.screens.project_picker import MoveTarget, ProjectPickerScreen

# orders deliberately differ from alphabetical, so the sort is by Todoist order
_PROJECTS = [
    Project(id="220", name="Errands", order=1),
    Project(id="5", name="Personal", order=2),
    Project(id="9", name="Work", order=0),
]
# Work has two sections, out of order to prove section_order sorts them
_SECTIONS = [
    Section(id="s2", project_id="9", name="In progress", order=2),
    Section(id="s1", project_id="9", name="Planning", order=1),
]
_WORK = MoveTarget(project_id="9", project_name="Work")
_WORK_PLANNING = MoveTarget("9", "Work", "s1", "Planning")
_WORK_PROGRESS = MoveTarget("9", "Work", "s2", "In progress")
_ERRANDS = MoveTarget(project_id="220", project_name="Errands")
_PERSONAL = MoveTarget(project_id="5", project_name="Personal")


class _Host(App[None]):
    def __init__(
        self,
        projects: list[Project],
        sections: list[Section],
        on_result: Callable[[MoveTarget | None], None],
        current_project: str | None = None,
        current_section: str | None = None,
    ) -> None:
        super().__init__()
        self._choices = projects  # not self._projects: keep off App-owned names
        self._sections = sections
        self._on_result = on_result
        self._current_project = current_project
        self._current_section = current_section

    def on_mount(self) -> None:
        self.push_screen(
            ProjectPickerScreen(
                self._choices,
                self._sections,
                current_project=self._current_project,
                current_section=self._current_section,
            ),
            self._on_result,
        )


def _labels(host: _Host) -> list[str]:
    ol = host.screen.query_one(OptionList)
    return [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]


@pytest.mark.anyio
async def test_lists_projects_then_their_sections_flat() -> None:
    host = _Host(_PROJECTS, _SECTIONS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        # Work (order 0) and its sections first, then Errands, then Personal
        assert _labels(host) == [
            "Work",
            "Work / Planning",
            "Work / In progress",
            "Errands",
            "Personal",
        ]


@pytest.mark.anyio
async def test_typing_matches_project_and_section_labels() -> None:
    host = _Host(_PROJECTS, _SECTIONS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p", "l", "a")  # "pla" only in "Work / Planning"
        await pilot.pause()
        assert _labels(host) == ["Work / Planning"]


@pytest.mark.anyio
async def test_enter_dismisses_with_highlighted_target() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host(_PROJECTS, _SECTIONS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_WORK]  # first in Todoist order


@pytest.mark.anyio
async def test_selecting_a_section_returns_its_target() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host(_PROJECTS, _SECTIONS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")  # Work -> Work / Planning
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_WORK_PLANNING]


@pytest.mark.anyio
async def test_current_project_and_section_are_preselected() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host(
        _PROJECTS, _SECTIONS, chosen.append, current_project="9", current_section="s2"
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_WORK_PROGRESS]  # current section wins over sort order


@pytest.mark.anyio
async def test_current_project_root_is_preselected() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host(_PROJECTS, _SECTIONS, chosen.append, current_project="5")
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_PERSONAL]


@pytest.mark.anyio
async def test_root_target_carries_is_inbox() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host([Project(id="1", name="Inbox", is_inbox=True)], [], chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [MoveTarget("1", "Inbox", is_inbox=True)]


@pytest.mark.anyio
async def test_escape_dismisses_with_none() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host(_PROJECTS, _SECTIONS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]


@pytest.mark.anyio
async def test_enter_with_no_match_is_a_noop() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host(_PROJECTS, _SECTIONS, chosen.append)
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
