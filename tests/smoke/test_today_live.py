"""Read-only live-API checks. Opt-in: `uv run pytest -m smoke`. Never writes."""

import pytest

from todoist_tui.api.client import TodoistClient
from todoist_tui.api.repository import ApiTaskRepository
from todoist_tui.application.today import load_today
from todoist_tui.config import ConfigError, default_config_path, load_token
from todoist_tui.domain.task import Task

pytestmark = pytest.mark.smoke


@pytest.fixture
def repo() -> ApiTaskRepository:
    try:
        token = load_token(default_config_path())
    except ConfigError as error:
        pytest.skip(f"no Todoist token: {error}")
    return ApiTaskRepository(TodoistClient.create(token))


@pytest.mark.anyio
async def test_today_returns_tasks(repo: ApiTaskRepository) -> None:
    tasks = await repo.today()

    assert isinstance(tasks, list)
    assert all(isinstance(task, Task) for task in tasks)


@pytest.mark.anyio
async def test_load_today_joins_projects(repo: ApiTaskRepository) -> None:
    rows = await load_today(repo)

    assert isinstance(rows, list)
