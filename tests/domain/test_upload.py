from pathlib import Path

import pytest

from todoist_tui.domain.upload import (
    MAX_UPLOAD_BYTES,
    FileUploads,
    UploadRejected,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _png(tmp_path: Path, name: str = "shot.png") -> Path:
    path = tmp_path / name
    path.write_bytes(_PNG)
    return path


def test_a_file_is_read_with_the_name_and_type_todoist_needs(tmp_path: Path) -> None:
    upload = FileUploads().read(str(_png(tmp_path)))

    assert upload.file_name == "shot.png"
    assert upload.content_type == "image/png"
    assert upload.data == _PNG


def test_a_leading_tilde_means_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _png(tmp_path)

    assert FileUploads().read("~/shot.png").file_name == "shot.png"


def test_a_quoted_path_is_taken_as_pasted(tmp_path: Path) -> None:
    """A path dragged into the terminal arrives wrapped in quotes."""
    path = _png(tmp_path, "one two.png")

    assert FileUploads().read(f"'{path}'").file_name == "one two.png"


def test_a_path_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(UploadRejected, match="no such file"):
        FileUploads().read(str(tmp_path / "missing.png"))


def test_a_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(UploadRejected, match="not a file"):
        FileUploads().read(str(tmp_path))


def test_a_file_bigger_than_todoist_takes_is_refused_before_it_is_read(
    tmp_path: Path,
) -> None:
    fat = tmp_path / "fat.png"
    fat.write_bytes(b"0" * (MAX_UPLOAD_BYTES + 1))

    with pytest.raises(UploadRejected, match="too big"):
        FileUploads().read(str(fat))


def test_a_file_of_unknown_type_still_goes_up(tmp_path: Path) -> None:
    """Todoist takes any attachment, not only images; only the preview cares."""
    odd = tmp_path / "notes"
    odd.write_bytes(b"hello")

    assert FileUploads().read(str(odd)).content_type == "application/octet-stream"


def test_an_empty_path_is_refused() -> None:
    with pytest.raises(UploadRejected, match="no file named"):
        FileUploads().read("   ")


def test_a_file_that_cannot_be_read_is_refused_like_any_other(tmp_path: Path) -> None:
    """Permission, a vanished file, a dead mount: the reason differs, but the
    caller has one thing to report."""
    shy = _png(tmp_path, "shy.png")
    shy.chmod(0o000)

    try:
        with pytest.raises(UploadRejected, match="could not read"):
            FileUploads().read(str(shy))
    finally:
        shy.chmod(0o600)
