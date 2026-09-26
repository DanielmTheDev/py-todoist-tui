import datetime

from rich.text import Text

from todoist_tui.domain.comment import Attachment
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.humanize import humanize_date
from todoist_tui.domain.links import parse
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reminder import Reminder
from todoist_tui.tui.theme import ACCENT, Tier

_LINK_STYLE = f"underline {ACCENT}"
MATCH_STYLE = ACCENT  # undecorated accent: points at what matched
_PRIORITY_DOT = "●"
_ELLIPSIS = "…"
_DESCRIPTION_GLYPH = " ≡"
_COMMENT_GLYPH = " ❞"


def priority_dot(priority: Priority) -> str:
    """Dot marking the priority; blank for P4, which needs no marking. The colour
    is the caller's (see `theme.priority_styles`) so the palette owns it, and the
    glyph is single-width so it costs one cell whatever the priority."""
    return "" if priority is Priority.P4 else _PRIORITY_DOT


def highlight_match(text: str, span: tuple[int, int] | None) -> Text:
    """`text` with the matched run accented, so a hit is visible at a glance."""
    result = Text(text)
    if span is not None:
        result.stylize(MATCH_STYLE, *span)
    return result


def match_snippet(text: str, span: tuple[int, int], width: int) -> Text:
    """A one-line window of `text` around the match, accented and elided.

    Lets a row whose title doesn't contain the term still show why it matched.
    """
    flat = text.replace("\n", " ")
    if len(flat) <= width:
        return highlight_match(flat, span)
    start, end = span
    margin = max(0, (width - (end - start)) // 2)
    left = min(max(0, start - margin), max(0, len(flat) - width))
    window = flat[left : left + width]
    shifted = (start - left, end - left)
    prefix = _ELLIPSIS if left > 0 else ""
    suffix = _ELLIPSIS if left + width < len(flat) else ""
    snippet = highlight_match(window, shifted)
    return Text.assemble(prefix, snippet, suffix)


def format_due(due: Due | None, today: datetime.date) -> str:
    """Relative label for the due date, plus HH:MM when it carries a time.
    Blank when unset."""
    if due is None:
        return ""
    text = humanize_date(due.date, today)
    if due.time is not None:
        text += " " + due.time.strftime("%H:%M")
    return text


def format_deadline(deadline: Deadline | None, today: datetime.date) -> str:
    """Relative label for the deadline date. Blank when unset."""
    return humanize_date(deadline.date, today) if deadline is not None else ""


def format_reminder(reminder: Reminder, today: datetime.date) -> str:
    """Short human label for one reminder."""
    if reminder.type == "relative":
        offset = reminder.minute_offset or 0
        return "at due time" if offset == 0 else f"{offset} min before"
    due = reminder.due
    if isinstance(due, DueText):
        return due.text
    if due is not None and due.is_recurring and due.string:
        return due.string
    return format_due(due, today) or "absolute"


def format_reminder_badge(count: int) -> str:
    """Mark for a task that has reminders; counted only when there's more than
    one, so the common single reminder stays a bare glyph."""
    return "•" if count == 1 else f"•{count}"


def description_marker(description: str) -> str:
    """Mark a task that carries a description; presence only, since the list has
    no room for the note itself. Blank-only text doesn't count as one."""
    return _DESCRIPTION_GLYPH if description.strip() else ""


def format_size(size: int) -> str:
    """A file size a person can read at a glance: one decimal from KB up."""
    if size < 1024:
        return f"{size} B"
    kilobytes = size / 1024
    if kilobytes < 1024:
        return f"{kilobytes:.1f} KB"
    return f"{kilobytes / 1024:.1f} MB"


def format_attachment(attachment: Attachment) -> str:
    """The one line that names a comment's file: what it is, how big, how wide."""
    parts = [attachment.file_name]
    if attachment.file_size:
        parts.append(format_size(attachment.file_size))
    if attachment.image_width and attachment.image_height:
        parts.append(f"{attachment.image_width}×{attachment.image_height}")
    return " · ".join(parts)


def comment_marker(count: int) -> str:
    """Mark a task that carries comments, counted only past the first — as the
    reminder badge does, so the common single comment stays a bare glyph."""
    if count <= 0:
        return ""
    return _COMMENT_GLYPH if count == 1 else f"{_COMMENT_GLYPH}{count}"


def date_tier(d: datetime.date, today: datetime.date) -> Tier:
    """How much a date should stand out: overdue shouts, today reads, later
    recedes behind the task title.

    Overdue is date-granular: the clock exposes only `today()`, so a timed task
    earlier today is not flagged."""
    if d < today:
        return Tier.OVERDUE
    return Tier.SECONDARY if d == today else Tier.MUTED


def due_tier(due: Due, today: datetime.date) -> Tier:
    """`date_tier`, but a clock time today earns the accent — that's the one due
    the eye should be pulled to. Overdue still outranks it."""
    tier = date_tier(due.date, today)
    if tier is Tier.SECONDARY and due.time is not None:
        return Tier.ACCENT
    return tier


def format_labels(labels: tuple[str, ...]) -> str:
    """`@`-prefixed label names joined by spaces; blank when none."""
    return " ".join(f"@{label}" for label in labels)


def render_links(text: str) -> Text:
    """Task text with links shown as their label (markdown) or full URL (bare),
    coloured/underlined and click-openable; the raw markdown syntax is hidden."""
    result = Text()
    for before, link, trailing in parse(text):
        result.append(before)
        if link is None:
            continue
        result.append(link.label, style=f"{_LINK_STYLE} link {link.url}")
        result.append(trailing)
    return result
