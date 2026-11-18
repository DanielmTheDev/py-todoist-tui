import subprocess
from pathlib import Path

import pytest

from todoist_tui.domain.clipboard import ClipboardFailed, XclipClipboard
from todoist_tui.domain.upload import MAX_UPLOAD_BYTES, UploadRejected

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


def test_an_image_over_the_upload_cap_is_refused_before_it_is_queued() -> None:
    huge = _PNG + b"0" * MAX_UPLOAD_BYTES
    xclip = _FakeXclip({"TARGETS": b"image/png\n", "image/png": huge})

    with pytest.raises(UploadRejected, match="too big"):
        XclipClipboard(xclip).grab()


def test_an_xclip_that_cannot_run_is_reported_not_raised() -> None:
    def denied(target: str) -> bytes:
        raise PermissionError("xclip")

    with pytest.raises(UploadRejected, match="could not read the clipboard"):
        XclipClipboard(denied).grab()


def test_copy_hands_the_file_to_xclip_under_its_type(tmp_path: Path) -> None:
    shot = tmp_path / "shot.png"
    written: list[tuple[str, Path]] = []

    XclipClipboard(
        _FakeXclip({}), lambda target, path: written.append((target, path))
    ).copy(shot, "image/png")

    assert written == [("image/png", shot)]


def test_copy_runs_xclip_detached_from_this_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """xclip stays behind to serve the selection; output pipes it inherited
    would hold the call open until the next copy."""
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(argv: list[str], **kwargs: object) -> None:
        calls.append((argv, kwargs))

    monkeypatch.setattr(subprocess, "run", run)
    XclipClipboard().copy(tmp_path / "a.png", "image/png")

    ((argv, kwargs),) = calls
    assert argv == [
        "xclip",
        "-selection",
        "clipboard",
        "-t",
        "image/png",
        "-i",
        str(tmp_path / "a.png"),
    ]
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL


@pytest.mark.parametrize(
    ("error", "said"),
    [
        (FileNotFoundError("xclip"), "xclip is not installed"),
        (subprocess.CalledProcessError(1, ["xclip"]), "the clipboard refused it"),
        (subprocess.TimeoutExpired(["xclip"], 5), "the clipboard refused it"),
    ],
)
def test_a_copy_that_fails_says_so_in_plain_words(
    error: Exception, said: str, tmp_path: Path
) -> None:
    def failing(target: str, path: Path) -> None:
        raise error

    with pytest.raises(ClipboardFailed, match=said):
        XclipClipboard(_FakeXclip({}), failing).copy(tmp_path / "a.png", "image/png")
