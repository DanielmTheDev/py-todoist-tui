from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static


class HelpScreen(ModalScreen[None]):
    """Overlay listing every keyboard shortcut. escape/enter/q/? closes it."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen Static {
        width: 50%;
        max-width: 60;
        height: auto;
        padding: 1 2;
        border: round $primary;
    }
    """

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        super().__init__()
        self._rows = rows

    def compose(self) -> ComposeResult:
        yield Static(self._content(), id="help")

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "enter", "q", "question_mark"):
            self.dismiss()
        event.stop()  # consume every key so app bindings never fire under the modal

    def _content(self) -> Text:
        width = max((len(key) for key, _ in self._rows), default=0)
        text = Text()
        text.append("Shortcuts\n\n", style="bold")
        for key, description in self._rows:
            text.append(f"{key:<{width}}  ", style="bold")
            text.append(f"{description}\n")
        text.append("\nesc close", style="dim")
        return text
