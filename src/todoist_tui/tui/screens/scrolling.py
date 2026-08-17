from textual.containers import VerticalScroll
from textual.widget import Widget

_PAGE = 10  # lines a page key moves, as in the help overlay


class ScrollBody(VerticalScroll):
    """A modal's content, capped to the terminal and paged with pageup/pagedown.

    Not focusable: these overlays read every key themselves, and the ones with a
    cursor of their own already answer to the arrows.
    """

    can_focus = False

    DEFAULT_CSS = """
    ScrollBody {
        height: auto;
        max-height: 80%;
    }
    """


def page_scrolled(screen: Widget, key: str) -> bool:
    """Page the screen's body, reporting whether `key` was a page key at all —
    the overlays consume every key, so each has to answer for these itself."""
    step = {"pageup": -_PAGE, "pagedown": _PAGE}.get(key)
    if step is None:
        return False
    screen.query_one(ScrollBody).scroll_relative(y=step, animate=False)
    return True
