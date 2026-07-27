import asyncio
import datetime

import pytest
from textual.widgets import DataTable, Footer, Static

from todoist_tui.domain.arrange import Arrangement, Field, SortKey
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.tui.app import InMemoryArrangements, TaskTable, TodoistApp
from todoist_tui.tui.screens.arrange import ArrangeScreen
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


async def _grouped_by_project() -> InMemoryArrangements:
    store = InMemoryArrangements()
    await store.save("today", Arrangement(group_by=(Field.PROJECT,)))
    return store


def _col2(table: DataTable[object]) -> list[str]:
    return [str(table.get_row_at(i)[2]) for i in range(table.row_count)]


@pytest.mark.anyio
async def test_grouping_renders_headers_and_tasks() -> None:
    repo = FakeRepository(
        [_row("w1", "220"), _row("h1", "9")],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        col2 = _col2(app.query_one(DataTable[object]))

        assert any("▾" in c and "Home" in c for c in col2)
        assert any("▾" in c and "Work" in c for c in col2)
        assert any(c.strip() == "h1" for c in col2)
        assert any(c.strip() == "w1" for c in col2)
        # Home group sorts before Work; its header leads
        assert col2[0].endswith("Home")


@pytest.mark.anyio
async def test_status_shows_arrangement_summary() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Group: Project" in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_e_on_a_group_header_does_nothing() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        assert "▾" in _col2(app.query_one(DataTable[object]))[0]  # header on top
        await pilot.press("e")
        await pilot.pause()
        assert repo.completed == []  # header rows are inert


@pytest.mark.anyio
async def test_e_on_a_task_under_a_header_completes_it() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("j")  # move off the header onto the task
        await pilot.press("e")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.completed == [TaskId("w1")]


@pytest.mark.anyio
async def test_label_grouping_lists_task_under_each_label() -> None:
    tagged = Task(
        id=TaskId("rent"),
        content="Pay rent",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
        labels=("home", "urgent"),
    )
    store = InMemoryArrangements()
    await store.save("today", Arrangement(group_by=(Field.LABELS,)))
    repo = FakeRepository([tagged], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=store)

    async with app.run_test() as pilot:
        await pilot.pause()
        col2 = _col2(app.query_one(DataTable[object]))

        assert sum(1 for c in col2 if c.strip() == "Pay rent") == 2  # once per label
        assert any("home" in c and "▾" in c for c in col2)
        assert any("urgent" in c and "▾" in c for c in col2)


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


def _two_project_repo() -> FakeRepository:
    return FakeRepository(
        [_row("w1", "220"), _row("h1", "9")],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )


@pytest.mark.anyio
async def test_g_opens_the_group_transient() -> None:
    app = TodoistApp(_two_project_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        assert isinstance(app.screen, ArrangeScreen)


@pytest.mark.anyio
async def test_g_then_field_keys_group_the_list_and_persist() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")  # group by Project
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        col2 = _col2(app.query_one(DataTable[object]))
        assert any("▾" in c and "Home" in c for c in col2)
        assert await store.get("today") == Arrangement(group_by=(Field.PROJECT,))


@pytest.mark.anyio
async def test_s_appends_then_toggles_sort_direction() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("d")  # sort by Due date (ascending)
        await pilot.press("d")  # tapping again flips to descending
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert await store.get("today") == Arrangement(
            sort_by=(SortKey(Field.DUE_DATE, ascending=False),)
        )


@pytest.mark.anyio
async def test_escape_cancels_without_changing_arrangement() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")
        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, ArrangeScreen)
        assert await store.get("today") == Arrangement()


@pytest.mark.anyio
async def test_group_chain_capped_at_three_levels() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        for key in ("p", "r", "d", "t"):  # four fields; the fourth is ignored
            await pilot.press(key)
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert len((await store.get("today")).group_by) == 3


@pytest.mark.anyio
async def test_transient_hint_shows_field_keys_as_literal_text() -> None:
    app = TodoistApp(_two_project_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        hint = str(app.screen.query_one("#arrange", Static).render())
        assert "[p] Project" in hint  # not swallowed as Rich markup


@pytest.mark.anyio
async def test_keys_do_not_leak_to_app_bindings_under_the_transient() -> None:
    app = TodoistApp(_two_project_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("g")  # must not stack a second transient
        await pilot.press("f")  # must not open the filter picker underneath
        await pilot.pause()
        assert len([s for s in app.screen_stack if isinstance(s, ArrangeScreen)]) == 1
        assert not any(isinstance(s, FilterScreen) for s in app.screen_stack)


@pytest.mark.anyio
async def test_backspace_removes_last_group_field() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")  # Project
        await pilot.press("r")  # Priority
        await pilot.press("backspace")  # drop Priority
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert await store.get("today") == Arrangement(group_by=(Field.PROJECT,))


@pytest.mark.anyio
async def test_capital_g_clears_the_group_chain() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")
        await pilot.press("r")
        await pilot.press("G")  # clear
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert await store.get("today") == Arrangement()


@pytest.mark.anyio
async def test_group_ignores_a_duplicate_field() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")
        await pilot.press("p")  # duplicate: ignored
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert await store.get("today") == Arrangement(group_by=(Field.PROJECT,))


@pytest.mark.anyio
async def test_arrange_saves_to_the_view_it_was_opened_for() -> None:
    store = InMemoryArrangements()
    repo = FakeRepository(
        [_row("w1", "220")], [Project(id="220", name="Work")], inbox=[_row("i1", "220")]
    )
    app = TodoistApp(repo, arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")
        await pilot.press("enter")  # schedules the apply worker for Today
        await pilot.press("i")  # switch to Inbox before it runs
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert await store.get("today") == Arrangement(group_by=(Field.PROJECT,))
        assert await store.get("inbox") == Arrangement()  # untouched


@pytest.mark.anyio
async def test_arrangement_is_restored_per_view() -> None:
    repo = FakeRepository(
        [_row("w1", "220")],
        [Project(id="220", name="Work")],
        inbox=[_row("i1", "220")],
    )
    app = TodoistApp(repo, arrangements=InMemoryArrangements())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")  # group Today by project
        await pilot.pause()
        await pilot.press("p")
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        await pilot.press("i")  # Inbox has no arrangement → flat
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert not any("▾" in c for c in _col2(app.query_one(DataTable[object])))

        await pilot.press("t")  # back to Today → its grouping returns
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert any("▾" in c for c in _col2(app.query_one(DataTable[object])))
