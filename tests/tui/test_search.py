import asyncio

import pytest
from textual.widgets import DataTable, Input, Static

from tests.tui.test_app import FakeRepository
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.tui.app import InMemoryHome, TodoistApp
from todoist_tui.tui.screens.search import SearchScreen

_PROJECTS = [Project(id="220", name="Errands")]


def _task(content: str) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=None,
        project_id="220",
    )


class SearchingRepository(FakeRepository):
    """Records the queries served from cache, alongside the refreshed ones."""

    def __init__(
        self, tasks: list[Task], projects: list[Project] | None = None
    ) -> None:
        super().__init__(tasks, projects or _PROJECTS)
        self.filtered_queries: list[str] = []
        self.release = asyncio.Event()  # held open so a resync can be blocked
        self.release.set()

    async def filtered(self, query: str) -> list[Task]:
        self.filtered_queries.append(query)
        return list(self._tasks)

    async def refresh(self) -> None:
        await self.release.wait()
        await super().refresh()


def _status(app: TodoistApp) -> str:
    return str(app.query_one("#status", Static).render())


def _contents(app: TodoistApp) -> list[str]:
    table = app.query_one(DataTable[object])
    column = list(table.columns)[1]  # 0 is the priority dot
    return [str(table.get_cell(row, column)) for row in table.rows]


@pytest.mark.anyio
async def test_slash_opens_the_search_modal() -> None:
    app = TodoistApp(SearchingRepository([]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)


@pytest.mark.anyio
async def test_slash_inside_the_modal_types_rather_than_stacking() -> None:
    app = TodoistApp(SearchingRepository([]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        screens = [s for s in app.screen_stack if isinstance(s, SearchScreen)]
        assert len(screens) == 1
        assert app.screen.query_one(Input).value == "/"


@pytest.mark.anyio
async def test_enter_promotes_the_search_into_a_view() -> None:
    repo = SearchingRepository([_task("Buy milk")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("m", "i", "l", "k")
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert not isinstance(app.screen, SearchScreen)
        assert _contents(app) == ["Buy milk"]
        assert "Search: milk" in _status(app)
        assert "search: milk" in repo.filtered_queries


@pytest.mark.anyio
async def test_promoted_search_revalidates_live_on_every_sync() -> None:
    repo = SearchingRepository([_task("Buy milk")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("m", "i", "l", "k")
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        repo.refresh_filtered_queries.clear()

        await pilot.press("r")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert repo.refresh_filtered_queries == ["search: milk"]


@pytest.mark.anyio
async def test_leaving_a_search_view_stops_refreshing_it() -> None:
    repo = SearchingRepository([_task("Buy milk")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("m", "i", "l", "k")
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press(".")  # back to Today
        await pilot.pause()
        repo.refresh_filtered_queries.clear()

        await pilot.press("r")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert repo.refresh_filtered_queries == []


@pytest.mark.anyio
async def test_tasks_stay_interactive_in_a_search_view() -> None:
    repo = SearchingRepository([_task("Buy milk")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("m", "i", "l", "k")
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        await pilot.press("e")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert repo.completed == [TaskId("Buy milk")]


@pytest.mark.anyio
async def test_rescheduling_keeps_a_still_matching_row_in_place() -> None:
    # unlike a saved filter, a due date cannot change what `search:` matches
    repo = SearchingRepository([_task("Buy milk")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("m", "i", "l", "k")
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        repo.release.clear()  # block the resync that would mask a wrong drop
        await pilot.press("t")  # schedule
        await pilot.pause()
        await pilot.press("m")  # tomorrow
        await pilot.pause()
        assert _contents(app) == ["Buy milk"]


@pytest.mark.anyio
async def test_moving_keeps_a_still_matching_row_in_place() -> None:
    repo = SearchingRepository(
        [_task("Buy milk")], [*_PROJECTS, Project(id="9", name="Work")]
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("m", "i", "l", "k")
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        repo.release.clear()  # block the resync that would mask a wrong drop
        await pilot.press("v")  # move
        await pilot.pause()
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await pilot.pause()
        assert _contents(app) == ["Buy milk"]


@pytest.mark.anyio
async def test_cancelling_the_search_keeps_the_current_view() -> None:
    repo = SearchingRepository([_task("Buy milk")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("m", "i", "l", "k")
        await pilot.press("escape")
        await pilot.pause()
        assert "Today" in _status(app)
        assert repo.filtered_queries == []


@pytest.mark.anyio
async def test_a_search_view_can_be_set_as_home_and_reopened() -> None:
    home = InMemoryHome()
    repo = SearchingRepository([_task("Buy milk")])
    app = TodoistApp(repo, home=home)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("m", "i", "l", "k")
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("H")
        await pilot.pause()
    assert await home.get() == "search:milk"

    reopened = SearchingRepository([_task("Buy milk")])
    app = TodoistApp(reopened, home=home)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert _contents(app) == ["Buy milk"]
        assert "Search: milk" in _status(app)
        assert reopened.refresh_filtered_queries == ["search: milk"]


@pytest.mark.anyio
async def test_the_preview_searches_through_the_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SearchScreen, "DEBOUNCE", 0.0)
    repo = SearchingRepository([_task("Buy milk")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("m", "i")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert repo.filtered_queries == ["search: mi"]
