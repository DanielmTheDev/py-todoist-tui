from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.sync_delta import SyncDelta, merge
from todoist_tui.domain.task import Task, TaskId


def _filter(fid: str, name: str | None = None) -> Filter:
    return Filter(id=fid, name=name or fid, query="today", order=0)


def _task(task_id: str, project_id: str = "9", content: str | None = None) -> Task:
    return Task(
        id=TaskId(task_id),
        content=content or task_id,
        priority=Priority.P2,
        due=None,
        project_id=project_id,
    )


def _prior() -> Snapshot:
    return Snapshot(
        projects=[
            Project(id="220", name="Inbox", is_inbox=True),
            Project(id="9", name="Work"),
        ],
        tasks=[_task("a", "220"), _task("b", "9")],
        sync_token="old",
    )


def test_full_sync_replaces_prior_state() -> None:
    delta = SyncDelta(
        projects=[Project(id="1", name="New")],
        tasks=[_task("z", "1")],
        deleted_project_ids=frozenset(),
        deleted_task_ids=frozenset(),
        sync_token="new",
        full_sync=True,
    )

    merged = merge(_prior(), delta)

    assert [p.id for p in merged.projects] == ["1"]
    assert [str(t.id) for t in merged.tasks] == ["z"]
    assert merged.sync_token == "new"


def test_no_prior_uses_delta_as_whole_state() -> None:
    delta = SyncDelta(
        projects=[Project(id="1", name="New")],
        tasks=[_task("z", "1")],
        deleted_project_ids=frozenset(),
        deleted_task_ids=frozenset(),
        sync_token="new",
        full_sync=False,
    )

    merged = merge(None, delta)

    assert [p.id for p in merged.projects] == ["1"]
    assert [str(t.id) for t in merged.tasks] == ["z"]
    assert merged.sync_token == "new"


def test_incremental_upserts_and_deletes_in_place() -> None:
    delta = SyncDelta(
        projects=[Project(id="9", name="Work renamed")],
        tasks=[_task("b", "9", content="b edited"), _task("c", "9")],
        deleted_project_ids=frozenset(),
        deleted_task_ids=frozenset({"a"}),
        sync_token="new",
        full_sync=False,
    )

    merged = merge(_prior(), delta)

    assert [(p.id, p.name) for p in merged.projects] == [
        ("220", "Inbox"),
        ("9", "Work renamed"),
    ]
    assert [(str(t.id), t.content) for t in merged.tasks] == [
        ("b", "b edited"),
        ("c", "c"),
    ]
    assert merged.sync_token == "new"


def test_full_sync_replaces_filters() -> None:
    prior = Snapshot(projects=[], tasks=[], sync_token="old", filters=[_filter("x")])
    delta = SyncDelta(
        projects=[],
        tasks=[],
        deleted_project_ids=frozenset(),
        deleted_task_ids=frozenset(),
        sync_token="new",
        full_sync=True,
        filters=[_filter("y")],
    )

    assert [f.id for f in merge(prior, delta).filters] == ["y"]


def test_incremental_upserts_and_deletes_filters() -> None:
    prior = Snapshot(
        projects=[],
        tasks=[],
        sync_token="old",
        filters=[_filter("a", "A"), _filter("b", "B")],
    )
    delta = SyncDelta(
        projects=[],
        tasks=[],
        deleted_project_ids=frozenset(),
        deleted_task_ids=frozenset(),
        sync_token="new",
        full_sync=False,
        filters=[_filter("b", "B renamed")],
        deleted_filter_ids=frozenset({"a"}),
    )

    merged = merge(prior, delta)

    assert [(f.id, f.name) for f in merged.filters] == [("b", "B renamed")]


def test_incremental_removes_deleted_project() -> None:
    delta = SyncDelta(
        projects=[],
        tasks=[],
        deleted_project_ids=frozenset({"9"}),
        deleted_task_ids=frozenset(),
        sync_token="new",
        full_sync=False,
    )

    merged = merge(_prior(), delta)

    assert [p.id for p in merged.projects] == ["220"]
