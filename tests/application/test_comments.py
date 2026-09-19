import datetime

import pytest

from todoist_tui.application.comments import load_comments
from todoist_tui.domain.comment import Comment
from todoist_tui.domain.task import TaskId

_AT = datetime.datetime(2026, 9, 18, 19, 4, tzinfo=datetime.UTC)


class FakeRepo:
    def __init__(self, comments: list[Comment]) -> None:
        self._comments = comments
        self.asked: list[TaskId] = []

    async def comments(self, task_id: TaskId) -> list[Comment]:
        self.asked.append(task_id)
        return self._comments


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
