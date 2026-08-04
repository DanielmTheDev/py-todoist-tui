from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class HelpScreen(ModalScreen[None]):
    """Overlay listing every keyboard shortcut. Type to filter; escape closes."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen Input {
        width: 50%;
        max-width: 60;
        border: round $primary;
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
        yield Input(placeholder="Filter shortcuts…")
        yield Static(self._content(self._rows), id="help")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.casefold()
        visible = [r for r in self._rows if query in f"{r[0]} {r[1]}".casefold()]
        self.query_one("#help", Static).update(self._content(visible))

    def _content(self, rows: list[tuple[str, str]]) -> Text:
        width = max((len(key) for key, _ in rows), default=0)
        text = Text()
        text.append("Shortcuts\n\n", style="bold")
        for key, description in rows:
            text.append(f"{key:<{width}}  ", style="bold")
            text.append(f"{description}\n")
        text.append("\nesc close", style="dim")
        return text
