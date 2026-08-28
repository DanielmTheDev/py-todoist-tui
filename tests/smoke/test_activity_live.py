"""Read-only live-API checks. Opt-in: `uv run pytest -m smoke`. Never writes."""

import pytest

from todoist_tui.api.client import TodoistClient
from todoist_tui.api.repository import ApiTaskRepository
from todoist_tui.domain.activity import ActivityEvent

pytestmark = pytest.mark.smoke


@pytest.fixture
def repo(token: str) -> ApiTaskRepository:
    return ApiTaskRepository(TodoistClient.create(token))


@pytest.mark.anyio
async def test_activity_answers_with_a_page(repo: ApiTaskRepository) -> None:
    page = await repo.activity()

    assert isinstance(page.events, tuple)
    assert page.next_cursor is None or isinstance(page.next_cursor, str)


@pytest.mark.anyio
async def test_events_carry_a_time_and_a_task(repo: ApiTaskRepository) -> None:
    page = await repo.activity()
    if not page.events:  # a free account's log can be empty
        pytest.skip("no activity on this account")

    event = page.events[0]
    assert isinstance(event, ActivityEvent)
    assert event.at.tzinfo is not None
    assert event.task_id
