"""Live-API check that a task's comments read back, and that a comment added
after a sync still reaches the count.

Opt-in: `-m smoke`. Writes to the throwaway smoke account and deletes the task
it creates (which takes its comments with it).
"""

import base64
import json
import uuid

import httpx
import pytest

from todoist_tui.api.attachments import HttpAttachments
from todoist_tui.api.client import BASE_URL, TodoistClient
from todoist_tui.api.repository import ApiSnapshotSource, ApiTaskRepository
from todoist_tui.domain.sync_delta import merge
from todoist_tui.domain.task import TaskId
from todoist_tui.domain.upload import PendingUpload

pytestmark = pytest.mark.smoke

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8DwnwEJMKEL0EwA"
    "AH5GAxWoJf3TAAAAAElFTkSuQmCC"
)


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


async def _drop_upload(token: str, file_url: str) -> None:
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}
    ) as http:
        await http.delete("/uploads", params={"file_url": file_url})


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


@pytest.mark.anyio
async def test_an_attached_image_comes_back_down_with_the_token(token: str) -> None:
    """The file host answers an unauthenticated request with its login page, at
    200 — so this checks that the real bytes arrive, not merely a response."""
    mapping = await _command(token, "item_add", {"content": "smoke: attachment"})
    task_id = str(next(iter(mapping.values())))
    client = TodoistClient.create(token)
    repo = ApiTaskRepository(client)
    uploaded: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(
            base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}
        ) as http:
            response = await http.post(
                "/uploads", files={"file": ("smoke.png", _PNG, "image/png")}
            )
            response.raise_for_status()
            uploaded = response.json()

        await _command(
            token,
            "note_add",
            {"item_id": task_id, "content": "", "file_attachment": uploaded},
        )
        (comment,) = await repo.comments(TaskId(task_id))
        attachment = comment.attachment
        assert attachment is not None and attachment.is_image

        async with HttpAttachments.create(token) as files:
            assert await files.fetch(attachment.file_url) == _PNG
            thumbnail = await files.fetch(attachment.preview_url)
        assert thumbnail.startswith(b"\x89PNG")
    finally:
        await _command(token, "item_delete", {"id": task_id})
        if uploaded:  # the upload outlives the task that pointed at it
            await _drop_upload(token, uploaded["file_url"])
        await client.aclose()


@pytest.mark.anyio
async def test_a_comment_written_here_reads_back_and_can_be_taken_away(
    token: str,
) -> None:
    mapping = await _command(token, "item_add", {"content": "smoke: writing"})
    task_id = str(next(iter(mapping.values())))
    client = TodoistClient.create(token)
    repo = ApiTaskRepository(client)
    try:
        await repo.add_comment(TaskId(task_id), "smoke: written here")

        (comment,) = await repo.comments(TaskId(task_id))
        assert comment.content == "smoke: written here"

        await repo.delete_comment(comment.id)
        assert await repo.comments(TaskId(task_id)) == []
    finally:
        await _command(token, "item_delete", {"id": task_id})
        await client.aclose()


@pytest.mark.anyio
async def test_a_file_uploaded_here_comes_back_on_its_comment(token: str) -> None:
    """The whole write path through our own client: upload, attach, read back."""
    mapping = await _command(token, "item_add", {"content": "smoke: attaching"})
    task_id = str(next(iter(mapping.values())))
    client = TodoistClient.create(token)
    repo = ApiTaskRepository(client)
    attachment = None
    try:
        attachment = await repo.upload_attachment(
            PendingUpload("smoke.png", "image/png", _PNG)
        )
        assert attachment.is_image

        await repo.add_comment(TaskId(task_id), "", attachment)

        (comment,) = await repo.comments(TaskId(task_id))
        assert comment.content == ""  # the image is the whole comment
        assert comment.attachment is not None
        assert comment.attachment.file_name == "smoke.png"
    finally:
        await _command(token, "item_delete", {"id": task_id})
        if attachment is not None:
            await _drop_upload(token, attachment.file_url)
        await client.aclose()
