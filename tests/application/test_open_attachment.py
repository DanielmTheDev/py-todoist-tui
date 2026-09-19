from pathlib import Path

import pytest

from todoist_tui.application.open_attachment import open_attachment
from todoist_tui.domain.comment import Attachment

_ATTACHMENT = Attachment(
    file_name="shot.png",
    file_type="image/png",
    file_url="https://files.todoist.com/x/shot.png",
)


class FakeFiles:
    def __init__(self, path: Path) -> None:
        self._path = path
        self.asked: list[Attachment] = []

    async def local(self, attachment: Attachment) -> Path:
        self.asked.append(attachment)
        return self._path


class FakeOpener:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open(self, url: str) -> None:
        self.opened.append(url)


@pytest.mark.anyio
async def test_the_viewer_is_handed_the_local_copy_not_the_url() -> None:
    """The URL itself would show Todoist's login page in a browser; the file on
    disk is the thing the user asked to see."""
    files = FakeFiles(Path("/cache/abc.png"))
    opener = FakeOpener()

    await open_attachment(files, opener, _ATTACHMENT)

    assert files.asked == [_ATTACHMENT]
    assert opener.opened == ["/cache/abc.png"]
