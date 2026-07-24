import asyncio
import datetime

import pytest
from textual.widgets import DataTable, Footer, Static

from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.tui.app import TaskTable, TodoistApp
from todoist_tui.tui.screens.filters import FilterScreen


class FakeRepository:
    def __init__(
        self,
        tasks: list[Task],
        projects: list[Project],
        inbox: list[Task] | None = None,
        filters: list[Filter] | None = None,
    ) -> None:
        self._tasks = tasks
        self._projects = projects
        self._inbox = inbox or []
        self._filters = filters or []
        self.completed: list[TaskId] = []
        self.uncompleted: list[TaskId] = []
        self._removed: dict[TaskId, Task] = {}
        self.today_calls = 0
        self.refresh_calls = 0
        self.refresh_filtered_queries: list[str] = []

    async def today(self) -> list[Task]:
        self.today_calls += 1
        return list(self._tasks)

    async def inbox(self) -> list[Task]:
        return list(self._inbox)

    async def filtered(self, query: str) -> list[Task]:
        return list(self._tasks)

    async def refresh_filtered(self, query: str) -> list[Task]:
        self.refresh_filtered_queries.append(query)
        return list(self._tasks)

    async def projects(self) -> list[Project]:
        return self._projects

    async def filters(self) -> list[Filter]:
        return list(self._filters)

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)
        self._removed.update({t.id: t for t in self._tasks if t.id == task_id})
        self._tasks = [t for t in self._tasks if t.id != task_id]

    async def uncomplete(self, task_id: TaskId) -> None:
        self.uncompleted.append(task_id)
        restored = self._removed.pop(task_id, None)
        if restored is not None:
            self._tasks = [*self._tasks, restored]

    async def refresh(self) -> None:
        self.refresh_calls += 1


@pytest.mark.anyio
async def test_footer_lists_shortcuts() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one(Footer)
        shown = {ab.binding.key for ab in footer.screen.active_bindings.values()}
        assert {"e", "z", "t", "i", "f", "r"} <= shown


@pytest.mark.anyio
async def test_f_opens_filter_screen_then_selection_switches_view() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Filtered task",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = FakeRepository(
        [task],
        [Project(id="220", name="Errands")],
        filters=[Filter(id="f1", name="My Filter", query="p1", order=1)],
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        assert isinstance(app.screen, FilterScreen)

        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert not isinstance(app.screen, FilterScreen)  # picker dismissed
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert table.get_row_at(0)[2] == "Filtered task"
        status = str(app.query_one("#status", Static).render())
        assert "My Filter" in status


@pytest.mark.anyio
async def test_f_with_no_saved_filters_reports_and_opens_nothing() -> None:
    app = TodoistApp(FakeRepository([], [], filters=[]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        assert not isinstance(app.screen, FilterScreen)
        status = str(app.query_one("#status", Static).render())
        assert "No saved filters" in status


class FailingFiltersRepository(FakeRepository):
    async def filters(self) -> list[Filter]:
        raise RuntimeError("offline")


@pytest.mark.anyio
async def test_f_reports_when_filters_fail_to_load() -> None:
    app = TodoistApp(FailingFiltersRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        assert not isinstance(app.screen, FilterScreen)
        status = str(app.query_one("#status", Static).render())
        assert "Failed to load filters: offline" in status


@pytest.mark.anyio
async def test_selecting_filter_revalidates_in_background() -> None:
    repo = FakeRepository(
        [], [], filters=[Filter(id="f1", name="My Filter", query="p1", order=1)]
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert "p1" in repo.refresh_filtered_queries
        status = str(app.query_one("#status", Static).render())
        assert "⟳" not in status  # sync indicator cleared after revalidation


@pytest.mark.anyio
async def test_leaving_filter_view_stops_background_filter_refresh() -> None:
    repo = FakeRepository(
        [], [], filters=[Filter(id="f1", name="My Filter", query="p1", order=1)]
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("t")  # back to Today clears the active filter
        await pilot.pause()
        repo.refresh_filtered_queries.clear()

        await pilot.press("r")  # force a sync
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert repo.refresh_filtered_queries == []


@pytest.mark.anyio
async def test_f_while_picker_open_does_not_stack_screens() -> None:
    repo = FakeRepository(
        [], [], filters=[Filter(id="f1", name="My Filter", query="p1", order=1)]
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("f")  # second press must not stack a second picker
        await pilot.pause()
        pickers = [s for s in app.screen_stack if isinstance(s, FilterScreen)]
        assert len(pickers) == 1


@pytest.mark.anyio
async def test_cancelling_filter_picker_keeps_current_view() -> None:
    repo = FakeRepository(
        [], [], filters=[Filter(id="f1", name="My Filter", query="p1", order=1)]
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        assert isinstance(app.screen, FilterScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, FilterScreen)
        status = str(app.query_one("#status", Static).render())
        assert "Today" in status  # unchanged from the startup view


@pytest.mark.anyio
async def test_pressing_r_forces_resync() -> None:
    repo = FakeRepository([], [])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        before = repo.refresh_calls  # 1 from the startup sync
        await pilot.press("r")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert repo.refresh_calls == before + 1


@pytest.mark.anyio
async def test_cursor_is_row() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(DataTable[object]).cursor_type == "row"


@pytest.mark.anyio
async def test_mount_renders_today_tasks_in_table() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 7, 21), time=datetime.time(9, 30)),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], [Project(id="220", name="Errands")]))

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        row = table.get_row_at(0)
        assert row[0] == "🔴"
        assert row[1] == "09:30"
        assert row[2] == "Buy milk"
        assert str(row[3]) == "Errands"


@pytest.mark.anyio
async def test_p4_has_no_dot() -> None:
    task = Task(
        id=TaskId("1"),
        content="Someday",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], [Project(id="220", name="Errands")]))

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == ""


