"""How a comment's image reaches the screen.

`textual-image` decides what the terminal can draw **while it is being
imported**: it writes escape sequences to stdout and reads the reply from stdin,
which only works before Textual takes those over. So the app loads it up front
(see `__main__`) and hands the screen the pane factory it got; a screen built
without one falls back to naming the file, which is also what a terminal with no
graphics protocol ends up showing.
"""

import os
from collections.abc import Callable
from pathlib import Path

from textual.widget import Widget
from textual.widgets import Static

RENDERER_ENV = "TODOIST_TUI_IMAGE"
"""Names the renderer to use — `tgp`, `sixel`, `halfcell`, `unicode` — when the
terminal's own answer about what it can draw turns out to be wrong."""

PREVIEW_ROWS = 12
"""Rows a preview fills. An image widget must be told: left on `auto` height it
measures zero and draws nothing at all."""

type ImagePane = Callable[[Path, str], Widget]
"""Builds the widget that shows `path`, named `file_name` if it cannot."""


def text_pane(_path: Path, file_name: str) -> Widget:
    return Static(f"[{file_name} — no inline preview]")


def graphics_pane() -> ImagePane:
    """Load the terminal's best image renderer, falling back to naming the file.

    Call before the app starts: the import is the probe — it asks the terminal
    what it can draw over stdout and stdin, which Textual owns once it runs.
    Anything the probe throws (a missing install, a terminal that reports no
    pixel size and divides the probe by zero) costs the preview, not the app.
    `TODOIST_TUI_IMAGE` overrides the answer.
    """
    try:
        # imported here, not at module scope: the import is the probe
        from textual_image.widget import (
            AutoImage,
            HalfcellImage,
            SixelImage,
            TGPImage,
            UnicodeImage,
        )

        named = {
            "tgp": TGPImage,
            "sixel": SixelImage,
            "halfcell": HalfcellImage,
            "unicode": UnicodeImage,
        }
        chosen = named.get(os.environ.get(RENDERER_ENV, "").lower(), AutoImage)
    except Exception:  # no renderer installed, or a terminal it cannot measure
        return text_pane

    def pane(path: Path, _file_name: str) -> Widget:
        image = chosen(path)
        image.styles.height = PREVIEW_ROWS
        # the width follows from the height and the picture's own proportions;
        # filling the pane instead would stretch every screenshot
        image.styles.width = "auto"
        return image

    return pane
