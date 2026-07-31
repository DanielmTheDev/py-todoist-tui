from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from todoist_tui.domain.filter import Filter, sorted_filters


class FilterScreen(ModalScreen["Filter | None"]):
    """Pick a saved filter by typing. Dismisses the chosen Filter, or None on cancel."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    FilterScreen {
        align: center middle;
    }
    FilterScreen Input {
        width: 60%;
        max-width: 80;
        border: round $primary;
    }
    FilterScreen OptionList {
        width: 60%;
        max-width: 80;
        height: auto;
        max-height: 60%;
        border: round $primary;
    }
    """

    def __init__(self, filters: list[Filter]) -> None:
        super().__init__()
        # Not `self._filters`: that name is App/Widget's own line-filter list.
        self._choices = sorted_filters(filters)
        self._visible = list(self._choices)
        self._by_id = {f.id: f for f in self._choices}

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type to filter…")
        yield OptionList(*(_option(f) for f in self._choices))

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.casefold()
        self._visible = [f for f in self._choices if query in f.name.casefold()]
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([_option(f) for f in self._visible])
        if self._visible:
            options.highlighted = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._select()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._by_id[str(event.option.id)])

    def action_cursor_down(self) -> None:
        self.query_one(OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(OptionList).action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _select(self) -> None:
        index = self.query_one(OptionList).highlighted
        if index is None:  # nothing matches the current filter: stay open
            return
        self.dismiss(self._visible[index])


def _option(f: Filter) -> Option:
    return Option(f.name, id=f.id)