@pytest.mark.anyio
async def test_all_day_task_has_blank_time() -> None:
    task = Task(
        id=TaskId("1"),
        content="Someday",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], [Project(id="220", name="Errands")]))

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(DataTable[object]).get_row_at(0)[1] == ""


@pytest.mark.anyio
async def test_task_without_project_blank() -> None:
    task = Task(
        id=TaskId("1"),
        content="Solo",
        priority=Priority.P3,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], []))  # no matching project name

    async with app.run_test() as pilot:
        await pilot.pause()
        assert str(app.query_one(DataTable[object]).get_row_at(0)[3]) == ""


@pytest.mark.anyio
async def test_pressing_e_completes_optimistically() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 1
        reloads = repo.today_calls
        syncs = repo.refresh_calls
        await pilot.press("e")
        # optimistic: row is gone before the network command resolves
        assert app.query_one(DataTable[object]).row_count == 0
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.completed == [TaskId("6X4")]
        assert app.query_one(DataTable[object]).row_count == 0
        assert "Today · no tasks" in str(app.query_one("#status", Static).render())
        assert repo.refresh_calls > syncs  # success pulls server delta
        assert repo.today_calls > reloads  # and re-renders the current view


class GatedRefreshRepository(FakeRepository):
    """refresh() blocks until released, so the syncing state is observable."""

    def __init__(self, tasks: list[Task], projects: list[Project]) -> None:
        super().__init__(tasks, projects)
        self.release = asyncio.Event()

    async def refresh(self) -> None:
        await self.release.wait()
        await super().refresh()


@pytest.mark.anyio
async def test_sync_indicator_shows_while_syncing_then_clears() -> None:
    repo = GatedRefreshRepository([], [])
    app = TodoistApp(repo)

    def status() -> str:
        return str(app.query_one("#status", Static).render())

    async with app.run_test() as pilot:
        await pilot.pause()  # startup sync started, blocked in refresh()
        assert "⟳" in status()
        repo.release.set()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert "⟳" not in status()


@pytest.mark.anyio
async def test_periodic_poll_resyncs() -> None:
    repo = FakeRepository([], [])

    class FastPollApp(TodoistApp):
        SYNC_INTERVAL = 0.05

    app = FastPollApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        before = repo.refresh_calls  # 1 from the startup sync
        await pilot.pause(0.2)  # let a few poll ticks fire
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert repo.refresh_calls > before


