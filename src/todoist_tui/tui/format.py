import datetime

from rich.text import Text

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.humanize import humanize_date
from todoist_tui.domain.links import parse

_LINK_STYLE = "underline #89ddff"  # cyan; readable on the dark and blue-selection rows


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
