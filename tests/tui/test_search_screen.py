import asyncio
import datetime
from collections.abc import Callable

import pytest
from rich.rule import Rule
from rich.text import Text
from textual.app import App
from textual.pilot import Pilot
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.search import InvalidSearchQuery, SearchTerm
from todoist_tui.domain.task import TaskId
from todoist_tui.tui.format import MATCH_STYLE
from todoist_tui.tui.screens.search import PREVIEW_LIMIT, Find, SearchScreen

_TODAY = datetime.date(2026, 8, 3)


def _row(
    content: str,
    description: str = "",
    priority: Priority = Priority.P4,
    due: Due | None = None,
    project_name: str | None = "Work",
) -> TaskRow:
    return TaskRow(
        id=TaskId(content),
        content=content,
        priority=priority,
        due=due,
        project_name=project_name,
        description=description,
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
        self.push_screen(self._screen_type(self._find, _TODAY), self._on_result)


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
        assert "hit mi" in _labels(host)[0]
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
        options = _options(host)
        tasks = [o for o in options if not o.disabled]
        assert len(tasks) == PREVIEW_LIMIT
        assert str(options[-1].prompt) == "…and 1 more"
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
        assert [label.strip() for label in _labels(host)] == ["hit test  Work"]


def _prompts(host: _Host) -> list[Text]:
    options = host.screen.query_one(OptionList)
    prompts: list[Text] = []
    for i in range(options.option_count):
        prompt = options.get_option_at_index(i).prompt
        assert isinstance(prompt, Text)
        prompts.append(prompt)
    return prompts


def _accented(text: Text) -> list[str]:
    return [
        text.plain[span.start : span.end]
        for span in text.spans
        if str(span.style) == MATCH_STYLE
    ]


class _Fixed:
    """Returns a fixed row set regardless of the term."""

    def __init__(self, rows: list[TaskRow]) -> None:
        self._rows = rows

    async def __call__(self, _term: SearchTerm) -> list[TaskRow]:
        return self._rows


async def _search_for(host: _Host, pilot: Pilot[None], *keys: str) -> None:
    await pilot.press(*keys)
    await host.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
    await pilot.pause()


@pytest.mark.anyio
async def test_a_matching_title_is_accented() -> None:
    host = _Host(_Fixed([_row("Geschenk Manni Marco")]), lambda _t: None)
    async with host.run_test() as pilot:
        await _search_for(host, pilot, "g", "e", "s", "c", "h")
        assert _accented(_prompts(host)[0]) == ["Gesch"]


@pytest.mark.anyio
async def test_a_description_only_match_is_shown_and_accented() -> None:
    # the row that looks like a mystery hit explains itself
    rows = [_row("Martin Kremmel bjj", description="Geschenk noch besorgen")]
    host = _Host(_Fixed(rows), lambda _t: None)
    async with host.run_test() as pilot:
        await _search_for(host, pilot, "g", "e", "s", "c", "h")
        prompt = _prompts(host)[0]
        assert "Geschenk noch besorgen" in prompt.plain
        assert _accented(prompt) == ["Gesch"]


@pytest.mark.anyio
async def test_a_title_match_does_not_repeat_the_description() -> None:
    rows = [_row("Geschenk Manni", description="wrapping paper too")]
    host = _Host(_Fixed(rows), lambda _t: None)
    async with host.run_test() as pilot:
        await _search_for(host, pilot, "g", "e", "s", "c", "h")
        assert "wrapping paper" not in _prompts(host)[0].plain


@pytest.mark.anyio
async def test_rows_carry_priority_project_and_due() -> None:
    rows = [
        _row(
            "Geschenk Manni",
            priority=Priority.P1,
            due=Due(date=datetime.date(2026, 8, 4)),
            project_name="Tasks",
        )
    ]
    host = _Host(_Fixed(rows), lambda _t: None)
    async with host.run_test() as pilot:
        await _search_for(host, pilot, "g", "e", "s", "c", "h")
        plain = _prompts(host)[0].plain
        assert "🔴" in plain
        assert "Tasks" in plain
        assert "Tomorrow" in plain


@pytest.mark.anyio
async def test_a_row_without_project_or_due_carries_no_separator() -> None:
    host = _Host(_Fixed([_row("Geschenk", project_name=None)]), lambda _t: None)
    async with host.run_test() as pilot:
        await _search_for(host, pilot, "g", "e", "s", "c", "h")
        assert _prompts(host)[0].plain.rstrip().endswith("Geschenk")


@pytest.mark.anyio
async def test_rows_clip_instead_of_wrapping() -> None:
    # a wrapped continuation line loses its indent and reads as another row
    rows = [_row("A very long title " * 5, description="x" * 300)]
    host = _Host(_Fixed(rows), lambda _t: None)
    async with host.run_test(size=(60, 20)) as pilot:
        await _search_for(host, pilot, "l", "o", "n", "g")
        styles = host.screen.query_one(OptionList).styles
        assert styles.text_wrap == "nowrap"
        assert styles.text_overflow == "ellipsis"


def _options(host: _Host) -> list[Option]:
    options = host.screen.query_one(OptionList)
    return [options.get_option_at_index(i) for i in range(options.option_count)]


@pytest.mark.anyio
async def test_a_dim_rule_sits_between_tasks_but_not_around_them() -> None:
    rows = [_row("Schuhe putzen"), _row("Schlaf Maske"), _row("Schach")]
    host = _Host(_Fixed(rows), lambda _t: None)
    async with host.run_test(size=(80, 24)) as pilot:
        await _search_for(host, pilot, "s", "c", "h")
        kinds = ["rule" if option.disabled else "task" for option in _options(host)]
        assert kinds == ["task", "rule", "task", "rule", "task"]


@pytest.mark.anyio
async def test_the_rule_sizes_itself_rather_than_clipping() -> None:
    # a fixed-width string would overrun the row's padding and end in an ellipsis
    host = _Host(_Fixed([_row("Schuhe"), _row("Schach")]), lambda _t: None)
    async with host.run_test(size=(80, 24)) as pilot:
        await _search_for(host, pilot, "s", "c", "h")
        rule = next(o for o in _options(host) if o.disabled)
        assert isinstance(rule.prompt, Rule)
        assert rule.prompt.style == "dim"


@pytest.mark.anyio
async def test_a_single_match_gets_no_rule() -> None:
    host = _Host(_Fixed([_row("Schuhe")]), lambda _t: None)
    async with host.run_test(size=(80, 24)) as pilot:
        await _search_for(host, pilot, "s", "c", "h")
        assert [o.disabled for o in _options(host)] == [False]


@pytest.mark.anyio
async def test_markdown_is_stripped_from_the_title_and_the_snippet() -> None:
    rows = [
        _row("**Schuhe** putzen"),
        _row("Zahnarzt", description="**Klaus-Peter Schicketanz**"),
    ]
    host = _Host(_Fixed(rows), lambda _t: None)
    async with host.run_test(size=(80, 24)) as pilot:
        await _search_for(host, pilot, "s", "c", "h")
        painted = " ".join(str(o.prompt) for o in _options(host))
        assert "**" not in painted
        assert "Schuhe putzen" in painted
        assert "Klaus-Peter Schicketanz" in painted


@pytest.mark.anyio
async def test_a_link_in_a_title_shows_its_label() -> None:
    rows = [_row("Schuhe [bestellen](https://example.com/shoes)")]
    host = _Host(_Fixed(rows), lambda _t: None)
    async with host.run_test(size=(80, 24)) as pilot:
        await _search_for(host, pilot, "s", "c", "h")
        prompt = str(_options(host)[0].prompt)
        assert "Schuhe bestellen" in prompt
        assert "example.com" not in prompt
