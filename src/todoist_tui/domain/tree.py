from todoist_tui.domain.task import Task, TaskId


def with_descendants(
    matched: list[Task], pool: list[Task]
) -> tuple[list[Task], set[TaskId]]:
    """`matched` plus every subtask of a match found in `pool`.

    A list view's query returns only the tasks that match it, so a matching task's
    subtasks are missing and its hierarchy is invisible. Each match keeps its
    subtree directly beneath it, so the result nests the way the caller renders it.
    Returns the tasks and the ids present *only* as a descendant — those did not
    match, so they are not members of the view.
    """
    children: dict[str, list[Task]] = {}
    for task in pool:
        if task.parent_id is not None:
            children.setdefault(task.parent_id, []).append(task)
    matched_ids = {task.id for task in matched}
    out: list[Task] = []
    seen: set[TaskId] = set()

    def emit(task: Task) -> None:
        if task.id in seen:  # a parent cycle would otherwise recurse forever
            return
        seen.add(task.id)
        out.append(task)
        for child in children.get(str(task.id), ()):
            emit(child)

    for task in matched:
        emit(task)
    return out, seen - matched_ids
