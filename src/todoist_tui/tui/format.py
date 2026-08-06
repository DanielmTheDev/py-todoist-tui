import datetime

from rich.text import Text

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.humanize import humanize_date
from todoist_tui.domain.links import parse
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reminder import Reminder

_LINK_STYLE = "underline #89ddff"  # cyan; readable on the dark and blue-selection rows
MATCH_STYLE = "#89ddff"  # the same accent, undecorated: points at what matched
_PRIORITY_DOTS = {Priority.P1: "🔴", Priority.P2: "🟠", Priority.P3: "🔵"}
_ELLIPSIS = "…"


def priority_dot(priority: Priority) -> str:
    """Coloured dot for the priority; blank for P4, which needs no marking."""
    return _PRIORITY_DOTS.get(priority, "")


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
    return format_due(reminder.due, today) or "absolute"


def format_reminder_badge(count: int) -> str:
    """Bell marking a task that has reminders; counted only when there's more
    than one, so the common single reminder stays a bare glyph."""
    return "🔔" if count == 1 else f"🔔{count}"


def styled_date(label: str, d: datetime.date, today: datetime.date) -> Text:
    """`label` red when `d` is overdue (before `today`), else dim so dates
    recede behind the task title.

    Overdue is date-granular: the clock exposes only `today()`, so a timed task
    earlier today is not flagged."""
    return Text(label, style="red" if d < today else "dim")


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
