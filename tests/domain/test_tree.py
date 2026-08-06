from todoist_tui.domain.priority import Priority
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.domain.tree import with_descendants


def _task(task_id: str, parent_id: str | None = None) -> Task:
    return Task(
        id=TaskId(task_id),
        content=task_id,
        priority=Priority.P4,
        due=None,
        project_id="1",
        parent_id=parent_id,
    )


def _ids(tasks: list[Task]) -> list[str]:
    return [str(task.id) for task in tasks]


def test_a_match_pulls_in_its_whole_subtree() -> None:
    parent, child, grandchild = _task("p"), _task("c", "p"), _task("g", "c")

    tasks, injected = with_descendants([parent], [parent, child, grandchild])

    assert _ids(tasks) == ["p", "c", "g"]
    assert injected == {TaskId("c"), TaskId("g")}


def test_a_match_without_subtasks_is_untouched() -> None:
    lone, unrelated = _task("a"), _task("b")

    tasks, injected = with_descendants([lone], [lone, unrelated])

    assert _ids(tasks) == ["a"]
    assert injected == set()


def test_a_child_that_matched_is_not_duplicated_nor_marked_injected() -> None:
    parent, child = _task("p"), _task("c", "p")

    tasks, injected = with_descendants([parent, child], [parent, child])

    assert _ids(tasks) == ["p", "c"]
    assert injected == set()


def test_each_match_keeps_its_subtree_beneath_it() -> None:
    first, second = _task("1"), _task("2")
    kid_of_first, kid_of_second = _task("1a", "1"), _task("2a", "2")
    pool = [first, second, kid_of_first, kid_of_second]

    tasks, _injected = with_descendants([first, second], pool)

    assert _ids(tasks) == ["1", "1a", "2", "2a"]


def test_a_matching_subtask_whose_parent_is_absent_stays_flat() -> None:
    parent, child = _task("p"), _task("c", "p")

    tasks, injected = with_descendants([child], [parent, child])

    assert _ids(tasks) == ["c"]  # the parent is not pulled in
    assert injected == set()


def test_a_parent_cycle_terminates() -> None:
    a, b = _task("a", "b"), _task("b", "a")

    tasks, _injected = with_descendants([a], [a, b])

    assert _ids(tasks) == ["a", "b"]
