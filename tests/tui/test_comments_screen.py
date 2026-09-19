import datetime

import pytest
from textual.app import App
from textual.widgets import Static

from todoist_tui.domain.comment import Attachment, Comment
from todoist_tui.tui.screens.comments import CommentsScreen

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


class _Host(App[None]):
    def __init__(self, comments: tuple[Comment, ...]) -> None:
        super().__init__()
        self._comments = comments
        self.result: str | None = "unset"

    def on_mount(self) -> None:
        self.push_screen(
            CommentsScreen(self._comments, _TODAY, tz=datetime.UTC), self._taken
        )

    def _taken(self, result: str | None) -> None:
        self.result = result


async def _shown(comments: tuple[Comment, ...], *keys: str) -> tuple[str, _Host]:
    host = _Host(comments)
    async with host.run_test() as pilot:
        await pilot.pause()
        for key in keys:
            await pilot.press(key)
        await pilot.pause()
        found = host.screen.query("#comments")
        text = str(found.only_one(Static).content) if found else ""
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
