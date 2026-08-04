import datetime
import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from todoist_tui.api.client import BASE_URL, TodoistClient
from todoist_tui.api.repository import ApiSnapshotSource, ApiTaskRepository
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reminder import Reminder
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
                        "description": "2% from the corner store",
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
    assert task.section_id is None
    assert task.labels == ()
    assert task.description == "2% from the corner store"
    assert task.deadline is None


@pytest.mark.anyio
@respx.mock
async def test_today_maps_deadline() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "6X4",
                        "content": "Ship it",
                        "priority": 1,
                        "project_id": "220",
                        "due": None,
                        "deadline": {"date": "2026-08-15", "lang": "en"},
                    }
                ],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (task,) = await repo.today()

    assert task.deadline == Deadline(date=datetime.date(2026, 8, 15))


@pytest.mark.anyio
@respx.mock
async def test_today_maps_section_id() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "6X4",
                        "content": "In a section",
                        "priority": 1,
                        "project_id": "220",
                        "section_id": "77",
                        "due": None,
                    }
                ],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (task,) = await repo.today()

    assert task.section_id == "77"


@pytest.mark.anyio
@respx.mock
async def test_today_defaults_missing_description_to_empty() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "6X4",
                        "content": "No notes",
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

    assert task.description == ""


@pytest.mark.anyio
@respx.mock
async def test_today_maps_parent_id() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "6X4",
                        "content": "A subtask",
                        "priority": 1,
                        "project_id": "220",
                        "due": None,
                        "parent_id": "6X0",
                    }
                ],
                "next_cursor": None,
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (task,) = await repo.today()

    assert task.parent_id == "6X0"


@pytest.mark.anyio
@respx.mock
async def test_today_defaults_missing_parent_id_to_none() -> None:
    respx.get(f"{BASE_URL}/tasks/filter").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "6X4",
                        "content": "Top level",
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

    assert task.parent_id is None


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
async def test_reminders_reads_via_sync_dropping_deleted() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [],
                "projects": [],
                "reminders": [
                    {
                        "id": "r1",
                        "item_id": "t1",
                        "type": "relative",
                        "minute_offset": 30,
                    },
                    {
                        "id": "r2",
                        "item_id": "t1",
                        "type": "absolute",
                        "due": {"date": "2030-01-01T08:30:00"},
                        "is_deleted": True,
                    },
                ],
                "sync_token": "t",
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (r,) = await repo.reminders()

    assert (r.id, r.item_id, r.type, r.minute_offset) == ("r1", "t1", "relative", 30)


@pytest.mark.anyio
@respx.mock
async def test_add_reminder_sends_reminder_add() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.add_reminder(
        Reminder(id="", item_id="6X4", type="relative", minute_offset=30)
    )

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "reminder_add"
    assert commands[0]["args"] == {
        "item_id": "6X4",
        "type": "relative",
        "minute_offset": 30,
    }


@pytest.mark.anyio
@respx.mock
async def test_delete_reminder_sends_reminder_delete() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.delete_reminder("r9")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands == [
        {"type": "reminder_delete", "uuid": "u-1", "args": {"id": "r9"}}
    ]


@pytest.mark.anyio
@respx.mock
async def test_delta_parses_reminders() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [],
                "projects": [],
                "reminders": [
                    {
                        "id": "r1",
                        "item_id": "t1",
                        "type": "relative",
                        "minute_offset": 30,
                    },
                    {
                        "id": "r2",
                        "item_id": "t2",
                        "type": "relative",
                        "is_deleted": True,
                    },
                ],
                "sync_token": "t",
            },
        )
    )
    source = ApiSnapshotSource(TodoistClient.create("tok"))

    delta = await source.delta(None)

    assert [r.id for r in delta.reminders] == ["r1"]
    assert delta.deleted_reminder_ids == frozenset({"r2"})


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
                    {
                        "id": "220",
                        "name": "Eingang",
                        "inbox_project": True,
                        "child_order": 0,
                    },
                    {
                        "id": "9",
                        "name": "Work",
                        "inbox_project": False,
                        "child_order": 5,
                    },
                ],
                "sync_token": "abc",
            },
        )
    )
    source = ApiSnapshotSource(TodoistClient.create("tok"))

    delta = await source.delta(None)

    assert delta.full_sync is True
    assert parse_qs(route.calls.last.request.content.decode())["sync_token"] == ["*"]
    assert [(p.id, p.is_inbox, p.order) for p in delta.projects] == [
        ("220", True, 0),
        ("9", False, 5),
    ]
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
async def test_delta_parses_and_splits_sections() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [],
                "projects": [],
                "sections": [
                    {
                        "id": "s1",
                        "project_id": "9",
                        "name": "Planning",
                        "section_order": 1,
                    },
                    {
                        "id": "s2",
                        "project_id": "9",
                        "name": "Old",
                        "section_order": 2,
                        "is_deleted": True,
                    },
                ],
                "sync_token": "abc",
            },
        )
    )
    source = ApiSnapshotSource(TodoistClient.create("tok"))

    delta = await source.delta(None)

    assert [(s.id, s.project_id, s.name, s.order) for s in delta.sections] == [
        ("s1", "9", "Planning", 1)
    ]
    assert delta.deleted_section_ids == frozenset({"s2"})


@pytest.mark.anyio
@respx.mock
async def test_delta_tolerates_missing_sections_key() -> None:
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

    assert delta.sections == []
    assert delta.deleted_section_ids == frozenset()


