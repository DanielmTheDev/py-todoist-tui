"""Live-API check that our reminder_add/reminder_delete payloads are accepted.

Opt-in: `-m smoke`. Writes to the throwaway smoke account and cleans up after
itself. Reminders are a Todoist Premium feature, so on a free account the add is
rejected with PREMIUM_ONLY and the test skips rather than fails.
"""

import json
import uuid

import httpx
import pytest

from todoist_tui.api.client import BASE_URL, SyncCommandError, TodoistClient
from todoist_tui.api.repository import ApiSnapshotSource

pytestmark = pytest.mark.smoke


async def _add_timed_task(token: str) -> str:
    """Create a task with a due datetime; return its id (raw sync, no client API
    for item_add since the app never creates tasks itself)."""
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
                            "args": {
                                "content": "SMOKE reminders (auto-delete)",
                                "due": {"date": "2030-01-01T09:00:00"},
                            },
                        }
                    ]
                )
            },
        )
        response.raise_for_status()
        return str(response.json()["temp_id_mapping"][temp])


@pytest.mark.anyio
async def test_add_then_delete_a_reminder(token: str) -> None:
    client = TodoistClient.create(token)
    source = ApiSnapshotSource(client)
    task_id = await _add_timed_task(token)
    try:
        try:
            await client.add_reminder(
                task_id, {"type": "relative", "minute_offset": 30}
            )
        except SyncCommandError as error:
            if "Premium" in str(error):
                pytest.skip("reminders are Premium-only; smoke account is free")
            raise

        delta = await source.delta(None)
        mine = [r for r in delta.reminders if r.item_id == task_id]
        assert mine and mine[0].type == "relative" and mine[0].minute_offset == 30

        await client.delete_reminder(mine[0].id)
        after = await source.delta(None)
        assert not [r for r in after.reminders if r.item_id == task_id]
    finally:
        await client.delete_item(task_id)
        await client.aclose()
