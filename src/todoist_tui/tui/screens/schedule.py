import datetime
from dataclasses import dataclass

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.domain.due import Due
from todoist_tui.domain.schedule import QuickKind, quick_due


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


class ScheduleScreen(ModalScreen["DueResult | None"]):
    """Pick a due date. Quick keys commit immediately; escape cancels (None)."""

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

    def __init__(self, today: datetime.date) -> None:
        super().__init__()
        self._today = today

    def compose(self) -> ComposeResult:
        # markup=False: the "[t]" key hints are literal text, not Rich tags.
        yield Static(f"Set due:\n\n{_HINT}\n\nesc=cancel", id="schedule", markup=False)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key in _QUICK_KEYS:
            kind, _label = _QUICK_KEYS[event.key]
            self.dismiss(DueResult(quick_due(kind, self._today)))
        event.stop()  # consume every key so app bindings never fire under the modal
