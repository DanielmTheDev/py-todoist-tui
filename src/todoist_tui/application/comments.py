from todoist_tui.domain.comment import Comment
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def load_comments(repo: TaskRepository, task_id: TaskId) -> tuple[Comment, ...]:
    """One task's thread, oldest first — the order it was written in."""
    comments = await repo.comments(task_id)
    return tuple(sorted(comments, key=lambda comment: comment.posted_at))
