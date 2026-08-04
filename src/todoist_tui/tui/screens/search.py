import asyncio
from collections.abc import Awaitable, Callable
from typing import ClassVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.search import (
    InvalidSearchQuery,
    SearchTerm,
    Unsearchable,
    parse_search,
)

_PREVIEW_LIMIT = 50  # the promoted view shows everything; this is just a peek

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
    }
    SearchScreen #search-hint {
        width: 60%;
        max-width: 80;
        padding: 0 1;
        color: $text-muted;
    }
    """

    DEBOUNCE: ClassVar[float] = 0.25  # settle a typing burst into one request

    def __init__(self, find: Find) -> None:
        super().__init__()
        self._find = find
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
            self._paint([], _unsearchable_hint(parsed))  # never hits the network
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
            self._paint([], "Invalid search query")
        except Exception as error:  # offline or the request failed
            self._paint([], f"Search failed: {error}")
        else:
            self._paint(rows, _count_hint(len(rows)))

    def _paint(self, rows: list[TaskRow], hint: str) -> None:
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([Option(row.content) for row in rows[:_PREVIEW_LIMIT]])
        remainder = len(rows) - _PREVIEW_LIMIT
        if remainder > 0:
            options.add_option(Option(f"…and {remainder} more", disabled=True))
        self.query_one("#search-hint", Static).update(hint)


def _unsearchable_hint(reason: Unsearchable) -> str:
    if not reason.illegal:  # too short to be worth a request
        return ""
    return f"Can't search for: {' '.join(reason.illegal)}"


def _count_hint(matches: int) -> str:
    return "1 match" if matches == 1 else f"{matches} matches"
