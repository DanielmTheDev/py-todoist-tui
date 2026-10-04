import pytest

from tests.application.test_add_task import FakeRepository
from todoist_tui.application.add_task import plan_task
from todoist_tui.application.collect import collect_under_new_parent
from todoist_tui.domain.creation import CreationPlan, NewMove
from todoist_tui.domain.task import TaskId


class CreatingRepository(FakeRepository):
    async def apply_creation(self, plan: CreationPlan) -> dict[str, str]:
        await super().apply_creation(plan)
        return {task.temp_id: f"real-{task.temp_id}" for task in plan.tasks}


@pytest.mark.anyio
async def test_collecting_nests_the_tasks_under_the_new_one_in_order() -> None:
    repo = CreatingRepository()
    parent = await plan_task(repo, "Trip", project_id="P", temp_ids=iter(["t-1"]))

    await collect_under_new_parent(repo, parent, [TaskId("B"), TaskId("A")])

    (plan,) = repo.applied
    assert plan.tasks == parent.tasks
    assert plan.moves == (NewMove(TaskId("B"), "t-1"), NewMove(TaskId("A"), "t-1"))


@pytest.mark.anyio
async def test_collecting_answers_the_id_the_new_parent_became() -> None:
    repo = CreatingRepository()
    parent = await plan_task(repo, "Trip", project_id="P", temp_ids=iter(["t-1"]))

    assert await collect_under_new_parent(repo, parent, [TaskId("A")]) == "real-t-1"
