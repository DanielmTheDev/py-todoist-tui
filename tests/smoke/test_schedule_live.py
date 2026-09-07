"""Live-API check that scheduling by phrase answers with the due Todoist parsed.

Opt-in: `-m smoke`. Writes to the throwaway smoke account and cleans up after
itself. The default reminder a due time earns rides on that answer, so a phrase
read back without its time would leave the task silent.
"""

import datetime
import json
import uuid

import httpx
import pytest

from todoist_tui.api.client import BASE_URL, TodoistClient
from todoist_tui.api.repository import ApiTaskRepository
from todoist_tui.domain.due import DueText
from todoist_tui.domain.task import TaskId

pytestmark = pytest.mark.smoke


async def _add_task(token: str) -> str:
    """Create an undated task; return its id (no client API for item_add — the
    app creates tasks through a whole `CreationPlan`)."""
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}
    ) as http:
        temp = str(uuid.uuid4())
        response = await http.post(
            "/sync",
            data={
                "commands": json.dumps(
                    [
                        {
                            "type": "item_add",
                            "uuid": str(uuid.uuid4()),
                            "temp_id": temp,
                            "args": {"content": "SMOKE schedule (auto-delete)"},
                        }
                    ]
                )
            },
        )
        response.raise_for_status()
        return str(response.json()["temp_id_mapping"][temp])


@pytest.mark.anyio
async def test_a_due_phrase_naming_a_time_lands_as_a_timed_due(token: str) -> None:
    client = TodoistClient.create(token)
    repo = ApiTaskRepository(client)
    task_id = await _add_task(token)
    try:
        landed = await repo.set_due(TaskId(task_id), DueText("tod 23:55"))

        assert landed is not None
        assert landed.time == datetime.time(23, 55)
    finally:
        await client.delete_item(task_id)
        await client.aclose()


@pytest.mark.anyio
async def test_a_due_phrase_without_a_time_lands_all_day(token: str) -> None:
    client = TodoistClient.create(token)
    repo = ApiTaskRepository(client)
    task_id = await _add_task(token)
    try:
        landed = await repo.set_due(TaskId(task_id), DueText("tomorrow"))

        assert landed is not None
        assert landed.time is None
    finally:
        await client.delete_item(task_id)
        await client.aclose()