@pytest.mark.anyio
@respx.mock
async def test_delta_parses_and_splits_labels() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [],
                "projects": [],
                "labels": [
                    {"id": "l1", "name": "work", "item_order": 1},
                    {"id": "l2", "name": "gone", "item_order": 2, "is_deleted": True},
                ],
                "sync_token": "abc",
            },
        )
    )
    source = ApiSnapshotSource(TodoistClient.create("tok"))

    delta = await source.delta(None)

    assert [(label.id, label.name, label.order) for label in delta.labels] == [
        ("l1", "work", 1)
    ]
    assert delta.deleted_label_ids == frozenset({"l2"})


@pytest.mark.anyio
@respx.mock
async def test_delta_tolerates_missing_labels_key() -> None:
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

    assert delta.labels == []
    assert delta.deleted_label_ids == frozenset()


@pytest.mark.anyio
@respx.mock
async def test_labels_reads_via_sync() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [],
                "projects": [],
                "labels": [
                    {"id": "l1", "name": "work", "item_order": 1},
                    {"id": "l2", "name": "gone", "item_order": 2, "is_deleted": True},
                ],
                "sync_token": "t",
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (label,) = await repo.labels()

    assert (label.id, label.name, label.order) == ("l1", "work", 1)


@pytest.mark.anyio
@respx.mock
async def test_sections_reads_via_sync() -> None:
    respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_sync": True,
                "items": [],
                "projects": [],
                "sections": [
                    {
                        "id": "s1",
                        "project_id": "9",
                        "name": "Planning",
                        "section_order": 1,
                    },
                    {
                        "id": "s2",
                        "project_id": "9",
                        "name": "Gone",
                        "section_order": 2,
                        "is_deleted": True,
                    },
                ],
                "sync_token": "t",
            },
        )
    )
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    (s,) = await repo.sections()

    assert (s.id, s.project_id, s.name, s.order) == ("s1", "9", "Planning", 1)


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
async def test_delete_deletes_the_task() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.delete(TaskId("6X4"))

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "item_delete"
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
@respx.mock
async def test_set_due_updates_the_task() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.set_due(TaskId("6X4"), Due(date=datetime.date(2026, 7, 29)))

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "item_update"
    assert commands[0]["args"] == {"id": "6X4", "due": {"date": "2026-07-29"}}


@pytest.mark.anyio
@respx.mock
async def test_set_due_recurring_sends_string_to_preserve_the_rule() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.set_due(
        TaskId("6X4"),
        Due(
            date=datetime.date(2026, 7, 29),
            is_recurring=True,
            string="every day",
            lang="en",
        ),
    )

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["args"] == {
        "id": "6X4",
        "due": {"date": "2026-07-29", "string": "every day", "lang": "en"},
    }


@pytest.mark.anyio
@respx.mock
async def test_set_due_none_clears_the_task_due() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.set_due(TaskId("6X4"), None)

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["args"] == {"id": "6X4", "due": None}


@pytest.mark.anyio
@respx.mock
async def test_set_deadline_updates_the_task() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.set_deadline(TaskId("6X4"), Deadline(date=datetime.date(2026, 8, 15)))

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "item_update"
    assert commands[0]["args"] == {"id": "6X4", "deadline": {"date": "2026-08-15"}}


@pytest.mark.anyio
@respx.mock
async def test_set_deadline_none_clears_the_task_deadline() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.set_deadline(TaskId("6X4"), None)

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["args"] == {"id": "6X4", "deadline": None}


@pytest.mark.anyio
@respx.mock
async def test_set_project_moves_the_task() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.set_project(TaskId("6X4"), "220")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "item_move"
    assert commands[0]["args"] == {"id": "6X4", "project_id": "220"}


@pytest.mark.anyio
@respx.mock
async def test_set_project_with_section_moves_into_section() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.set_project(TaskId("6X4"), "220", "77")

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "item_move"
    assert commands[0]["args"] == {"id": "6X4", "section_id": "77"}


@pytest.mark.anyio
@respx.mock
async def test_set_labels_updates_the_task() -> None:
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"u-1": "ok"}})
    )
    repo = ApiTaskRepository(TodoistClient.create("tok", uuid_factory=lambda: "u-1"))

    await repo.set_labels(TaskId("6X4"), ("home", "urgent"))

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert commands[0]["type"] == "item_update"
    assert commands[0]["args"] == {"id": "6X4", "labels": ["home", "urgent"]}


@pytest.mark.anyio
@respx.mock
async def test_set_labels_creates_unknown_labels_first() -> None:
    ids = iter(["a", "b", "c"])
    route = respx.post(f"{BASE_URL}/sync").mock(
        return_value=httpx.Response(200, json={"sync_status": {"a": "ok", "c": "ok"}})
    )
    repo = ApiTaskRepository(
        TodoistClient.create("tok", uuid_factory=lambda: next(ids))
    )

    await repo.set_labels(TaskId("6X4"), ("fresh",), create=("fresh",))

    commands = json.loads(
        parse_qs(route.calls.last.request.content.decode())["commands"][0]
    )
    assert [c["type"] for c in commands] == ["label_add", "item_update"]
    assert commands[0]["args"] == {"name": "fresh"}


@pytest.mark.anyio
async def test_refresh_is_a_noop() -> None:
    repo = ApiTaskRepository(TodoistClient.create("tok"))

    assert await repo.refresh() is None  # no cache to invalidate, no network trip
