import datetime
import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from todoist_tui.api.client import BASE_URL, TodoistClient
from todoist_tui.api.repository import ApiTaskRepository
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
            json={"results": [{"id": "220", "name": "Inbox"}], "next_cursor": None},
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (project,) = await repo.projects()

    assert project.id == "220"
    assert project.name == "Inbox"


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
