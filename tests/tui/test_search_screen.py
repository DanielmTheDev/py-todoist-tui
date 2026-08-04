import asyncio
from collections.abc import Callable

import pytest
from textual.app import App
from textual.widgets import OptionList, Static

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.search import InvalidSearchQuery, SearchTerm
from todoist_tui.domain.task import TaskId
from todoist_tui.tui.screens.search import Find, SearchScreen


def _row(content: str) -> TaskRow:
    return TaskRow(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=None,
        project_name="Work",
    )


class _Find:
    """Records every term searched; returns one row named after the term."""

    def __init__(self) -> None:
        self.terms: list[str] = []

    async def __call__(self, term: SearchTerm) -> list[TaskRow]:
        self.terms.append(term.text)
        return [_row(f"hit {term.text}")]


class _Instant(SearchScreen):
    DEBOUNCE = 0.0  # the debounce itself is covered by _Slow below


class _Slow(SearchScreen):
    DEBOUNCE = 30.0  # far longer than any test runs


class _Host(App[None]):
    def __init__(
        self,
        find: Find,
        on_result: Callable[[SearchTerm | None], None],
        screen: type[SearchScreen] = _Instant,
    ) -> None:
        super().__init__()
        self._find = find
        self._on_result = on_result
        self._screen_type = screen

    def on_mount(self) -> None:
        self.push_screen(self._screen_type(self._find), self._on_result)


def _labels(host: _Host) -> list[str]:
    options = host.screen.query_one(OptionList)
    return [
        str(options.get_option_at_index(i).prompt) for i in range(options.option_count)
    ]


def _hint(host: _Host) -> str:
    return str(host.screen.query_one("#search-hint", Static).render())


@pytest.mark.anyio
async def test_opens_empty_and_searches_nothing() -> None:
    find = _Find()
    host = _Host(find, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _labels(host) == []
        assert find.terms == []


@pytest.mark.anyio
async def test_typing_paints_matches_and_their_count() -> None:
    find = _Find()
    host = _Host(find, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.press("m", "i")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert find.terms == ["mi"]
        assert _labels(host) == ["hit mi"]
        assert "1 match" in _hint(host)


@pytest.mark.anyio
async def test_a_single_character_is_not_searched() -> None:
    find = _Find()
    host = _Host(find, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.press("m")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert find.terms == []
        assert _labels(host) == []


@pytest.mark.anyio
async def test_backspacing_to_blank_clears_the_results() -> None:
    find = _Find()
    host = _Host(find, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.press("m", "i")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("backspace", "backspace")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert _labels(host) == []
        assert _hint(host) == ""


@pytest.mark.anyio
async def test_a_rejected_character_is_named_and_never_sent() -> None:
    find = _Find()
    host = _Host(find, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.press("a", "b")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("&")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert find.terms == ["ab"]  # "ab&" never reached the API
        assert _labels(host) == []
        assert "&" in _hint(host)


@pytest.mark.anyio
async def test_enter_dismisses_with_the_typed_term() -> None:
    chosen: list[SearchTerm | None] = []
    host = _Host(_Find(), chosen.append)
    async with host.run_test() as pilot:
        await pilot.press("m", "i", "l", "k")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [SearchTerm("milk")]


@pytest.mark.anyio
@pytest.mark.parametrize("typed", ["m", "a&b"])
async def test_enter_on_an_unsearchable_term_stays_open(typed: str) -> None:
    chosen: list[SearchTerm | None] = []
    host = _Host(_Find(), chosen.append)
    async with host.run_test() as pilot:
        await pilot.press(*typed)
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == []
        assert isinstance(host.screen, SearchScreen)


@pytest.mark.anyio
async def test_escape_cancels() -> None:
    chosen: list[SearchTerm | None] = []
    host = _Host(_Find(), chosen.append)
    async with host.run_test() as pilot:
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == [None]


@pytest.mark.anyio
async def test_a_rejected_query_reports_itself_without_a_traceback() -> None:
    async def find(_term: SearchTerm) -> list[TaskRow]:
        raise InvalidSearchQuery("search: nope")

    host = _Host(find, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.press("n", "o")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert _hint(host) == "Invalid search query"
        assert _labels(host) == []


@pytest.mark.anyio
async def test_being_offline_reports_the_failure() -> None:
    async def find(_term: SearchTerm) -> list[TaskRow]:
        raise OSError("no route to host")

    host = _Host(find, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.press("n", "o")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert "no route to host" in _hint(host)
        assert _labels(host) == []


@pytest.mark.anyio
async def test_long_result_sets_are_capped_with_a_remainder_line() -> None:
    async def find(_term: SearchTerm) -> list[TaskRow]:
        return [_row(f"task {i}") for i in range(51)]

    host = _Host(find, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.press("t", "a")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        labels = _labels(host)
        assert len(labels) == 51  # 50 tasks plus the remainder line
        assert labels[-1] == "…and 1 more"
        assert "51 matches" in _hint(host)


@pytest.mark.anyio
async def test_a_typing_burst_is_not_searched_until_it_settles() -> None:
    find = _Find()
    host = _Host(find, lambda _t: None, screen=_Slow)
    async with host.run_test() as pilot:
        await pilot.press("m", "i", "l", "k")
        await pilot.pause()
        assert find.terms == []  # still inside the debounce window


class _Gated:
    """Blocks each search until its term is released, so ordering is explicit."""

    def __init__(self) -> None:
        self.gates: dict[str, asyncio.Event] = {}
        self.painted: list[str] = []

    async def __call__(self, term: SearchTerm) -> list[TaskRow]:
        gate = self.gates.setdefault(term.text, asyncio.Event())
        await gate.wait()
        return [_row(f"hit {term.text}")]

    def release(self, *terms: str) -> None:
        for term in terms:
            self.gates.setdefault(term, asyncio.Event()).set()


@pytest.mark.anyio
async def test_a_superseded_search_never_paints() -> None:
    find = _Gated()
    host = _Host(find, lambda _t: None)
    async with host.run_test() as pilot:
        await pilot.press("t", "e")
        await pilot.pause()
        await pilot.press("s", "t")  # supersedes the in-flight "te"
        await pilot.pause()
        find.release("te", "test")
        await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert _labels(host) == ["hit test"]
