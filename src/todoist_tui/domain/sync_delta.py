from collections.abc import Callable, Iterable
from dataclasses import dataclass

from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.task import Task


@dataclass(frozen=True, slots=True)
class SyncDelta:
    """One incremental /sync trip: changed records, deletions and the new token.

    A `full_sync` response carries the whole account state (deletions absent);
    an incremental one carries only what changed since the previous token.
    """

    projects: list[Project]
    tasks: list[Task]
    deleted_project_ids: frozenset[str]
    deleted_task_ids: frozenset[str]
    sync_token: str
    full_sync: bool


def merge(prior: Snapshot | None, delta: SyncDelta) -> Snapshot:
    """Fold a delta onto the prior snapshot, yielding the new full state."""
    if prior is None or delta.full_sync:
        return Snapshot(
            projects=delta.projects, tasks=delta.tasks, sync_token=delta.sync_token
        )
    return Snapshot(
        projects=_apply(
            prior.projects, delta.projects, delta.deleted_project_ids, lambda p: p.id
        ),
        tasks=_apply(
            prior.tasks, delta.tasks, delta.deleted_task_ids, lambda t: str(t.id)
        ),
        sync_token=delta.sync_token,
    )


def _apply[T](
    prior: Iterable[T],
    changed: Iterable[T],
    deleted_ids: frozenset[str],
    key: Callable[[T], str],
) -> list[T]:
    by_id = {key(item): item for item in prior}
    for item in changed:  # updates keep their slot; new ids append
        by_id[key(item)] = item
    for deleted_id in deleted_ids:
        by_id.pop(deleted_id, None)
    return list(by_id.values())
