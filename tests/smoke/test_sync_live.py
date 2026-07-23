"""Read-only live-API checks for incremental /sync. Opt-in: `-m smoke`. Never writes."""

import pytest

from todoist_tui.api.client import TodoistClient
from todoist_tui.api.repository import ApiSnapshotSource

pytestmark = pytest.mark.smoke


@pytest.fixture
def source(token: str) -> ApiSnapshotSource:
    return ApiSnapshotSource(TodoistClient.create(token))


@pytest.mark.anyio
async def test_full_then_incremental_reuses_token(source: ApiSnapshotSource) -> None:
    full = await source.delta(None)
    assert full.full_sync is True
    assert full.sync_token

    incremental = await source.delta(full.sync_token)
    assert incremental.full_sync is False  # token is honored, not a re-full-sync
