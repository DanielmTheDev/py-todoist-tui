from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from todoist_tui.domain.filter import Filter, sorted_filters


class FilterList(OptionList):
    """OptionList with vim j/k aliases for the built-in cursor moves."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]


class FilterScreen(ModalScreen["Filter | None"]):
    """Pick a saved filter. Dismisses with the chosen Filter, or None on cancel."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    FilterScreen {
        align: center middle;
    }
    FilterScreen FilterList {
        width: 60%;
        max-width: 80;
        height: auto;
        max-height: 80%;
        border: round $primary;
    }
    """

    def __init__(self, filters: list[Filter]) -> None:
        super().__init__()
        # Not `self._filters`: that name is App/Widget's own line-filter list.
        self._choices = sorted_filters(filters)
        self._by_id = {f.id: f for f in self._choices}

    def compose(self) -> ComposeResult:
        yield FilterList(*(_option(f) for f in self._choices))

    def on_mount(self) -> None:
        self.query_one(FilterList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._by_id[str(event.option.id)])

    def action_cancel(self) -> None:
        self.dismiss(None)


def _option(f: Filter) -> Option:
    label = Text.assemble(f.name, "\n", (f.query, "dim"))
    return Option(label, id=f.id)
