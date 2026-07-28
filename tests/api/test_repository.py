import datetime
import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from todoist_tui.api.client import BASE_URL, TodoistClient
from todoist_tui.api.repository import ApiSnapshotSource, ApiTaskRepository
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.task import TaskId


@pytest.mark.anyio
@respx.mock
async def test_today_maps_json_to_domain_task() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "6X4",
                        "content": "Buy milk",
                        "priority": 3,
                        "project_id": "220",
                        "due": {"date": "2026-07-21T09:30:00", "is_recurring": False},
                    }
                ],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (task,) = await repo.today()

    assert task.id == TaskId("6X4")
    assert task.content == "Buy milk"
    assert task.priority is Priority.P2
    assert task.due is not None
    assert task.due.time == datetime.time(9, 30)
    assert task.project_id == "220"
    assert task.labels == ()


@pytest.mark.anyio
@respx.mock
async def test_today_maps_labels() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "6X4",
                        "content": "Tagged",
                        "priority": 1,
                        "project_id": "220",
                        "due": None,
                        "labels": ["home", "urgent"],
                    }
                ],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (task,) = await repo.today()

    assert task.labels == ("home", "urgent")


@pytest.mark.anyio
@respx.mock
async def test_today_maps_task_without_due() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "1",
                        "content": "No due",
                        "priority": 1,
                        "project_id": "220",
                        "due": None,
                    }
                ],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (task,) = await repo.today()

    assert task.due is None


@pytest.mark.anyio
@respx.mock
async def test_filtered_maps_json_and_sends_query() -> None:
    route = respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "6X4",
                        "content": "Do it",
                        "priority": 1,
                        "project_id": "9",
                        "due": None,
                    }
                ],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (task,) = await repo.filtered("overdue & p1")

    assert task.id == TaskId("6X4")
    assert route.calls.last.request.url.params["query"] == "overdue & p1"


@pytest.mark.anyio
@respx.mock
async def test_filters_reads_saved_filters_via_sync() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [],
                "projects": [],
                "filters": [
                    {"id": "f1", "name": "P1", "query": "p1", "item_order": 1},
                    {
                        "id": "f2",
                        "name": "Gone",
                        "query": "today",
                        "item_order": 2,
                        "is_deleted": True,
                    },
                ],
                "sync_token": "t",
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (f,) = await repo.filters()

    assert (f.id, f.name, f.query, f.order) == ("f1", "P1", "p1", 1)


@pytest.mark.anyio
@respx.mock
async def test_inbox_fetches_tasks_of_inbox_project() -> None:
    respx.get(f"{BASE_URL}/projects").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "9", "name": "Work", "inbox_project": False},
                    {"id": "220", "name": "Eingang", "inbox_project": True},
                ],
                "next_cursor": None,
            },
        )
    )
    tasks_route = respx.get(f"{BASE_URL}/tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "6X4",
                        "content": "Sort me",
                        "priority": 1,
                        "project_id": "220",
                        "due": None,
                    }
                ],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (task,) = await repo.inbox()

    assert task.id == TaskId("6X4")
    assert tasks_route.calls.last.request.url.params["project_id"] == "220"


@pytest.mark.anyio
@respx.mock
async def test_inbox_raises_when_no_inbox_project() -> None:
    respx.get(f"{BASE_URL}/projects").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": "9", "name": "Work", "inbox_project": False}],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    with pytest.raises(LookupError, match="inbox"):
        await repo.inbox()


@pytest.mark.anyio
@respx.mock
async def test_projects_maps_json_to_domain_project() -> None:
    respx.get(f"{BASE_URL}/projects").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "220", "name": "Inbox", "inbox_project": True},
                    {"id": "9", "name": "Work", "inbox_project": False},
                ],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    inbox, work = await repo.projects()

    assert (inbox.id, inbox.name, inbox.is_inbox) == ("220", "Inbox", True)
    assert (work.id, work.name, work.is_inbox) == ("9", "Work", False)


