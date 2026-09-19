import datetime
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from todoist_tui.domain.comment import Comment
from todoist_tui.domain.humanize import humanize_date
from todoist_tui.tui.format import format_attachment
from todoist_tui.tui.screens.scrolling import ScrollBody, page_scrolled
from todoist_tui.tui.theme import PALETTE_CLASSES, PALETTE_CSS, Tier, tier_styles

_TITLE = "COMMENTS"
_CURSOR = "❯ "  # marks the comment the keys act on
_NO_CURSOR = "  "
_ATTACHMENT = "\U0001f5bc "  # frames the file a comment carries
_CLOSE_KEYS = ("escape", "q")
_DOWN_KEYS = ("j", "down")
_UP_KEYS = ("k", "up")


class CommentThread(Static):
    """The rendered thread. Palette-aware, so its tiers resolve where it sits."""

    COMPONENT_CLASSES: ClassVar[set[str]] = set(PALETTE_CLASSES)
    DEFAULT_CSS = PALETTE_CSS


class CommentsScreen(ModalScreen[str | None]):
    """One task's comments, oldest first, with the newest under the cursor —
    that is the one you came to read. Read-only for now: `j`/`k` walk the
    thread, escape or `q` closes it."""

    DEFAULT_CSS = """
    CommentsScreen {
        align: center middle;
    }
    CommentsScreen ScrollBody {
        width: 70%;
        max-width: 90;
        padding: 1 2;
        border: round $primary;
    }
    CommentsScreen CommentThread {
        width: 100%;
        height: auto;
    }
    """

    def __init__(
        self,
        comments: tuple[Comment, ...],
        today: datetime.date,
        tz: datetime.tzinfo | None = None,
    ) -> None:
        super().__init__()
        self._comments = comments
        self._today = today
        self._tz = tz  # None means the machine's own zone
        self._cursor = max(len(comments) - 1, 0)

    def compose(self) -> ComposeResult:
        # a thread can run longer than the terminal is tall
        with ScrollBody():
            yield CommentThread(id="comments")

    def on_mount(self) -> None:
        self._show()

    def on_key(self, event: events.Key) -> None:
        if page_scrolled(self, event.key):
            pass
        elif event.key in _CLOSE_KEYS:
            self.dismiss(None)
        elif event.key in _DOWN_KEYS:
            self._move(1)
        elif event.key in _UP_KEYS:
            self._move(-1)
        event.stop()  # consume every key so app bindings never fire under the modal

    def _move(self, step: int) -> None:
        if not self._comments:
            return
        self._cursor = max(0, min(len(self._comments) - 1, self._cursor + step))
        self._show()

    def _show(self) -> None:
        self.query_one("#comments", CommentThread).update(self._content())

    def _content(self) -> Text:
        thread = self.query_one("#comments", CommentThread)
        styles = tier_styles(thread)
        text = Text()
        text.append(f"{_TITLE}\n\n", style=styles[Tier.PRIMARY] + Style(bold=True))
        if not self._comments:
            text.append("No comments", style=styles[Tier.MUTED])
            return text
        day: datetime.date | None = None
        for index, comment in enumerate(self._comments):
            at = comment.posted_at.astimezone(self._tz)
            if at.date() != day:
                if day is not None:  # a blank line between days, none above the first
                    text.append("\n")
                day = at.date()
                text.append(
                    f"{humanize_date(day, self._today)}\n", style=styles[Tier.ACCENT]
                )
            selected = index == self._cursor
            text.append(
                _CURSOR if selected else _NO_CURSOR,
                style=styles[Tier.ACCENT],
            )
            text.append(f"{at:%H:%M}  ", style=styles[Tier.SECONDARY])
            body = comment.content or "(no text)"
            text.append(f"{body}\n", style=styles[Tier.PRIMARY])
            if comment.attachment is not None:
                text.append(_NO_CURSOR + "       ", style=styles[Tier.MUTED])
                text.append(
                    f"{_ATTACHMENT}{format_attachment(comment.attachment)}\n",
                    style=styles[Tier.MUTED],
                )
        return text
