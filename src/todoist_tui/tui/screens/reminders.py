import datetime
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.domain.reminder import Reminder
from todoist_tui.tui.format import format_reminder

Mode = Literal["manage", "add"]


@dataclass(frozen=True, slots=True)
class ReminderRequest:
    """The one reminder action the user chose. `add_absolute` carries no payload —
    the caller opens a date+time picker to complete it; the others are ready to
    apply as-is."""

    delete_id: str | None = None
    add_relative: int | None = None  # minute_offset before the task's due time
    add_absolute: bool = False


# Quick relative offsets: key -> (minute_offset, label).
_PRESETS: dict[str, tuple[int, str]] = {
    "t": (0, "at due time"),
    "h": (60, "1 hour before"),
    "d": (1440, "1 day before"),
}


class RemindersScreen(ModalScreen["ReminderRequest | None"]):
    """Manage a task's reminders (list, add, delete) or, in `add` mode, only pick
    a new reminder to apply across a selection. Fully keyboard-driven; escape
    steps back a level and cancels from the top."""

    DEFAULT_CSS = """
    RemindersScreen {
        align: center middle;
    }
    RemindersScreen Static {
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
        existing: tuple[Reminder, ...] = (),
        allow_relative: bool = True,
        mode: Mode = "manage",
    ) -> None:
        super().__init__()
        self._today = today
        self._existing = existing
        self._allow_relative = allow_relative
        self._mode: Mode = mode
        self._state = "type" if mode == "add" else "menu"
        self._cursor = 0  # highlighted reminder in the menu list
        self._digits = ""  # typed minute_offset buffer in the relative state
        self._error: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(self._content(), id="reminders")

    def on_key(self, event: events.Key) -> None:
        if self._state == "menu":
            self._on_menu_key(event)
        elif self._state == "type":
            self._on_type_key(event)
        else:
            self._on_relative_key(event)
        event.stop()  # consume every key so app bindings never fire under the modal

    def _on_menu_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "a":
            self._state = "type"
            self._refresh()
        elif event.key in ("d", "x") and self._existing:
            self.dismiss(ReminderRequest(delete_id=self._existing[self._cursor].id))
        elif event.key in ("j", "down"):
            self._move_cursor(1)
        elif event.key in ("k", "up"):
            self._move_cursor(-1)

    def _on_type_key(self, event: events.Key) -> None:
        if event.key == "escape":
            if self._mode == "manage":
                self._state = "menu"
                self._refresh()
            else:
                self.dismiss(None)
        elif event.key == "a":
            self.dismiss(ReminderRequest(add_absolute=True))
        elif event.key == "r" and self._allow_relative:
            self._state = "relative"
            self._digits = ""
            self._error = None
            self._refresh()

    def _on_relative_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self._state = "type"
            self._refresh()
        elif event.character in _PRESETS:
            self.dismiss(ReminderRequest(add_relative=_PRESETS[event.character][0]))
        elif event.character and event.character.isdigit() and len(self._digits) < 5:
            self._digits += event.character
            self._refresh()
        elif event.key == "backspace":
            self._digits = self._digits[:-1]
            self._refresh()
        elif event.key == "enter":
            if not self._digits:
                self._error = "type minutes, or pick a preset"
                self._refresh()
                return
            self.dismiss(ReminderRequest(add_relative=int(self._digits)))

    def _move_cursor(self, delta: int) -> None:
        if not self._existing:
            return
        self._cursor = (self._cursor + delta) % len(self._existing)
        self._refresh()

    def _refresh(self) -> None:
        self.query_one("#reminders", Static).update(self._content())

    def _content(self) -> Text:
        if self._state == "menu":
            return self._menu_content()
        if self._state == "type":
            return self._type_content()
        return self._relative_content()

    def _menu_content(self) -> Text:
        text = Text()
        text.append("Reminders\n\n", style="bold")
        if not self._existing:
            text.append("No reminders yet.\n\n", style="dim")
        for index, reminder in enumerate(self._existing):
            style = "reverse" if index == self._cursor else ""
            text.append(f"{format_reminder(reminder, self._today)}\n", style=style)
        text.append("\n")
        hint = "a add"
        if self._existing:
            hint = "j/k move  d delete  " + hint
        text.append(f"{hint}  esc close", style="dim")
        return text

    def _type_content(self) -> Text:
        text = Text()
        text.append("Add reminder\n\n", style="bold")
        text.append("a  absolute date & time\n")
        if self._allow_relative:
            text.append("r  relative to the task's due time\n")
        else:
            text.append("relative needs a due time on the task\n", style="dim")
        back = "esc back" if self._mode == "manage" else "esc cancel"
        text.append(f"\n{back}", style="dim")
        return text

    def _relative_content(self) -> Text:
        text = Text()
        text.append("Remind before due\n\n", style="bold")
        presets = "  ".join(f"[{key}] {label}" for key, (_m, label) in _PRESETS.items())
        text.append(f"{presets}\n\n")
        buffer = self._digits or "—"
        text.append(f"Minutes: {buffer}\n", style="bold")
        if self._error is not None:
            text.append(f"{self._error}\n", style="bold red")
        text.append("\ndigits then enter  esc back", style="dim")
        return text
