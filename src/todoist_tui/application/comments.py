from todoist_tui.domain.comment import Attachment, Comment
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId
from todoist_tui.domain.upload import PendingUpload


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


async def attach_file(
    repo: TaskRepository, task_id: TaskId, upload: PendingUpload, content: str = ""
) -> None:
    """Send a file up and hang it on a comment. The file goes first: a comment
    pointing at something that never arrived is worse than no comment."""
    attachment = await repo.upload_attachment(upload)
    await post_comment(repo, task_id, content, attachment)
