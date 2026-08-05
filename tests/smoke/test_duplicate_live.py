"""Live-API check that duplicating a project recreates its sections and tasks.

Opt-in: `-m smoke`. Writes to the throwaway smoke account and deletes both the
source and the copy afterwards. Uses only free-tier fields (priority, labels) so
it never trips PREMIUM_ONLY.
"""

import json
import uuid

import httpx
import pytest

from todoist_tui.api.client import BASE_URL, TodoistClient
from todoist_tui.api.repository import ApiTaskRepository
from todoist_tui.application.duplicate import duplicate_project
from todoist_tui.domain.priority import Priority

pytestmark = pytest.mark.smoke


async def _create_source(http: httpx.AsyncClient) -> str:
    """Create a project with one section and one labelled P2 task in it; return
    the project id."""
    project, section, task = (str(uuid.uuid4()) for _ in range(3))
    commands = [
        {
            "type": "project_add",
            "uuid": str(uuid.uuid4()),
            "temp_id": project,
            "args": {"name": "SMOKE dup src (auto-delete)"},
        },
        {
            "type": "section_add",
            "uuid": str(uuid.uuid4()),
            "temp_id": section,
            "args": {"name": "Sec", "project_id": project},
        },
        {
            "type": "item_add",
            "uuid": str(uuid.uuid4()),
            "temp_id": task,
            "args": {
                "content": "t",
                "project_id": project,
                "section_id": section,
                "priority": 3,
                "labels": ["smoke"],
            },
        },
    ]
    response = await http.post("/sync", data={"commands": json.dumps(commands)})
    response.raise_for_status()
    return str(response.json()["temp_id_mapping"][project])


async def _delete_project(http: httpx.AsyncClient, project_id: str) -> None:
    await http.post(
        "/sync",
        data={
            "commands": json.dumps(
                [
                    {
                        "type": "project_delete",
                        "uuid": str(uuid.uuid4()),
                        "args": {"id": project_id},
                    }
                ]
            )
        },
    )


@pytest.mark.anyio
async def test_duplicate_project_recreates_sections_and_tasks(token: str) -> None:
    client = TodoistClient.create(token)
    repo = ApiTaskRepository(client)
    http = httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}
    )
    source_id = await _create_source(http)
    copy_id: str | None = None
    try:
        await duplicate_project(repo, source_id, "SMOKE dup copy (auto-delete)")

        copy = next(
            (
                p
                for p in await repo.projects()
                if p.name == "SMOKE dup copy (auto-delete)"
            ),
            None,
        )
        assert copy is not None
        copy_id = copy.id

        sections = [s for s in await repo.sections() if s.project_id == copy.id]
        assert [s.name for s in sections] == ["Sec"]

        (task,) = await repo.by_project(copy.id)
        assert task.content == "t"
        assert task.priority is Priority.P2
        assert task.labels == ("smoke",)
        assert task.section_id == sections[0].id
    finally:
        if copy_id is not None:
            await _delete_project(http, copy_id)
        await _delete_project(http, source_id)
        await http.aclose()
        await client.aclose()