@pytest.mark.anyio
@respx.mock
async def test_delta_none_does_a_full_sync() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [
                    {
                        "id": "6X4",
                        "content": "Sort me",
                        "priority": 1,
                        "project_id": "220",
                        "due": None,
                    }
                ],
                "projects": [
                    {"id": "220", "name": "Eingang", "inbox_project": True},
                    {"id": "9", "name": "Work", "inbox_project": False},
                ],
                "sync_token": "abc",
            },
        )
    )
    source = ApiSnapshotSource(TodoistClient.create("tok"))

    delta = await source.delta(None)

    assert delta.full_sync is True
    assert parse_qs(route.calls.last.request.content.decode())["sync_token"] == ["*"]
    assert [(p.id, p.is_inbox) for p in delta.projects] == [("220", True), ("9", False)]
    (task,) = delta.tasks
    assert task.id == TaskId("6X4")
    assert delta.sync_token == "abc"


@pytest.mark.anyio
@respx.mock
async def test_delta_incremental_splits_deletions_and_completions() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": False,
                "items": [
                    {
                        "id": "keep",
                        "content": "still here",
                        "priority": 1,
                        "project_id": "9",
                        "due": None,
                    },
                    {
                        "id": "gone",
                        "content": "removed",
                        "priority": 1,
                        "project_id": "9",
                        "due": None,
                        "is_deleted": True,
                    },
                    {
                        "id": "done",
                        "content": "completed",
                        "priority": 1,
                        "project_id": "9",
                        "due": None,
                        "checked": True,
                    },
                ],
                "projects": [
                    {"id": "9", "name": "Work", "inbox_project": False},
                    {"id": "old", "name": "Gone", "is_deleted": True},
                ],
                "sync_token": "next",
            },
        )
    )
    source = ApiSnapshotSource(TodoistClient.create("tok"))

    delta = await source.delta("prev")

    assert parse_qs(route.calls.last.request.content.decode())["sync_token"] == ["prev"]
    assert delta.full_sync is False
    assert [str(t.id) for t in delta.tasks] == ["keep"]
    assert delta.deleted_task_ids == frozenset({"gone", "done"})
    assert [p.id for p in delta.projects] == ["9"]
    assert delta.deleted_project_ids == frozenset({"old"})
    assert delta.sync_token == "next"


@pytest.mark.anyio
@respx.mock
async def test_delta_parses_and_splits_filters() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [],
                "projects": [],
                "filters": [
                    {"id": "f1", "name": "P1", "query": "p1", "item_order": 1},
                    {
                        "id": "f2",
                        "name": "Old",
                        "query": "today",
                        "item_order": 2,
                        "is_deleted": True,
                    },
                ],
                "sync_token": "abc",
            },
        )
    )
    source = ApiSnapshotSource(TodoistClient.create("tok"))

    delta = await source.delta(None)

    assert [(f.id, f.name, f.query, f.order) for f in delta.filters] == [
        ("f1", "P1", "p1", 1)
    ]
    assert delta.deleted_filter_ids == frozenset({"f2"})


@pytest.mark.anyio
@respx.mock
async def test_delta_tolerates_missing_filters_key() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [],
                "projects": [],
                "sync_token": "abc",
            },
        )
    )
    source = ApiSnapshotSource(TodoistClient.create("tok"))

    delta = await source.delta(None)

    assert delta.filters == []
    assert delta.deleted_filter_ids == frozenset()


@pytest.mark.anyio
@respx.mock
async def test_complete_closes_the_task() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.complete(TaskId("6X4"))

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "item_close"
    assert commands[0]["args"] == {"id": "6X4"}


@pytest.mark.anyio
@respx.mock
async def test_uncomplete_reopens_the_task() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.uncomplete(TaskId("6X4"))

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "item_uncomplete"
    assert commands[0]["args"] == {"id": "6X4"}


@pytest.mark.anyio
@respx.mock
async def test_set_priority_updates_the_task() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.set_priority(TaskId("6X4"), Priority.P1)

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "item_update"
    assert commands[0]["args"] == {"id": "6X4", "priority": 4}  # P1 -> Todoist 4


@pytest.mark.anyio
async def test_refresh_is_a_noop() -> None:
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    assert await repo.refresh() is None  # no cache to invalidate, no network trip
