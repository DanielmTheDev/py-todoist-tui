from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class TextPromptScreen(ModalScreen["str | None"]):
    """Prompt for a single line of text. Enter dismisses the trimmed value
    (a blank entry keeps the prompt open); escape dismisses None. The initial
    value is preselected so it can be replaced by typing."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    TextPromptScreen {
        align: center middle;
    }
    TextPromptScreen #prompt {
        width: 60%;
        max-width: 80;
        padding: 0 1;
    }
    TextPromptScreen Input {
        width: 60%;
        max-width: 80;
        border: round $primary;
    }
    """

    def __init__(self, prompt: str, initial: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._initial = initial

    def compose(self) -> ComposeResult:
        yield Static(self._prompt, id="prompt")
        yield Input(value=self._initial)

    def on_mount(self) -> None:
        field = self.query_one(Input)
        field.focus()
        field.select_all()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if name:  # a blank name is not a valid copy name: stay open
            self.dismiss(name)

    def action_cancel(self) -> None:
        self.dismiss(None)
