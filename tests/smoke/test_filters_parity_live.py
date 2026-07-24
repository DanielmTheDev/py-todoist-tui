"""Parity gate: every saved filter fetches via our stack == server endpoint.

Read-only live-API check. Opt-in: `uv run pytest -m smoke`. Never writes.
Confirms saved filters sync/parse and that each account filter's query is
accepted by Todoist and mapped without dropping tasks.
"""

import pytest

from todoist_tui.api.client import TodoistClient
from todoist_tui.api.repository import ApiSnapshotSource, ApiTaskRepository
from todoist_tui.domain.sync_delta import merge

pytestmark = pytest.mark.smoke


@pytest.mark.anyio
async def test_saved_filters_sync_and_parse(token: str) -> None:
    client = TodoistClient.create(token)

    snapshot = merge(None, await ApiSnapshotSource(client).delta(None))

    for f in snapshot.filters:  # every synced filter must be usable
        assert f.name and f.query


@pytest.mark.anyio
async def test_each_saved_filter_matches_server(token: str) -> None:
    client = TodoistClient.create(token)
    repo = ApiTaskRepository(client)
    snapshot = merge(None, await ApiSnapshotSource(client).delta(None))
    if not snapshot.filters:
        pytest.skip("account has no saved filters")

    for f in snapshot.filters:
        ours = {str(t.id) for t in await repo.filtered(f.query)}
        server = {str(record["id"]) for record in await client.filter_tasks(f.query)}
        assert ours == server, f"filter {f.name!r} ({f.query!r}) mismatch"
