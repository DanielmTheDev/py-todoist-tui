import asyncio

import pytest

from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.store.repository import SnapshotTaskRepository


def _task(task_id: str, project_id: str) -> Task:
    return Task(
        id=TaskId(task_id),
        content=task_id,
        priority=Priority.P2,
        due=None,
        project_id=project_id,
    )


class FakeInner:
    """Backs today()/complete(); the snapshot repo must never call the rest."""

    def __init__(self, today: list[Task] | None = None) -> None:
        self._today = today or []
        self.today_calls = 0
        self.completed: list[TaskId] = []

    async def today(self) -> list[Task]:
        self.today_calls += 1
        return self._today

    async def inbox(self) -> list[Task]:  # pragma: no cover - must not be called
        raise AssertionError("inbox() must be served from the snapshot")

    async def projects(self) -> list[Project]:  # pragma: no cover
        raise AssertionError("projects() must be served from the snapshot")

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)


class FakeSource:
    def __init__(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot
        self.snapshot_calls = 0

    async def snapshot(self) -> Snapshot:
        self.snapshot_calls += 1
        return self._snapshot


def _snapshot() -> Snapshot:
    return Snapshot(
        projects=[
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
        ],
        tasks=[_task("a", "220"), _task("b", "9"), _task("c", "220")],
    )


@pytest.mark.anyio
async def test_projects_and_inbox_share_one_sync() -> None:
    source = FakeSource(_snapshot())
    repo = SnapshotTaskRepository(FakeInner(), source)

    projects = await repo.projects()
    inbox = await repo.inbox()

    assert [p.id for p in projects] == ["220", "9"]
    assert [t.id for t in inbox] == [TaskId("a"), TaskId("c")]
    assert source.snapshot_calls == 1


@pytest.mark.anyio
async def test_inbox_raises_when_no_inbox_project() -> None:
    source = FakeSource(Snapshot(projects=[Project(id="9", name="Work")], tasks=[]))
    repo = SnapshotTaskRepository(FakeInner(), source)

    with pytest.raises(LookupError, match="inbox"):
        await repo.inbox()


@pytest.mark.anyio
async def test_today_delegates_to_inner_without_syncing() -> None:
    inner = FakeInner(today=[_task("t", "9")])
    source = FakeSource(_snapshot())
    repo = SnapshotTaskRepository(inner, source)

    assert [t.id for t in await repo.today()] == [TaskId("t")]
    assert inner.today_calls == 1
    assert source.snapshot_calls == 0


@pytest.mark.anyio
async def test_complete_forwards_and_invalidates_snapshot() -> None:
    inner = FakeInner()
    source = FakeSource(_snapshot())
    repo = SnapshotTaskRepository(inner, source)

    await repo.projects()
    await repo.complete(TaskId("a"))
    await repo.projects()

    assert inner.completed == [TaskId("a")]
    assert source.snapshot_calls == 2


@pytest.mark.anyio
async def test_concurrent_first_fetch_shares_single_sync() -> None:
    source = FakeSource(_snapshot())
    repo = SnapshotTaskRepository(FakeInner(), source)

    await asyncio.gather(repo.projects(), repo.inbox())

    assert source.snapshot_calls == 1
