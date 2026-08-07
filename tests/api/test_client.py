import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from todoist_tui.api.client import BASE_URL, SyncCommandError, TodoistClient
from todoist_tui.domain.search import InvalidSearchQuery


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
async def test_rejected_query_raises_invalid_search_query() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": "The search query is incorrect",
                "error_code": 55,
                "error_extra": {"retry_after": 2},
                "error_tag": "INVALID_SEARCH_QUERY",
                "http_code": 400,
            },
        )
    )
    client = TodoistClient.create("tok")

    with pytest.raises(InvalidSearchQuery):
        await client.filter_tasks("search: a&b")
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_other_filter_failures_stay_http_errors() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(return_value=httpx.Response(500))
    client = TodoistClient.create("tok")

    with pytest.raises(httpx.HTTPStatusError):
        await client.filter_tasks("today")
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
async def test_filter_tasks_sends_given_query() -> None:
    route = respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "1"}], "next_cursor": None}
        )
    )
    client = TodoistClient.create("tok")

    tasks = await client.filter_tasks("@work & p1")

    assert tasks == [{"id": "1"}]
    assert route.calls.last.request.url.params["query"] == "@work & p1"
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
async def test_reopen_item_posts_item_uncomplete_command() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.reopen_item("6X4")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "item_uncomplete", "uuid": "u-1", "args": {"id": "6X4"}}
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_update_item_posts_item_update_command_with_priority() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.update_item("6X4", 4)

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "item_update", "uuid": "u-1", "args": {"id": "6X4", "priority": 4}}
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_update_item_due_posts_item_update_command_with_due() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.update_item_due("6X4", {"date": "2026-07-29"})

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "item_update",
            "uuid": "u-1",
            "args": {"id": "6X4", "due": {"date": "2026-07-29"}},
        }
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_update_item_due_none_clears_due() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.update_item_due("6X4", None)

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "item_update", "uuid": "u-1", "args": {"id": "6X4", "due": None}}
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_update_item_deadline_posts_item_update_command() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.update_item_deadline("6X4", {"date": "2026-08-15"})

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "item_update",
            "uuid": "u-1",
            "args": {"id": "6X4", "deadline": {"date": "2026-08-15"}},
        }
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_update_item_deadline_none_clears_deadline() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.update_item_deadline("6X4", None)

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "item_update", "uuid": "u-1", "args": {"id": "6X4", "deadline": None}}
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_update_item_labels_replaces_the_label_set() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.update_item_labels("6X4", ["home", "urgent"])

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "item_update",
            "uuid": "u-1",
            "args": {"id": "6X4", "labels": ["home", "urgent"]},
        }
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_update_item_labels_creates_new_labels_first() -> None:
    ids = iter(["a", "b", "c"])
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"a": "ok", "c": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: next(ids))

    await client.update_item_labels("6X4", ["home", "fresh"], create=["fresh"])

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "label_add", "uuid": "a", "temp_id": "b", "args": {"name": "fresh"}},
        {
            "type": "item_update",
            "uuid": "c",
            "args": {"id": "6X4", "labels": ["home", "fresh"]},
        },
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_update_item_text_sends_content_and_description_together() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.update_item_text("6X4", "Buy oat milk", "2 cartons")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "item_update",
            "uuid": "u-1",
            "args": {
                "id": "6X4",
                "content": "Buy oat milk",
                "description": "2 cartons",
            },
        }
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_update_item_text_clears_the_description_with_an_empty_string() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.update_item_text("6X4", "Buy oat milk", "")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["args"]["description"] == ""
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_move_item_posts_item_move_command_with_project() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.move_item("6X4", "220")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "item_move",
            "uuid": "u-1",
            "args": {"id": "6X4", "project_id": "220"},
        }
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_move_item_with_section_sends_section_id_only() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.move_item("6X4", "220", section_id="77")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "item_move", "uuid": "u-1", "args": {"id": "6X4", "section_id": "77"}}
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_move_item_raises_on_command_error() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "sync_status": {
                    "u-1": {"error_tag": "PROJECT_NOT_FOUND", "error": "not found"}
                }
            },
        )
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    with pytest.raises(SyncCommandError, match="not found"):
        await client.move_item("6X4", "nope")
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_reopen_item_raises_on_command_error() -> None:
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
        await client.reopen_item("nope")
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
    assert json.loads(form["resource_types"][0]) == [
        "items",
        "projects",
        "filters",
        "sections",
        "labels",
        "reminders",
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_add_reminder_posts_reminder_add_command() -> None:
    ids = iter(["u-1", "temp-1"])
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: next(ids))

    await client.add_reminder("6X4", {"type": "relative", "minute_offset": 30})

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "reminder_add",
            "uuid": "u-1",
            "temp_id": "temp-1",
            "args": {"item_id": "6X4", "type": "relative", "minute_offset": 30},
        }
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_delete_reminder_posts_reminder_delete_command() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.delete_reminder("r9")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "reminder_delete", "uuid": "u-1", "args": {"id": "r9"}}
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_sync_sends_given_token_for_incremental() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"full_sync": False})
    )
    client = TodoistClient.create("tok")

    await client.sync("prev-token")

    form = parse_qs(route.calls.last.request.content.decode())
    assert form["sync_token"] == ["prev-token"]
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


@pytest.mark.anyio
@respx.mock
async def test_delete_item_posts_item_delete_command() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.delete_item("6X4")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [{"type": "item_delete", "uuid": "u-1", "args": {"id": "6X4"}}]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_delete_item_raises_on_command_error() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={"sync_status": {"u-1": {"error": "not found"}}},
        )
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    with pytest.raises(SyncCommandError, match="not found"):
        await client.delete_item("nope")
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_delete_section_posts_section_delete_command() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.delete_section("6S1")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "section_delete", "uuid": "u-1", "args": {"id": "6S1"}}
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_delete_section_raises_on_command_error() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={"sync_status": {"u-1": {"error": "not found"}}},
        )
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    with pytest.raises(SyncCommandError, match="not found"):
        await client.delete_section("nope")
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_create_entities_wraps_specs_in_temp_id_commands() -> None:
    ids = iter(["u-1", "u-2"])
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200, json={"sync_status": {"u-1": "ok", "u-2": "ok"}}
        )
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: next(ids))

    await client.create_entities(
        [
            ("project_add", "tp", {"name": "Work (copy)"}),
            ("section_add", "ts", {"name": "Now", "project_id": "tp"}),
        ]
    )

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "project_add",
            "uuid": "u-1",
            "temp_id": "tp",
            "args": {"name": "Work (copy)"},
        },
        {
            "type": "section_add",
            "uuid": "u-2",
            "temp_id": "ts",
            "args": {"name": "Now", "project_id": "tp"},
        },
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_requests_use_a_generous_timeout() -> None:
    # a big batched duplicate create can take >5s server-side; httpx's 5s
    # default would ReadTimeout after the server already committed
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.create_entities([("project_add", "tp", {"name": "x"})])

    assert route.calls.last.request.extensions["timeout"]["read"] == 30.0
    await client.aclose()
