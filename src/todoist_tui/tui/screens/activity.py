import datetime
from collections.abc import Awaitable, Callable
from typing import ClassVar, cast

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from todoist_tui.application.activity import ActivityRow
from todoist_tui.domain.activity import EventKind
from todoist_tui.domain.humanize import humanize_date
from todoist_tui.tui.screens.help import HelpScreen, shortcut_rows
from todoist_tui.tui.screens.scrolling import ScrollBody
from todoist_tui.tui.theme import PALETTE_CLASSES, PALETTE_CSS, Tier, tier_styles

type LoadPage = Callable[
    [EventKind | None, str | None],
    Awaitable[tuple[tuple[ActivityRow, ...], str | None]],
]

# what `tab` walks: the whole feed first, then one kind at a time. `OTHER` is
# this client's name for a verb Todoist may add, so it is nothing to ask for.
_CYCLE: tuple[EventKind | None, ...] = (
    None,
    *(k for k in EventKind if k is not EventKind.OTHER),
)

_VERB_WIDTH = max(len(kind.value) for kind in EventKind)
_TITLE = "Activity"
_HINT = "tab next filter · f1 keys · esc close"
_EXHAUSTED = "end of activity"


class ActivityFeed(Static):
    """The rendered log. Palette-aware, so its own tiers resolve where it sits."""

    COMPONENT_CLASSES: ClassVar[set[str]] = set(PALETTE_CLASSES)
    DEFAULT_CSS = PALETTE_CSS


class ActivityScreen(ModalScreen[None]):
    """What happened to your tasks, newest first, a day at a time.

    Read-only. The first page is handed in; reaching the bottom asks `load` for
    the next one, and `tab` narrows the whole feed to one kind of event —
    server-side, so filtering by kind reaches past what is already on screen.
    The typed filter is the other half: it narrows only what has been loaded.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "cycle_filter", "Next event filter"),
        Binding("f1", "help", "Keys"),  # `?` is a character the filter box takes
        Binding("escape", "dismiss", "Close"),
        # the filter box keeps focus, so the feed is scrolled from here
        Binding("down", "scroll(1)", "Down", show=False),
        Binding("up", "scroll(-1)", "Up", show=False),
        Binding("pagedown", "scroll(10)", "Page down", show=False),
        Binding("pageup", "scroll(-10)", "Page up", show=False),
    ]

    DEFAULT_CSS = """
    ActivityScreen {
        align: center middle;
    }
    ActivityScreen Input {
        width: 70%;
        max-width: 90;
        border: round $primary;
    }
    ActivityScreen ScrollBody {
        width: 70%;
        max-width: 90;
        padding: 1 2;
        border: round $primary;
    }
    ActivityScreen ActivityFeed {
        height: auto;
    }
    ActivityScreen #activity-hint {
        width: 70%;
        max-width: 90;
        padding: 0 2;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        rows: tuple[ActivityRow, ...],
        today: datetime.date,
        load: LoadPage,
        cursor: str | None = None,
        tz: datetime.tzinfo | None = None,
    ) -> None:
        super().__init__()
        self._rows = rows
        self._today = today
        self._load = load
        self._cursor = cursor  # None once history is exhausted
        self._tz = tz  # None means the machine's own zone
        self._kind: EventKind | None = None
        self._query = ""
        self._loading = False
        self._generation = 0  # bumped on every filter change; late pages check it
        self._error: str | None = None

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter activity…")
        with ScrollBody():
            yield ActivityFeed(id="activity")
        # outside the scroll body: a hint that scrolls away is a hint nobody reads
        yield Static(id="activity-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self._show()

    def action_scroll(self, lines: int) -> None:
        body = self.query_one(ScrollBody)
        # where this keypress asks to land, not where the widget already is: the
        # scroll itself only takes effect a frame later, so reading it back here
        # would miss the keypress that reaches the end
        landing = body.scroll_target_y + lines
        body.scroll_relative(y=lines, animate=False)
        if landing >= body.max_scroll_y:
            self._fetch()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._query = event.value.casefold()
        self._show()

    def action_help(self) -> None:
        # Textual types `self.app` as App[Unknown]; the pushed screen owns its
        # own result type, so nothing here depends on the app's
        app = cast("App[object]", self.app)  # pyright: ignore[reportUnknownMemberType]
        app.push_screen(HelpScreen(shortcut_rows(self.BINDINGS)))

    def action_cycle_filter(self) -> None:
        self._kind = _CYCLE[(_CYCLE.index(self._kind) + 1) % len(_CYCLE)]
        self._rows = ()
        self._cursor = None
        self._generation += 1
        self._show()
        self._fetch(fresh=True)

    def _fetch(self, fresh: bool = False) -> None:
        """Ask for the next page — or, after a filter change, the first one.

        A filter change always goes out, even mid-page: the rows it replaces are
        already gone, so making it wait would leave the feed empty. What the page
        is *for* is settled here, not in the worker: two filter changes in one
        frame both queue, and the second must not find the first's state.
        """
        if not fresh and (self._loading or self._cursor is None):
            return
        self._loading = True
        self.run_worker(
            self._append(self._kind, None if fresh else self._cursor, self._generation)
        )

    async def _append(
        self, kind: EventKind | None, cursor: str | None, generation: int
    ) -> None:
        try:
            rows, next_cursor = await self._load(kind, cursor)
        except Exception as error:  # offline: say so, keep what is on screen
            self._error = str(error)
            self._loading = False
            self._show()
            return
        if generation != self._generation:  # the filter moved on mid-flight
            return
        self._loading = False
        self._error = None
        self._rows += rows
        self._cursor = next_cursor
        self._show()

    def _visible(self) -> tuple[ActivityRow, ...]:
        return tuple(row for row in self._rows if self._query in self._haystack(row))

    def _haystack(self, row: ActivityRow) -> str:
        return (
            f"{row.event.content} {row.project_name or ''} {row.event.kind}".casefold()
        )

    def _show(self) -> None:
        feed = self.query_one("#activity", ActivityFeed)
        feed.update(self._content(self._visible()))
        self.query_one("#activity-hint", Static).update(self._hint())

    def _hint(self) -> str:
        named = "all" if self._kind is None else self._kind.value
        parts = [f"filter: {named}", _HINT]
        if self._cursor is None:
            parts.append(_EXHAUSTED)
        if self._error is not None:
            parts.append(self._error)
        return " · ".join(parts)

    def _content(self, rows: tuple[ActivityRow, ...]) -> Text:
        styles = tier_styles(self.query_one("#activity", ActivityFeed))
        text = Text()
        text.append(f"{_TITLE}\n\n", style=styles[Tier.PRIMARY] + Style(bold=True))
        day: datetime.date | None = None
        for row in rows:
            at = row.event.at.astimezone(self._tz)
            if at.date() != day:
                if day is not None:  # a blank line between days, none above the first
                    text.append("\n")
                day = at.date()
                text.append(
                    f"{humanize_date(day, self._today)}\n", style=styles[Tier.ACCENT]
                )
            text.append(f"{at:%H:%M}  ", style=styles[Tier.SECONDARY])
            text.append(
                f"{row.event.kind.value:<{_VERB_WIDTH}}  ", style=styles[Tier.MUTED]
            )
            text.append(row.event.content, style=styles[Tier.PRIMARY])
            if row.project_name:
                text.append(f"  #{row.project_name}", style=styles[Tier.MUTED])
            text.append("\n")
        return text
