from collections.abc import Callable

import pytest
from textual.app import App
from textual.widgets import Input, OptionList

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


class _Host(App[None]):
    def __init__(
        self,
        projects: list[Project],
        sections: list[Section],
        on_result: Callable[[MoveTarget | None], None],
        sections_only: bool = False,
    ) -> None:
        super().__init__()
        self._choices = projects  # not self._projects: keep off App-owned names
        self._sections = sections
        self._on_result = on_result
        self._sections_only = sections_only

    def on_mount(self) -> None:
        self.push_screen(
            ProjectPickerScreen(
                self._choices,
                self._sections,
                sections_only=self._sections_only,
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
            "1 Work",
            "2 Work / Planning",
            "3 Work / In progress",
            "4 Errands",
            "5 Personal",
        ]


@pytest.mark.anyio
async def test_typing_matches_project_and_section_labels() -> None:
    host = _Host(_PROJECTS, _SECTIONS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p", "l", "a")  # "pla" only in "Work / Planning"
        await pilot.pause()
        assert _labels(host) == ["1 Work / Planning"]


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
async def test_the_first_row_is_highlighted_whatever_the_task_is_in() -> None:
    """The numbers count from the top, so the highlight starts there too."""
    chosen: list[MoveTarget | None] = []
    host = _Host(_PROJECTS, _SECTIONS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [_WORK]


@pytest.mark.anyio
async def test_inbox_is_not_a_move_target() -> None:
    projects = [
        Project(id="1", name="Inbox", is_inbox=True),
        Project(id="9", name="Work"),
    ]
    host = _Host(projects, [], lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host) == ["1 Work"]  # Inbox has its own `i` key, not a target


@pytest.mark.anyio
async def test_sections_only_drops_the_project_roots() -> None:
    host = _Host(_PROJECTS, _SECTIONS, lambda _t: None, sections_only=True)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host) == ["1 Work / Planning", "2 Work / In progress"]


@pytest.mark.anyio
async def test_sections_only_keeps_inbox_sections() -> None:
    projects = [Project(id="1", name="Inbox", is_inbox=True)]
    sections = [Section(id="s3", project_id="1", name="Later")]
    host = _Host(projects, sections, lambda _t: None, sections_only=True)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host) == ["1 Inbox / Later"]  # only the root is not a target


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


@pytest.mark.anyio
async def test_rows_are_numbered_so_a_digit_can_pick_them() -> None:
    host = _Host(_PROJECTS, _SECTIONS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host) == [
            "1 Work",
            "2 Work / Planning",
            "3 Work / In progress",
            "4 Errands",
            "5 Personal",
        ]


@pytest.mark.anyio
async def test_a_digit_picks_that_row_without_highlighting_it() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host(_PROJECTS, _SECTIONS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        assert chosen == [_ERRANDS]


@pytest.mark.anyio
async def test_digits_number_the_filtered_rows_afresh() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host(_PROJECTS, _SECTIONS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("w", "o", "r")
        await pilot.pause()
        assert _labels(host) == ["1 Work", "2 Work / Planning", "3 Work / In progress"]
        await pilot.press("3")
        await pilot.pause()
        assert chosen == [_WORK_PROGRESS]


@pytest.mark.anyio
async def test_a_digit_never_reaches_the_filter() -> None:
    host = _Host(_PROJECTS, _SECTIONS, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("w", "9", "o")  # the 9 picks nothing: only five rows
        await pilot.pause()
        assert host.screen.query_one(Input).value == "wo"


@pytest.mark.anyio
async def test_a_digit_past_the_last_row_is_a_noop() -> None:
    chosen: list[MoveTarget | None] = []
    host = _Host(_PROJECTS, _SECTIONS, chosen.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("6")
        await pilot.pause()
        assert chosen == []
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]


@pytest.mark.anyio
async def test_the_list_fits_a_terminal_shorter_than_its_cap() -> None:
    """The filter box sits beside the list, and a percentage cap is measured
    against the screen alone — so the list's bottom fell off a short terminal."""
    host = _Host(_PROJECTS, _SECTIONS, lambda _t: None)
    async with host.run_test(size=(80, 5)) as pilot:
        await pilot.pause()
        options = host.screen.query_one(OptionList)
        assert options.region.bottom <= 5
        assert options.max_scroll_y > 0
