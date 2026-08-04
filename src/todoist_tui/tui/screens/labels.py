from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class LabelsScreen(ModalScreen["tuple[str, ...] | None"]):
    """Toggle a task's labels. Dismisses the chosen set, or None on cancel.

    Key-driven rather than Input-backed: Space must toggle the highlighted label,
    which a focused Input would instead swallow as a literal space.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    LabelsScreen {
        align: center middle;
    }
    LabelsScreen #labels-header {
        width: 60%;
        max-width: 80;
        padding: 0 1;
        border: round $primary;
    }
    LabelsScreen OptionList {
        width: 60%;
        max-width: 80;
        height: auto;
        max-height: 60%;
        border: round $primary;
    }
    """

    def __init__(self, all_labels: list[str], current: tuple[str, ...]) -> None:
        super().__init__()
        # `current` may hold a label the catalog lacks; show it so it's togglable.
        self._all = sorted(set(all_labels) | set(current))
        self._selected: set[str] = set(current)
        self._filter = ""
        self._entries: list[tuple[str, str]] = []  # (kind, value): kind in label/create

    def compose(self) -> ComposeResult:
        yield Static(id="labels-header")
        options = OptionList()
        options.can_focus = False  # keep key events on the screen, not the list
        yield options

    def on_mount(self) -> None:
        self._sync_view()

    def on_key(self, event: events.Key) -> None:
        if event.key == "space":
            event.stop()
            self._toggle_highlighted()
        elif event.key == "enter":
            event.stop()
            self.dismiss(tuple(sorted(self._selected)))
        elif event.key == "backspace":
            event.stop()
            self._filter = self._filter[:-1]
            self._sync_view(reset_cursor=True)
        elif event.key in ("up", "down"):
            event.stop()
            self._move_cursor(-1 if event.key == "up" else 1)
        elif event.is_printable and event.character:
            event.stop()
            self._filter += event.character
            self._sync_view(reset_cursor=True)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _toggle_highlighted(self) -> None:
        options = self.query_one(OptionList)
        index = options.highlighted
        if index is None or index >= len(self._entries):
            return
        kind, value = self._entries[index]
        if kind == "create":
            self._all.append(value)
            self._selected.add(value)
            self._filter = ""
            self._sync_view(reset_cursor=True)
            return
        self._selected.symmetric_difference_update({value})
        self._sync_view()

    def _move_cursor(self, step: int) -> None:
        options = self.query_one(OptionList)
        if not self._entries or options.highlighted is None:
            return
        options.highlighted = max(
            0, min(options.highlighted + step, len(self._entries) - 1)
        )

    def _sync_view(self, reset_cursor: bool = False) -> None:
        query = self._filter.casefold()
        visible = [name for name in self._all if query in name.casefold()]
        self._entries = [("label", name) for name in visible]
        if self._filter and not visible:  # nothing matches: offer to create it
            self._entries.append(("create", self._filter))

        options = self.query_one(OptionList)
        prior = 0 if reset_cursor else (options.highlighted or 0)
        options.clear_options()
        options.add_options(
            [self._option(kind, value) for kind, value in self._entries]
        )
        if self._entries:
            options.highlighted = min(prior, len(self._entries) - 1)
        self.query_one("#labels-header", Static).update(f"filter: {self._filter}")

    def _option(self, kind: str, value: str) -> Option:
        # Text, not a markup string: a bracketed prefix like "[x]" would be parsed
        # as Rich markup and swallowed, hiding the checkbox.
        if kind == "create":
            return Option(Text(f"[+] create @{value}"))
        mark = "x" if value in self._selected else " "
        return Option(Text(f"[{mark}] {value}"))
