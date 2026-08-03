import asyncio
import datetime
from dataclasses import replace

import pytest
from textual.widgets import DataTable, Footer, Static

from todoist_tui.domain.arrange import Arrangement, Field, SortKey
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.tui.app import (
    InMemoryArrangements,
    InMemoryHome,
    TaskTable,
    TodoistApp,
)
from todoist_tui.tui.screens.arrange import ArrangeScreen
from todoist_tui.tui.screens.detail import TaskDetailScreen
from todoist_tui.tui.screens.filters import FilterScreen
from todoist_tui.tui.screens.project_list import ProjectListScreen
from todoist_tui.tui.screens.project_picker import ProjectPickerScreen
from todoist_tui.tui.screens.schedule import ScheduleScreen


class FakeRepository:
    def __init__(
        self,
        tasks: list[Task],
        projects: list[Project],
        inbox: list[Task] | None = None,
        filters: list[Filter] | None = None,
        sections: list[Section] | None = None,
    ) -> None:
        self._tasks = tasks
        self._projects = projects
        self._inbox = inbox or []
        self._filters = filters or []
        self._sections = sections or []
        self.completed: list[TaskId] = []
        self.uncompleted: list[TaskId] = []
        self.priorities: list[tuple[TaskId, Priority]] = []
        self.dues: list[tuple[TaskId, Due | None]] = []
        self.deadlines: list[tuple[TaskId, Deadline | None]] = []
        self.moves: list[tuple[TaskId, str, str | None]] = []
        self._removed: dict[TaskId, Task] = {}
        self.today_calls = 0
        self.refresh_calls = 0
        self.refresh_filtered_queries: list[str] = []

    async def today(self) -> list[Task]:
        self.today_calls += 1
        return list(self._tasks)

    async def inbox(self) -> list[Task]:
        return list(self._inbox)

    async def by_project(self, project_id: str) -> list[Task]:
        return [t for t in self._tasks if t.project_id == project_id]

    async def filtered(self, query: str) -> list[Task]:
        return list(self._tasks)

    async def refresh_filtered(self, query: str) -> list[Task]:
        self.refresh_filtered_queries.append(query)
        return list(self._tasks)

    async def projects(self) -> list[Project]:
        return self._projects

    async def sections(self) -> list[Section]:
        return list(self._sections)

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

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None:
        self.priorities.append((task_id, priority))
        self._tasks = [
            replace(t, priority=priority) if t.id == task_id else t for t in self._tasks
        ]

    async def set_due(self, task_id: TaskId, due: Due | None) -> None:
        self.dues.append((task_id, due))
        self._tasks = [
            replace(t, due=due) if t.id == task_id else t for t in self._tasks
        ]

    async def set_deadline(self, task_id: TaskId, deadline: Deadline | None) -> None:
        self.deadlines.append((task_id, deadline))
        self._tasks = [
            replace(t, deadline=deadline) if t.id == task_id else t for t in self._tasks
        ]

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        self.moves.append((task_id, project_id, section_id))
        self._tasks = [
            replace(t, project_id=project_id, section_id=section_id)
            if t.id == task_id
            else t
            for t in self._tasks
        ]
        inbox_id = next((p.id for p in self._projects if p.is_inbox), None)
        if project_id != inbox_id:  # left the inbox: it no longer lists the task
            self._inbox = [t for t in self._inbox if t.id != task_id]

    async def refresh(self) -> None:
        self.refresh_calls += 1


class FakeClock:
    def __init__(self, today: datetime.date) -> None:
        self._today = today

    def today(self) -> datetime.date:
        return self._today


_TODAY = datetime.date(2026, 7, 28)  # a Tuesday


