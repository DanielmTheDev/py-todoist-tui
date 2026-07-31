from rich.text import Text

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.links import parse

_LINK_STYLE = "underline #89ddff"  # cyan; readable on the dark and blue-selection rows


def format_due(due: Due | None) -> str:
    """Date as ISO, plus HH:MM when the due carries a time. Blank when unset."""
    if due is None:
        return ""
    text = due.date.isoformat()
    if due.time is not None:
        text += " " + due.time.strftime("%H:%M")
    return text


def format_deadline(deadline: Deadline | None) -> str:
    """Deadline date as ISO. Blank when unset."""
    return deadline.date.isoformat() if deadline is not None else ""


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
