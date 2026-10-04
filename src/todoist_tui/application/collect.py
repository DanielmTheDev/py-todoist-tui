"""Gather existing tasks under a parent created for them, in one Sync trip: the
parent has no id until the batch lands, so each move names its temp_id."""

from collections.abc import Sequence
from dataclasses import replace

from todoist_tui.domain.creation import CreationPlan, NewMove
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId


async def collect_under_new_parent(
    repo: TaskRepository, parent: CreationPlan, tasks: Sequence[TaskId]
) -> TaskId:
    """Create `parent` (its plan's first task) and nest `tasks` under it in their
    given order, answering the id the parent became — undoing it needs one."""
    ref = parent.tasks[0].temp_id
    plan = replace(parent, moves=tuple(NewMove(task, ref) for task in tasks))
    created = await repo.apply_creation(plan)
    return TaskId(created[ref])
