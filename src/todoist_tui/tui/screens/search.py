import asyncio
import datetime
from collections.abc import Awaitable, Callable
from typing import ClassVar

from rich.rule import Rule
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.links import plain
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.search import (
    InvalidSearchQuery,
    SearchTerm,
    Unsearchable,
    parse_search,
)
from todoist_tui.tui.format import (
    format_due,
    highlight_match,
    match_snippet,
    priority_dot,
)

PREVIEW_LIMIT = 50  # the promoted view shows everything; this is just a peek
_SNIPPET_WIDTH = 32  # of description context: a hint, not a sentence
_SNIPPET_INDENT = "      "  # sets the snippet under, not beside, its title
_RULE_CHAR = "─"

Find = Callable[[SearchTerm], Awaitable[list[TaskRow]]]


class SearchScreen(ModalScreen["SearchTerm | None"]):
    """Search every task by typing, previewing matches live. Dismisses the term
    to promote into a view, or None on cancel."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    SearchScreen {
        align: center middle;
    }
    SearchScreen Input {
        width: 60%;
        max-width: 80;
        border: round $primary;
    }
    SearchScreen OptionList {
        width: 60%;
        max-width: 80;
        height: auto;
        max-height: 60%;
        border: round $primary;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    SearchScreen #search-hint {
        width: 60%;
        max-width: 80;
        padding: 0 1;
        color: $text-muted;
    }
    """

    DEBOUNCE: ClassVar[float] = 0.25  # settle a typing burst into one request

    def __init__(self, find: Find, today: datetime.date) -> None:
        super().__init__()
        self._find = find
        self._today = today
        self._term: SearchTerm | None = None  # what Enter would promote

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type to search…")
        yield OptionList()
        yield Static("", id="search-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        parsed = parse_search(event.value)
        if isinstance(parsed, Unsearchable):
            self._term = None
            self._clear(_unsearchable_hint(parsed))  # never hits the network
            return
        self._term = parsed
        self._search(parsed)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._term is None:  # nothing searchable typed yet: stay open
            return
        self.dismiss(self._term)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @work(exclusive=True, group="search")
    async def _search(self, term: SearchTerm) -> None:
        await asyncio.sleep(self.DEBOUNCE)  # the next keystroke cancels this worker
        try:
            rows = await self._find(term)
        except InvalidSearchQuery:
            self._clear("Invalid search query")
        except Exception as error:  # offline or the request failed
            self._clear(f"Search failed: {error}")
        else:
            self._paint(rows, term)

    def _paint(self, rows: list[TaskRow], term: SearchTerm) -> None:
        options = self._reset(_count_hint(len(rows)))
        for index, row in enumerate(rows[:PREVIEW_LIMIT]):
            if index:  # between tasks only: none above the first or below the last
                options.add_option(_separator())
            options.add_option(Option(_preview(row, term, self._today)))
        remainder = len(rows) - PREVIEW_LIMIT
        if remainder > 0:
            options.add_option(Option(f"…and {remainder} more", disabled=True))

    def _clear(self, hint: str) -> None:
        self._reset(hint)

    def _reset(self, hint: str) -> OptionList:
        options = self.query_one(OptionList)
        options.clear_options()
        self.query_one("#search-hint", Static).update(hint)
        return options


def _preview(row: TaskRow, term: SearchTerm, today: datetime.date) -> Text:
    """One task as it reads in the preview: what it is, why it matched, where."""
    title = plain(row.content)
    in_title = term.find_in(title)
    line = Text.assemble(
        _dot(row.priority),
        highlight_match(title, in_title),
        _context(row, today),
    )
    if in_title is not None:
        return line
    description = plain(row.description)
    in_description = term.find_in(description)
    if in_description is None:  # matched somewhere only the server can see
        return line
    snippet = match_snippet(description, in_description, _SNIPPET_WIDTH)
    snippet.style = "dim"  # the accent still carries; the rest recedes
    return Text.assemble(line, "\n", _SNIPPET_INDENT, snippet)


def _separator() -> Option:
    """A dim rule between tasks. `Rule` sizes itself to the row, so it can never
    clip to an ellipsis the way a fixed-width string does."""
    return Option(Rule(characters=_RULE_CHAR, style="dim"), disabled=True)


def _dot(priority: Priority) -> str:
    dot = priority_dot(priority)
    return f"{dot} " if dot else "   "  # keep titles aligned across priorities


def _context(row: TaskRow, today: datetime.date) -> Text:
    """Project and due date, dim, so two similar titles are tellable apart."""
    parts = [part for part in (row.project_name, format_due(row.due, today)) if part]
    return Text(f"  {' · '.join(parts)}", style="dim") if parts else Text()


def _unsearchable_hint(reason: Unsearchable) -> str:
    if not reason.illegal:  # too short to be worth a request
        return ""
    return f"Can't search for: {' '.join(reason.illegal)}"


def _count_hint(matches: int) -> str:
    return "1 match" if matches == 1 else f"{matches} matches"