@pytest.mark.anyio
async def test_pressing_e_on_empty_table_does_nothing() -> None:
    repo = FakeRepository([], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()

        assert repo.completed == []


@pytest.mark.anyio
async def test_pressing_u_undoes_last_complete() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("e")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 0

        await pilot.press("z")
        # optimistic: the row is back before the reopen command resolves
        assert app.query_one(DataTable[object]).row_count == 1
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.uncompleted == [TaskId("6X4")]
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert table.get_row_at(0)[2] == "Buy milk"
        assert "Today · 1 task(s)" in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_undo_is_single_shot() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("e")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("z")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("z")  # nothing left to undo
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.uncompleted == [TaskId("6X4")]  # only the first z acted


@pytest.mark.anyio
async def test_undo_with_nothing_to_undo_is_noop() -> None:
    repo = FakeRepository([_row("Solo")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("z")
        await pilot.pause()

        assert repo.uncompleted == []
        assert app.query_one(DataTable[object]).row_count == 1


class FailingCompleteRepository(FakeRepository):
    async def complete(self, task_id: TaskId) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_complete_failure_is_surfaced() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    app = TodoistApp(FailingCompleteRepository([task], [Project(id="220", name="X")]))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert "Failed to complete task: boom" in str(
            app.query_one("#status", Static).render()
        )
        assert app.query_one(DataTable[object]).row_count == 1


class FailingUncompleteRepository(FakeRepository):
    async def uncomplete(self, task_id: TaskId) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_undo_failure_is_surfaced() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = FailingUncompleteRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("e")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("z")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert "Failed to undo: boom" in str(app.query_one("#status", Static).render())
        # failed reopen resyncs to server truth: the task stays completed (gone)
        assert app.query_one(DataTable[object]).row_count == 0


class RefreshingRepository(FakeRepository):
    """Serves an empty (cached) view first, then fresh tasks on refresh."""

    def __init__(self, projects: list[Project], after: list[Task]) -> None:
        super().__init__([], projects)
        self._after = after

    async def refresh(self) -> None:
        await super().refresh()
        self._tasks = list(self._after)


@pytest.mark.anyio
async def test_background_refresh_rerenders_after_cache_load() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = RefreshingRepository([Project(id="220", name="Errands")], after=[task])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.refresh_calls == 1
        assert repo.today_calls == 2  # cache-first load, then post-refresh re-render
        assert app.query_one(DataTable[object]).row_count == 1  # fresh task rendered


class OfflineRefreshRepository(FakeRepository):
    async def refresh(self) -> None:
        raise RuntimeError("offline")


@pytest.mark.anyio
async def test_background_refresh_failure_keeps_cached_view() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = OfflineRefreshRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert app.query_one(DataTable[object]).row_count == 1  # cached view survives
        assert repo.today_calls == 1  # failed refresh does not re-render


class FailingLoadRepository(FakeRepository):
    async def today(self) -> list[Task]:
        raise RuntimeError("offline")


@pytest.mark.anyio
async def test_load_failure_is_surfaced() -> None:
    app = TodoistApp(FailingLoadRepository([], []))

    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Failed to load tasks: offline" in str(
            app.query_one("#status", Static).render()
        )


@pytest.mark.anyio
async def test_empty_shows_status_message() -> None:
    app = TodoistApp(FakeRepository([], []))

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 0
        assert "Today · no tasks" in str(app.query_one("#status", Static).render())


def _row(content: str, project_id: str = "220") -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id=project_id,
    )


@pytest.mark.anyio
async def test_j_and_k_move_row_cursor() -> None:
    repo = FakeRepository([_row("First"), _row("Second")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert table.cursor_row == 0
        await pilot.press("j")
        assert table.cursor_row == 1
        await pilot.press("k")
        assert table.cursor_row == 0
        for key in ("h", "l"):  # no horizontal move in row mode; must not error
            await pilot.press(key)
            assert table.cursor_row == 0


@pytest.mark.anyio
async def test_refresh_keeps_cursor_on_the_same_task() -> None:
    repo = FakeRepository([_row("First"), _row("Second")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("j")  # move off the top row
        table = app.query_one(TaskTable)
        assert table.cursor_row == 1

        await pilot.press("r")  # background resync re-renders the table
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert table.cursor_row == 1  # cursor stayed on "Second", not reset to top
        assert table.get_row_at(table.cursor_row)[2] == "Second"


@pytest.mark.anyio
async def test_switch_view_resets_cursor_to_top() -> None:
    repo = FakeRepository([_row("T1"), _row("T2")], [], inbox=[_row("I1"), _row("I2")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")  # cursor on second Today row
        await pilot.press("i")  # switch view: the prior task is absent here
        await pilot.pause()

        assert app.query_one(TaskTable).cursor_row == 0


@pytest.mark.anyio
async def test_pressing_i_switches_to_inbox() -> None:
    repo = FakeRepository([_row("Today thing")], [], inbox=[_row("Inbox thing")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(DataTable[object]).get_row_at(0)[2] == "Today thing"

        await pilot.press("i")
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert table.get_row_at(0)[2] == "Inbox thing"
        assert "Inbox · 1 task(s)" in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_pressing_t_switches_back_to_today() -> None:
    repo = FakeRepository([_row("Today thing")], [], inbox=[_row("Inbox thing")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert table.get_row_at(0)[2] == "Today thing"
        assert "Today · 1 task(s)" in str(app.query_one("#status", Static).render())
