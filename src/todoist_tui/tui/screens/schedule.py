import datetime
from collections.abc import Callable
from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.domain.due import Due
from todoist_tui.domain.schedule import QuickKind, month_weeks, quick_due, shift_month


@dataclass(frozen=True, slots=True)
class DueResult:
    """A chosen due date. `due is None` means "clear the date" (distinct from a
    cancelled modal, which dismisses with None instead of a DueResult)."""

    due: Due | None


# Quick-key row: key -> (quick kind, label shown in the hint).
_QUICK_KEYS: dict[str, tuple[QuickKind, str]] = {
    "t": ("today", "Today"),
    "m": ("tomorrow", "Tomorrow"),
    "w": ("next_week", "Next week"),
    "e": ("weekend", "Weekend"),
    "x": ("clear", "No date"),
}
_HINT = "  ".join(f"[{key}] {label}" for key, (_kind, label) in _QUICK_KEYS.items())
_WEEKDAYS = "Mo Tu We Th Fr Sa Su"

_DAY = datetime.timedelta(days=1)
_WEEK = datetime.timedelta(days=7)
# Calendar cursor moves: h/j/k/l like the task list, [/] step whole months.
_NAV: dict[str, Callable[[datetime.date], datetime.date]] = {
    "h": lambda d: d - _DAY,
    "l": lambda d: d + _DAY,
    "k": lambda d: d - _WEEK,
    "j": lambda d: d + _WEEK,
    "[": lambda d: shift_month(d, -1),
    "]": lambda d: shift_month(d, 1),
}


class ScheduleScreen(ModalScreen["DueResult | None"]):
    """Pick a due date: quick keys commit at once, or arrow the calendar and
    press enter. Escape cancels (dismisses None)."""

    DEFAULT_CSS = """
    ScheduleScreen {
        align: center middle;
    }
    ScheduleScreen Static {
        width: 70%;
        max-width: 80;
        height: auto;
        padding: 1 2;
        border: round $primary;
    }
    """

    def __init__(
        self, today: datetime.date, current: datetime.date | None = None
    ) -> None:
        super().__init__()
        self._today = today
        self._cursor = current or today  # calendar starts on the task's due date

    def compose(self) -> ComposeResult:
        yield Static(self._content(), id="schedule")

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self.dismiss(DueResult(Due(date=self._cursor)))
        elif event.key in _QUICK_KEYS:
            kind, _label = _QUICK_KEYS[event.key]
            self.dismiss(DueResult(quick_due(kind, self._today)))
        elif (move := _NAV.get(event.character or "")) is not None:
            self._cursor = move(self._cursor)
            self.query_one("#schedule", Static).update(self._content())
        event.stop()  # consume every key so app bindings never fire under the modal

    def _content(self) -> Text:
        text = Text()
        text.append(f"Set due — {self._cursor:%B %Y}\n\n", style="bold")
        text.append(f"{_HINT}\n\n")
        text.append(f"{_WEEKDAYS}\n", style="dim")
        for week in month_weeks(self._cursor.year, self._cursor.month):
            for column, cell in enumerate(week):
                if column:
                    text.append(" ")
                if cell is None:
                    text.append("  ")
                elif cell == self._cursor:
                    text.append(f"{cell.day:2d}", style="reverse")
                elif cell == self._today:
                    text.append(f"{cell.day:2d}", style="bold underline")
                else:
                    text.append(f"{cell.day:2d}")
            text.append("\n")
        text.append("\nhjkl move  [ ] month  enter pick  esc cancel", style="dim")
        return text
