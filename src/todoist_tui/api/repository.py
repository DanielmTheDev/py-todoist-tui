from collections.abc import Callable
from typing import Any

from todoist_tui.api.client import TodoistClient
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.sync_delta import SyncDelta
from todoist_tui.domain.task import Task, TaskId


class ApiTaskRepository:
    """Adapter binding the Todoist client to the domain `TaskRepository` port."""

    def __init__(self, client: TodoistClient) -> None:
        self._client = client

    async def today(self) -> list[Task]:
        return [_to_task(record) for record in await self._client.today_tasks()]

    async def filtered(self, query: str) -> list[Task]:
        records = await self._client.filter_tasks(query)
        return [_to_task(record) for record in records]

    async def filters(self) -> list[Filter]:
        # No REST list endpoint for filters; a full /sync is the only source.
        # Network-direct like projects(); the caching wrapper overrides it.
        body = await self._client.sync("*")
        live, _deleted = _split(body.get("filters", []), _to_filter)
        return live

    async def inbox(self) -> list[Task]:
        projects = await self._client.projects()
        inbox = next((p for p in projects if p.get("inbox_project")), None)
        if inbox is None:
            raise LookupError("no inbox project found")
        records = await self._client.tasks_in_project(str(inbox["id"]))
        return [_to_task(record) for record in records]

    async def projects(self) -> list[Project]:
        return [_to_project(record) for record in await self._client.projects()]

    async def complete(self, task_id: TaskId) -> None:
        await self._client.close_item(str(task_id))

    async def uncomplete(self, task_id: TaskId) -> None:
        await self._client.reopen_item(str(task_id))

    async def refresh(self) -> None:
        """No-op: every read already hits the network, so there is no cache."""


class ApiSnapshotSource:
    """Builds a domain `SyncDelta` from a single Todoist `/sync` trip."""

    def __init__(self, client: TodoistClient) -> None:
        self._client = client

    async def delta(self, since: str | None) -> SyncDelta:
        body = await self._client.sync(since if since is not None else "*")
        projects, deleted_projects = _split(body["projects"], _to_project)
        tasks, deleted_tasks = _split(body["items"], _to_task, _is_gone)
        filters, deleted_filters = _split(body.get("filters", []), _to_filter)
        return SyncDelta(
            projects=projects,
            tasks=tasks,
            deleted_project_ids=deleted_projects,
            deleted_task_ids=deleted_tasks,
            sync_token=str(body["sync_token"]),
            full_sync=bool(body["full_sync"]),
            filters=filters,
            deleted_filter_ids=deleted_filters,
        )


def _is_gone(record: dict[str, Any]) -> bool:
    return bool(record.get("is_deleted") or record.get("checked"))


def _split[T](
    records: list[dict[str, Any]],
    to_domain: Callable[[dict[str, Any]], T],
    gone: Callable[[dict[str, Any]], bool] = lambda r: bool(r.get("is_deleted")),
) -> tuple[list[T], frozenset[str]]:
    live = [to_domain(r) for r in records if not gone(r)]
    deleted = frozenset(str(r["id"]) for r in records if gone(r))
    return live, deleted


def _to_project(record: dict[str, Any]) -> Project:
    return Project(
        id=str(record["id"]),
        name=str(record["name"]),
        is_inbox=bool(record.get("inbox_project")),
    )


def _to_filter(record: dict[str, Any]) -> Filter:
    return Filter(
        id=str(record["id"]),
        name=str(record["name"]),
        query=str(record["query"]),
        order=int(record["item_order"]),
    )


def _to_task(record: dict[str, Any]) -> Task:
    due = record.get("due")
    return Task(
        id=TaskId(str(record["id"])),
        content=str(record["content"]),
        priority=Priority.from_api(int(record["priority"])),
        due=Due.from_api(due) if due else None,
        project_id=str(record["project_id"]),
    )
