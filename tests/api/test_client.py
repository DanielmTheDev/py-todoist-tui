import asyncio
import json
from typing import Any, cast
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from todoist_tui.api.client import (
    ACTIVITY_PAGE,
    BASE_URL,
    COMMAND_LIMIT,
    SyncCommandError,
    TodoistClient,
)
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
async def test_update_day_orders_posts_one_command_keyed_by_id() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.update_day_orders([("6X4", 2), ("6X5", 1)])

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "item_update_day_orders",
            "uuid": "u-1",
            "args": {"ids_to_orders": {"6X4": 2, "6X5": 1}},
        }
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_reorder_sections_posts_one_section_reorder_command() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.reorder_sections([("s1", 2), ("s2", 1)])

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "section_reorder",
            "uuid": "u-1",
            "args": {
                "sections": [
                    {"id": "s1", "section_order": 2},
                    {"id": "s2", "section_order": 1},
                ]
            },
        }
    ]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_reorder_items_posts_one_item_reorder_command() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.reorder_items([("6X4", 2), ("6X5", 1)])

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {
            "type": "item_reorder",
            "uuid": "u-1",
            "args": {
                "items": [
                    {"id": "6X4", "child_order": 2},
                    {"id": "6X5", "child_order": 1},
                ]
            },
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
async def test_move_item_under_sends_parent_id_only() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: "u-1")

    await client.move_item_under("6X4", "6P9")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "item_move", "uuid": "u-1", "args": {"id": "6X4", "parent_id": "6P9"}}
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
        "notes",
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


@pytest.mark.anyio
@respx.mock
async def test_commands_issued_together_travel_in_one_request() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200, json={"sync_status": {"u-1": "ok", "u-2": "ok"}}
        )
    )
    uuids = iter(["u-1", "u-2"])
    client = TodoistClient.create("tok", uuid_factory=lambda: next(uuids))

    await asyncio.gather(client.close_item("A"), client.close_item("B"))

    assert route.call_count == 1
    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert [c["args"]["id"] for c in commands] == ["A", "B"]  # issue order
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_a_rejection_in_a_shared_request_raises_for_its_caller_alone() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={"sync_status": {"u-1": "ok", "u-2": {"error": "not found"}}},
        )
    )
    uuids = iter(["u-1", "u-2"])
    client = TodoistClient.create("tok", uuid_factory=lambda: next(uuids))

    accepted, rejected = await asyncio.gather(
        client.close_item("A"), client.close_item("B"), return_exceptions=True
    )

    assert accepted is None
    assert isinstance(rejected, SyncCommandError)
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_a_verdict_missing_from_a_shared_request_strands_no_one() -> None:
    """Whatever one caller's commands turn out to be, the rest still get an
    answer — a request that resolved nobody would hang the outbox for good."""
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    uuids = iter(["u-1", "u-2"])
    client = TodoistClient.create("tok", uuid_factory=lambda: next(uuids))

    async with asyncio.timeout(5):  # a strand shows as a hang, so cut it short
        accepted, unanswered = await asyncio.gather(
            client.close_item("A"), client.close_item("B"), return_exceptions=True
        )

    assert accepted is None
    assert isinstance(unanswered, Exception)
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_a_wave_past_the_command_limit_is_split_across_requests() -> None:
    over = COMMAND_LIMIT + 5
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200, json={"sync_status": {f"u-{i}": "ok" for i in range(over)}}
        )
    )
    uuids = iter([f"u-{i}" for i in range(over)])
    client = TodoistClient.create("tok", uuid_factory=lambda: next(uuids))

    await asyncio.gather(*(client.close_item(str(i)) for i in range(over)))

    sent = [_commands_sent(route, i) for i in range(route.call_count)]
    assert [len(batch) for batch in sent] == [COMMAND_LIMIT, 5]
    assert [c["args"]["id"] for batch in sent for c in batch] == [
        str(i) for i in range(over)
    ]  # still one unbroken run, in issue order
    await client.aclose()


def _commands_sent(route: respx.Route, index: int) -> list[dict[str, Any]]:
    """The commands one request carried. `route.calls.last` is typed; an indexed
    call is not, so the cast lives here rather than at every use."""
    call = cast("respx.models.Call", route.calls[index])
    request = call.request
    return cast(
        "list[dict[str, Any]]",
        json.loads(parse_qs(request.content.decode())["commands"][0]),
    )


