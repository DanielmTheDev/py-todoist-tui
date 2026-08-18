from collections.abc import Callable, Mapping

import pytest
from rich.text import Text
from textual.app import App
from textual.content import Content
from textual.visual import visualize
from textual.widgets import OptionList, Static

from todoist_tui.application.views import all_views
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.project import Project
from todoist_tui.domain.view_slots import ViewSlots
from todoist_tui.tui.screens.views import ViewsOutcome, ViewsScreen

_PROJECTS = [
    Project(id="220", name="Eingang", is_inbox=True),
    Project(id="9", name="Work"),
    Project(id="7", name="Backlog"),
]
_FILTERS = [Filter(id="f1", name="Next", query="p1", order=1)]
_TAKEN = {"t": "Due", "escape": "Clear selection"}


class _Host(App[None]):
    def __init__(
        self,
        on_result: Callable[[ViewsOutcome | None], None],
        slots: ViewSlots | None = None,
        taken: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._slots = slots or ViewSlots()
        self._taken = taken if taken is not None else _TAKEN
        self._on_result = on_result

    def on_mount(self) -> None:
        self.push_screen(
            ViewsScreen(all_views(_PROJECTS, _FILTERS), self._slots, self._taken),
            self._on_result,
        )


def _labels(host: _Host) -> list[str]:
    options = host.screen.query_one(OptionList)
    return [
        str(options.get_option_at_index(i).prompt) for i in range(options.option_count)
    ]


def _painted(host: _Host) -> list[str]:
    """What Textual actually paints: a plain-string prompt is read as markup, which
    would swallow a `[w]` badge whole."""
    options = host.screen.query_one(OptionList)
    painted = [
        visualize(options, options.get_option_at_index(i).prompt)
        for i in range(options.option_count)
    ]
    assert all(isinstance(p, Content) for p in painted)
    return [p.plain for p in painted if isinstance(p, Content)]


def _only(outcomes: list[ViewsOutcome | None]) -> ViewsOutcome:
    """The single outcome the screen dismissed with — never None: the screen always
    returns its slots, even when closed without opening a view."""
    assert len(outcomes) == 1 and outcomes[0] is not None
    return outcomes[0]


def _spans(host: _Host, index: int) -> list[tuple[str, str]]:
    """The styled runs of an option's label, so a test can assert which part recedes
    without naming a colour. Unstyled runs are absent."""
    prompt = host.screen.query_one(OptionList).get_option_at_index(index).prompt
    assert isinstance(prompt, Text)
    return [(prompt.plain[s.start : s.end], str(s.style)) for s in prompt.spans]


def _hint(host: _Host) -> str:
    return str(host.screen.query_one("#views-hint", Static).render())


@pytest.mark.anyio
async def test_a_sigil_marks_each_view_s_kind() -> None:
    host = _Host(lambda _o: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host) == [
            "⚑ Next",
            "# Work",
            "# Backlog",
            "Today",  # one of a kind: nothing to tell it apart from
            "Inbox",
        ]


@pytest.mark.anyio
async def test_the_sigil_recedes_and_the_name_leads() -> None:
    host = _Host(lambda _o: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host)[0] == "⚑ Next"
        assert _spans(host, 0) == [("⚑ ", "dim")]  # the name carries no style


@pytest.mark.anyio
async def test_assigned_views_lead_the_list_badged_and_starred() -> None:
    slots = ViewSlots().assign("w", "filter:f1").with_startup("project:9")
    host = _Host(lambda _o: None, slots)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host) == [
            "[w] ⚑ Next",
            "★ # Work",
            "# Backlog",
            "Today",
            "Inbox",
        ]


@pytest.mark.anyio
async def test_a_badge_survives_being_painted() -> None:
    host = _Host(lambda _o: None, ViewSlots().assign("w", "project:9"))
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _painted(host)[0] == "[w] # Work"


