from pathlib import Path

import pytest

from todoist_tui.domain.attachments import NotTheFile, cache_name
from todoist_tui.domain.comment import Attachment
from todoist_tui.store.attachments import CachedAttachments

_ATTACHMENT = Attachment(
    file_name="shot.png",
    file_type="image/png",
    file_url="https://files.todoist.com/x/shot.png",
)
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class FakeSource:
    def __init__(self, data: bytes = _PNG, error: Exception | None = None) -> None:
        self._data = data
        self._error = error
        self.fetched: list[str] = []

    async def fetch(self, url: str) -> bytes:
        self.fetched.append(url)
        if self._error is not None:
            raise self._error
        return self._data


@pytest.mark.anyio
async def test_the_file_is_written_once_and_read_from_disk_after(
    tmp_path: Path,
) -> None:
    source = FakeSource()
    files = CachedAttachments(tmp_path, source)

    first = await files.local(_ATTACHMENT)
    second = await files.local(_ATTACHMENT)

    assert first == second == tmp_path / cache_name(_ATTACHMENT)
    assert first.read_bytes() == _PNG
    assert source.fetched == ["https://files.todoist.com/x/shot.png"]


@pytest.mark.anyio
async def test_a_download_that_fails_leaves_nothing_behind(tmp_path: Path) -> None:
    """A half-written file would read as a cache hit ever after."""
    files = CachedAttachments(tmp_path, FakeSource(error=NotTheFile("login page")))

    with pytest.raises(NotTheFile):
        await files.local(_ATTACHMENT)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
async def test_the_cache_directory_is_made_on_the_way(tmp_path: Path) -> None:
    files = CachedAttachments(tmp_path / "attachments", FakeSource())

    path = await files.local(_ATTACHMENT)

    assert path.is_file()
