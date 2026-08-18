from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import OptionList

_PAGE = 10  # lines a page key moves, as in the help overlay


def fit_to_terminal(body: Widget, share: float) -> None:
    """Cap a modal's body to its share of the terminal *and* to whatever its
    siblings leave: a percentage cap is measured against the screen alone, so a
    filter box above the body pushes the body's tail off a short terminal."""
    height = body.screen.size.height
    others = sum(w.outer_size.height for w in body.siblings)
    body.styles.max_height = max(1, min(int(height * share), height - others))


class ScrollBody(VerticalScroll):
    """A modal's content, capped to the terminal and paged with pageup/pagedown.

    Not focusable: these overlays read every key themselves, and the ones with a
    cursor of their own already answer to the arrows.
    """

    can_focus = False
    SHARE = 0.8  # of the terminal, leaving the overlay a margin to sit in

    DEFAULT_CSS = """
    ScrollBody {
        height: auto;
    }
    """

    def on_resize(self) -> None:
        fit_to_terminal(self, self.SHARE)


class PickList(OptionList):
    """A picker's rows, capped the same way: the filter box and the hint beside
    them cost rows a percentage cap never sees."""

    SHARE = 0.6  # of the terminal: the pickers leave more room than the overlays

    DEFAULT_CSS = """
    PickList {
        height: auto;
    }
    """

    def on_resize(self) -> None:
        fit_to_terminal(self, self.SHARE)


def page_scrolled(screen: Widget, key: str) -> bool:
    """Page the screen's body, reporting whether `key` was a page key at all —
    the overlays consume every key, so each has to answer for these itself."""
    step = {"pageup": -_PAGE, "pagedown": _PAGE}.get(key)
    if step is None:
        return False
    screen.query_one(ScrollBody).scroll_relative(y=step, animate=False)
    return True
