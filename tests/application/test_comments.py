import datetime

import pytest

from todoist_tui.application.comments import load_comments, post_comment
from todoist_tui.domain.comment import Attachment, Comment
from todoist_tui.domain.task import TaskId

_AT = datetime.datetime(2026, 9, 18, 19, 4, tzinfo=datetime.UTC)


class FakeRepo:
    def __init__(self, comments: list[Comment]) -> None:
        self._comments = comments
        self.asked: list[TaskId] = []
        self.posted: list[tuple[TaskId, str, Attachment | None]] = []

    async def comments(self, task_id: TaskId) -> list[Comment]:
        self.asked.append(task_id)
        return self._comments

    async def add_comment(
        self, task_id: TaskId, content: str, attachment: Attachment | None = None
    ) -> None:
        self.posted.append((task_id, content, attachment))


@pytest.mark.anyio
async def test_load_comments_reads_one_task_thread() -> None:
    older = Comment(id="c1", task_id="t1", content="first", posted_at=_AT)
    newer = Comment(
        id="c2",
        task_id="t1",
        content="second",
        posted_at=_AT + datetime.timedelta(hours=1),
    )
    repo = FakeRepo([newer, older])

    loaded = await load_comments(repo, TaskId("t1"))  # pyright: ignore[reportArgumentType]

    assert repo.asked == [TaskId("t1")]
    assert [c.id for c in loaded] == ["c1", "c2"]  # oldest first, as a thread reads


@pytest.mark.anyio
async def test_post_comment_writes_the_text_to_its_task() -> None:
    repo = FakeRepo([])

    await post_comment(repo, TaskId("t1"), "ship it")  # pyright: ignore[reportArgumentType]

    assert repo.posted == [(TaskId("t1"), "ship it", None)]


@pytest.mark.anyio
async def test_a_file_can_be_the_whole_comment() -> None:
    """A screenshot says what it says; Todoist takes a comment with no text."""
    repo = FakeRepo([])
    attachment = Attachment(
        file_name="shot.png", file_type="image/png", file_url="https://x/shot.png"
    )

    await post_comment(repo, TaskId("t1"), "", attachment)  # pyright: ignore[reportArgumentType]

    assert repo.posted == [(TaskId("t1"), "", attachment)]
