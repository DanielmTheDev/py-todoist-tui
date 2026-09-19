"""The image sitting on the X clipboard, if there is one.

`xclip` is shelled out to the way `xdg-open` is (see `links.py`): a port here, a
stdlib adapter beside it, and a fake in the tests so no selection is read.
"""

import datetime
import subprocess
from collections.abc import Callable
from typing import Protocol

from todoist_tui.domain.upload import PendingUpload, UploadRejected

_TIMEOUT_SECONDS = 5.0  # a selection owner that never answers must not hang the app
# what we can send, best first; each is (target, extension, magic bytes)
_IMAGE_TARGETS = (
    ("image/png", ".png", b"\x89PNG\r\n\x1a\n"),
    ("image/jpeg", ".jpg", b"\xff\xd8\xff"),
    ("image/webp", ".webp", b"RIFF"),
)
_NO_IMAGE = "no image on the clipboard"

type Xclip = Callable[[str], bytes]
"""Reads one clipboard target, answering its bytes (empty when it has none)."""


class Clipboard(Protocol):
    """Port to the clipboard's image. Raises `UploadRejected` when there is
    nothing to take, so a caller has one thing to report."""

    def grab(self) -> PendingUpload: ...


class XclipClipboard:
    """Reads the clipboard through `xclip`.

    The offered targets decide, never the exit code: with a clipboard manager
    holding the selection, `xclip -t image/png -o` exits 0 and prints nothing.
    The magic bytes decide again, since a target can be offered and lie.
    """

    def __init__(self, xclip: Xclip | None = None) -> None:
        self._xclip = xclip or _run_xclip

    def grab(self) -> PendingUpload:
        try:
            offered = self._xclip("TARGETS").decode(errors="replace").split()
            for target, suffix, magic in _IMAGE_TARGETS:
                if target not in offered:
                    continue
                data = self._xclip(target)
                if not data:
                    break  # offered but empty: the manager has nothing to give
                if not data.startswith(magic):
                    raise UploadRejected(f"the clipboard is not a {target[6:].upper()}")
                return PendingUpload(_named(suffix), target, data)
        except FileNotFoundError as missing:
            raise UploadRejected("xclip is not installed") from missing
        except subprocess.SubprocessError as failed:
            raise UploadRejected(f"the clipboard did not answer: {failed}") from failed
        raise UploadRejected(_NO_IMAGE)


def _named(suffix: str) -> str:
    """A clipboard image has no name, so it is given the one a screenshot would
    have: the moment it was taken."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return f"clipboard-{stamp}{suffix}"


def _run_xclip(target: str) -> bytes:
    finished = subprocess.run(
        ["xclip", "-selection", "clipboard", "-t", target, "-o"],
        capture_output=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,  # a missing target is an ordinary answer, not a failure
    )
    return finished.stdout
