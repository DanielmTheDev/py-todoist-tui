import datetime

import pytest

from todoist_tui.application.activity import load_activity
from todoist_tui.domain.activity import ActivityEvent, ActivityPage, EventKind
from todoist_tui.domain.project import Project


def _event(task_id: str, project_id: str | None) -> ActivityEvent:
    return ActivityEvent(
        id=task_id,
        at=datetime.datetime(2026, 8, 27, 11, 24, tzinfo=datetime.UTC),
        kind=EventKind.COMPLETED,
        content=f"task {task_id}",
        task_id=task_id,
        project_id=project_id,
    )


class FakeRepo:
    def __init__(self, page: ActivityPage) -> None:
        self.calls: list[tuple[EventKind | None, str | None]] = []
        self._page = page

    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        self.calls.append((event_type, cursor))
        return self._page

    async def projects(self) -> list[Project]:
        return [Project(id="9", name="Work")]


@pytest.mark.anyio
async def test_rows_carry_the_project_name() -> None:
    repo = FakeRepo(ActivityPage(events=(_event("a", "9"),), next_cursor="more"))

    rows, cursor = await load_activity(repo)  # pyright: ignore[reportArgumentType]

    assert cursor == "more"
    assert [(row.event.task_id, row.project_name) for row in rows] == [("a", "Work")]


@pytest.mark.anyio
async def test_unknown_or_missing_project_leaves_the_name_empty() -> None:
    page = ActivityPage(
        events=(_event("a", "404"), _event("b", None)), next_cursor=None
    )
    repo = FakeRepo(page)

    rows, cursor = await load_activity(repo)  # pyright: ignore[reportArgumentType]

    assert cursor is None
    assert [row.project_name for row in rows] == [None, None]


@pytest.mark.anyio
async def test_filter_and_cursor_reach_the_repository() -> None:
    repo = FakeRepo(ActivityPage(events=(), next_cursor=None))

    await load_activity(
        repo,  # pyright: ignore[reportArgumentType]
        event_type=EventKind.ADDED,
        cursor="abc",
    )

    assert repo.calls == [(EventKind.ADDED, "abc")]
