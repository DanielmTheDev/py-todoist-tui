from typing import Any, cast

import httpx

BASE_URL = "https://api.todoist.com/api/v1"


class TodoistClient:
    """Thin httpx wrapper over the Todoist API v1. Returns raw JSON records."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    @classmethod
    def create(cls, token: str) -> "TodoistClient":
        http = httpx.AsyncClient(
            base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}
        )
        return cls(http)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "TodoistClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def today_tasks(self) -> list[dict[str, Any]]:
        return await self._paginate("/tasks/filter", {"query": "today"})

    async def projects(self) -> list[dict[str, Any]]:
        return await self._paginate("/projects", {})

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
