import hashlib
from pathlib import Path
from typing import Protocol

from todoist_tui.domain.comment import Attachment

# Big enough for any screenshot, small enough that a mistyped URL cannot fill
# the disk. Todoist's own free-plan upload cap is 5 MB; a comment may still
# carry a file from a bigger plan.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

# Suffixes worth keeping on the cached copy: the viewer picks its program by
# them, and anything else is not ours to vouch for.
_KNOWN_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".pdf", ".txt"}
)
_UNKNOWN_SUFFIX = ".bin"


class AttachmentTooLarge(Exception):
    """The file is past `MAX_ATTACHMENT_BYTES`; it is not worth a terminal."""


class NotTheFile(Exception):
    """The server answered with something other than the file — Todoist serves a
    login page, with a 200, to a request that forgot its token."""


def cache_name(attachment: Attachment) -> str:
    """The file name a cached copy takes: the URL's digest plus a suffix.

    Addressed by URL because Todoist gives an attachment no id of its own, and
    every second screenshot is called `Screenshot.png`. The suffix is taken from
    the file name only when it is one we recognise, so a name like `../.bashrc`
    can neither escape the directory nor name what it is not.
    """
    digest = hashlib.sha256(attachment.file_url.encode()).hexdigest()[:32]
    suffix = Path(attachment.file_name).suffix.lower()
    if suffix not in _KNOWN_SUFFIXES:
        suffix = _UNKNOWN_SUFFIX
    return f"{digest}{suffix}"


class AttachmentSource(Protocol):
    """Port to the server holding the file. Raises `AttachmentTooLarge` or
    `NotTheFile` rather than answering with something unusable."""

    async def fetch(self, url: str) -> bytes: ...


class AttachmentFiles(Protocol):
    """Port to the local copies of attachments: fetched once, kept on disk."""

    async def local(self, attachment: Attachment) -> Path: ...
