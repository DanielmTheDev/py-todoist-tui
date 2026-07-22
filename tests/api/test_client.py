import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from todoist_tui.api.client import BASE_URL, SyncCommandError, TodoistClient


@pytest.mark.anyio
@respx.mock
async def test_today_tasks_sends_bearer_and_query() -> None:
    route = respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "1"}], "next_cursor": None}
        )
    )
    client = TodoistClient.create("tok")

    tasks = await client.today_tasks()

    assert tasks == [{"id": "1"}]
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.url.params["query"] == "today"
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_today_tasks_follows_cursor_pagination() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        side_effect=[
            httpx.Response(200, json={"results": [{"id": "1"}], "next_cursor": "abc"}),
            httpx.Response(200, json={"results": [{"id": "2"}], "next_cursor": None}),
        ]
    )
    client = TodoistClient.create("tok")

    tasks = await client.today_tasks()

    assert [t["id"] for t in tasks] == ["1", "2"]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_tasks_in_project_sends_project_id() -> None:
    route = respx.get(f"{BASE_URL}/tasks").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "1"}], "next_cursor": None}
        )
    )
    client = TodoistClient.create("tok")

    tasks = await client.tasks_in_project("220")

    assert tasks == [{"id": "1"}]
    assert route.calls.last.request.url.params["project_id"] == "220"
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_projects_parses_results() -> None:
    respx.get(f"{BASE_URL}/projects").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "220", "name": "Inbox"}], "next_cursor": None}
        )
    )
    client = TodoistClient.create("tok")

    assert await client.projects() == [{"id": "220", "name": "Inbox"}]
    await client.aclose()


@pytest.mark.anyio
async def test_async_context_manager_closes_client() -> None:
    async with TodoistClient.create("tok") as client:
        pass

    with pytest.raises(RuntimeError, match="closed"):
        await client.today_tasks()


@pytest.mark.anyio
@respx.mock
async def test_raises_on_http_error() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(return_value=httpx.Response(401))
    client = TodoistClient.create("bad")

    with pytest.raises(httpx.HTTPStatusError):
        await client.today_tasks()
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_close_item_posts_item_close_command() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.close_item("6X4")

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok"
    assert "application/x-www-form-urlencoded" in request.headers["content-type"]
    commands = json.loads(parse_qs(request.content.decode())["commands"][0])
    assert commands == [{"type": "item_close", "uuid": "u-1", "args": {"id": "6X4"}}]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_sync_posts_full_sync_and_returns_body() -> None:
    body = {
        "items": [{"id": "1"}],
        "projects": [{"id": "220", "name": "Inbox"}],
        "sync_token": "abc",
        "full_sync": True,
    }
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json=body)
    )
    client = TodoistClient.create("tok")

    assert await client.sync() == body

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok"
    assert "application/x-www-form-urlencoded" in request.headers["content-type"]
    form = parse_qs(request.content.decode())
    assert form["sync_token"] == ["*"]
    assert json.loads(form["resource_types"][0]) == ["items", "projects"]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_close_item_raises_on_command_error() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "sync_status": {
                    "u-1": {"error_tag": "ITEM_NOT_FOUND", "error": "not found"}
                }
            },
        )
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    with pytest.raises(SyncCommandError, match="not found"):
        await client.close_item("nope")
    await client.aclose()
