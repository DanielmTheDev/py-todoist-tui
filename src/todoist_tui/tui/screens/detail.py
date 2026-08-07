import datetime
from collections.abc import Mapping
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.links import Link, LinkOpener, XdgOpenLinkOpener, annotate
from todoist_tui.tui.format import (
    date_tier,
    format_deadline,
    format_due,
    format_labels,
    format_reminder,
    priority_dot,
)
from todoist_tui.tui.theme import TIER_CLASSES, TIER_CSS, Tier, tier_styles

_DASH = "—"  # stands in for an unset field
_LABEL_WIDTH = 10  # so the field values line up in a column of their own
_MIN_RULE = 8  # a rule shorter than this reads as debris, not a separator


class DetailCard(Static):
    """The card's body: fields, description, links, key hint. Labels recede so the
    values they name lead, and the sections are ruled apart."""

    COMPONENT_CLASSES: ClassVar[set[str]] = set(TIER_CLASSES)
    DEFAULT_CSS = TIER_CSS

    def __init__(
        self,
        row: TaskRow,
        title: str,
        description: str,
        links: list[Link],
        today: datetime.date,
    ) -> None:
        super().__init__(id="detail", markup=False)
        self._row = row
        self._title = title
        self._description = description
        self._links = links
        self._today = today

    def render(self) -> Text:
        return self._content()  # rebuilt per paint, so the rules follow the width

    def _content(self) -> Text:
        styles = tier_styles(self)
        label, value = styles[Tier.MUTED], styles[Tier.PRIMARY]
        text = Text(f"{self._title}\n\n", style=value + Style(bold=True))
        for name, render in (
            ("Due", self._due),
            ("Deadline", self._deadline),
            ("Reminders", self._reminders),
            ("Priority", self._priority),
            ("Project", self._project),
            ("Section", self._section),
            ("Labels", self._labels),
        ):
            text.append(name.ljust(_LABEL_WIDTH), style=label)
            text.append_text(render(styles))
            text.append("\n")
        self._append_section(text, "DESCRIPTION", styles)
        if self._row.description:
            text.append(self._description, style=value)
        else:
            text.append("No description", style=label)
        if self._links:
            self._append_section(text, "LINKS", styles)
            for number, link in enumerate(self._links, start=1):
                text.append(f"[{number}] ", style=label)
                text.append(
                    f"{link.url}\n", style=styles[Tier.ACCENT] + Style(link=link.url)
                )
        text.append(f"\n{self._rule()}\n", style=label)
        text.append(self._hint(), style=label)
        return text

    def _append_section(
        self, text: Text, heading: str, styles: Mapping[Tier, Style]
    ) -> None:
        text.append(
            f"\n{heading} {self._rule(len(heading) + 1)}\n", style=styles[Tier.MUTED]
        )

    def _rule(self, taken: int = 0) -> str:
        return "─" * max(_MIN_RULE, self.content_size.width - taken)

    def _hint(self) -> str:
        links = "1-9 open link  o open  " if self._links else ""
        return f"{links}ctrl+e edit  esc close"

    def _due(self, styles: Mapping[Tier, Style]) -> Text:
        due = self._row.due
        if due is None:
            return Text(_DASH, style=styles[Tier.PRIMARY])
        label = format_due(due, self._today)
        text = Text(label, style=styles[date_tier(due.date, self._today)])
        if due.string:  # recurring: show the rule alongside the next date
            text.append(f" ({due.string})", style=styles[Tier.MUTED])
        return text

    def _deadline(self, styles: Mapping[Tier, Style]) -> Text:
        deadline = self._row.deadline
        if deadline is None:
            return Text(_DASH, style=styles[Tier.PRIMARY])
        label = format_deadline(deadline, self._today)
        return Text(label, style=styles[date_tier(deadline.date, self._today)])

    def _reminders(self, styles: Mapping[Tier, Style]) -> Text:
        joined = ", ".join(format_reminder(r, self._today) for r in self._row.reminders)
        return Text(joined or _DASH, style=styles[Tier.PRIMARY])

    def _priority(self, styles: Mapping[Tier, Style]) -> Text:
        dot = priority_dot(self._row.priority)
        lead = f"{dot} " if dot else ""
        return Text(f"{lead}{self._row.priority.label}", style=styles[Tier.PRIMARY])

    def _project(self, styles: Mapping[Tier, Style]) -> Text:
        return Text(self._row.project_name or _DASH, style=styles[Tier.PRIMARY])

    def _section(self, styles: Mapping[Tier, Style]) -> Text:
        return Text(self._row.section_name or _DASH, style=styles[Tier.PRIMARY])

    def _labels(self, styles: Mapping[Tier, Style]) -> Text:
        return Text(
            format_labels(self._row.labels) or _DASH, style=styles[Tier.PRIMARY]
        )


class TaskDetailScreen(ModalScreen[bool]):
    """Read-only card for a single task. Any of escape/enter/q closes it; ctrl+e
    closes it asking the app to open the editor (dismisses True).
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
        yield DetailCard(
            self._row,
            self._content_text,
            self._description_text,
            self._links,
            self._today,
        )

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "enter", "q"):
            self.dismiss(False)
        elif event.key == "ctrl+e":
            self.dismiss(True)
        elif event.key == "o":
            self._open(1)
        elif event.character and event.character.isdigit():
            self._open(int(event.character))
        event.stop()  # consume every key so app bindings never fire under the modal

    def _open(self, number: int) -> None:
        if 1 <= number <= len(self._links):
            self._opener.open(self._links[number - 1].url)
