import datetime
from collections.abc import Mapping
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.message import Message
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
from todoist_tui.tui.screens.scrolling import ScrollBody, page_scrolled
from todoist_tui.tui.theme import (
    PALETTE_CLASSES,
    PALETTE_CSS,
    Tier,
    priority_styles,
    tier_styles,
)

_DASH = "—"  # stands in for an unset field
_LABEL_WIDTH = 10  # so the field values line up in a column of their own
_MIN_RULE = 8  # a rule shorter than this reads as debris, not a separator
# 1-4 set the priority, as they do in the list, so links start above them and
# run out of keys at 9. A sixth link is listed but carries no reference.
FIRST_LINK = 5
LAST_LINK = 9
CLOSE_KEYS = ("escape", "enter", "q")
HELP_KEYS = ("question_mark", "f1")  # f1 as well, since the editor needs it
# The card is a lid over the list, not a different place: a key that acts on a
# task there acts on the open task here. The card holds no repository, so it
# names the app's own action and lets the app run it. `a` is an alias — in the
# list it adds a sibling, but there is no sibling to add from inside one task.
FORWARDED: Mapping[str, str] = {
    "ctrl+e": "edit_task",
    "a": "add_subtask",
    "A": "add_subtask",
    "n": "move_parent",
    "V": "move_parent",
    "v": "move_task",
    "t": "set_due",
    "d": "set_deadline",
    "at": "set_labels",
    "m": "reminders",
    "R": "reminders",
    "e": "complete",
    "delete": "delete",
    **{str(n): f"set_priority('P{n}')" for n in range(1, 5)},
}
# What the card does that the list cannot, for `?` help — the forwarded keys are
# the list's own and are already listed there. Declared, not bound: the card
# handles keys itself so that none of them reach the app underneath it.
CARD_BINDINGS: list[BindingType] = [
    Binding(f"{FIRST_LINK}-{LAST_LINK}", "open_link", "Open link"),
    Binding("o", "open_link", "Open the first link"),
    Binding(",".join(CLOSE_KEYS), "close", "Close"),
]


class DetailCard(Static):
    """The card's body: fields, description, links, key hint. Labels recede so the
    values they name lead, and the sections are ruled apart."""

    COMPONENT_CLASSES: ClassVar[set[str]] = set(PALETTE_CLASSES)
    DEFAULT_CSS = PALETTE_CSS

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
            for number, link in enumerate(self._links, start=FIRST_LINK):
                ref = f"[{number}] " if number <= LAST_LINK else ""
                text.append(ref, style=label)
                text.append(
                    f"{link.url}\n", style=styles[Tier.ACCENT] + Style(link=link.url)
                )
        return text

    def _append_section(
        self, text: Text, heading: str, styles: Mapping[Tier, Style]
    ) -> None:
        text.append(
            f"\n{heading} {self._rule(len(heading) + 1)}\n", style=styles[Tier.MUTED]
        )

    def _rule(self, taken: int = 0) -> str:
        return "─" * max(_MIN_RULE, self.content_size.width - taken)

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
        priority = self._row.priority
        text = Text()
        if dot := priority_dot(priority):  # coloured as in the list, same language
            text.append(f"{dot} ", style=priority_styles(self)[priority])
        text.append(priority.label, style=styles[Tier.PRIMARY])
        return text

    def _project(self, styles: Mapping[Tier, Style]) -> Text:
        return Text(self._row.project_name or _DASH, style=styles[Tier.PRIMARY])

    def _section(self, styles: Mapping[Tier, Style]) -> Text:
        return Text(self._row.section_name or _DASH, style=styles[Tier.PRIMARY])

    def _labels(self, styles: Mapping[Tier, Style]) -> Text:
        return Text(
            format_labels(self._row.labels) or _DASH, style=styles[Tier.PRIMARY]
        )


class TaskDetailScreen(ModalScreen[str]):
    """Read-only card for a single task. Any of escape/enter/q closes it. Every
    key in `FORWARDED` closes it naming the app action to run on the open task.
    Links in the title/description are numbered; 5-9 or `o` open them."""

    DEFAULT_CSS = """
    TaskDetailScreen {
        align: center middle;
    }
    TaskDetailScreen ScrollBody {
        width: 70%;
        max-width: 80;
        padding: 1 2;
        border: round $primary;
    }
    TaskDetailScreen DetailCard {
        width: 100%;
        height: auto;
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
        content, content_links = annotate(row.content, FIRST_LINK, LAST_LINK)
        description, description_links = annotate(
            row.description, FIRST_LINK + len(content_links), LAST_LINK
        )
        self._content_text = content
        self._description_text = description
        self._links: list[Link] = content_links + description_links

    def compose(self) -> ComposeResult:
        # a card taller than the terminal would otherwise paint past its edge
        with ScrollBody():
            yield DetailCard(
                self._row,
                self._content_text,
                self._description_text,
                self._links,
                self._today,
            )

    class HelpRequested(Message):
        """The card was asked to name the keys it takes."""

    def on_key(self, event: events.Key) -> None:
        if page_scrolled(self, event.key):
            event.stop()
            return
        if event.key in HELP_KEYS:
            self.post_message(self.HelpRequested())  # help lays over the card
        elif event.key in CLOSE_KEYS:
            self.dismiss("")
        elif (action := FORWARDED.get(event.key)) is not None:
            self.dismiss(action)
        elif event.key == "o":
            self._open(FIRST_LINK)
        elif event.character and event.character.isdigit():
            self._open(int(event.character))
        event.stop()  # consume every key so app bindings never fire under the modal

    def _open(self, number: int) -> None:
        index = number - FIRST_LINK
        if 0 <= index < len(self._links) and number <= LAST_LINK:
            self._opener.open(self._links[index].url)