@pytest.mark.anyio
async def test_footer_shows_only_the_help_hint() -> None:
    app = TodoistApp(FakeRepository([], []))
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one(Footer)
        shown = {
            ab.binding.key
            for ab in footer.screen.active_bindings.values()
            if ab.binding.show
        }
        assert "question_mark" in shown
        assert not ({"e", "z", "t", "i", "f", "p", "r", "v"} & shown)  # all hidden


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
        assert str(table.get_row_at(0)[3]) == "Filtered task"
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
        await pilot.press(".")  # back to Today clears the active filter
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
async def test_p_opens_project_list_then_selection_switches_view() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Work task",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="9",
    )
    repo = FakeRepository(
        [task],
        [
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
        ],
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, ProjectListScreen)

        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert not isinstance(app.screen, ProjectListScreen)  # picker dismissed
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert str(table.get_row_at(0)[3]) == "Work task"
        status = str(app.query_one("#status", Static).render())
        assert "Work" in status


@pytest.mark.anyio
async def test_p_with_no_projects_reports_and_opens_nothing() -> None:
    repo = FakeRepository([], [Project(id="220", name="Eingang", is_inbox=True)])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert not isinstance(app.screen, ProjectListScreen)
        status = str(app.query_one("#status", Static).render())
        assert "No projects" in status


@pytest.mark.anyio
async def test_p_while_picker_open_does_not_stack_screens() -> None:
    repo = FakeRepository([], [Project(id="9", name="Work")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("p")  # second press must not stack a second picker
        await pilot.pause()
        pickers = [s for s in app.screen_stack if isinstance(s, ProjectListScreen)]
        assert len(pickers) == 1


@pytest.mark.anyio
async def test_cancelling_project_list_keeps_current_view() -> None:
    repo = FakeRepository([], [Project(id="9", name="Work")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, ProjectListScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ProjectListScreen)
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
        assert row[1] == "2026-07-21 09:30"
        assert str(row[3]) == "Buy milk"
        assert str(row[4]) == "Errands"


@pytest.mark.anyio
async def test_list_hides_markdown_link_syntax_showing_the_label() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="[Check calendar](https://cal) today",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], [Project(id="220", name="Errands")]))

    async with app.run_test() as pilot:
        await pilot.pause()
        assert (
            str(app.query_one(DataTable[object]).get_row_at(0)[3])
            == "Check calendar today"
        )


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
async def test_all_day_task_shows_date_without_time() -> None:
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
        assert app.query_one(DataTable[object]).get_row_at(0)[1] == "2026-07-21"


