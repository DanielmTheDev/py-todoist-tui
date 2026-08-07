import pytest

from tests.application.test_complete import FakeRepository
from todoist_tui.application.delete import delete_section, delete_task
from todoist_tui.domain.task import TaskId


@pytest.mark.anyio
async def test_delete_task_delegates_to_repo() -> None:
    repo = FakeRepository()

    await delete_task(repo, TaskId("6X4"))

    assert repo.deleted == [TaskId("6X4")]


@pytest.mark.anyio
async def test_delete_section_delegates_to_repo() -> None:
    repo = FakeRepository()

    await delete_section(repo, "6S1")

    assert repo.deleted_sections == ["6S1"]
