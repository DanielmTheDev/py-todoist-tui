from dataclasses import dataclass
from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Static, TextArea

from todoist_tui.domain.links import attach, sole_url
from todoist_tui.tui.screens.scrolling import ScrollBody


@dataclass(frozen=True, slots=True)
class TaskText:
    content: str
    description: str


class TitleInput(Input):
    """Textual maps ctrl+backspace to delete_right_word; every other editor
    deletes the word to the left. A pasted URL is folded into the title so the
    whole title reads as the link instead of the URL eating the row."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+backspace,alt+backspace", "delete_left_word", show=False),
    ]

    class LinkPasted(Message):
        """A URL arrived with no title yet to hang it on; hold it until there is
        one."""

        def __init__(self, url: str) -> None:
            super().__init__()
            self.url = url

    def _on_paste(self, event: events.Paste) -> None:
        url = sole_url(event.text)
        if url is None:
            return  # Input's own handler, next in the MRO, inserts it verbatim
        event.prevent_default()  # only this stops that handler running too
        event.stop()
        if self.value.strip():
            self.value = attach(self.value, url)
            self.cursor_position = len(self.value)
        else:
            self.post_message(self.LinkPasted(url))


class DescriptionArea(TextArea):
    """Select-all on the same key as the title field, not only TextArea's f7."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+shift+a", "select_all", show=False),
    ]


class TaskEditScreen(ModalScreen["TaskText | None"]):
    """Edit a task's title and description together. Tab moves between the
    fields, ctrl+s (or enter in the title) dismisses both trimmed values, escape
    dismisses None. A blank title keeps the prompt open."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    TaskEditScreen { align: center middle; }
    TaskEditScreen #fields { width: 70%; max-width: 80; height: auto; }
    TaskEditScreen #heading { padding: 0 1; text-style: bold; }
    TaskEditScreen .label { padding: 0 1; }
    TaskEditScreen Input { border: round $primary; }
    TaskEditScreen TextArea { height: 8; border: round $primary; }
    TaskEditScreen #hint { padding: 0 1; color: $text-muted; }
    TaskEditScreen #link { padding: 0 1; color: $text-muted; }
    """

    def __init__(
        self, content: str, description: str, heading: str | None = None
    ) -> None:
        super().__init__()
        self._content = content
        self._description = description
        self._heading = heading
        self._pending_url: str | None = None

    def compose(self) -> ComposeResult:
        # the description box alone is taller than a short terminal
        with ScrollBody(id="fields"):
            if self._heading is not None:  # so an add does not read as an edit
                yield Static(self._heading, id="heading")
            yield Static("Title", classes="label")
            # select_on_focus would make the first keystroke wipe the title
            yield TitleInput(value=self._content.strip(), select_on_focus=False)
            yield Static("", id="link")
            yield Static("Description", classes="label")
            yield DescriptionArea(self._description.strip())
            yield Static("tab switch · ctrl+s save · esc cancel", id="hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        description = self.query_one(TextArea)
        description.move_cursor(description.document.end)  # append, don't prepend

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def on_title_input_link_pasted(self, event: TitleInput.LinkPasted) -> None:
        event.stop()
        self._pending_url = event.url  # a second paste means the first was wrong
        self.query_one("#link", Static).update(f"↳ link: {event.url}")

    def action_save(self) -> None:
        content = self.query_one(Input).value.strip()
        if not content:  # a task must keep a title: stay open
            return
        if self._pending_url is not None:
            content = attach(content, self._pending_url)
        self.dismiss(TaskText(content, self.query_one(TextArea).text.strip()))

    def action_cancel(self) -> None:
        self.dismiss(None)
