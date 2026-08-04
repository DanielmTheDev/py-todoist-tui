import json
import uuid
from collections.abc import Callable
from typing import Any, cast

import httpx

from todoist_tui.domain.search import InvalidSearchQuery

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
        return await self.filter_tasks("today")

    async def filter_tasks(self, query: str) -> list[dict[str, Any]]:
        try:
            return await self._paginate("/tasks/filter", {"query": query})
        except httpx.HTTPStatusError as error:
            # this endpoint's only 400 is a malformed query; the UI can't read
            # an httpx error, and its message would leak the whole URL
            if error.response.status_code == 400:
                raise InvalidSearchQuery(query) from error
            raise

    async def tasks_in_project(self, project_id: str) -> list[dict[str, Any]]:
        return await self._paginate("/tasks", {"project_id": project_id})

    async def projects(self) -> list[dict[str, Any]]:
        return await self._paginate("/projects", {})

    async def sync(self, sync_token: str = "*") -> dict[str, Any]:
        response = await self._http.post(
            "/sync",
            data={
                "sync_token": sync_token,
                "resource_types": json.dumps(
                    ["items", "projects", "filters", "sections", "labels"]
                ),
            },
        )
        response.raise_for_status()
        return cast("dict[str, Any]", response.json())

    async def close_item(self, task_id: str) -> None:
        await self._command("item_close", {"id": task_id})

    async def reopen_item(self, task_id: str) -> None:
        await self._command("item_uncomplete", {"id": task_id})

    async def delete_item(self, task_id: str) -> None:
        await self._command("item_delete", {"id": task_id})

    async def update_item(self, task_id: str, priority: int) -> None:
        await self._command("item_update", {"id": task_id, "priority": priority})

    async def update_item_due(self, task_id: str, due: dict[str, str] | None) -> None:
        # `due=None` clears the date; otherwise a Sync `due` object (date/datetime).
        await self._command("item_update", {"id": task_id, "due": due})

    async def update_item_deadline(
        self, task_id: str, deadline: dict[str, str] | None
    ) -> None:
        # `deadline=None` clears it; otherwise a Sync `deadline` object (date-only).
        await self._command("item_update", {"id": task_id, "deadline": deadline})

    async def update_item_labels(
        self, task_id: str, labels: list[str], create: list[str] | None = None
    ) -> None:
        # `labels` replaces the task's whole set. Names in `create` don't yet
        # exist as personal labels (item_update alone won't register them), so a
        # label_add precedes the update in the same trip.
        commands: list[dict[str, Any]] = [
            {
                "type": "label_add",
                "uuid": self._uuid(),
                "temp_id": self._uuid(),
                "args": {"name": name},
            }
            for name in create or []
        ]
        commands.append(
            {
                "type": "item_update",
                "uuid": self._uuid(),
                "args": {"id": task_id, "labels": labels},
            }
        )
        await self._run(commands)

    async def move_item(
        self, task_id: str, project_id: str, section_id: str | None = None
    ) -> None:
        # A section move sends section_id alone (Todoist infers the project);
        # a project move sends project_id alone and clears any section.
        args = (
            {"id": task_id, "section_id": section_id}
            if section_id is not None
            else {"id": task_id, "project_id": project_id}
        )
        await self._command("item_move", args)

    async def _command(self, kind: str, args: dict[str, Any]) -> None:
        await self._run([{"type": kind, "uuid": self._uuid(), "args": args}])

    async def _run(self, commands: list[dict[str, Any]]) -> None:
        response = await self._http.post(
            "/sync", data={"commands": json.dumps(commands)}
        )
        response.raise_for_status()
        sync_status = cast("dict[str, Any]", response.json())["sync_status"]
        for command in commands:
            status = sync_status[command["uuid"]]
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
