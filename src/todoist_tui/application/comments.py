from todoist_tui.domain.comment import Attachment, Comment
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def load_comments(repo: TaskRepository, task_id: TaskId) -> tuple[Comment, ...]:
    """One task's thread, oldest first — the order it was written in."""
    comments = await repo.comments(task_id)
    return tuple(sorted(comments, key=lambda comment: comment.posted_at))


async def post_comment(
    repo: TaskRepository,
    task_id: TaskId,
    content: str,
    attachment: Attachment | None = None,
) -> None:
    await repo.add_comment(task_id, content, attachment)


async def delete_comment(repo: TaskRepository, comment_id: str) -> None:
    await repo.delete_comment(comment_id)
