import asyncio

import pytest

from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.store.repository import CachingTaskRepository


class CountingRepository:
    def __init__(
        self,
        today: list[Task] | None = None,
        inbox: list[Task] | None = None,
        projects: list[Project] | None = None,
    ) -> None:
        self._today = today or []
        self._inbox = inbox or []
        self._projects = projects or []
        self.projects_calls = 0
        self.today_calls = 0
        self.inbox_calls = 0
        self.completed: list[TaskId] = []

    async def today(self) -> list[Task]:
        self.today_calls += 1
        return self._today

    async def inbox(self) -> list[Task]:
        self.inbox_calls += 1
        return self._inbox

    async def projects(self) -> list[Project]:
        self.projects_calls += 1
        return self._projects

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)


@pytest.mark.anyio
async def test_projects_fetched_once_and_memoized() -> None:
    inner = CountingRepository(projects=[Project(id="1", name="Errands")])
    repo = CachingTaskRepository(inner)

    first = await repo.projects()
    second = await repo.projects()

    assert inner.projects_calls == 1
    assert first == second == [Project(id="1", name="Errands")]


@pytest.mark.anyio
async def test_today_and_inbox_delegate_uncached() -> None:
    task = Task(
        id=TaskId("t"), content="c", priority=Priority.P2, due=None, project_id="1"
    )
    inner = CountingRepository(today=[task], inbox=[task])
    repo = CachingTaskRepository(inner)

    assert await repo.today() == [task]
    assert await repo.today() == [task]
    assert await repo.inbox() == [task]

    assert inner.today_calls == 2
    assert inner.inbox_calls == 1


@pytest.mark.anyio
async def test_complete_forwards_task_id() -> None:
    inner = CountingRepository()
    repo = CachingTaskRepository(inner)

    await repo.complete(TaskId("42"))

    assert inner.completed == [TaskId("42")]


@pytest.mark.anyio
async def test_concurrent_first_fetch_shares_single_trip() -> None:
    inner = CountingRepository(projects=[Project(id="1", name="Errands")])
    repo = CachingTaskRepository(inner)

    await asyncio.gather(repo.projects(), repo.projects())

    assert inner.projects_calls == 1
