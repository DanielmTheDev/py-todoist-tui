from dataclasses import dataclass
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from todoist_tui.domain.project import Project, sorted_projects
from todoist_tui.domain.section import Section, sorted_sections


@dataclass(frozen=True, slots=True)
class MoveTarget:
    """Where a task should move: a project root, or a section within it."""

    project_id: str
    project_name: str
    section_id: str | None = None
    section_name: str | None = None


class ProjectPickerScreen(ModalScreen["MoveTarget | None"]):
    """Pick a move target — a project root or one of its sections — by typing.
    Dismisses the chosen `MoveTarget`, or None on cancel."""

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

    def __init__(
        self,
        projects: list[Project],
        sections: list[Section],
        current_project: str | None = None,
        current_section: str | None = None,
        placeholder: str = "Move to project or section…",
    ) -> None:
        super().__init__()
        self._targets = _targets(projects, sections)
        self._visible = list(self._targets)
        self._current_project = current_project
        self._current_section = current_section
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield Input(placeholder=self._placeholder)
        yield OptionList(*(_option(t) for t in self._targets))

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        index = next(
            (
                i
                for i, t in enumerate(self._targets)
                if t.project_id == self._current_project
                and t.section_id == self._current_section
            ),
            None,
        )
        if index is not None:
            self.query_one(OptionList).highlighted = index

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.casefold()
        self._visible = [t for t in self._targets if query in _label(t).casefold()]
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([_option(t) for t in self._visible])
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


def _targets(projects: list[Project], sections: list[Section]) -> list[MoveTarget]:
    by_project: dict[str, list[Section]] = {}
    for section in sections:
        by_project.setdefault(section.project_id, []).append(section)
    targets: list[MoveTarget] = []
    for project in sorted_projects(projects):
        if project.is_inbox:  # Inbox is not a move target (has its own `i` key)
            continue
        targets.append(MoveTarget(project.id, project.name))
        for section in sorted_sections(by_project.get(project.id, [])):
            targets.append(
                MoveTarget(project.id, project.name, section.id, section.name)
            )
    return targets


def _label(target: MoveTarget) -> str:
    if target.section_name is None:
        return target.project_name
    return f"{target.project_name} / {target.section_name}"


def _option(target: MoveTarget) -> Option:
    return Option(_label(target))