@pytest.mark.anyio
@respx.mock
async def test_a_command_raised_mid_flight_is_still_sent() -> None:
    """A command that reads before it writes reaches the client after the batch
    ahead of it has gone. Only the flush already running can pick it up."""
    posting = asyncio.Event()
    release = asyncio.Event()

    async def held(_request: httpx.Request) -> httpx.Response:
        posting.set()
        await release.wait()
        return httpx.Response(200, json={"sync_status": {"u-1": "ok", "u-2": "ok"}})

    route = respx.post(f"{BASE_URL}/sync").mock(side_effect=held)
    uuids = iter(["u-1", "u-2"])
    client = TodoistClient.create("tok", uuid_factory=lambda: next(uuids))

    ahead = asyncio.create_task(client.close_item("A"))
    await posting.wait()  # the first batch is on the wire
    behind = asyncio.create_task(client.close_item("B"))
    await asyncio.sleep(0)  # ...and the second is queued behind it
    release.set()

    async with asyncio.timeout(5):  # a stranded command shows as a hang
        await asyncio.gather(ahead, behind)

    assert route.call_count == 2
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_activities_asks_for_one_page_of_task_events() -> None:
    route = respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "1"}], "next_cursor": "next"}
        )
    )
    client = TodoistClient.create("tok")

    body = await client.activities()

    assert body == {"results": [{"id": "1"}], "next_cursor": "next"}
    params = route.calls.last.request.url.params
    assert params["object_type"] == "item"
    assert params["limit"] == str(ACTIVITY_PAGE)
    assert "event_type" not in params
    assert "cursor" not in params
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_activities_passes_event_type_and_cursor() -> None:
    route = respx.get(f"{BASE_URL}/activities").mock(
        return_value=httpx.Response(200, json={"results": [], "next_cursor": None})
    )
    client = TodoistClient.create("tok")

    await client.activities(event_type="completed", cursor="abc")

    params = route.calls.last.request.url.params
    assert params["event_type"] == "completed"
    assert params["cursor"] == "abc"
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_comments_asks_for_one_task_and_drains_the_pages() -> None:
    route = respx.get(f"{BASE_URL}/comments").mock(
        side_effect=[
            httpx.Response(200, json={"results": [{"id": "c1"}], "next_cursor": "ab"}),
            httpx.Response(200, json={"results": [{"id": "c2"}], "next_cursor": None}),
        ]
    )
    client = TodoistClient.create("tok")

    comments = await client.comments("t1")

    assert [c["id"] for c in comments] == ["c1", "c2"]
    assert route.calls.last.request.url.params["task_id"] == "t1"
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_sync_asks_for_the_notes_resource() -> None:
    """The comment marker is counted from the notes; an item's own note_count is
    only filled on a full sync and never refreshed afterwards."""
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={"full_sync": True, "items": [], "projects": [], "sync_token": "t"},
        )
    )
    client = TodoistClient.create("tok")

    await client.sync()

    sent = parse_qs(route.calls.last.request.content.decode())
    assert "notes" in json.loads(sent["resource_types"][0])
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_add_note_posts_the_comment_against_its_task() -> None:
    ids = iter(["u-1", "temp-1"])
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: next(ids))

    await client.add_note("t1", "looks good")

    sent = parse_qs(route.calls.last.request.content.decode())
    (command,) = json.loads(sent["commands"][0])
    assert command["type"] == "note_add"
    assert command["args"] == {"item_id": "t1", "content": "looks good"}
    assert command["temp_id"]  # a new note needs one, as a new reminder does
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_add_note_carries_the_file_the_comment_is_about() -> None:
    ids = iter(["u-1", "temp-1"])
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: next(ids))
    attachment = {"file_name": "shot.png", "file_url": "https://files.todoist.com/x"}

    await client.add_note("t1", "", attachment)

    sent = parse_qs(route.calls.last.request.content.decode())
    (command,) = json.loads(sent["commands"][0])
    assert command["args"]["file_attachment"] == attachment
    assert command["args"]["content"] == ""  # an image needs no words
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_delete_note_removes_one_comment() -> None:
    ids = iter(["u-1"])
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    client = TodoistClient.create("tok", uuid_factory=lambda: next(ids))

    await client.delete_note("c1")

    sent = parse_qs(route.calls.last.request.content.decode())
    (command,) = json.loads(sent["commands"][0])
    assert command["type"] == "note_delete"
    assert command["args"] == {"id": "c1"}
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_upload_sends_the_file_as_multipart_and_answers_the_attachment() -> None:
    """Todoist answers /uploads with the very dict a comment carries."""
    answer = {
        "file_name": "shot.png",
        "file_type": "image/png",
        "file_url": "https://files.todoist.com/x/shot.png",
        "file_size": 40,
        "image_width": 4,
        "image_height": 2,
        "upload_state": "completed",
    }
    route = respx.post(f"{BASE_URL}/uploads").mock(
        return_value=httpx.Response(200, json=answer)
    )
    client = TodoistClient.create("tok")

    assert await client.upload("shot.png", b"\x89PNG data", "image/png") == answer

    request = route.calls.last.request
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert b'name="file"' in body
    assert b'filename="shot.png"' in body
    assert b"\x89PNG data" in body
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_a_refused_upload_surfaces_as_an_http_error() -> None:
    respx.post(f"{BASE_URL}/uploads").mock(return_value=httpx.Response(413))
    client = TodoistClient.create("tok")

    with pytest.raises(httpx.HTTPStatusError):
        await client.upload("shot.png", b"x", "image/png")
    await client.aclose()