@pytest.mark.anyio
async def test_task_without_due_has_blank_due_cell() -> None:
    task = Task(
        id=TaskId("1"),
        content="Someday",
        priority=Priority.P4,
        due=None,
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
        assert str(app.query_one(DataTable[object]).get_row_at(0)[4]) == ""


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

    def __init__(
        self,
        tasks: list[Task],
        projects: list[Project],
        inbox: list[Task] | None = None,
        filters: list[Filter] | None = None,
    ) -> None:
        super().__init__(tasks, projects, inbox=inbox, filters=filters)
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
async def test_pressing_digit_sets_priority_optimistically() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == ""  # P4: no dot
        syncs = repo.refresh_calls

        await pilot.press("1")
        # optimistic: the dot repaints before the network command resolves
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == "🔴"
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.priorities == [(TaskId("6X4"), Priority.P1)]
        assert repo.refresh_calls > syncs  # success pulls server delta


@pytest.mark.anyio
async def test_pressing_4_clears_the_priority_dot() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == "🔴"

        await pilot.press("4")
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == ""  # P4: no dot
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.priorities == [(TaskId("6X4"), Priority.P4)]


@pytest.mark.anyio
async def test_setting_priority_regroups_task_immediately_when_grouped() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    store = InMemoryArrangements()
    await store.save("today", Arrangement(group_by=(Field.PRIORITY,)))
    # gate refresh so the background sync cannot re-group for us: the jump must
    # be the local optimistic re-arrange, not the server round-trip.
    repo = GatedRefreshRepository([task], [Project(id="220", name="Errands")])
    repo.release.set()  # let the startup sync through
    app = TodoistApp(repo, arrangements=store)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        table = app.query_one(TaskTable)
        assert "P4" in _content_col(table)[0]  # starts under the P4 header
        await pilot.press("j")  # move cursor onto the task
        repo.release.clear()  # block the post-change sync

        await pilot.press("1")
        # optimistic, before the network resolves: it jumped to a fresh P1 group
        col2 = _content_col(table)
        assert "P1" in col2[0]
        assert col2[1].strip() == "Buy milk"
        assert not any("P4" in c for c in col2)
        assert str(table.get_row_at(table.cursor_row)[3]).strip() == "Buy milk"  # <-

        repo.release.set()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert repo.priorities == [(TaskId("6X4"), Priority.P1)]


@pytest.mark.anyio
async def test_pressing_digit_on_empty_table_does_nothing() -> None:
    repo = FakeRepository([], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

        assert repo.priorities == []


@pytest.mark.anyio
async def test_digit_on_a_group_header_does_nothing() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert "──" in _content_col(table)[0]  # header on top
        table.move_cursor(row=0)  # cursor never rests here; force it for the guard
        await pilot.press("1")
        await pilot.pause()

        assert repo.priorities == []  # header rows are inert


class FailingSetPriorityRepository(FakeRepository):
    async def set_priority(self, task_id: TaskId, priority: Priority) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_set_priority_failure_is_surfaced_and_resyncs() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    app = TodoistApp(
        FailingSetPriorityRepository([task], [Project(id="220", name="X")])
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("1")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert "Failed to set priority: boom" in str(
            app.query_one("#status", Static).render()
        )
        # failed command resyncs to server truth: the dot reverts to P4 (blank)
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == ""


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
        assert str(table.get_row_at(0)[3]) == "Buy milk"
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


class LaggingCompleteRepository(FakeRepository):
    """Todoist eventual consistency: a closed task keeps coming back from
    today()/by_project() until the server catches up."""

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)  # recorded, but it still syncs back

    def catch_up(self) -> None:
        self._tasks = [t for t in self._tasks if t.id not in self.completed]


@pytest.mark.anyio
async def test_completed_task_stays_gone_while_server_lags() -> None:
    repo = LaggingCompleteRepository(
        [_row("Buy milk")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("e")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()  # a sync that still lists the closed task landed

        assert repo.completed == [TaskId("Buy milk")]
        assert app.query_one(DataTable[object]).row_count == 0  # must not flash back

        repo.catch_up()  # server finally drops it
        await pilot.press("r")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 0


@pytest.mark.anyio
async def test_rapid_completes_do_not_reappear() -> None:
    repo = LaggingCompleteRepository(
        [_row("First"), _row("Second")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert app.query_one(DataTable[object]).row_count == 2
        await pilot.press("e")
        await pilot.press("e")  # second close before the first's sync settles
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert set(repo.completed) == {TaskId("First"), TaskId("Second")}
        assert app.query_one(DataTable[object]).row_count == 0  # neither reappears


@pytest.mark.anyio
async def test_undo_restores_a_completed_task_even_while_server_lags() -> None:
    repo = LaggingCompleteRepository(
        [_row("Buy milk")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("e")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 0

        await pilot.press("z")  # reopen: it must not stay filtered out
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.uncompleted == [TaskId("Buy milk")]
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert str(table.get_row_at(0)[3]) == "Buy milk"


class RecurringCompleteRepository(FakeRepository):
    """Todoist recurring task: complete() reschedules it (new due) and keeps it."""

    def __init__(
        self,
        tasks: list[Task],
        projects: list[Project],
        *,
        next_due: Due,
    ) -> None:
        super().__init__(tasks, projects)
        self._next_due = next_due

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)
        self._tasks = [
            replace(t, due=self._next_due) if t.id == task_id else t
            for t in self._tasks
        ]


@pytest.mark.anyio
async def test_recurring_completion_reappears_with_its_next_due() -> None:
    repo = RecurringCompleteRepository(
        [_row("Water plants", project_id="9")],
        [
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
        ],
        next_due=Due(date=datetime.date(2026, 7, 22)),
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("enter")  # open the Work project view
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 1

        await pilot.press("e")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        # its next occurrence has a new due: it must come back, not stay hidden
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert str(table.get_row_at(0)[3]) == "Water plants"


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


@pytest.mark.anyio
async def test_pressing_t_opens_schedule_screen() -> None:
    repo = FakeRepository([_row("Buy milk")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)


@pytest.mark.anyio
async def test_pressing_d_sets_a_deadline_and_shows_it() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Ship it",
        priority=Priority.P2,
        due=Due(date=_TODAY),  # stays in Today regardless of the deadline
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow (quick key)
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.deadlines == [
            (TaskId("6X4"), Deadline(date=datetime.date(2026, 7, 29)))
        ]
        table = app.query_one(DataTable[object])
        assert table.get_row_at(0)[2] == "2026-07-29"  # Deadline column


@pytest.mark.anyio
async def test_pressing_d_clear_removes_the_deadline() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Ship it",
        priority=Priority.P2,
        due=Due(date=_TODAY),
        project_id="220",
        deadline=Deadline(date=datetime.date(2026, 7, 29)),
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert app.query_one(DataTable[object]).get_row_at(0)[2] == "2026-07-29"
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("x")  # clear
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.deadlines == [(TaskId("6X4"), None)]
        assert app.query_one(DataTable[object]).get_row_at(0)[2] == ""


@pytest.mark.anyio
async def test_d_then_tomorrow_drops_task_from_today_immediately() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=_TODAY),
        project_id="220",
    )
    # gate the post-change sync so the observed drop is the optimistic re-filter,
    # not the server round-trip
    repo = GatedRefreshRepository([task], [Project(id="220", name="Errands")])
    repo.release.set()  # let the startup sync through
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")  # tomorrow: it no longer belongs in Today
        # optimistic: the row leaves Today before the network command resolves
        assert app.query_one(DataTable[object]).row_count == 0

        repo.release.set()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert repo.dues == [(TaskId("6X4"), Due(date=datetime.date(2026, 7, 29)))]


@pytest.mark.anyio
async def test_d_then_today_keeps_task_in_today_with_date() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=None,  # a due-less task shown in Today (fake) gains today's date
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("t")  # today: it stays, now dated
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert table.get_row_at(0)[1] == "2026-07-28"


@pytest.mark.anyio
async def test_d_then_clear_removes_due() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 28)),
        project_id="220",
    )
    repo = GatedRefreshRepository([task], [Project(id="220", name="Errands")])
    repo.release.set()  # let the startup sync through
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert app.query_one(DataTable[object]).get_row_at(0)[1] == "2026-07-28"
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("x")  # clear: an undated task no longer belongs in Today
        assert app.query_one(DataTable[object]).row_count == 0

        repo.release.set()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert repo.dues == [(TaskId("6X4"), None)]


@pytest.mark.anyio
async def test_calendar_pick_applies_optimistically() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=_TODAY),
        project_id="220",
    )
    repo = GatedRefreshRepository([task], [Project(id="220", name="Errands")])
    repo.release.set()  # let the startup sync through
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("l")  # calendar: move cursor to tomorrow
        await pilot.press("enter")  # pick it: task leaves Today
        # optimistic: the row is gone before the network command resolves
        assert app.query_one(DataTable[object]).row_count == 0

        repo.release.set()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert repo.dues == [(TaskId("6X4"), Due(date=datetime.date(2026, 7, 29)))]


@pytest.mark.anyio
async def test_reschedule_on_filter_view_drops_task_immediately() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Overdue thing",
        priority=Priority.P2,
        due=Due(date=_TODAY),
        project_id="220",
    )
    # a filter's membership can't be evaluated locally, so a reschedule drops the
    # edited task at once and the background refresh restores it if it still fits
    repo = GatedRefreshRepository(
        [task],
        [Project(id="220", name="Errands")],
        filters=[Filter(id="f1", name="Overdue", query="overdue", order=1)],
    )
    repo.release.set()  # let the startup sync through
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("enter")  # enter the Overdue filter view
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert app.query_one(DataTable[object]).row_count == 1
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")  # reschedule: it leaves the filter immediately
        assert app.query_one(DataTable[object]).row_count == 0

        repo.release.set()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert repo.dues == [(TaskId("6X4"), Due(date=datetime.date(2026, 7, 29)))]


@pytest.mark.anyio
async def test_reschedule_on_inbox_keeps_task_and_updates_due_cell() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Sort me",
        priority=Priority.P2,
        due=None,
        project_id="220",
    )
    repo = GatedRefreshRepository([], [Project(id="220", name="Errands")], inbox=[task])
    repo.release.set()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")  # Inbox: membership is by project, not due
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        repo.release.clear()  # block the sync so we observe the optimistic state

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")  # a due change must not remove it from Inbox
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert table.get_row_at(0)[1] == "2026-07-29"


