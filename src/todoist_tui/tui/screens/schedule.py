import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.domain.due import Due
from todoist_tui.domain.schedule import (
    QuickKind,
    month_weeks,
    parse_time_digits,
    quick_due,
    shift_month,
)

Kind = Literal["due", "deadline"]


@dataclass(frozen=True, slots=True)
class DueResult:
    """A chosen date. `due is None` means "clear it" (distinct from a cancelled
    modal, which dismisses with None instead of a DueResult). In deadline mode
    the carried `Due` is date-only — the caller reads its `date`."""

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
        self,
        today: datetime.date,
        current: datetime.date | None = None,
        current_time: datetime.time | None = None,
        kind: Kind = "due",
    ) -> None:
        super().__init__()
        self._today = today
        self._kind = kind
        self._cursor = current or today  # calendar starts on the task's date
        # Time-of-day buffer as typed digits (HHMM); "" means all-day. Deadlines
        # are date-only, so the buffer is always empty and the time UI is hidden.
        self._time = (
            f"{current_time:%H%M}" if kind == "due" and current_time is not None else ""
        )
        self._error: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(self._content(), id="schedule")

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self._confirm()
        elif event.key in _QUICK_KEYS:  # quick keys are all-day, ignore any time
            kind, _label = _QUICK_KEYS[event.key]
            self.dismiss(DueResult(quick_due(kind, self._today)))
        elif (
            self._kind == "due"
            and event.character
            and event.character.isdigit()
            and len(self._time) < 4
        ):
            self._time += event.character
            self._error = None
            self._refresh()
        elif self._kind == "due" and event.key == "backspace":
            self._time = self._time[:-1]
            self._error = None
            self._refresh()
        elif self._kind == "due" and event.key == "r":  # remove time, keep date
            self._time = ""
            self._error = None
            self._refresh()
        elif (move := _NAV.get(event.character or "")) is not None:
            self._cursor = move(self._cursor)
            self._refresh()
        event.stop()  # consume every key so app bindings never fire under the modal

    def _confirm(self) -> None:
        try:
            time = parse_time_digits(self._time)
        except ValueError:
            self._error = f"invalid time: {self._time}"
            self._refresh()
            return
        self.dismiss(DueResult(Due(date=self._cursor, time=time)))

    def _refresh(self) -> None:
        self.query_one("#schedule", Static).update(self._content())

    def _content(self) -> Text:
        text = Text()
        label = "deadline" if self._kind == "deadline" else "due"
        text.append(f"Set {label} — {self._cursor:%B %Y}\n\n", style="bold")
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
        if self._kind == "due":
            text.append(f"\n\n{self._time_line()}\n")
        else:
            text.append("\n\n")
        if self._error is not None:
            text.append(f"{self._error}\n", style="bold red")
        hint = "hjkl move  [ ] month"
        if self._kind == "due":
            hint += "  digits time"
            if self._time:
                hint += "  r remove time"
        hint += "  enter pick  esc cancel"
        text.append(hint, style="dim")
        return text

    def _time_line(self) -> Text:
        line = Text("Time: ", style="bold")
        if not self._time:
            line.append("all-day", style="dim")
            return line
        line.append(self._time)
        try:  # show the parsed HH:MM preview while the buffer is valid
            parsed = parse_time_digits(self._time)
        except ValueError:
            return line
        if parsed is not None:
            line.append(f"  → {parsed:%H:%M}", style="dim")
        return line
