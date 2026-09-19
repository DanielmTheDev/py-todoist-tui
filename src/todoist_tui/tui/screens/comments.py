import datetime
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static

from todoist_tui.domain.comment import Attachment, Comment
from todoist_tui.domain.humanize import humanize_date
from todoist_tui.tui.format import format_attachment
from todoist_tui.tui.imaging import ImagePane, text_pane
from todoist_tui.tui.screens.scrolling import ScrollBody, page_scrolled
from todoist_tui.tui.theme import PALETTE_CLASSES, PALETTE_CSS, Tier, tier_styles

_TITLE = "COMMENTS"
_CURSOR = "❯ "  # marks the comment the keys act on
_NO_CURSOR = "  "
_ATTACHMENT = "\U0001f5bc "  # frames the file a comment carries
_CLOSE_KEYS = ("escape", "q")
_HINT = "j/k move \u00b7 o open the file \u00b7 esc close"
_DOWN_KEYS = ("j", "down")
_UP_KEYS = ("k", "up")


type OpenFile = Callable[[Attachment], Awaitable[None]]
type FetchFile = Callable[[Attachment], Awaitable[Path]]


async def _nothing_to_open(attachment: Attachment) -> None:
    """Stand-in for a screen built without a way to reach the file — the tests
    that only read a thread never press `o`."""
    raise RuntimeError(f"no viewer for {attachment.file_name}")


async def _nothing_to_fetch(attachment: Attachment) -> Path:
    raise RuntimeError(f"no copy of {attachment.file_name}")


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
    CommentsScreen #comments-preview {
        width: 70%;
        max-width: 90;
        height: auto;
        max-height: 14;
        padding: 0 2;
    }
    CommentsScreen #comments-hint {
        width: 70%;
        max-width: 90;
        padding: 0 2;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        comments: tuple[Comment, ...],
        today: datetime.date,
        tz: datetime.tzinfo | None = None,
        open_file: OpenFile = _nothing_to_open,
        fetch_file: FetchFile = _nothing_to_fetch,
        image_pane: ImagePane = text_pane,
    ) -> None:
        super().__init__()
        self._comments = comments
        self._today = today
        self._tz = tz  # None means the machine's own zone
        self._open_file = open_file
        self._fetch_file = fetch_file
        self._image_pane = image_pane
        self._cursor = max(len(comments) - 1, 0)
        self._shown_image = 0  # bumped per preview, so a late one knows it is late

    def compose(self) -> ComposeResult:
        # a thread can run longer than the terminal is tall
        with ScrollBody():
            yield CommentThread(id="comments")
        # outside the scroll body, so scrolling the thread never redraws the
        # image: a graphics-protocol image is re-uploaded on every repaint
        yield Container(id="comments-preview")
        # a hint that scrolls away is a hint nobody reads
        yield Static(_HINT, id="comments-hint")

    def on_mount(self) -> None:
        self._show()
        self._preview()

    def on_key(self, event: events.Key) -> None:
        if page_scrolled(self, event.key):
            pass
        elif event.key in _CLOSE_KEYS:
            self.dismiss(None)
        elif event.key in _DOWN_KEYS:
            self._move(1)
        elif event.key in _UP_KEYS:
            self._move(-1)
        elif event.key == "o":
            self._open()
        event.stop()  # consume every key so app bindings never fire under the modal

    def _open(self) -> None:
        attachment = self._selected_attachment()
        if attachment is None:
            self._say("Nothing attached to this comment")
            return
        self._say(f"Opening {attachment.file_name}\u2026")
        self.run_worker(self._showing(attachment))

    async def _showing(self, attachment: Attachment) -> None:
        try:
            await self._open_file(attachment)
        except Exception as error:  # offline, refused, too big: say so, stay open
            self._say(f"Could not open {attachment.file_name}: {error}")
        else:
            self._say(_HINT)

    def _preview(self) -> None:
        """Draw the image the cursor rests on, and nothing else."""
        self._shown_image += 1
        self._clear_preview()
        attachment = self._selected_attachment()
        if attachment is None or not attachment.is_image:
            return
        self.run_worker(self._drawing(attachment, self._shown_image))

    async def _drawing(self, attachment: Attachment, generation: int) -> None:
        try:
            path = await self._fetch_file(attachment)
        except Exception as error:  # offline, refused, too big
            excuse = f"No preview: {error}"
            self._into_preview(lambda: Static(excuse), generation)
            return
        self._into_preview(
            lambda: self._image_pane(path, attachment.file_name), generation
        )

    def _into_preview(self, build: Callable[[], Widget], generation: int) -> None:
        """Build the pane only if it is still wanted: the cursor may have walked
        on while the file came down, and drawing an image costs the terminal a
        whole upload."""
        if generation != self._shown_image or not self.is_attached:
            return
        try:
            pane = build()
        except Exception as error:  # a file the renderer cannot read
            pane = Static(f"No preview: {error}")
        region = self.query_one("#comments-preview", Container)
        region.mount(pane)

    def _clear_preview(self) -> None:
        if self.is_attached:
            self.query_one("#comments-preview", Container).remove_children()

    def _selected_attachment(self) -> Attachment | None:
        if not self._comments:
            return None
        return self._comments[self._cursor].attachment

    def _say(self, message: str) -> None:
        # a download that lands in the tick the thread closes has no hint left
        # to write on: closing the screen is the answer, not a crash
        if self.is_attached:
            self.query_one("#comments-hint", Static).update(message)

    def _move(self, step: int) -> None:
        if not self._comments:
            return
        self._cursor = max(0, min(len(self._comments) - 1, self._cursor + step))
        self._say(_HINT)  # the last file's news belonged to the comment it named
        self._show()
        self._preview()

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
