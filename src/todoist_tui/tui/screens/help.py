from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from todoist_tui.tui.screens.scrolling import ScrollBody


def as_binding(entry: BindingType) -> Binding:
    """Normalize a Textual binding entry (tuple or `Binding`) to a `Binding`."""
    if isinstance(entry, Binding):
        return entry
    key, action, *rest = entry
    return Binding(key, action, rest[0] if rest else "")


_KEY_SYMBOLS = {"at": "@", "asterisk": "*", "question_mark": "?"}


def pressed(*keys: str) -> str:
    """The keys as they are printed on the keyboard, not as Textual names them."""
    return " / ".join(_KEY_SYMBOLS.get(key, key) for key in keys)


def shortcut_rows(*binding_lists: list[BindingType]) -> list[tuple[str, str]]:
    """Flatten Textual binding definitions into (key, description) help rows,
    dropping entries with no description and the help binding itself. A binding
    holding several keys ("h,left") lists them all: "h / left"."""
    rows: list[tuple[str, str]] = []
    for bindings in binding_lists:
        for binding in map(as_binding, bindings):
            if binding.action == "help" or not binding.description:
                continue
            rows.append((pressed(*binding.key.split(",")), binding.description))
    return rows


class HelpScreen(ModalScreen[None]):
    """Overlay listing every keyboard shortcut. Type to filter; escape closes."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss", "Close"),
        # the filter box keeps focus, so the list is scrolled from here
        Binding("down", "scroll(1)", "Down", show=False),
        Binding("up", "scroll(-1)", "Up", show=False),
        Binding("pagedown", "scroll(10)", "Page down", show=False),
        Binding("pageup", "scroll(-10)", "Page up", show=False),
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
    HelpScreen ScrollBody {
        width: 50%;
        max-width: 60;
        padding: 1 2;
        border: round $primary;
    }
    HelpScreen Static {
        height: auto;
    }
    """

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        super().__init__()
        self._rows = rows

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter shortcuts…")
        # the list outgrows a short terminal, and a clipped shortcut is a
        # shortcut nobody finds
        with ScrollBody():
            yield Static(self._content(self._rows), id="help")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def action_scroll(self, lines: int) -> None:
        self.query_one(ScrollBody).scroll_relative(y=lines, animate=False)

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
