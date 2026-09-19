import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Todoist's own cap on a free plan is 5 MB; a paid one takes 100. Refusing at
# 20 keeps a mistyped path from being sent up a slow line, and the server is
# still the one that decides.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_FALLBACK_TYPE = "application/octet-stream"
_QUOTES = "'\""


class UploadRejected(Exception):
    """The file cannot be sent, and the reason is worth reading."""


@dataclass(frozen=True, slots=True)
class PendingUpload:
    """A file read off the disk, ready for Todoist."""

    file_name: str
    content_type: str
    data: bytes


class Uploads(Protocol):
    """Port to the local files a comment can carry."""

    def read(self, path_text: str) -> PendingUpload: ...


class FileUploads:
    """Reads the file a typed path names, refusing what Todoist would not take.

    Nothing leaves the machine until the path has been resolved and the size
    checked: a wrong path should cost a message, not an upload.
    """

    def read(self, path_text: str) -> PendingUpload:
        path = _resolve(path_text)
        try:
            if not path.exists():
                raise UploadRejected(f"no such file: {path}")
            if not path.is_file():
                raise UploadRejected(f"not a file: {path}")
            size = path.stat().st_size
            if size > MAX_UPLOAD_BYTES:
                raise UploadRejected(f"too big: {size} bytes")
            data = path.read_bytes()
        except OSError as error:
            # unreadable, gone since the check, a mount that died: one report
            raise UploadRejected(f"could not read {path}: {error}") from error
        guessed, _encoding = mimetypes.guess_type(path.name)
        return PendingUpload(path.name, guessed or _FALLBACK_TYPE, data)


def _resolve(path_text: str) -> Path:
    # a path dragged into the terminal arrives quoted, and `~` is the shell's
    # job, not ours — both would otherwise read as part of the name
    stripped = path_text.strip().strip(_QUOTES).strip()
    if not stripped:
        raise UploadRejected("no file named")
    return Path(stripped).expanduser()
