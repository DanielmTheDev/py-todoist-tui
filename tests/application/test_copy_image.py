import datetime
from pathlib import Path

import pytest

from todoist_tui.application.copy_image import copy_image, newest_image
from todoist_tui.domain.comment import Attachment, Comment
from todoist_tui.domain.upload import PendingUpload

_AT = datetime.datetime(2026, 9, 18, 19, 4, tzinfo=datetime.UTC)


def _file(name: str, file_type: str = "image/png") -> Attachment:
    return Attachment(name, file_type, f"https://files.todoist.com/{name}")


def _comment(minutes: int, attachment: Attachment | None = None) -> Comment:
    return Comment(
        id=str(minutes),
        task_id="t1",
        content="",
        posted_at=_AT + datetime.timedelta(minutes=minutes),
        attachment=attachment,
    )


class FakeFiles:
    def __init__(self) -> None:
        self.asked: list[Attachment] = []

    async def local(self, attachment: Attachment) -> Path:
        self.asked.append(attachment)
        return Path(f"/cache/{attachment.file_name}")


class FakeClipboard:
    def __init__(self) -> None:
        self.copied: list[tuple[Path, str]] = []

    def grab(self) -> PendingUpload:
        raise AssertionError("this test pastes nothing")

    def copy(self, path: Path, content_type: str) -> None:
        self.copied.append((path, content_type))


@pytest.mark.anyio
async def test_copy_image_puts_the_local_copy_on_the_clipboard() -> None:
    """The file host answers a bare URL with its login page, so the bytes on
    the clipboard have to be the downloaded ones."""
    files, clipboard = FakeFiles(), FakeClipboard()
    shot = _file("shot.jpg", "image/jpeg")

    await copy_image(files, clipboard, shot)

    assert files.asked == [shot]
    assert clipboard.copied == [(Path("/cache/shot.jpg"), "image/jpeg")]


def test_newest_image_skips_text_and_other_files() -> None:
    older, newer = _file("old.png"), _file("new.png")
    thread = (
        _comment(3),
        _comment(0, older),
        _comment(2, _file("spec.pdf", "application/pdf")),
        _comment(1, newer),
    )

    assert newest_image(thread) == newer


def test_a_thread_without_an_image_has_no_newest_one() -> None:
    assert newest_image((_comment(0), _comment(1, _file("a.pdf", "x/pdf")))) is None
