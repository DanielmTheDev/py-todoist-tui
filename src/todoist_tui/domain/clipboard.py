"""The image on the X clipboard: taken from it, or put on it.

`xclip` is shelled out to the way `xdg-open` is (see `links.py`): a port here, a
stdlib adapter beside it, and a fake in the tests so no selection is read.
"""

import datetime
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from todoist_tui.domain.upload import MAX_UPLOAD_BYTES, PendingUpload, UploadRejected

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

type XclipIn = Callable[[str, Path], None]
"""Puts a file on the clipboard as the given target."""


class ClipboardFailed(Exception):
    """The file could not be put on the clipboard, and the reason is worth
    reading."""


class Clipboard(Protocol):
    """Port to the clipboard's image. `grab` raises `UploadRejected` when there
    is nothing to take, `copy` raises `ClipboardFailed`, so a caller has one
    thing to report either way."""

    def grab(self) -> PendingUpload: ...

    def copy(self, path: Path, content_type: str) -> None: ...


class XclipClipboard:
    """Reads the clipboard through `xclip`.

    The offered targets decide, never the exit code: with a clipboard manager
    holding the selection, `xclip -t image/png -o` exits 0 and prints nothing.
    The magic bytes decide again, since a target can be offered and lie.
    """

    def __init__(
        self, xclip: Xclip | None = None, xclip_in: XclipIn | None = None
    ) -> None:
        self._xclip = xclip or _run_xclip
        self._xclip_in = xclip_in or _run_xclip_in

    def copy(self, path: Path, content_type: str) -> None:
        try:
            self._xclip_in(content_type, path)
        except FileNotFoundError as missing:
            raise ClipboardFailed("xclip is not installed") from missing
        except (OSError, subprocess.SubprocessError) as failed:
            # a failed run's own message spells out the whole command line
            raise ClipboardFailed("the clipboard refused it") from failed

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
                if len(data) > MAX_UPLOAD_BYTES:
                    raise UploadRejected(f"too big: {len(data)} bytes")
                return PendingUpload(_named(suffix), target, data)
        except FileNotFoundError as missing:
            raise UploadRejected("xclip is not installed") from missing
        except subprocess.SubprocessError as failed:
            raise UploadRejected(f"the clipboard did not answer: {failed}") from failed
        except OSError as error:
            raise UploadRejected(f"could not read the clipboard: {error}") from error
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


def _run_xclip_in(target: str, path: Path) -> None:
    subprocess.run(
        ["xclip", "-selection", "clipboard", "-t", target, "-i", str(path)],
        # xclip stays behind to serve the selection; a pipe it inherits would
        # hold this call open until the next copy replaced it
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=_TIMEOUT_SECONDS,
        check=True,
    )
