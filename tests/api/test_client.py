import httpx
import pytest
import respx

from todoist_tui.api.client import BASE_URL, TodoistClient


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
