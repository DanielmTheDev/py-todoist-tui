from dataclasses import dataclass
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static, TextArea


@dataclass(frozen=True, slots=True)
class TaskText:
    content: str
    description: str


class TaskEditScreen(ModalScreen["TaskText | None"]):
    """Edit a task's title and description together. Tab moves between the
    fields, ctrl+s (or enter in the title) dismisses both trimmed values, escape
    dismisses None. A blank title keeps the prompt open."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    TaskEditScreen { align: center middle; }
    TaskEditScreen #fields { width: 70%; max-width: 80; height: auto; }
    TaskEditScreen .label { padding: 0 1; }
    TaskEditScreen Input { border: round $primary; }
    TaskEditScreen TextArea { height: 8; border: round $primary; }
    TaskEditScreen #hint { padding: 0 1; color: $text-muted; }
    """

    def __init__(self, content: str, description: str) -> None:
        super().__init__()
        self._content = content
        self._description = description

    def compose(self) -> ComposeResult:
        with Vertical(id="fields"):
            yield Static("Title", classes="label")
            # select_on_focus would make the first keystroke wipe the title
            yield Input(value=self._content.strip(), select_on_focus=False)
            yield Static("Description", classes="label")
            yield TextArea(self._description.strip())
            yield Static("tab switch · ctrl+s save · esc cancel", id="hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        description = self.query_one(TextArea)
        description.move_cursor(description.document.end)  # append, don't prepend

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def action_save(self) -> None:
        content = self.query_one(Input).value.strip()
        if not content:  # a task must keep a title: stay open
            return
        self.dismiss(TaskText(content, self.query_one(TextArea).text.strip()))

    def action_cancel(self) -> None:
        self.dismiss(None)
