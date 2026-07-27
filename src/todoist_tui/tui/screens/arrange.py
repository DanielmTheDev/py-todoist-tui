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
        self._group: list[Field] = list(arrangement.group_by)
        self._sort: list[SortKey] = list(arrangement.sort_by)

    def compose(self) -> ComposeResult:
        # markup=False: field-key hints like "[p]" are literal text, not Rich tags.
        yield Static(self._text(), id="arrange", markup=False)

    def on_key(self, event: events.Key) -> None:
        key = event.key
        if key == "enter":
            self.dismiss(self._result())
        elif key == "escape":
            self.dismiss(None)
        elif key == "backspace":
            self._pop()
        elif key == ("G" if self._mode == "group" else "S"):
            self._clear()
        elif key in _FIELD_KEYS:
            self._add(_FIELD_KEYS[key])
        event.stop()  # consume every key so app bindings never fire under the modal

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _add(self, field: Field) -> None:
        if self._mode == "group":
            if field not in self._group and len(self._group) < MAX_LEVELS:
                self._group.append(field)
        else:
            existing = next((s for s in self._sort if s.field is field), None)
            if existing is not None:  # tapping a chosen field flips its direction
                self._sort = [
                    SortKey(field, not s.ascending) if s is existing else s
                    for s in self._sort
                ]
            elif len(self._sort) < MAX_LEVELS:
                self._sort.append(SortKey(field))
        self._refresh()

    def _pop(self) -> None:
        chain = self._group if self._mode == "group" else self._sort
        if chain:
            chain.pop()
        self._refresh()

    def _clear(self) -> None:
        if self._mode == "group":
            self._group.clear()
        else:
            self._sort.clear()
        self._refresh()

    def _result(self) -> Arrangement:
        if self._mode == "group":
            return Arrangement(group_by=tuple(self._group), sort_by=self._base.sort_by)
        return Arrangement(group_by=self._base.group_by, sort_by=tuple(self._sort))

    def _refresh(self) -> None:
        self.query_one("#arrange", Static).update(self._text())

    def _text(self) -> str:
        title = "Group by" if self._mode == "group" else "Sort by"
        chain = _chain_text(self._group if self._mode == "group" else self._sort)
        clear = "shift+G" if self._mode == "group" else "shift+S"
        return (
            f"{title}:  {chain}\n\n{_HINT}\n\n"
            f"enter=apply  esc=cancel  ⌫=remove last  {clear}=clear"
        )


def _chain_text(chain: list[Field] | list[SortKey]) -> str:
    if not chain:
        return "(none)"
    return " › ".join(_step_label(step) for step in chain)


def _step_label(step: Field | SortKey) -> str:
    if isinstance(step, Field):
        return step.label
    arrow = "↑" if step.ascending else "↓"
    return f"{step.field.label} {arrow}"
