import asyncio
import datetime
from pathlib import Path

import pytest
from textual.app import App
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import WorkerState

from todoist_tui.domain.comment import Attachment, Comment
from todoist_tui.tui.imaging import text_pane
from todoist_tui.tui.screens.comments import (
    CommentRequest,
    CommentsScreen,
    OpenFile,
)

_TODAY = datetime.date(2026, 9, 18)
_AT = datetime.datetime(2026, 9, 18, 19, 4, tzinfo=datetime.UTC)

_PLAIN = Comment(id="c1", task_id="t1", content="looks good", posted_at=_AT)
_WITH_IMAGE = Comment(
    id="c2",
    task_id="t1",
    content="the shot",
    posted_at=_AT + datetime.timedelta(hours=1),
    attachment=Attachment(
        file_name="shot.png",
        file_type="image/png",
        file_url="https://files.todoist.com/x/shot.png",
        file_size=2048,
        image_width=1200,
        image_height=800,
    ),
)


async def _no_viewer(attachment: Attachment) -> None:
    raise AssertionError(f"this test should not open {attachment.file_name}")


async def _no_copy(attachment: Attachment) -> Path:
    raise AssertionError(f"this test should not fetch {attachment.file_name}")


class _Opener:
    """Stands in for the download-and-show flow the app injects."""

    def __init__(self, error: Exception | None = None) -> None:
        self.opened: list[Attachment] = []
        self._error = error

    async def __call__(self, attachment: Attachment) -> None:
        self.opened.append(attachment)
        if self._error is not None:
            raise self._error


def _text_of(widget: Widget) -> str:
    """Whatever the region ended up holding: its own text, or its child's."""
    if isinstance(widget, Static):
        return str(widget.content)
    return " ".join(str(child.content) for child in widget.query(Static))


class _Files:
    """Stands in for the fetch-and-cache flow; `hold` keeps one in flight."""

    def __init__(self, error: Exception | None = None) -> None:
        self.asked: list[Attachment] = []
        self.hold: asyncio.Event | None = None
        self._error = error

    async def __call__(self, attachment: Attachment) -> Path:
        self.asked.append(attachment)
        if self.hold is not None:
            await self.hold.wait()
        if self._error is not None:
            raise self._error
        return Path(f"/cache/{attachment.file_name}")


class _Panes:
    """Records what the screen asked to draw, instead of drawing it."""

    def __init__(self) -> None:
        self.drawn: list[Path] = []

    def __call__(self, path: Path, file_name: str) -> Widget:
        self.drawn.append(path)
        return Static(f"<image {file_name}>", id="drawn")


class _Host(App[None]):
    def __init__(
        self,
        comments: tuple[Comment, ...],
        opener: OpenFile | None = None,
        files: _Files | None = None,
        panes: _Panes | None = None,
    ) -> None:
        super().__init__()
        self._comments = comments
        self._opener = opener
        self._files = files
        self._panes = panes
        self.result: CommentRequest | None | str = "unset"

    def on_mount(self) -> None:
        self.push_screen(
            CommentsScreen(
                self._comments,
                _TODAY,
                datetime.UTC,
                open_file=self._opener or _no_viewer,
                fetch_file=self._files or _no_copy,
                image_pane=self._panes or text_pane,
            ),
            self._taken,
        )

    def _taken(self, result: CommentRequest | None) -> None:
        self.result = result


async def _shown(
    comments: tuple[Comment, ...],
    *keys: str,
    opener: OpenFile | None = None,
    files: _Files | None = None,
    panes: _Panes | None = None,
) -> tuple[str, _Host]:
    host = _Host(comments, opener, files, panes)
    async with host.run_test() as pilot:
        await pilot.pause()
        for key in keys:
            await pilot.press(key)
        await pilot.pause()
        found = host.screen.query("#comments")
        text = str(found.only_one(Static).content) if found else ""
        for extra in ("#comments-hint", "#comments-preview"):
            found = host.screen.query(extra)
            if found:
                text += "\n" + _text_of(found.first())
    return text, host


@pytest.mark.anyio
async def test_a_thread_lists_every_comment_with_its_time() -> None:
    text, _ = await _shown((_PLAIN, _WITH_IMAGE))

    assert "looks good" in text
    assert "the shot" in text
    assert "19:04" in text


@pytest.mark.anyio
async def test_an_attachment_is_named_sized_and_measured() -> None:
    text, _ = await _shown((_WITH_IMAGE,))

    assert "shot.png" in text
    assert "2.0 KB" in text
    assert "1200×800" in text


@pytest.mark.anyio
async def test_an_empty_thread_says_so() -> None:
    text, _ = await _shown(())

    assert "No comments" in text


@pytest.mark.anyio
async def test_the_cursor_starts_on_the_newest_and_walks_back() -> None:
    """The newest comment is the one you came to read, so it is where the cursor
    rests; `k` walks back through the thread."""
    at_newest, _ = await _shown((_PLAIN, _WITH_IMAGE))
    at_oldest, _ = await _shown((_PLAIN, _WITH_IMAGE), "k")

    assert at_newest.index("❯") > at_newest.index("looks good")
    assert at_oldest.index("❯") < at_oldest.index("looks good")


@pytest.mark.anyio
async def test_escape_closes_the_thread() -> None:
    _, host = await _shown((_PLAIN,), "escape")

    assert host.result is None


