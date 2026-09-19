"""Live-API check that a task's comments read back, and that a comment added
after a sync still reaches the count.

Opt-in: `-m smoke`. Writes to the throwaway smoke account and deletes the task
it creates (which takes its comments with it).
"""

import json
import uuid

import httpx
import pytest

from todoist_tui.api.client import BASE_URL, TodoistClient
from todoist_tui.api.repository import ApiSnapshotSource, ApiTaskRepository
from todoist_tui.domain.sync_delta import merge
from todoist_tui.domain.task import TaskId

pytestmark = pytest.mark.smoke


async def _command(token: str, type_: str, args: dict[str, object]) -> dict[str, str]:
    """Run one Sync command straight, returning its temp_id mapping — the app's
    client has no item_add/note_add of its own yet."""
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}
    ) as http:
        response = await http.post(
            "/sync",
            data={
                "commands": json.dumps(
                    [
                        {
                            "type": type_,
                            "uuid": str(uuid.uuid4()),
                            "temp_id": str(uuid.uuid4()),
                            "args": args,
                        }
                    ]
                )
            },
        )
        response.raise_for_status()
        body = response.json()
        assert all(status == "ok" for status in body["sync_status"].values()), body
        return body["temp_id_mapping"]


@pytest.mark.anyio
async def test_a_comment_reads_back_and_reaches_the_count(token: str) -> None:
    mapping = await _command(token, "item_add", {"content": "smoke: comments"})
    task_id = str(next(iter(mapping.values())))
    client = TodoistClient.create(token)
    repo = ApiTaskRepository(client)
    source = ApiSnapshotSource(client)
    try:
        # sync first, so the comment lands after the token: Todoist never
        # re-sends the item for a new comment, only the note itself
        before = merge(None, await source.delta(None))
        assert before.notes.get(task_id) is None

        await _command(
            token, "note_add", {"item_id": task_id, "content": "smoke: hello"}
        )

        (comment,) = await repo.comments(TaskId(task_id))
        assert comment.content == "smoke: hello"
        assert comment.attachment is None

        after = merge(before, await source.delta(before.sync_token))
        counted = next(t for t in after.tasks if str(t.id) == task_id)
        assert counted.note_count == 1
    finally:
        await _command(token, "item_delete", {"id": task_id})
        await client.aclose()
