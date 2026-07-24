import json
import uuid
from collections.abc import Callable
from typing import Any, cast

import httpx

BASE_URL = "https://api.todoist.com/api/v1"


def _random_uuid() -> str:
    return str(uuid.uuid4())


class SyncCommandError(Exception):
    """A Sync command was rejected by Todoist (non-'ok' sync_status)."""


class TodoistClient:
    """Thin httpx wrapper over the Todoist API v1. Returns raw JSON records."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        uuid_factory: Callable[[], str] = _random_uuid,
    ) -> None:
        self._http = http
        self._uuid = uuid_factory

    @classmethod
    def create(
        cls, token: str, uuid_factory: Callable[[], str] = _random_uuid
    ) -> "TodoistClient":
        http = httpx.AsyncClient(
            base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}
        )
        return cls(http, uuid_factory)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "TodoistClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def today_tasks(self) -> list[dict[str, Any]]:
        return await self._paginate("/tasks/filter", {"query": "today"})

    async def tasks_in_project(self, project_id: str) -> list[dict[str, Any]]:
        return await self._paginate("/tasks", {"project_id": project_id})

    async def projects(self) -> list[dict[str, Any]]:
        return await self._paginate("/projects", {})

    async def sync(self, sync_token: str = "*") -> dict[str, Any]:
        response = await self._http.post(
            "/sync",
            data={
                "sync_token": sync_token,
                "resource_types": json.dumps(["items", "projects", "filters"]),
            },
        )
        response.raise_for_status()
        return cast("dict[str, Any]", response.json())

    async def close_item(self, task_id: str) -> None:
        await self._command("item_close", {"id": task_id})

    async def reopen_item(self, task_id: str) -> None:
        await self._command("item_uncomplete", {"id": task_id})

    async def _command(self, kind: str, args: dict[str, Any]) -> None:
        command_uuid = self._uuid()
        command = {"type": kind, "uuid": command_uuid, "args": args}
        response = await self._http.post(
            "/sync", data={"commands": json.dumps([command])}
        )
        response.raise_for_status()
        status = cast("dict[str, Any]", response.json())["sync_status"][command_uuid]
        if status != "ok":
            raise SyncCommandError(str(status.get("error", status)))

    async def _paginate(
        self, path: str, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        query = dict(params)
        items: list[dict[str, Any]] = []
        while True:
            response = await self._http.get(path, params=query)
            response.raise_for_status()
            body = cast("dict[str, Any]", response.json())
            items.extend(cast("list[dict[str, Any]]", body["results"]))
            cursor = body.get("next_cursor")
            if not cursor:
                return items
            query["cursor"] = cast("str", cursor)
