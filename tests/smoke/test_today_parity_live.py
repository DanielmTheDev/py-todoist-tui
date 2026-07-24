"""Parity gate: client-side `today` == server `/tasks/filter?query=today`.

Read-only live-API check. Opt-in: `uv run pytest -m smoke`. Never writes.
This must pass before trusting the client-side cutover in SnapshotTaskRepository.
"""

import pytest

from todoist_tui.api.client import TodoistClient
from todoist_tui.api.repository import ApiSnapshotSource
from todoist_tui.domain.clock import SystemClock
from todoist_tui.domain.filter_query import FilterQuery
from todoist_tui.domain.sync_delta import merge

pytestmark = pytest.mark.smoke


@pytest.mark.anyio
async def test_client_today_matches_server_filter(token: str) -> None:
    client = TodoistClient.create(token)

    server_ids = {str(record["id"]) for record in await client.today_tasks()}

    snapshot = merge(None, await ApiSnapshotSource(client).delta(None))
    query = FilterQuery("today")
    today = SystemClock().today()
    client_ids = {str(t.id) for t in snapshot.tasks if query.matches(t, today)}

    assert client_ids == server_ids