@pytest.mark.anyio
async def test_o_shows_the_attachment_under_the_cursor() -> None:
    opener = _Opener()

    await _shown((_PLAIN, _WITH_IMAGE), "o", opener=opener)

    assert [a.file_name for a in opener.opened] == ["shot.png"]


@pytest.mark.anyio
async def test_o_on_a_comment_carrying_nothing_says_so() -> None:
    opener = _Opener()

    text, _ = await _shown((_WITH_IMAGE, _PLAIN), "o", opener=opener)

    assert opener.opened == []
    assert "Nothing attached" in text


@pytest.mark.anyio
async def test_a_file_that_will_not_come_down_is_reported_in_place() -> None:
    """The thread stays open: a failed download is a message, not a dead end."""
    opener = _Opener(error=RuntimeError("offline"))

    text, host = await _shown((_WITH_IMAGE,), "o", opener=opener)

    assert "offline" in text
    assert host.result == "unset"  # still open


@pytest.mark.anyio
async def test_closing_the_thread_mid_download_does_not_crash_the_worker() -> None:
    """The file arrives after the screen is gone; nothing may be drawn on it."""
    released = asyncio.Event()
    started = asyncio.Event()

    class _SlowOpener:
        def __init__(self) -> None:
            self.opened: list[Attachment] = []

        async def __call__(self, attachment: Attachment) -> None:
            self.opened.append(attachment)
            started.set()
            await released.wait()

    opener = _SlowOpener()
    host = _Host((_WITH_IMAGE,), opener)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("o")
        await asyncio.wait_for(started.wait(), timeout=2)
        await pilot.press("escape")
        await pilot.pause()
        released.set()
        await pilot.pause()
        await pilot.pause()

        assert opener.opened
        assert [w.state for w in host.workers if w.state is WorkerState.ERROR] == []


@pytest.mark.anyio
async def test_a_message_for_a_thread_that_is_gone_is_dropped() -> None:
    """The download can land in the very tick the screen closes, too late to be
    cancelled and too late to be shown."""
    screen = CommentsScreen((_WITH_IMAGE,), _TODAY)

    screen._say("Opening shot.png\u2026")  # pyright: ignore[reportPrivateUsage]


@pytest.mark.anyio
async def test_the_image_under_the_cursor_is_drawn_once_it_is_on_disk() -> None:
    files, panes = _Files(), _Panes()

    text, _ = await _shown((_WITH_IMAGE,), files=files, panes=panes)

    assert [a.file_name for a in files.asked] == ["shot.png"]
    assert panes.drawn == [Path("/cache/shot.png")]
    assert "shot.png" in text


@pytest.mark.anyio
async def test_a_comment_with_no_image_draws_nothing() -> None:
    files, panes = _Files(), _Panes()

    await _shown((_PLAIN,), files=files, panes=panes)

    assert files.asked == []
    assert panes.drawn == []


@pytest.mark.anyio
async def test_walking_off_an_image_takes_its_preview_with_it() -> None:
    files, panes = _Files(), _Panes()
    host = _Host((_PLAIN, _WITH_IMAGE), None, files, panes)

    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.screen.query("#drawn")  # the newest comment carries the image

        await pilot.press("k")
        await pilot.pause()

        assert not host.screen.query("#drawn")


@pytest.mark.anyio
async def test_a_slow_image_never_lands_on_a_comment_moved_away_from() -> None:
    """The fetch for the image is still running when the cursor moves on; its
    result belongs to a comment nobody is looking at any more."""
    files, panes = _Files(), _Panes()
    files.hold = asyncio.Event()

    host = _Host((_PLAIN, _WITH_IMAGE), None, files, panes)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("k")  # away from the image, while its fetch is in flight
        await pilot.pause()
        files.hold.set()
        await pilot.pause()
        await pilot.pause()

        assert panes.drawn == []


@pytest.mark.anyio
async def test_an_image_that_will_not_come_down_says_so_where_it_would_have_been() -> (
    None
):
    files, panes = _Files(error=RuntimeError("offline")), _Panes()

    text, _ = await _shown((_WITH_IMAGE,), files=files, panes=panes)

    assert panes.drawn == []
    assert "No preview" in text


@pytest.mark.anyio
async def test_an_image_the_renderer_chokes_on_says_so() -> None:
    """A file on disk is not necessarily an image the renderer can open."""

    class _BadPanes:
        def __call__(self, path: Path, file_name: str) -> Widget:
            raise OSError("broken data stream when reading image file")

    text, _ = await _shown(
        (_WITH_IMAGE,),
        files=_Files(),
        panes=_BadPanes(),  # pyright: ignore[reportArgumentType]
    )

    assert "No preview" in text


@pytest.mark.anyio
async def test_a_asks_for_a_comment_to_be_written() -> None:
    _, host = await _shown((_PLAIN,), "a")

    assert host.result == CommentRequest(write=True)


@pytest.mark.anyio
async def test_the_hint_names_writing_a_comment() -> None:
    text, _ = await _shown((_PLAIN,))

    assert "a add" in text


@pytest.mark.anyio
async def test_d_asks_for_the_comment_under_the_cursor_to_go() -> None:
    _, host = await _shown((_PLAIN, _WITH_IMAGE), "d")

    assert host.result == CommentRequest(delete_id="c2")


@pytest.mark.anyio
async def test_d_on_an_empty_thread_asks_for_nothing() -> None:
    _, host = await _shown((), "d")

    assert host.result == "unset"  # still open, nothing to delete