@pytest.mark.anyio
async def test_d_on_recurring_task_reschedules_keeping_the_rule() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Water plants",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 28), is_recurring=True, string="every day"),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)  # picker opens for recurring
        await pilot.press("m")  # tomorrow
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        (task_id, due) = repo.dues[-1]
        assert task_id == TaskId("6X4")
        assert due is not None
        assert due.date == datetime.date(2026, 7, 29)  # next occurrence moved
        assert due.is_recurring is True  # rule kept
        assert due.string == "every day"


@pytest.mark.anyio
async def test_d_then_escape_changes_nothing() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 28)),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, ScheduleScreen)
        assert repo.dues == []
        assert app.query_one(DataTable[object]).get_row_at(0)[1] == "2026-07-28"


@pytest.mark.anyio
async def test_d_on_empty_table_does_nothing() -> None:
    repo = FakeRepository([], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()

        assert not isinstance(app.screen, ScheduleScreen)
        assert repo.dues == []


@pytest.mark.anyio
async def test_d_on_a_group_header_does_nothing() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(
        repo, arrangements=await _grouped_by_project(), clock=FakeClock(_TODAY)
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert "──" in _content_col(table)[0]  # header on top
        table.move_cursor(row=0)  # cursor never rests here; force it for the guard
        await pilot.press("t")
        await pilot.pause()

        assert not isinstance(app.screen, ScheduleScreen)
        assert repo.dues == []  # header rows are inert


class FailingSetDueRepository(FakeRepository):
    async def set_due(self, task_id: TaskId, due: Due | None) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_set_due_failure_is_surfaced_and_resyncs() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=None,
        project_id="220",
    )
    app = TodoistApp(
        FailingSetDueRepository([task], [Project(id="220", name="X")]),
        clock=FakeClock(_TODAY),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert "Failed to set due: boom" in str(
            app.query_one("#status", Static).render()
        )
        # failed command resyncs to server truth: the due cell reverts to blank
        assert app.query_one(DataTable[object]).get_row_at(0)[1] == ""


@pytest.mark.anyio
async def test_pressing_enter_opens_detail_screen() -> None:
    repo = FakeRepository([_row("Buy milk")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, TaskDetailScreen)
        details = [s for s in app.screen_stack if isinstance(s, TaskDetailScreen)]
        assert len(details) == 1  # one Enter opens exactly one card


@pytest.mark.anyio
async def test_enter_then_escape_returns_to_the_list() -> None:
    repo = FakeRepository([_row("Buy milk")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, TaskDetailScreen)


@pytest.mark.anyio
async def test_enter_on_empty_table_does_nothing() -> None:
    app = TodoistApp(FakeRepository([], []))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, TaskDetailScreen)


@pytest.mark.anyio
async def test_enter_on_a_group_header_does_nothing() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert "──" in _content_col(table)[0]  # header on top
        table.move_cursor(row=0)  # cursor never rests here; force it for the guard
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, TaskDetailScreen)  # header rows are inert


@pytest.mark.anyio
async def test_v_opens_project_picker() -> None:
    repo = FakeRepository([_row("Buy milk")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)


@pytest.mark.anyio
async def test_v_pick_moves_task_and_updates_project_cell() -> None:
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.moves == [(TaskId("t1"), "9", None)]
        assert str(app.query_one(DataTable[object]).get_row_at(0)[4]) == "Work"


@pytest.mark.anyio
async def test_v_pick_section_moves_task_into_section() -> None:
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Planning")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("/")  # "Work / Planning" is the only entry with a slash
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.moves == [(TaskId("t1"), "9", "s1")]


@pytest.mark.anyio
async def test_v_moving_out_of_inbox_drops_the_row() -> None:
    repo = FakeRepository(
        [],
        [Project(id="220", name="Inbox", is_inbox=True), Project(id="9", name="Work")],
        inbox=[_row("in1", "220")],
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")  # switch to Inbox
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 1
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.moves == [(TaskId("in1"), "9", None)]
        assert app.query_one(DataTable[object]).row_count == 0  # left the Inbox


@pytest.mark.anyio
async def test_v_on_empty_table_does_nothing() -> None:
    repo = FakeRepository([], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        assert not isinstance(app.screen, ProjectPickerScreen)
        assert repo.moves == []


@pytest.mark.anyio
async def test_v_on_a_group_header_does_nothing() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert "──" in _content_col(table)[0]  # header on top
        table.move_cursor(row=0)  # cursor never rests here; force it for the guard
        await pilot.press("v")
        await pilot.pause()
        assert not isinstance(app.screen, ProjectPickerScreen)  # header rows are inert


@pytest.mark.anyio
async def test_v_while_picker_open_does_not_stack_screens() -> None:
    repo = FakeRepository([_row("t1")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("v")  # second press must not stack a second picker
        await pilot.pause()
        pickers = [s for s in app.screen_stack if isinstance(s, ProjectPickerScreen)]
        assert len(pickers) == 1


@pytest.mark.anyio
async def test_cancelling_project_picker_leaves_task_unchanged() -> None:
    repo = FakeRepository([_row("t1")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ProjectPickerScreen)
        assert repo.moves == []


class FailingMoveRepository(FakeRepository):
    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_move_failure_is_surfaced_and_resyncs() -> None:
    repo = FailingMoveRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert "Failed to move task: boom" in str(
            app.query_one("#status", Static).render()
        )
        # failed command resyncs to server truth: the project cell reverts
        assert str(app.query_one(DataTable[object]).get_row_at(0)[4]) == "Errands"


def _row(content: str, project_id: str = "220", parent_id: str | None = None) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id=project_id,
        parent_id=parent_id,
    )


async def _grouped_by_project() -> InMemoryArrangements:
    store = InMemoryArrangements()
    await store.save("today", Arrangement(group_by=(Field.PROJECT,)))
    return store


def _content_col(table: DataTable[object]) -> list[str]:
    return [str(table.get_row_at(i)[3]) for i in range(table.row_count)]


def _in_section(content: str, section_id: str | None) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=None,
        project_id="9",
        section_id=section_id,
    )


@pytest.mark.anyio
async def test_opening_a_project_groups_tasks_under_section_headers() -> None:
    repo = FakeRepository(
        [_in_section("planned", "s1"), _in_section("loose", None)],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        col = _content_col(app.query_one(DataTable[object]))

    assert any("──" in c and "Planning" in c for c in col)  # section header shown
    assert any(c.strip() == "planned" for c in col)
    assert any(c.strip() == "loose" for c in col)  # section-less task still listed
    assert not any("──" in c and "section" in c.lower() for c in col)  # no such header


@pytest.mark.anyio
async def test_saved_project_arrangement_overrides_the_section_default() -> None:
    repo = FakeRepository(
        [_in_section("planned", "s1")],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
    )
    store = InMemoryArrangements()
    await store.save("project:9", Arrangement())  # user cleared grouping for this view
    app = TodoistApp(repo, arrangements=store)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        col = _content_col(app.query_one(DataTable[object]))

    assert not any("Planning" in c for c in col)  # saved empty beats the default


@pytest.mark.anyio
async def test_grouping_renders_headers_and_tasks() -> None:
    repo = FakeRepository(
        [_row("w1", "220"), _row("h1", "9")],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        col2 = _content_col(app.query_one(DataTable[object]))

        assert any("──" in c and "Home" in c for c in col2)
        assert any("──" in c and "Work" in c for c in col2)
        assert any(c.strip() == "h1" for c in col2)
        assert any(c.strip() == "w1" for c in col2)
        # Home group sorts before Work; its header leads, with a task count
        assert col2[0].lstrip().startswith("──") and "Home (1)" in col2[0]


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
        table = app.query_one(TaskTable)
        assert "──" in _content_col(table)[0]  # header on top
        table.move_cursor(row=0)  # cursor never rests here; force it for the guard
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
        col2 = _content_col(app.query_one(DataTable[object]))

        assert sum(1 for c in col2 if c.strip() == "Pay rent") == 2  # once per label
        assert any("home" in c and "──" in c for c in col2)
        assert any("urgent" in c and "──" in c for c in col2)


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
        for key in ("h", "l"):  # childless roots: expand/collapse are no-ops here
            await pilot.press(key)
            assert table.cursor_row == 0


def _cursor_content(table: TaskTable) -> str:
    return _content_col(table)[table.cursor_row]


def _parent_and_child() -> FakeRepository:
    return FakeRepository(
        [_row("parent"), _row("child", parent_id="parent")],
        [Project(id="220", name="Work")],
    )


@pytest.mark.anyio
async def test_subtasks_are_hidden_by_default_with_an_expand_marker() -> None:
    app = TodoistApp(_parent_and_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        contents = _content_col(table)
        assert [c.strip() for c in contents] == ["▸ parent"]  # child hidden


@pytest.mark.anyio
async def test_l_expands_a_parent_revealing_its_child() -> None:
    app = TodoistApp(_parent_and_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("l")
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert contents == ["▾ parent", "child"]
        assert table.cursor_row == 0  # cursor stays on the parent


@pytest.mark.anyio
async def test_h_collapses_an_expanded_parent() -> None:
    app = TodoistApp(_parent_and_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("l")
        await pilot.pause()
        assert table.row_count == 2
        await pilot.press("h")
        await pilot.pause()
        assert [c.strip() for c in _content_col(table)] == ["▸ parent"]


@pytest.mark.anyio
async def test_h_on_a_child_jumps_the_cursor_to_its_parent() -> None:
    app = TodoistApp(_parent_and_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("l")  # expand
        await pilot.pause()
        await pilot.press("j")  # move onto the child
        assert _cursor_content(table).strip() == "child"
        await pilot.press("h")  # collapse+jump: land on the parent
        await pilot.pause()
        assert _cursor_content(table).strip() == "▾ parent"


@pytest.mark.anyio
async def test_initial_cursor_lands_on_first_task_not_header() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert "──" in _content_col(table)[0]  # row 0 is a group header
        assert table.cursor_row == 1
        assert _cursor_content(table).strip() == "w1"  # a task, not the header


@pytest.mark.anyio
async def test_j_skips_a_single_group_header_downward() -> None:
    repo = FakeRepository(
        [_row("w1", "220"), _row("h1", "9")],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert table.cursor_row == 1  # h1, under the Home header
        await pilot.press("j")  # skip the Work header at row 2
        assert table.cursor_row == 3
        assert _content_col(table)[3].strip() == "w1"


@pytest.mark.anyio
async def test_j_skips_multiple_consecutive_headers_downward() -> None:
    home = Task(
        id=TaskId("home"),
        content="home",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="9",
        labels=("a",),
    )
    work = Task(
        id=TaskId("work"),
        content="work",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
        labels=("b",),
    )
    store = InMemoryArrangements()
    await store.save("today", Arrangement(group_by=(Field.PROJECT, Field.LABELS)))
    repo = FakeRepository(
        [work, home],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )
    app = TodoistApp(repo, arrangements=store)

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        first = table.cursor_row
        assert "──" not in _cursor_content(table)  # starts on a task
        await pilot.press("j")  # cross project + label headers to the next task
        assert table.cursor_row > first + 1
        assert "──" not in _cursor_content(table)  # skipped both headers


@pytest.mark.anyio
async def test_k_skips_a_group_header_upward() -> None:
    repo = FakeRepository(
        [_row("w1", "220"), _row("h1", "9")],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("j")  # onto w1 at row 3
        assert table.cursor_row == 3
        await pilot.press("k")  # skip the Work header at row 2
        assert table.cursor_row == 1
        assert _content_col(table)[1].strip() == "h1"


@pytest.mark.anyio
async def test_k_at_first_task_stays_put() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert table.cursor_row == 1
        await pilot.press("k")  # only a header above; must not move onto it
        assert table.cursor_row == 1


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
        assert str(table.get_row_at(table.cursor_row)[3]) == "Second"


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
        assert str(app.query_one(DataTable[object]).get_row_at(0)[3]) == "Today thing"

        await pilot.press("i")
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert str(table.get_row_at(0)[3]) == "Inbox thing"
        assert "Inbox · 1 task(s)" in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_pressing_t_switches_back_to_today() -> None:
    repo = FakeRepository([_row("Today thing")], [], inbox=[_row("Inbox thing")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        await pilot.press(".")
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert str(table.get_row_at(0)[3]) == "Today thing"
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

        col2 = _content_col(app.query_one(DataTable[object]))
        assert any("──" in c and "Home" in c for c in col2)
        assert await store.get("today") == Arrangement(group_by=(Field.PROJECT,))


@pytest.mark.anyio
async def test_g_then_s_groups_the_list_by_section() -> None:
    repo = FakeRepository(
        [_in_section("planned", "s1")],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
    )
    store = InMemoryArrangements()
    app = TodoistApp(repo, arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("s")  # group by Section
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        col = _content_col(app.query_one(DataTable[object]))
        assert any("──" in c and "Planning" in c for c in col)
        assert await store.get("today") == Arrangement(group_by=(Field.SECTION,))


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
async def test_shift_g_clears_the_group_chain() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")
        await pilot.press("r")
        await pilot.press("G")  # shift+G clears
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert await store.get("today") == Arrangement()


@pytest.mark.anyio
async def test_re_tapping_a_group_field_flips_its_direction() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")  # Project ascending
        await pilot.press("p")  # re-tap → descending
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert await store.get("today") == Arrangement(
            group_by=(Field.PROJECT,), group_desc=frozenset({Field.PROJECT})
        )


@pytest.mark.anyio
async def test_re_tapping_a_group_field_twice_returns_to_ascending() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")  # asc
        await pilot.press("p")  # desc
        await pilot.press("p")  # asc again
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
        assert not any(
            "──" in c for c in _content_col(app.query_one(DataTable[object]))
        )

        await pilot.press(".")  # back to Today → its grouping returns
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert any("──" in c for c in _content_col(app.query_one(DataTable[object])))


@pytest.mark.anyio
async def test_pressing_m_sets_current_view_as_home() -> None:
    home = InMemoryHome()
    repo = FakeRepository(
        [_row("w1", "9")],
        [
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
        ],
    )
    app = TodoistApp(repo, home=home)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")  # browse into the Work project
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        await pilot.press("m")  # pin it as home
        await pilot.pause()
        assert await home.get() == "project:9"
        assert "Home set to Work" in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_startup_opens_the_stored_home_view() -> None:
    home = InMemoryHome()
    await home.save("inbox")
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands")],
        inbox=[_row("i1", "220")],
    )
    app = TodoistApp(repo, home=home)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert str(table.get_row_at(0)[3]) == "i1"
        assert "Inbox" in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_startup_falls_back_to_today_when_home_target_gone() -> None:
    home = InMemoryHome()
    await home.save("project:999")  # a project that no longer exists
    repo = FakeRepository([_row("t1", "220")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, home=home)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Today" in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_pressing_H_returns_to_the_home_view() -> None:
    home = InMemoryHome()
    await home.save("inbox")
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands")],
        inbox=[_row("i1", "220")],
    )
    app = TodoistApp(repo, home=home)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(".")  # go to Today
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert "Today" in str(app.query_one("#status", Static).render())

        await pilot.press("H")  # jump home
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert "Inbox" in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_home_filter_view_refreshes_live() -> None:
    home = InMemoryHome()
    await home.save("filter:f1")
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands")],
        filters=[Filter(id="f1", name="My Filter", query="p1", order=1)],
    )
    app = TodoistApp(repo, home=home)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(".")  # leave for Today
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        repo.refresh_filtered_queries.clear()

        await pilot.press("H")  # back to the filter home
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert "My Filter" in str(app.query_one("#status", Static).render())
        assert "p1" in repo.refresh_filtered_queries  # live-refreshed as a filter
