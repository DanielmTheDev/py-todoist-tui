from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.tui.screens.description import DescriptionArea

_PROMPT = "NEW COMMENT"
_HINT = "ctrl+s post · esc leave insert, again to cancel"


class ComposeCommentScreen(ModalScreen["str | None"]):
    """Write a comment the way a description is written: vim keys, several lines
    if you want them. `ctrl+s` posts the trimmed text, escape cancels — the
    field takes the first escape to leave insert mode, as the editor's does."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "post", "Post the comment"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ComposeCommentScreen {
        align: center middle;
    }
    ComposeCommentScreen #compose-prompt, ComposeCommentScreen #compose-hint {
        width: 70%;
        max-width: 90;
        padding: 0 1;
    }
    ComposeCommentScreen #compose-hint {
        color: $text-muted;
    }
    ComposeCommentScreen DescriptionArea {
        width: 70%;
        max-width: 90;
        height: 10;
        border: round $primary;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(_PROMPT, id="compose-prompt")
        yield DescriptionArea()
        yield Static(_HINT, id="compose-hint")

    def on_mount(self) -> None:
        self.query_one(DescriptionArea).focus()

    def action_post(self) -> None:
        written = self.query_one(DescriptionArea).text.strip()
        if written:  # an empty comment is nothing to say
            self.dismiss(written)

    def action_cancel(self) -> None:
        self.dismiss(None)
