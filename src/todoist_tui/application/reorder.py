from collections.abc import Sequence

from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def reorder(repo: TaskRepository, items: Sequence[tuple[TaskId, int]]) -> None:
    await repo.reorder(items)
