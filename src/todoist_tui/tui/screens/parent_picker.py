from dataclasses import dataclass
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from todoist_tui.application.views import TaskRow

_TOP_LEVEL = "— No parent (top level)"


@dataclass(frozen=True, slots=True)
class ParentTarget:
    """The task a move nests under; None puts it back at its project's top level."""

    row: TaskRow | None


class ParentPickerScreen(ModalScreen["ParentTarget | None"]):
    """Pick the task to nest under by typing. The top-level entry heads the list
    and survives every filter, so un-parenting is always one keystroke away.
    Dismisses the chosen `ParentTarget`, or None on cancel."""

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
        height: auto;
        max-height: 60%;
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
        yield Input(placeholder=self._placeholder)
        yield OptionList(*self._options())

    def on_mount(self) -> None:
        self.query_one(Input).focus()

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
        return [Option(_TOP_LEVEL)] + [Option(_label(r)) for r in self._visible]

    def _select(self) -> None:
        index = self.query_one(OptionList).highlighted
        if index is None:
            return
        row = None if index == 0 else self._visible[index - 1]
        self.dismiss(ParentTarget(row))


def _label(row: TaskRow) -> str:
    """Title plus where it lives, so same-named tasks stay tellable apart."""
    place = " / ".join(p for p in (row.project_name, row.section_name) if p)
    return f"{row.content} — {place}" if place else row.content
