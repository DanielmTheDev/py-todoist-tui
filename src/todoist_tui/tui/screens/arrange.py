from typing import ClassVar, Literal

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.domain.arrange import MAX_LEVELS, Arrangement, Field, SortKey

Mode = Literal["group", "sort"]

# Single-letter key per arrangeable field (shown in the hint bar).
_FIELD_KEYS: dict[str, Field] = {
    "p": Field.PROJECT,
    "s": Field.SECTION,
    "r": Field.PRIORITY,
    "d": Field.DUE_DATE,
    "t": Field.DUE_TIME,
    "u": Field.RECURRING,
    "c": Field.CONTENT,
    "l": Field.LABELS,
}
_HINT = "  ".join(f"[{key}] {field.label}" for key, field in _FIELD_KEYS.items())


class ArrangeScreen(ModalScreen["Arrangement | None"]):
    """Transient chain builder. Tap field keys to build the group or sort chain;
    enter applies (dismisses the new Arrangement), escape cancels (dismisses None).
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ArrangeScreen {
        align: center middle;
    }
    ArrangeScreen Static {
        width: 70%;
        max-width: 80;
        height: auto;
        padding: 1 2;
        border: round $primary;
    }
    """

    def __init__(self, arrangement: Arrangement, mode: Mode) -> None:
        super().__init__()
        self._base = arrangement
        self._mode: Mode = mode
        # Both modes are the same shape: an ordered field+direction chain.
        if mode == "group":
            self._chain = [
                SortKey(f, arrangement.group_ascending(f)) for f in arrangement.group_by
            ]
        else:
            self._chain = list(arrangement.sort_by)

    def compose(self) -> ComposeResult:
        # markup=False: field-key hints like "[p]" are literal text, not Rich tags.
        yield Static(self._text(), id="arrange", markup=False)

    def on_key(self, event: events.Key) -> None:
        key = event.key
        clear_char = "G" if self._mode == "group" else "S"
        if key == "enter":
            self.dismiss(self._result())
        elif key == "escape":
            self.dismiss(None)
        elif key == "backspace":
            self._pop()
        elif event.character == clear_char:
            self._clear()  # match the char, not a key name, so shift+G is reliable
        elif key in _FIELD_KEYS:
            self._add(_FIELD_KEYS[key])
        event.stop()  # consume every key so app bindings never fire under the modal

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _add(self, field: Field) -> None:
        existing = next((s for s in self._chain if s.field is field), None)
        if existing is not None:  # tapping a chosen field flips its direction
            self._chain = [
                SortKey(field, not s.ascending) if s is existing else s
                for s in self._chain
            ]
        elif len(self._chain) < MAX_LEVELS:
            self._chain.append(SortKey(field))
        self._refresh()

    def _pop(self) -> None:
        if self._chain:
            self._chain.pop()
        self._refresh()

    def _clear(self) -> None:
        self._chain.clear()
        self._refresh()

    def _result(self) -> Arrangement:
        if self._mode == "group":
            return Arrangement(
                group_by=tuple(s.field for s in self._chain),
                group_desc=frozenset(s.field for s in self._chain if not s.ascending),
                sort_by=self._base.sort_by,
            )
        return Arrangement(
            group_by=self._base.group_by,
            group_desc=self._base.group_desc,
            sort_by=tuple(self._chain),
        )

    def _refresh(self) -> None:
        self.query_one("#arrange", Static).update(self._text())

    def _text(self) -> str:
        title = "Group by" if self._mode == "group" else "Sort by"
        chain = _chain_text(self._chain)
        clear = "shift+G" if self._mode == "group" else "shift+S"
        return (
            f"{title}:  {chain}\n\n{_HINT}\n\n"
            f"enter=apply  tap a chosen field again = flip ↑/↓\n"
            f"esc=cancel  ⌫=remove last  {clear}=clear"
        )


def _chain_text(chain: list[SortKey]) -> str:
    if not chain:
        return "(none)"
    return " › ".join(f"{s.field.label} {'↑' if s.ascending else '↓'}" for s in chain)
