import pytest

from todoist_tui.domain.clipboard import XclipClipboard
from todoist_tui.domain.upload import UploadRejected

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class _FakeXclip:
    """Stands in for the binary: what each `-t <target> -o` call answers."""

    def __init__(self, answers: dict[str, bytes], missing: bool = False) -> None:
        self._answers = answers
        self._missing = missing
        self.calls: list[str] = []

    def __call__(self, target: str) -> bytes:
        self.calls.append(target)
        if self._missing:
            raise FileNotFoundError("xclip")
        return self._answers.get(target, b"")


def test_a_png_on_the_clipboard_becomes_an_upload() -> None:
    xclip = _FakeXclip({"TARGETS": b"TIMESTAMP\nimage/png\n", "image/png": _PNG})

    upload = XclipClipboard(xclip).grab()

    assert upload.content_type == "image/png"
    assert upload.data == _PNG
    assert upload.file_name.endswith(".png")
    assert xclip.calls == ["TARGETS", "image/png"]


def test_a_jpeg_is_taken_when_that_is_what_is_offered() -> None:
    jpeg = b"\xff\xd8\xff" + b"0" * 16
    xclip = _FakeXclip({"TARGETS": b"image/jpeg\n", "image/jpeg": jpeg})

    upload = XclipClipboard(xclip).grab()

    assert upload.content_type == "image/jpeg"
    assert upload.file_name.endswith(".jpg")


def test_text_on_the_clipboard_is_not_an_image() -> None:
    xclip = _FakeXclip({"TARGETS": b"UTF8_STRING\ntext/plain\n"})

    with pytest.raises(UploadRejected, match="no image on the clipboard"):
        XclipClipboard(xclip).grab()


def test_an_offered_image_that_arrives_empty_is_refused() -> None:
    """With CopyQ holding the selection, xclip exits 0 and prints nothing, so
    the exit code says nothing — the bytes have to."""
    xclip = _FakeXclip({"TARGETS": b"image/png\n", "image/png": b""})

    with pytest.raises(UploadRejected, match="no image on the clipboard"):
        XclipClipboard(xclip).grab()


def test_something_that_is_not_the_image_it_claims_is_refused() -> None:
    xclip = _FakeXclip({"TARGETS": b"image/png\n", "image/png": b"<html>nope"})

    with pytest.raises(UploadRejected, match="not a PNG"):
        XclipClipboard(xclip).grab()


def test_a_missing_xclip_says_so_rather_than_crashing() -> None:
    xclip = _FakeXclip({}, missing=True)

    with pytest.raises(UploadRejected, match="xclip"):
        XclipClipboard(xclip).grab()
