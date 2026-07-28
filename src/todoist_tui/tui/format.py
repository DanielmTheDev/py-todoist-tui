from todoist_tui.domain.due import Due


def format_due(due: Due | None) -> str:
    """Date as ISO, plus HH:MM when the due carries a time. Blank when unset."""
    if due is None:
        return ""
    text = due.date.isoformat()
    if due.time is not None:
        text += " " + due.time.strftime("%H:%M")
    return text
