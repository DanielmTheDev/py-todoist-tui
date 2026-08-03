from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no overlay for a destructive action. y/enter confirms; n/esc/q cancels."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen Static {
        width: 50%;
        max-width: 60;
        height: auto;
        padding: 1 2;
        border: round $error;
    }
    """

    def __init__(self, prompt: str, confirm_label: str = "delete") -> None:
        super().__init__()
        self._prompt = prompt
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        yield Static(self._content(), id="confirm")

    def on_key(self, event: events.Key) -> None:
        if event.key in ("y", "enter"):
            self.dismiss(True)
        elif event.key in ("n", "escape", "q"):
            self.dismiss(False)
        event.stop()  # consume every key so app bindings never fire under the modal

    def _content(self) -> Text:
        text = Text()
        text.append(f"{self._prompt}\n\n")
        text.append(f"y {self._confirm_label}", style="bold")
        text.append("   n / esc cancel", style="dim")
        return text
