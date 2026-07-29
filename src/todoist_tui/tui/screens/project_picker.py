from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from todoist_tui.domain.project import Project, sorted_projects


class ProjectPickerScreen(ModalScreen["Project | None"]):
    """Pick a project, filtering by typing. Dismisses the choice, or None on cancel."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    ProjectPickerScreen {
        align: center middle;
    }
    ProjectPickerScreen Input {
        width: 60%;
        max-width: 80;
        border: round $primary;
    }
    ProjectPickerScreen OptionList {
        width: 60%;
        max-width: 80;
        height: auto;
        max-height: 60%;
        border: round $primary;
    }
    """

    def __init__(self, projects: list[Project], current: str | None = None) -> None:
        super().__init__()
        self._sorted = sorted_projects(projects)
        self._visible = list(self._sorted)
        self._current = current

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Move to project…")
        yield OptionList(*(_option(p) for p in self._sorted))

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        if self._current is not None:
            index = next(
                (i for i, p in enumerate(self._sorted) if p.id == self._current), None
            )
            if index is not None:
                self.query_one(OptionList).highlighted = index

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.casefold()
        self._visible = [p for p in self._sorted if query in p.name.casefold()]
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([_option(p) for p in self._visible])
        if self._visible:
            options.highlighted = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._select()

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


def _option(project: Project) -> Option:
    return Option(project.name, id=project.id)
