from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.application.views import TaskRow
from todoist_tui.tui.format import format_due

_DASH = "—"  # stands in for an unset field


class TaskDetailScreen(ModalScreen[None]):
    """Read-only card for a single task. Any of escape/enter/q closes it."""

    DEFAULT_CSS = """
    TaskDetailScreen {
        align: center middle;
    }
    TaskDetailScreen Static {
        width: 70%;
        max-width: 80;
        height: auto;
        padding: 1 2;
        border: round $primary;
    }
    """

    def __init__(self, row: TaskRow) -> None:
        super().__init__()
        self._row = row

    def compose(self) -> ComposeResult:
        yield Static(self._content(), id="detail")

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "enter", "q"):
            self.dismiss()
        event.stop()  # consume every key so app bindings never fire under the modal

    def _content(self) -> Text:
        row = self._row
        text = Text()
        text.append(f"{row.content}\n\n", style="bold")
        text.append(f"Due       {self._due_line()}\n")
        text.append(f"Priority  {row.priority.label}\n")
        text.append(f"Project   {row.project_name or _DASH}\n")
        text.append(f"Labels    {self._labels_line()}\n\n")
        text.append("Description\n", style="bold")
        if row.description:
            text.append(row.description)
        else:
            text.append("No description", style="dim")
        text.append("\n\nesc close", style="dim")
        return text

    def _due_line(self) -> str:
        due = self._row.due
        if due is None:
            return _DASH
        formatted = format_due(due)
        if due.string:  # recurring: show the rule alongside the next date
            return f"{formatted} ({due.string})"
        return formatted

    def _labels_line(self) -> str:
        if not self._row.labels:
            return _DASH
        return " ".join(f"@{label}" for label in self._row.labels)
