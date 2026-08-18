from dataclasses import dataclass
from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from todoist_tui.application.views import TaskRow
from todoist_tui.tui.screens.picking import PickFilter, numbered, row_for_key
from todoist_tui.tui.screens.scrolling import PickList

_TOP_LEVEL = "— No parent (top level)"


@dataclass(frozen=True, slots=True)
class ParentTarget:
    """The task a move nests under; None puts it back at its project's top level."""

    row: TaskRow | None


class ParentPickerScreen(ModalScreen["ParentTarget | None"]):
    """Pick the task to nest under by typing, or by the number the row carries. The
    top-level entry heads the list and survives every filter, so un-parenting is
    always one keystroke away. Dismisses the chosen `ParentTarget`, or None on
    cancel."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    ParentPickerScreen {
        align: center middle;
    }
    ParentPickerScreen Input {
        width: 60%;
        max-width: 80;
        border: round $primary;
    }
    ParentPickerScreen OptionList {
        width: 60%;
        max-width: 80;
        border: round $primary;
    }
    """

    def __init__(
        self, rows: list[TaskRow], placeholder: str = "Move under parent…"
    ) -> None:
        super().__init__()
        self._rows = rows
        self._visible = list(rows)
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield PickFilter(placeholder=self._placeholder)
        yield PickList(*self._options())

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_key(self, event: events.Key) -> None:
        index = row_for_key(event.key)
        # one row more than `_visible`: the top-level entry heads the list as index 0
        if index is None or index > len(self._visible):
            return
        event.stop()
        self._dismiss_at(index)

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.casefold()
        self._visible = [r for r in self._rows if query in _label(r).casefold()]
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options(self._options())
        options.highlighted = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._select()

    def action_cursor_down(self) -> None:
        self.query_one(OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(OptionList).action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _options(self) -> list[Option]:
        labels = numbered([_TOP_LEVEL] + [_label(r) for r in self._visible])
        return [Option(label) for label in labels]

    def _select(self) -> None:
        index = self.query_one(OptionList).highlighted
        if index is None:
            return
        self._dismiss_at(index)

    def _dismiss_at(self, index: int) -> None:
        row = None if index == 0 else self._visible[index - 1]
        self.dismiss(ParentTarget(row))


def _label(row: TaskRow) -> str:
    """Title plus where it lives, so same-named tasks stay tellable apart."""
    place = " / ".join(p for p in (row.project_name, row.section_name) if p)
    return f"{row.content} — {place}" if place else row.content
