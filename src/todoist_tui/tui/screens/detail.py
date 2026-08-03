import datetime

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.links import Link, LinkOpener, XdgOpenLinkOpener, annotate
from todoist_tui.tui.format import (
    format_deadline,
    format_due,
    format_labels,
    styled_date,
)

_DASH = "—"  # stands in for an unset field


class TaskDetailScreen(ModalScreen[None]):
    """Read-only card for a single task. Any of escape/enter/q closes it.
    Links in the title/description are numbered; 1-9 or `o` open them."""

    DEFAULT_CSS = """
    TaskDetailScreen {
        align: center middle;
    }
    TaskDetailScreen Static {
        width: 70%;
        max-width: 80;
        height: auto;
        padding: 1 2;
        border: round $primary;
    }
    """

    def __init__(
        self,
        row: TaskRow,
        opener: LinkOpener | None = None,
        today: datetime.date | None = None,
    ) -> None:
        super().__init__()
        self._row = row
        self._opener = opener or XdgOpenLinkOpener()
        self._today = today or datetime.date.today()
        content, content_links = annotate(row.content, 1)
        description, description_links = annotate(
            row.description, len(content_links) + 1
        )
        self._content_text = content
        self._description_text = description
        self._links: list[Link] = content_links + description_links

    def compose(self) -> ComposeResult:
        yield Static(self._content(), id="detail")

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "enter", "q"):
            self.dismiss()
        elif event.key == "o":
            self._open(1)
        elif event.character and event.character.isdigit():
            self._open(int(event.character))
        event.stop()  # consume every key so app bindings never fire under the modal

    def _open(self, number: int) -> None:
        if 1 <= number <= len(self._links):
            self._opener.open(self._links[number - 1].url)

    def _content(self) -> Text:
        row = self._row
        text = Text()
        text.append(f"{self._content_text}\n\n", style="bold")
        text.append("Due       ")
        self._append_due(text)
        text.append("\nDeadline  ")
        self._append_deadline(text)
        text.append(f"\nPriority  {row.priority.label}\n")
        text.append(f"Project   {row.project_name or _DASH}\n")
        text.append(f"Section   {row.section_name or _DASH}\n")
        text.append(f"Labels    {self._labels_line()}\n\n")
        text.append("Description\n", style="bold")
        if row.description:
            text.append(self._description_text)
        else:
            text.append("No description", style="dim")
        if self._links:
            text.append("\n\nLinks\n", style="bold")
            for number, link in enumerate(self._links, start=1):
                text.append(f"[{number}] ")
                text.append(f"{link.url}\n", style=f"link {link.url}")
        hint = "1-9 open link  o open  esc close" if self._links else "esc close"
        text.append(f"\n{hint}", style="dim")
        return text

    def _append_due(self, text: Text) -> None:
        due = self._row.due
        if due is None:
            text.append(_DASH)
            return
        text.append_text(
            styled_date(format_due(due, self._today), due.date, self._today)
        )
        if due.string:  # recurring: show the rule alongside the next date
            text.append(f" ({due.string})")

    def _append_deadline(self, text: Text) -> None:
        deadline = self._row.deadline
        if deadline is None:
            text.append(_DASH)
            return
        label = format_deadline(deadline, self._today)
        text.append_text(styled_date(label, deadline.date, self._today))

    def _labels_line(self) -> str:
        return format_labels(self._row.labels) or _DASH