@pytest.mark.anyio
async def test_typing_filters_by_title() -> None:
    host = _Host(lambda _o: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("b", "a", "c")  # "bac" only in "Backlog"
        await pilot.pause()
        assert _labels(host) == ["# Backlog"]


@pytest.mark.anyio
async def test_enter_jumps_to_the_highlighted_view() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")  # Next -> Work
        await pilot.press("enter")
        await pilot.pause()
    jump = _only(outcomes).jump
    assert jump is not None and jump.key == "project:9"


@pytest.mark.anyio
async def test_escape_closes_without_a_jump() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert outcomes == [ViewsOutcome(ViewSlots(), None)]


@pytest.mark.anyio
async def test_enter_with_no_match_stays_open() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("z", "z", "z")
        await pilot.press("enter")
        await pilot.pause()
        assert outcomes == []


@pytest.mark.anyio
async def test_binding_a_free_key_badges_the_row() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")  # Next -> Work
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert "Work" in _hint(host)

        await pilot.press("w")
        await pilot.pause()
        assert "[w] # Work" in _labels(host)

        await pilot.press("escape")
        await pilot.pause()
    assert _only(outcomes).slots == ViewSlots().assign("w", "project:9")


@pytest.mark.anyio
async def test_a_punctuation_key_is_shown_as_the_character_typed() -> None:
    """Textual names `.` "full_stop"; a badge showing that would be unreadable."""
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+b", "full_stop")
        await pilot.pause()
        assert _labels(host)[0] == "[.] ⚑ Next"

        await pilot.press("escape")
        await pilot.pause()
    assert _only(outcomes).slots.view_key_for(".") == "filter:f1"


@pytest.mark.anyio
async def test_typing_resumes_filtering_after_a_key_is_bound() -> None:
    """The capture blurs the Input; leaving it blurred would freeze the search."""
    host = _Host(lambda _o: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+b", "w")
        await pilot.pause()
        await pilot.press("b", "a", "c")
        await pilot.pause()
        assert _labels(host) == ["# Backlog"]


@pytest.mark.anyio
async def test_binding_a_key_an_app_binding_owns_is_refused() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+b", "t")
        await pilot.pause()
        assert "t is already Due" in _hint(host)
        assert _labels(host)[0] == "⚑ Next"

        await pilot.press("escape")  # a refusal keeps waiting, so this only cancels
        await pilot.press("escape")
        await pilot.pause()
    assert _only(outcomes).slots == ViewSlots()


@pytest.mark.anyio
async def test_escape_during_capture_only_cancels_the_capture() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+b")
        await pilot.press("escape")
        await pilot.pause()
        assert outcomes == []  # the screen is still open

        await pilot.press("escape")
        await pilot.pause()
    assert outcomes == [ViewsOutcome(ViewSlots(), None)]


@pytest.mark.anyio
async def test_backspace_during_capture_unbinds_the_row() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append, ViewSlots().assign("w", "project:9"))
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host)[0] == "[w] # Work"

        await pilot.press("ctrl+b", "backspace")
        await pilot.pause()
        assert "# Work" in _labels(host)

        await pilot.press("escape")
        await pilot.pause()
    assert _only(outcomes).slots == ViewSlots()


@pytest.mark.anyio
async def test_a_bound_key_moves_when_given_to_another_view() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append, ViewSlots().assign("w", "project:9"))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("b", "a", "c")  # narrow to Backlog
        await pilot.pause()
        await pilot.press("ctrl+b", "w")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert _only(outcomes).slots == ViewSlots().assign("w", "project:7")


@pytest.mark.anyio
async def test_ctrl_s_marks_the_highlighted_view_as_startup() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")  # Work
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert "★ # Work" in _labels(host)

        await pilot.press("escape")
        await pilot.pause()
    assert _only(outcomes).slots.startup == "project:9"


@pytest.mark.anyio
async def test_ctrl_s_on_the_startup_view_drops_it() -> None:
    outcomes: list[ViewsOutcome | None] = []
    host = _Host(outcomes.append, ViewSlots().with_startup("filter:f1"))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")  # the leading filter is highlighted first
        await pilot.pause()
        assert _labels(host)[0] == "⚑ Next"

        await pilot.press("escape")
        await pilot.pause()
    assert _only(outcomes).slots.startup is None


@pytest.mark.anyio
async def test_capture_ignores_a_key_that_types_nothing() -> None:
    host = _Host(lambda _o: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+b", "f1")
        await pilot.pause()
        assert "Next" in _hint(host)  # still waiting for a usable key


@pytest.mark.anyio
async def test_the_list_fits_a_terminal_shorter_than_its_cap() -> None:
    """The filter box and the hint sit beside the list, and a percentage cap is
    measured against the screen alone — so the hint below it fell off."""
    host = _Host(lambda _o: None)
    async with host.run_test(size=(80, 9)) as pilot:
        await pilot.pause()
        assert host.screen.query_one("#views-hint", Static).region.bottom <= 9
        assert host.screen.query_one(OptionList).max_scroll_y > 0
