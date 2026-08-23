_STARTUP = 2
_KEY = 5
_SIGIL = 2


def view_label(
    title: str, *, star: bool = False, key: str | None = None, sigil: str = ""
) -> str:
    """A Views-screen row as the screen builds it: three fixed-width gutter fields,
    then the title — so a test states the fields instead of counting spaces."""
    badge = "" if key is None else f"[{key}]"
    return f"{'★' if star else '':<{_STARTUP}}{badge:<{_KEY}}{sigil:<{_SIGIL}}{title}"
