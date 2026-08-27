"""The subtasks of the task being edited, listed under its description.

Each key is the one the list uses for that action, so the two read the same: the
list only reports what was pressed — the editor owns the drafts and applies it.
"""

from typing import ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.widgets.option_list import Option

from todoist_tui.tui.screens.draft import Subtask
from todoist_tui.tui.screens.scrolling import PickList

EMPTY = "No subtasks — alt+a adds one."
HINT = "subtasks: ctrl+e edit · e done · delete remove"


class SubtaskList(PickList):
    """A focusable list of subtask drafts. Vim keys join the arrows, as in the
    task list."""

    SHARE = 0.3  # of the terminal: the editor's fields need the rest

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("ctrl+e", "edit", "Subtasks: edit", show=False),
        Binding("e", "complete", "Subtasks: complete", show=False),
        Binding("delete", "remove", "Subtasks: remove", show=False),
    ]

    class Acted(Message):
        """What the user asked of the highlighted subtask."""

        def __init__(self, action: str, index: int) -> None:
            super().__init__()
            self.action = action
            self.index = index

    def show(self, subtasks: tuple[Subtask, ...]) -> None:
        """Redraw the list, keeping the cursor where it can still land."""
        prior = self.highlighted or 0
        self.clear_options()
        self.add_options(
            [Option(line(subtask)) for subtask in subtasks]
            or [Option(Text(EMPTY), disabled=True)]
        )
        if subtasks:
            self.highlighted = max(0, min(prior, len(subtasks) - 1))

    def action_edit(self) -> None:
        self._act("edit")

    def action_complete(self) -> None:
        self._act("complete")

    def action_remove(self) -> None:
        self._act("remove")

    def _act(self, action: str) -> None:
        if self.highlighted is not None and self.option_count:
            self.post_message(self.Acted(action, self.highlighted))


def line(subtask: Subtask) -> Text:
    """Text, not markup: a title is the user's own and may carry brackets Rich
    would parse."""
    done = "✓ " if subtask.done else ""
    pending = "" if subtask.row is not None else " (new)"
    return Text(f"{done}{subtask.content}{pending}")
