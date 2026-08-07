import asyncio
import datetime
from dataclasses import replace

import pytest
from rich.text import Text
from textual.widgets import DataTable, Footer, Input, Static, TextArea

from todoist_tui.domain.arrange import Arrangement, Field, SortKey
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.duplication import DuplicationPlan
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.tui.app import (
    InMemoryArrangements,
    InMemoryHome,
    TaskTable,
    TodoistApp,
)
from todoist_tui.tui.screens.arrange import ArrangeScreen
from todoist_tui.tui.screens.confirm import ConfirmScreen
from todoist_tui.tui.screens.detail import TaskDetailScreen
from todoist_tui.tui.screens.edit import TaskEditScreen
from todoist_tui.tui.screens.filters import FilterScreen
from todoist_tui.tui.screens.labels import LabelsScreen
from todoist_tui.tui.screens.project_list import ProjectListScreen
from todoist_tui.tui.screens.project_picker import ProjectPickerScreen
from todoist_tui.tui.screens.reminders import RemindersScreen
from todoist_tui.tui.screens.schedule import ScheduleScreen
from todoist_tui.tui.screens.text_prompt import TextPromptScreen


class FakeRepository:
    def __init__(
        self,
        tasks: list[Task],
        projects: list[Project],
        inbox: list[Task] | None = None,
        filters: list[Filter] | None = None,
        sections: list[Section] | None = None,
        labels: list[Label] | None = None,
        reminders: list[Reminder] | None = None,
        pool: list[Task] | None = None,
    ) -> None:
        self._tasks = tasks
        self._projects = projects
        self._inbox = inbox or []
        self._pool = pool or []  # tasks no view returns, e.g. non-matching subtasks
        self._filters = filters or []
        self._sections = sections or []
        self._labels = labels or []
        self._reminders = reminders or []
        self.added_reminders: list[Reminder] = []
        self.deleted_reminders: list[str] = []
        self.label_edits: list[tuple[TaskId, tuple[str, ...], tuple[str, ...]]] = []
        self.text_edits: list[tuple[TaskId, str, str]] = []
        self.completed: list[TaskId] = []
        self.uncompleted: list[TaskId] = []
        self.deleted: list[TaskId] = []
        self.deleted_sections: list[str] = []
        self.priorities: list[tuple[TaskId, Priority]] = []
        self.dues: list[tuple[TaskId, Due | None]] = []
        self.deadlines: list[tuple[TaskId, Deadline | None]] = []
        self.moves: list[tuple[TaskId, str, str | None]] = []
        self.applied: list[DuplicationPlan] = []
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

    async def all_tasks(self) -> list[Task]:
        by_id = {t.id: t for t in [*self._tasks, *self._inbox, *self._pool]}
        return list(by_id.values())

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

    async def labels(self) -> list[Label]:
        return list(self._labels)

    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None:
        self.label_edits.append((task_id, labels, create))
        self._tasks = [
            replace(t, labels=labels) if t.id == task_id else t for t in self._tasks
        ]

    async def set_text(self, task_id: TaskId, content: str, description: str) -> None:
        self.text_edits.append((task_id, content, description))
        self._tasks = [
            replace(t, content=content, description=description)
            if t.id == task_id
            else t
            for t in self._tasks
        ]

    async def complete(self, task_id: TaskId) -> None:
        self.completed.append(task_id)
        self._removed.update({t.id: t for t in self._tasks if t.id == task_id})
        self._tasks = [t for t in self._tasks if t.id != task_id]
        self._pool = [t for t in self._pool if t.id != task_id]

    async def uncomplete(self, task_id: TaskId) -> None:
        self.uncompleted.append(task_id)
        restored = self._removed.pop(task_id, None)
        if restored is not None:
            self._tasks = [*self._tasks, restored]

    async def delete(self, task_id: TaskId) -> None:
        self.deleted.append(task_id)
        self._tasks = [t for t in self._tasks if t.id != task_id]
        self._pool = [t for t in self._pool if t.id != task_id]

    async def delete_section(self, section_id: str) -> None:
        self.deleted_sections.append(section_id)
        self._sections = [s for s in self._sections if s.id != section_id]
        self._tasks = [t for t in self._tasks if t.section_id != section_id]
        self._pool = [t for t in self._pool if t.section_id != section_id]

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

    async def reminders(self) -> list[Reminder]:
        return list(self._reminders)

    async def add_reminder(self, reminder: Reminder) -> None:
        self.added_reminders.append(reminder)
        stored = (
            reminder
            if reminder.id
            else replace(reminder, id=f"r{len(self._reminders) + 1}")
        )
        self._reminders = [*self._reminders, stored]

    async def delete_reminder(self, reminder_id: str) -> None:
        self.deleted_reminders.append(reminder_id)
        self._reminders = [r for r in self._reminders if r.id != reminder_id]

    async def apply_creation(self, plan: DuplicationPlan) -> None:
        self.applied.append(plan)

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
        # all hidden, including the new multi-select keys
        assert not ({"e", "z", "t", "i", "f", "p", "r", "v", "x", "asterisk"} & shown)


def _status(app: TodoistApp) -> str:
    return str(app.query_one("#status", Static).render())


def _selected_rows(table: DataTable[object]) -> list[int]:
    """Row indices whose title cell carries the selection accent (magenta)."""
    marked: list[int] = []
    for i in range(table.row_count):
        cell = table.get_row_at(i)[1]
        styles = str(getattr(cell, "style", "")) + " ".join(
            str(span.style) for span in getattr(cell, "spans", [])
        )
        if "magenta" in styles:
            marked.append(i)
    return marked


@pytest.mark.anyio
async def test_x_selects_the_cursor_task_and_advances() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.pause()

        table = app.query_one(DataTable[object])
        assert _selected_rows(table) == [0]  # A accented, no rightward shift
        assert _content_col(table)[0] == "A"  # title text unchanged
        assert table.cursor_row == 1  # cursor advanced to B
        assert "1 selected" in _status(app)


@pytest.mark.anyio
async def test_x_again_deselects_the_task() -> None:
    repo = FakeRepository([_row("A"), _row("B")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A, cursor -> B
        await pilot.press("k")  # back to A
        await pilot.press("x")  # deselect A
        await pilot.pause()

        table = app.query_one(DataTable[object])
        assert _selected_rows(table) == []
        assert "selected" not in _status(app)


@pytest.mark.anyio
async def test_select_all_marks_every_task() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("*")
        await pilot.pause()

        table = app.query_one(DataTable[object])
        assert _selected_rows(table) == [0, 1, 2]
        assert "3 selected" in _status(app)


@pytest.mark.anyio
async def test_escape_clears_the_selection() -> None:
    repo = FakeRepository([_row("A"), _row("B")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("*")
        await pilot.press("escape")
        await pilot.pause()

        table = app.query_one(DataTable[object])
        assert _selected_rows(table) == []
        assert "selected" not in _status(app)


@pytest.mark.anyio
async def test_toggling_on_a_group_header_is_a_noop() -> None:
    repo = FakeRepository([_row("A")], [Project(id="220", name="Errands")])
    app = TodoistApp(
        repo, arrangements=await _grouped_by_project(), clock=FakeClock(_TODAY)
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        table = app.query_one(DataTable[object])
        table.move_cursor(row=0)  # the group header
        await pilot.press("x")
        await pilot.pause()

        assert "selected" not in _status(app)


@pytest.mark.anyio
async def test_completing_applies_to_the_whole_selection() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A, cursor -> B
        await pilot.press("j")  # cursor -> C
        await pilot.press("x")  # select C
        await pilot.press("e")  # complete the selection {A, C}
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert set(repo.completed) == {TaskId("A"), TaskId("C")}
        table = app.query_one(DataTable[object])
        assert _content_col(table) == ["B"]  # only the unselected task remains
        assert "selected" not in _status(app)  # selection cleared after the action


@pytest.mark.anyio
async def test_undo_restores_the_whole_completed_batch() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("e")  # complete {A, C}
        await app.workers.wait_for_complete()
        await pilot.press("z")  # undo the batch
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert set(repo.uncompleted) == {TaskId("A"), TaskId("C")}
        table = app.query_one(DataTable[object])
        assert set(_content_col(table)) == {"A", "B", "C"}


class FailingOnCompleteRepository(FakeRepository):
    """complete() raises for one specific id, succeeds for the rest."""

    def __init__(self, *args: object, fail_id: TaskId, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        self._fail_id = fail_id

    async def complete(self, task_id: TaskId) -> None:
        if task_id == self._fail_id:
            raise RuntimeError("boom")
        await super().complete(task_id)


@pytest.mark.anyio
async def test_partial_batch_complete_undoes_only_the_successes() -> None:
    repo = FailingOnCompleteRepository(
        [_row("A"), _row("B"), _row("C")], [], fail_id=TaskId("C")
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("j")  # cursor -> B
        await pilot.press("e")  # a prior single completion sets an earlier undo (B)
        await app.workers.wait_for_complete()
        # now a batch where C fails but A succeeds
        await pilot.press("x")  # select the current task (C)
        await pilot.press("k")  # -> A
        await pilot.press("x")  # select A
        await pilot.press("e")  # batch complete {A, C}; C rejected
        await app.workers.wait_for_complete()
        await pilot.press("z")  # undo must reverse A (the success), not the prior B
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert TaskId("A") in repo.uncompleted  # the confirmed close is undoable
        assert TaskId("B") not in repo.uncompleted  # the stale prior undo is gone


@pytest.mark.anyio
async def test_deleting_a_selection_confirms_with_the_count() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("delete")

        assert isinstance(app.screen, ConfirmScreen)
        assert "2 tasks" in str(app.screen.query_one("#confirm", Static).render())
        await pilot.press("y")  # confirm
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert set(repo.deleted) == {TaskId("A"), TaskId("C")}
        assert _content_col(app.query_one(DataTable[object])) == ["B"]
        assert "selected" not in _status(app)


@pytest.mark.anyio
async def test_cancelling_a_selection_delete_keeps_all_and_the_selection() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("delete")
        await pilot.press("n")  # cancel
        await pilot.pause()

        assert repo.deleted == []
        assert set(_content_col(app.query_one(DataTable[object]))) == {"A", "B", "C"}
        assert "2 selected" in _status(app)  # selection survives a cancel


@pytest.mark.anyio
async def test_setting_priority_applies_to_the_whole_selection() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("1")  # set P1 on the selection
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert set(repo.priorities) == {
            (TaskId("A"), Priority.P1),
            (TaskId("C"), Priority.P1),
        }
        assert "selected" not in _status(app)


@pytest.mark.anyio
async def test_scheduling_applies_to_the_whole_selection() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("t")  # one schedule screen for the selection
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow: 2026-07-29
        await app.workers.wait_for_complete()
        await pilot.pause()

        tomorrow = Due(date=datetime.date(2026, 7, 29))
        assert set(repo.dues) == {(TaskId("A"), tomorrow), (TaskId("C"), tomorrow)}
        assert "selected" not in _status(app)


def _timed(content: str) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21), time=datetime.time(9, 0)),
        project_id="220",
    )


@pytest.mark.anyio
async def test_reminder_add_relative_to_a_task_with_due_time() -> None:
    repo = FakeRepository([_timed("A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("R")  # open the reminders manager
        await pilot.pause()
        assert isinstance(app.screen, RemindersScreen)
        await pilot.press("a", "r", "3", "0", "enter")  # add relative, 30 min before
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert [(r.item_id, r.type, r.minute_offset) for r in repo.added_reminders] == [
            ("A", "relative", 30)
        ]


@pytest.mark.anyio
async def test_reminder_delete_from_the_manager() -> None:
    existing = Reminder(id="r1", item_id="A", type="relative", minute_offset=30)
    repo = FakeRepository([_timed("A")], [], reminders=[existing])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("d")  # delete the highlighted reminder
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert repo.deleted_reminders == ["r1"]


@pytest.mark.anyio
async def test_reminder_add_over_a_selection_hits_each_task() -> None:
    repo = FakeRepository([_timed("A"), _timed("B"), _timed("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("R")  # add-only flow for the selection
        await pilot.pause()
        await pilot.press("r", "h")  # relative, 1 hour before
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert {(r.item_id, r.minute_offset) for r in repo.added_reminders} == {
            ("A", 60),
            ("C", 60),
        }
        assert "selected" not in _status(app)


@pytest.mark.anyio
async def test_reminder_relative_over_selection_skips_tasks_without_due_time() -> None:
    # A has a due time, B does not: a relative add reaches only A.
    repo = FakeRepository([_timed("A"), _row("B")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("x")  # select B (cursor advanced onto B)
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("r", "h")  # relative, 1 hour before
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert {r.item_id for r in repo.added_reminders} == {"A"}


@pytest.mark.anyio
async def test_reminder_relative_with_no_eligible_task_reports() -> None:
    # A selection of tasks that all lack a due time: bulk add-mode offers relative,
    # but the request adds nothing and reports why.
    repo = FakeRepository([_row("A"), _row("B")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("x")  # select B
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("r", "h")  # relative, 1 hour before
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert repo.added_reminders == []
        assert "due time" in _status(app)


@pytest.mark.anyio
async def test_reminder_add_absolute_picks_a_date() -> None:
    repo = FakeRepository([_row("A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("a", "a")  # add -> absolute -> opens the date picker
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow: 2026-07-29
        await app.workers.wait_for_complete()
        await pilot.pause()

        (reminder,) = repo.added_reminders
        assert reminder.item_id == "A"
        assert reminder.type == "absolute"
        assert reminder.due is not None
        assert reminder.due.date == datetime.date(2026, 7, 29)


@pytest.mark.anyio
async def test_reminder_bell_rides_along_the_due_cell() -> None:
    existing = Reminder(id="r1", item_id="A", type="relative", minute_offset=30)
    repo = FakeRepository([_timed("A")], [], reminders=[existing])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()

        table = app.query_one(DataTable[object])
        assert "Rem" not in [str(c.label) for c in table.ordered_columns]
        assert "🔔" in str(_cell(table, 0, "Due"))


@pytest.mark.anyio
async def test_two_reminders_show_a_count() -> None:
    reminders = [
        Reminder(id="r1", item_id="A", type="relative", minute_offset=30),
        Reminder(id="r2", item_id="A", type="relative", minute_offset=60),
    ]
    repo = FakeRepository([_timed("A")], [], reminders=reminders)
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()

        table = app.query_one(DataTable[object])
        assert "🔔2" in str(_cell(table, 0, "Due"))


@pytest.mark.anyio
async def test_a_reminder_alone_keeps_the_due_column() -> None:
    task = Task(
        id=TaskId("A"),
        content="Buy milk",
        priority=Priority.P4,
        due=None,
        project_id="220",
    )
    existing = Reminder(
        id="r1",
        item_id="A",
        type="absolute",
        due=Due(date=datetime.date(2026, 7, 29), time=datetime.time(11, 0)),
    )
    repo = FakeRepository([task], [], reminders=[existing])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()

        table = app.query_one(DataTable[object])
        assert str(_cell(table, 0, "Due")) == "🔔"


@pytest.mark.anyio
async def test_setting_deadline_applies_to_the_whole_selection() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("d")  # one deadline screen for the selection
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow
        await app.workers.wait_for_complete()
        await pilot.pause()

        by = Deadline(date=datetime.date(2026, 7, 29))
        assert set(repo.deadlines) == {(TaskId("A"), by), (TaskId("C"), by)}
        assert "selected" not in _status(app)


@pytest.mark.anyio
async def test_moving_applies_to_the_whole_selection() -> None:
    repo = FakeRepository(
        [_row("A", "220"), _row("B", "220")],
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("x")  # select B (cursor already on B)
        await pilot.press("v")  # one project picker for the selection
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert set(repo.moves) == {(TaskId("A"), "9", None), (TaskId("B"), "9", None)}
        assert "selected" not in _status(app)


@pytest.mark.anyio
async def test_duplicate_project_copies_it_under_a_new_name() -> None:
    repo = FakeRepository(
        [_row("A", "9"), _row("B", "9")],
        [Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("Y")  # open the duplicate picker
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)
        await pilot.press("enter")  # highlight + choose "Work"
        await pilot.pause()
        assert isinstance(app.screen, TextPromptScreen)
        await pilot.press("enter")  # accept the "Work (copy)" default
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert len(repo.applied) == 1
        plan = repo.applied[0]
        assert plan.projects[0].name == "Work (copy)"
        assert {t.content for t in plan.tasks} == {"A", "B"}


@pytest.mark.anyio
async def test_duplicate_section_copies_its_tasks_into_the_project() -> None:
    task = Task(
        id=TaskId("A"),
        content="A",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="9",
        section_id="s1",
    )
    repo = FakeRepository(
        [task],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("Y")
        await pilot.pause()
        await pilot.press("down")  # Work -> Work / Planning
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, TextPromptScreen)
        await pilot.press("enter")  # accept "Planning (copy)"
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert len(repo.applied) == 1
        plan = repo.applied[0]
        assert plan.projects == ()
        assert plan.sections[0].name == "Planning (copy)"
        assert plan.sections[0].project_ref == "9"
        assert {t.content for t in plan.tasks} == {"A"}


def _section_repo() -> FakeRepository:
    task = Task(
        id=TaskId("A"),
        content="A",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="9",
        section_id="s1",
    )
    return FakeRepository(
        [task],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
    )


@pytest.mark.anyio
async def test_delete_section_removes_it_after_confirmation() -> None:
    repo = _section_repo()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("D")  # open the section picker
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)
        await pilot.press("enter")  # only "Work / Planning" is listed
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert repo.deleted_sections == ["s1"]


@pytest.mark.anyio
async def test_delete_section_cancelled_at_the_confirmation_deletes_nothing() -> None:
    repo = _section_repo()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("D")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert repo.deleted_sections == []
        await pilot.press("D")  # the guard released, so the picker reopens
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)


class OfflineSectionsRepository(FakeRepository):
    """Sections load fails while `offline`, so a retry proves the guard released."""

    offline = False

    async def sections(self) -> list[Section]:
        if self.offline:
            raise RuntimeError("offline")
        return await super().sections()


@pytest.mark.anyio
async def test_delete_section_load_failure_is_surfaced_and_releases_the_guard() -> None:
    repo = OfflineSectionsRepository(
        [],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        repo.offline = True
        await pilot.press("D")
        await pilot.pause()

        assert not isinstance(app.screen, ProjectPickerScreen)
        assert "Failed to load sections: offline" in _status(app)

        repo.offline = False
        await pilot.press("D")  # the guard released, so a retry still opens
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)


class FailingDeleteSectionRepository(FakeRepository):
    async def delete_section(self, section_id: str) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_delete_section_failure_is_surfaced() -> None:
    app = TodoistApp(
        FailingDeleteSectionRepository(
            [],
            [Project(id="9", name="Work")],
            sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
        ),
        clock=FakeClock(_TODAY),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("D")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("y")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert "Failed to delete section: boom" in _status(app)


@pytest.mark.anyio
async def test_labels_over_a_selection_add_to_each_task() -> None:
    repo = FakeRepository(
        [_labeled("A", ("home",)), _labeled("B", ()), _labeled("C", ("work",))],
        [],
        labels=[
            Label(id="l1", name="home"),
            Label(id="l2", name="urgent"),
            Label(id="l3", name="work"),
        ],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("at")  # one label editor for the selection
        await pilot.pause()
        assert isinstance(app.screen, LabelsScreen)
        await pilot.press("down")  # highlight "urgent" (sorted: home, urgent, work)
        await pilot.press("space")  # add it
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        added = {task_id: labels for task_id, labels, _ in repo.label_edits}
        assert added == {  # existing labels kept, "urgent" unioned in
            TaskId("A"): ("home", "urgent"),
            TaskId("C"): ("work", "urgent"),
        }
        assert "selected" not in _status(app)


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
        assert str(table.get_row_at(0)[1]) == "Filtered task"
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
        assert str(table.get_row_at(0)[1]) == "Work task"
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
    app = TodoistApp(
        FakeRepository([task], [Project(id="220", name="Errands")]),
        clock=FakeClock(_TODAY),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        row = table.get_row_at(0)
        assert row[0] == "🔴"
        assert str(row[1]) == "Buy milk"  # title leads, right after the priority dot
        assert str(_cell(table, 0, "Due")) == "21 Jul 09:30"  # overdue vs _TODAY
        assert str(_cell(table, 0, "Project")) == "Errands"


@pytest.mark.anyio
async def test_all_empty_metadata_columns_are_hidden() -> None:
    # no deadline, no project on any task -> those columns drop out entirely
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 7, 30)),
        project_id="220",  # no matching Project provided -> no project name
    )
    app = TodoistApp(FakeRepository([task], []), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[object])
        labels = [str(c.label) for c in table.ordered_columns]
        assert labels == ["", "Task", "Due"]  # Deadline + Project omitted


@pytest.mark.anyio
async def test_labels_render_in_own_dim_column() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=None,
        project_id="220",
        labels=("errand", "home"),
    )
    app = TodoistApp(FakeRepository([task], []), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[object])
        columns = [str(c.label) for c in table.ordered_columns]
        assert columns == ["", "Task", "Labels"]  # Labels sits right after the title
        cell = _cell(table, 0, "Labels")
        assert isinstance(cell, Text) and cell.style == "dim"  # recedes behind title
        assert str(cell) == "@errand @home"


@pytest.mark.anyio
async def test_labels_column_hidden_when_no_task_has_labels() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=None,
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], []), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[object])
        columns = [str(c.label) for c in table.ordered_columns]
        assert "Labels" not in columns


@pytest.mark.anyio
async def test_title_is_bold_and_dates_dimmed() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 7, 30)),  # future: dim, not red
        project_id="220",
    )
    app = TodoistApp(
        FakeRepository([task], [Project(id="220", name="Errands")]),
        clock=FakeClock(_TODAY),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[object])
        title = table.get_row_at(0)[1]
        due = _cell(table, 0, "Due")
        project = _cell(table, 0, "Project")
        assert isinstance(title, Text) and title.style == "bold"  # title, theme-safe
        assert isinstance(due, Text) and due.style == "dim"  # due recedes
        assert isinstance(project, Text) and project.style == "dim"  # project recedes


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
            str(app.query_one(DataTable[object]).get_row_at(0)[1])
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
    app = TodoistApp(
        FakeRepository([task], [Project(id="220", name="Errands")]),
        clock=FakeClock(_TODAY),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert str(_cell(table, 0, "Due")) == "21 Jul"


@pytest.mark.anyio
async def test_recurring_task_marks_due_cell() -> None:
    task = Task(
        id=TaskId("1"),
        content="Water plants",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 8, 5), is_recurring=True, string="every day"),
        project_id="220",
    )
    app = TodoistApp(
        FakeRepository([task], [Project(id="220", name="Errands")]),
        clock=FakeClock(_TODAY),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        assert "↻" in str(_cell(app.query_one(DataTable[object]), 0, "Due"))


@pytest.mark.anyio
async def test_non_recurring_task_due_cell_has_no_marker() -> None:
    task = Task(
        id=TaskId("1"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 8, 5)),
        project_id="220",
    )
    app = TodoistApp(
        FakeRepository([task], [Project(id="220", name="Errands")]),
        clock=FakeClock(_TODAY),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        assert "↻" not in str(_cell(app.query_one(DataTable[object]), 0, "Due"))


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
        # the sole task has no due → the Due column drops out entirely
        assert _cell(app.query_one(DataTable[object]), 0, "Due") is None


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
        # no task has a project name → the Project column drops out entirely
        assert _cell(app.query_one(DataTable[object]), 0, "Project") is None


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


@pytest.mark.anyio
async def test_pressing_delete_cancelled_keeps_the_task() -> None:
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
        await pilot.press("delete")
        assert isinstance(app.screen, ConfirmScreen)  # confirm before deleting
        await pilot.press("n")  # cancel
        await pilot.pause()

        assert not isinstance(app.screen, ConfirmScreen)  # dialog dismissed
        assert repo.deleted == []  # nothing deleted
        assert app.query_one(DataTable[object]).row_count == 1  # row still there


@pytest.mark.anyio
async def test_pressing_delete_confirmed_deletes_optimistically() -> None:
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
        await pilot.press("delete")
        await pilot.press("y")  # confirm
        # optimistic: row is gone before the network command resolves
        assert app.query_one(DataTable[object]).row_count == 0
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.deleted == [TaskId("6X4")]
        assert app.query_one(DataTable[object]).row_count == 0


class GatedRefreshRepository(FakeRepository):
    """refresh() blocks until released, so the syncing state is observable."""

    def __init__(
        self,
        tasks: list[Task],
        projects: list[Project],
        inbox: list[Task] | None = None,
        filters: list[Filter] | None = None,
        pool: list[Task] | None = None,
    ) -> None:
        super().__init__(tasks, projects, inbox=inbox, filters=filters, pool=pool)
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
        assert str(table.get_row_at(table.cursor_row)[1]).strip() == "Buy milk"  # <-

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


class LaggingEditRepository(FakeRepository):
    """Todoist eventual consistency: an edit is accepted but the sync snapshot
    keeps returning the old field value until the server catches up."""

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None:
        self.priorities.append((task_id, priority))  # recorded, not yet reflected

    async def set_due(self, task_id: TaskId, due: Due | None) -> None:
        self.dues.append((task_id, due))

    async def set_deadline(self, task_id: TaskId, deadline: Deadline | None) -> None:
        self.deadlines.append((task_id, deadline))

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        self.moves.append((task_id, project_id, section_id))

    def catch_up(self) -> None:
        for tid, priority in self.priorities:
            self._tasks = [
                replace(t, priority=priority) if t.id == tid else t for t in self._tasks
            ]
        for tid, due in self.dues:
            self._tasks = [
                replace(t, due=due) if t.id == tid else t for t in self._tasks
            ]
        for tid, deadline in self.deadlines:
            self._tasks = [
                replace(t, deadline=deadline) if t.id == tid else t for t in self._tasks
            ]
        for tid, project_id, section_id in self.moves:
            self._tasks = [
                replace(t, project_id=project_id, section_id=section_id)
                if t.id == tid
                else t
                for t in self._tasks
            ]


@pytest.mark.anyio
async def test_priority_survives_a_lagging_sync() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = LaggingEditRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        await pilot.press("1")
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == "🔴"
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()  # the success sync lands, still lists P4

        # optimistic P1 must not be reverted by the lagging snapshot
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == "🔴"

        repo.catch_up()  # server finally reflects the change
        await pilot.press("r")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == "🔴"


@pytest.mark.anyio
async def test_rapid_priority_sets_settle_on_the_last_value() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = LaggingEditRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        await pilot.press("1")
        await pilot.press("2")  # second set before the first's sync settles
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == "🟠"  # P2
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.priorities == [
            (TaskId("6X4"), Priority.P1),
            (TaskId("6X4"), Priority.P2),
        ]
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == "🟠"  # holds P2

        repo.catch_up()
        await pilot.press("r")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert app.query_one(DataTable[object]).get_row_at(0)[0] == "🟠"


@pytest.mark.anyio
async def test_due_survives_a_lagging_sync() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="9",
    )
    repo = LaggingEditRepository([task], [Project(id="9", name="Work")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("enter")  # open the Work project view (keeps=project)
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")  # tomorrow: 2026-07-29
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.dues == [(TaskId("6X4"), Due(date=datetime.date(2026, 7, 29)))]
        # the lagging snapshot still says 21 Jul; the optimistic due must hold
        assert str(_cell(app.query_one(DataTable[object]), 0, "Due")) == "Tomorrow"


@pytest.mark.anyio
async def test_deadline_survives_a_lagging_sync() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Ship it",
        priority=Priority.P2,
        due=Due(date=_TODAY),  # stays in Today regardless of the deadline
        project_id="220",
    )
    repo = LaggingEditRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("m")  # tomorrow
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        # the lagging snapshot has no deadline; the optimistic one must hold
        assert str(_cell(app.query_one(DataTable[object]), 0, "Deadline")) == "Tomorrow"


@pytest.mark.anyio
async def test_move_survives_a_lagging_sync() -> None:
    repo = LaggingEditRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.moves == [(TaskId("t1"), "9", None)]
        # the lagging snapshot still lists Errands; the optimistic project must hold
        assert str(_cell(app.query_one(DataTable[object]), 0, "Project")) == "Work"


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
        assert str(table.get_row_at(0)[1]) == "Buy milk"
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


class FailingDeleteRepository(FakeRepository):
    async def delete(self, task_id: TaskId) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_delete_failure_is_surfaced_and_unhides() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    app = TodoistApp(FailingDeleteRepository([task], [Project(id="220", name="X")]))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("delete")
        await pilot.press("y")  # confirm
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert "Failed to delete task: boom" in str(
            app.query_one("#status", Static).render()
        )
        assert app.query_one(DataTable[object]).row_count == 1  # unhidden


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
        assert str(table.get_row_at(0)[1]) == "Buy milk"


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
        assert str(table.get_row_at(0)[1]) == "Water plants"


@pytest.mark.anyio
async def test_completing_moves_cursor_to_the_task_below() -> None:
    repo = FakeRepository(
        [_row("A"), _row("B"), _row("C")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("j")  # cursor: A -> B
        await pilot.press("e")  # complete B
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        table = app.query_one(DataTable[object])
        assert table.row_count == 2
        assert str(table.get_row_at(table.cursor_row)[1]) == "C"  # not back up to A


@pytest.mark.anyio
async def test_completing_the_last_task_moves_cursor_up() -> None:
    repo = FakeRepository(
        [_row("A"), _row("B"), _row("C")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.press("j")
        await pilot.press("j")  # cursor: A -> B -> C (last)
        await pilot.press("e")  # complete C
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        table = app.query_one(DataTable[object])
        assert table.row_count == 2
        assert str(table.get_row_at(table.cursor_row)[1]) == "B"  # up to the one above


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
        assert str(_cell(table, 0, "Deadline")) == "Tomorrow"


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
        assert str(_cell(app.query_one(DataTable[object]), 0, "Deadline")) == "Tomorrow"
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("x")  # clear
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.deadlines == [(TaskId("6X4"), None)]
        # deadline cleared → the Deadline column drops out
        assert _cell(app.query_one(DataTable[object]), 0, "Deadline") is None


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
        assert str(_cell(table, 0, "Due")) == "Today"


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
        assert str(_cell(app.query_one(DataTable[object]), 0, "Due")) == "Today"
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
        assert str(_cell(table, 0, "Due")) == "Tomorrow"


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
        assert str(_cell(app.query_one(DataTable[object]), 0, "Due")) == "Today"


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
        # failed command resyncs to server truth: due reverts to none, column drops
        assert _cell(app.query_one(DataTable[object]), 0, "Due") is None


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
        assert str(_cell(app.query_one(DataTable[object]), 0, "Project")) == "Work"


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
        assert str(_cell(app.query_one(DataTable[object]), 0, "Project")) == "Errands"


def _labeled(content: str, labels: tuple[str, ...]) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
        labels=labels,
    )


@pytest.mark.anyio
async def test_at_opens_labels_editor() -> None:
    repo = FakeRepository(
        [_labeled("t1", ())], [], labels=[Label(id="l1", name="home")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("at")
        await pilot.pause()
        assert isinstance(app.screen, LabelsScreen)


@pytest.mark.anyio
async def test_at_toggle_and_confirm_updates_cell_and_records() -> None:
    repo = FakeRepository(
        [_labeled("t1", ("work",))],
        [],
        labels=[Label(id="l1", name="home"), Label(id="l2", name="work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("at")
        await pilot.pause()
        await pilot.press("space")  # toggle "home" on ("work" already checked)
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.label_edits == [(TaskId("t1"), ("home", "work"), ())]
        assert str(_cell(app.query_one(DataTable[object]), 0, "Labels")) == (
            "@home @work"
        )


@pytest.mark.anyio
async def test_at_create_new_label_passes_it_as_a_creation() -> None:
    repo = FakeRepository(
        [_labeled("t1", ())], [], labels=[Label(id="l1", name="home")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("at")
        await pilot.pause()
        await pilot.press("f", "r", "e", "s", "h")  # no existing match
        await pilot.press("space")  # create + select "fresh"
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.label_edits == [(TaskId("t1"), ("fresh",), ("fresh",))]


@pytest.mark.anyio
async def test_at_unchanged_selection_is_a_noop() -> None:
    repo = FakeRepository(
        [_labeled("t1", ("work",))], [], labels=[Label(id="l2", name="work")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("at")
        await pilot.pause()
        await pilot.press("enter")  # confirm without toggling anything
        await pilot.pause()

        assert repo.label_edits == []


class FailingSetLabelsRepository(FakeRepository):
    async def set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...] = ()
    ) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_set_labels_failure_is_surfaced_and_resyncs() -> None:
    repo = FailingSetLabelsRepository(
        [_labeled("t1", ("work",))], [], labels=[Label(id="l1", name="home")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("at")
        await pilot.pause()
        await pilot.press("space")  # toggle "home" on
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert "Failed to set labels: boom" in str(
            app.query_one("#status", Static).render()
        )
        # failed command resyncs to server truth: the cell reverts to just "@work"
        assert str(_cell(app.query_one(DataTable[object]), 0, "Labels")) == "@work"


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
    return [str(table.get_row_at(i)[1]) for i in range(table.row_count)]


def _cell(table: DataTable[object], row: int, label: str) -> object:
    """A cell by column label, or None when that column is hidden (all-empty)."""
    labels = [str(c.label) for c in table.ordered_columns]
    if label not in labels:
        return None
    return table.get_row_at(row)[labels.index(label)]


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
        assert col2[0].lstrip().startswith("▾ ──") and "Home (1)" in col2[0]


@pytest.mark.anyio
async def test_due_date_group_headers_show_humanized_labels() -> None:
    def _due(content: str, date: datetime.date) -> Task:
        return Task(
            id=TaskId(content),
            content=content,
            priority=Priority.P4,
            due=Due(date=date),
            project_id="220",
        )

    repo = FakeRepository(
        [_due("today-task", _TODAY), _due("old-task", datetime.date(2026, 7, 21))],
        [Project(id="220", name="Work")],
    )
    store = InMemoryArrangements()
    await store.save("today", Arrangement(group_by=(Field.DUE_DATE,)))
    app = TodoistApp(repo, clock=FakeClock(_TODAY), arrangements=store)

    async with app.run_test() as pilot:
        await pilot.pause()
        col2 = _content_col(app.query_one(DataTable[object]))
        assert any("──" in c and "Today (1)" in c for c in col2)
        assert any("──" in c and "21 Jul (1)" in c for c in col2)


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
async def test_down_and_up_arrows_move_row_cursor() -> None:
    repo = FakeRepository([_row("First"), _row("Second")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("down")
        assert table.cursor_row == 1
        await pilot.press("up")
        assert table.cursor_row == 0


@pytest.mark.anyio
async def test_right_arrow_expands_a_parent_revealing_its_child() -> None:
    app = TodoistApp(_parent_and_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("right")
        await pilot.pause()
        assert [c.strip() for c in _content_col(table)] == ["▾ parent", "child"]


@pytest.mark.anyio
async def test_left_arrow_collapses_an_expanded_parent() -> None:
    app = TodoistApp(_parent_and_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("right")
        await pilot.pause()
        assert table.row_count == 2
        await pilot.press("left")
        await pilot.pause()
        assert [c.strip() for c in _content_col(table)] == ["▸ parent"]


@pytest.mark.anyio
async def test_left_arrow_on_a_child_jumps_the_cursor_to_its_parent() -> None:
    app = TodoistApp(_parent_and_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("right")
        await pilot.pause()
        await pilot.press("down")
        assert _cursor_content(table).strip() == "child"
        await pilot.press("left")
        await pilot.pause()
        assert _cursor_content(table).strip() == "▾ parent"


def _match_with_unmatched_child() -> FakeRepository:
    """A view whose query returns the parent only — the subtask cannot match it."""
    child = Task(
        id=TaskId("child"),
        content="child",
        priority=Priority.P4,
        due=None,  # no due date: never returned by a Today/filter query
        project_id="220",
        parent_id="parent",
    )
    return FakeRepository(
        [_row("parent")], [Project(id="220", name="Work")], pool=[child]
    )


@pytest.mark.anyio
async def test_a_subtask_the_query_missed_is_still_nested_under_its_parent() -> None:
    app = TodoistApp(_match_with_unmatched_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert [c.strip() for c in _content_col(table)] == ["▸ parent"]
        await pilot.press("l")
        await pilot.pause()
        assert [c.strip() for c in _content_col(table)] == ["▾ parent", "child"]


@pytest.mark.anyio
async def test_a_pulled_in_subtask_does_not_count_towards_the_view() -> None:
    app = TodoistApp(_match_with_unmatched_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one("#status", Static)
        assert "Today · 1 task(s)" in str(status.render())
        await pilot.press("l")  # revealing it must not inflate the count
        await pilot.pause()
        assert "Today · 1 task(s)" in str(status.render())


@pytest.mark.anyio
async def test_a_collapsed_matching_subtask_still_counts() -> None:
    app = TodoistApp(_parent_and_child())

    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Today · 2 task(s)" in str(app.query_one("#status", Static).render())


def _due_today(content: str, parent_id: str | None = None) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=_TODAY),
        project_id="220",
        parent_id=parent_id,
    )


def _today_view_with_a_pulled_in_subtask() -> GatedRefreshRepository:
    sub = Task(
        id=TaskId("sub"),
        content="sub",
        priority=Priority.P4,
        due=None,  # not due today: only here as a subtask of "a parent"
        project_id="220",
        parent_id="a parent",
    )
    repo = GatedRefreshRepository(
        [_due_today("a parent"), _due_today("b other")],
        [Project(id="220", name="Work")],
        pool=[sub],
    )
    repo.release.set()  # let the startup sync through
    return repo


@pytest.mark.anyio
async def test_editing_another_task_leaves_a_pulled_in_subtask_alone() -> None:
    repo = _today_view_with_a_pulled_in_subtask()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        table = app.query_one(TaskTable)
        await pilot.press("l")  # reveal the subtask
        await pilot.pause()
        await pilot.press("j", "j")  # onto "b other"
        assert _cursor_content(table).strip() == "b other"
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("l")  # calendar: move to tomorrow
        await pilot.press("enter")  # pick it: only "b other" leaves Today

        assert [c.strip() for c in _content_col(table)] == ["▾ a parent", "sub"]


@pytest.mark.anyio
async def test_a_reload_hides_the_subtask_of_a_not_yet_confirmed_close() -> None:
    class UnconfirmedCloseRepository(GatedRefreshRepository):
        """complete() is accepted but the server keeps listing the task."""

        async def complete(self, task_id: TaskId) -> None:
            self.completed.append(task_id)

    sub = Task(
        id=TaskId("sub"),
        content="sub",
        priority=Priority.P4,
        due=None,
        project_id="220",
        parent_id="a parent",
    )
    repo = UnconfirmedCloseRepository(
        [_due_today("a parent"), _due_today("b other")],
        [Project(id="220", name="Work")],
        pool=[sub],
    )
    repo.release.set()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        table = app.query_one(TaskTable)
        await pilot.press("l")  # reveal the subtask
        await pilot.pause()
        await pilot.press("e")  # close the parent
        await pilot.pause()
        await pilot.press("r")  # reload: the close is not confirmed yet
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert [c.strip() for c in _content_col(table)] == ["b other"]


@pytest.mark.anyio
async def test_a_pulled_in_subtask_leaves_with_the_parent_that_carried_it() -> None:
    repo = _today_view_with_a_pulled_in_subtask()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        table = app.query_one(TaskTable)
        await pilot.press("l")  # reveal the subtask
        await pilot.pause()
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")  # cursor is on "a parent"
        await pilot.pause()
        await pilot.press("l")  # calendar: move to tomorrow
        await pilot.press("enter")  # pick it: the parent leaves Today

        assert [c.strip() for c in _content_col(table)] == ["b other"]


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
async def test_j_moves_onto_a_group_header() -> None:
    repo = FakeRepository(
        [_row("w1", "220"), _row("h1", "9")],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert table.cursor_row == 1  # h1, under the Home header
        await pilot.press("j")  # headers are foldable, so the cursor rests on them
        assert table.cursor_row == 2
        assert "Work (1)" in _cursor_content(table)


@pytest.mark.anyio
async def test_k_moves_onto_a_group_header() -> None:
    repo = FakeRepository(
        [_row("w1", "220"), _row("h1", "9")],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("k")
        assert table.cursor_row == 0
        assert "Home (1)" in _cursor_content(table)


# --- group fold/collapse ---


async def _grouped_by_project_and_priority() -> InMemoryArrangements:
    store = InMemoryArrangements()
    await store.save("today", Arrangement(group_by=(Field.PROJECT, Field.PRIORITY)))
    return store


@pytest.mark.anyio
async def test_group_headers_carry_a_fold_marker() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        assert _content_col(app.query_one(TaskTable))[0].startswith("▾ ──")


@pytest.mark.anyio
async def test_h_folds_the_group_under_the_cursor() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("k")  # onto the Home header
        await pilot.press("h")
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert "h1" not in contents  # its task is folded away
        assert contents[0].startswith("▸ ──") and "Home (1)" in contents[0]
        assert table.cursor_row == 0  # cursor stays on the header it folded
        assert "w1" in contents  # the other group is untouched


@pytest.mark.anyio
async def test_l_reopens_a_folded_group() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("k")
        await pilot.press("h")
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert contents[0].startswith("▾ ──")
        assert "h1" in contents
        assert table.cursor_row == 0


@pytest.mark.anyio
async def test_folding_a_group_keeps_the_view_count() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one("#status", Static)
        assert "Today · 2 task(s)" in str(status.render())
        await pilot.press("k")
        await pilot.press("h")
        await pilot.pause()
        assert "Today · 2 task(s)" in str(status.render())


@pytest.mark.anyio
async def test_folding_an_outer_group_hides_its_inner_headers() -> None:
    app = TodoistApp(
        _two_project_repo(), arrangements=await _grouped_by_project_and_priority()
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("k")  # onto the Home header at row 0
        await pilot.press("k")
        await pilot.press("h")
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert contents[0].startswith("▸ ──") and "Home (1)" in contents[0]
        # only Work's priority header survives; Home's went with its subtree
        assert sum(Priority.P4.label in c for c in contents) == 1
        assert "h1" not in contents


@pytest.mark.anyio
async def test_folding_an_inner_group_leaves_its_outer_header_open() -> None:
    app = TodoistApp(
        _two_project_repo(), arrangements=await _grouped_by_project_and_priority()
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        table.move_cursor(row=1)  # the priority header under Home
        await pilot.press("h")
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert contents[0].startswith("▾ ──") and "Home (1)" in contents[0]
        assert contents[1].startswith("▸ ──")
        assert "h1" not in contents


@pytest.mark.anyio
async def test_h_on_a_folded_header_jumps_to_its_outer_header() -> None:
    app = TodoistApp(
        _two_project_repo(), arrangements=await _grouped_by_project_and_priority()
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        table.move_cursor(row=1)
        await pilot.press("h")  # fold the inner group
        await pilot.pause()
        await pilot.press("h")  # already folded: step out to the outer header
        await pilot.pause()
        assert table.cursor_row == 0
        assert "Home (1)" in _cursor_content(table)


@pytest.mark.anyio
async def test_h_on_a_top_level_folded_header_stays_put() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("k")
        await pilot.press("h")
        await pilot.pause()
        await pilot.press("h")  # no outer group to step out to
        await pilot.pause()
        assert table.cursor_row == 0


@pytest.mark.anyio
async def test_x_on_a_group_header_selects_nothing() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("k")  # onto the Home header
        await pilot.press("x")
        await pilot.pause()
        assert "selected" not in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_enter_on_a_group_header_opens_no_detail() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("k")
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, TaskDetailScreen)


@pytest.mark.anyio
async def test_regrouping_unfolds_everything() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("k")
        await pilot.press("h")  # fold "Home"
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("r")  # group by Priority: the old label paths are stale
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert not any(c.startswith("▸ ──") for c in contents)
        assert "h1" in contents and "w1" in contents


@pytest.mark.anyio
async def test_k_at_the_top_row_stays_put() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("k")  # onto the header
        assert table.cursor_row == 0
        await pilot.press("k")  # nothing above it
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
        assert str(table.get_row_at(table.cursor_row)[1]) == "Second"


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
        assert str(app.query_one(DataTable[object]).get_row_at(0)[1]) == "Today thing"

        await pilot.press("i")
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert str(table.get_row_at(0)[1]) == "Inbox thing"
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
        assert str(table.get_row_at(0)[1]) == "Today thing"
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
async def test_pressing_H_sets_current_view_as_home() -> None:
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

        await pilot.press("H")  # pin it as home
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
        assert str(table.get_row_at(0)[1]) == "i1"
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
async def test_pressing_m_returns_to_the_home_view() -> None:
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

        await pilot.press("m")  # jump home
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

        await pilot.press("m")  # back to the filter home
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        assert "My Filter" in str(app.query_one("#status", Static).render())
        assert "p1" in repo.refresh_filtered_queries  # live-refreshed as a filter


def _noted(content: str, description: str = "") -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
        description=description,
    )


@pytest.mark.anyio
async def test_a_description_marks_the_title_and_a_bare_task_stays_clean() -> None:
    repo = FakeRepository([_noted("t1", "a note"), _noted("t2")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert _content_col(app.query_one(TaskTable)) == ["t1 ≡", "t2"]


@pytest.mark.anyio
async def test_the_description_marker_recedes_behind_the_bold_title() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        cell = app.query_one(TaskTable).get_row_at(0)[1]
        assert isinstance(cell, Text)
        assert [
            (str(span.style), cell.plain[span.start : span.end]) for span in cell.spans
        ] == [("not bold dim", " ≡")]


@pytest.mark.anyio
async def test_adding_a_description_makes_the_marker_appear_at_once() -> None:
    repo = FakeRepository([_noted("t1")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert _content_col(app.query_one(TaskTable)) == ["t1"]
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.press("n")  # description becomes "n"
        await pilot.press("ctrl+s")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert _content_col(app.query_one(TaskTable)) == ["t1 ≡"]


@pytest.mark.anyio
async def test_ctrl_e_opens_the_editor_prefilled_from_the_cursor_row() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert isinstance(app.screen, TaskEditScreen)
        assert app.screen.query_one(Input).value == "t1"
        assert app.screen.query_one(TextArea).text == "a note"


@pytest.mark.anyio
async def test_saving_the_editor_repaints_the_title_and_sends_one_update() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("!")  # title becomes "t1!"
        await pilot.press("tab")
        await pilot.press("s")  # description becomes "a notes"
        await pilot.press("ctrl+s")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert repo.text_edits == [(TaskId("t1"), "t1!", "a notes")]
        assert _content_col(app.query_one(TaskTable))[0] == "t1! ≡"


@pytest.mark.anyio
async def test_ctrl_e_ignores_the_selection_and_edits_the_cursor_task() -> None:
    repo = FakeRepository([_noted("t1"), _noted("t2")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("x")  # selects t1, cursor advances to t2
        await pilot.press("x")  # selects t2
        await pilot.press("k")  # cursor back on t1
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("!")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]

        assert repo.text_edits == [(TaskId("t1"), "t1!", "")]
        assert _selected_rows(app.query_one(TaskTable)) == [0, 1]  # selection kept


@pytest.mark.anyio
async def test_cancelling_the_editor_records_nothing() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("!")
        await pilot.press("escape")
        await pilot.pause()

        assert repo.text_edits == []
        assert _content_col(app.query_one(TaskTable))[0] == "t1 ≡"


@pytest.mark.anyio
async def test_saving_unchanged_text_is_a_noop() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("ctrl+s")  # nothing typed
        await pilot.pause()

        assert repo.text_edits == []


@pytest.mark.anyio
async def test_ctrl_e_on_an_empty_table_does_nothing() -> None:
    app = TodoistApp(FakeRepository([], []))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert not isinstance(app.screen, TaskEditScreen)


@pytest.mark.anyio
async def test_ctrl_e_on_a_group_header_does_nothing() -> None:
    repo = FakeRepository([_noted("t1")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        table.move_cursor(row=0)  # the group header
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert not isinstance(app.screen, TaskEditScreen)


class FailingSetTextRepository(FakeRepository):
    async def set_text(self, task_id: TaskId, content: str, description: str) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_set_text_failure_is_surfaced_and_resyncs() -> None:
    repo = FailingSetTextRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("!")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert "Failed to edit task: boom" in _status(app)
        # failed command resyncs to server truth: the title reverts
        assert _content_col(app.query_one(TaskTable))[0] == "t1 ≡"


@pytest.mark.anyio
async def test_ctrl_e_in_the_detail_card_opens_the_editor() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert isinstance(app.screen, TaskEditScreen)
        assert not [s for s in app.screen_stack if isinstance(s, TaskDetailScreen)]


@pytest.mark.anyio
async def test_saving_from_the_detail_card_reopens_it_with_the_new_text() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("!")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        assert isinstance(app.screen, TaskDetailScreen)
        details = [s for s in app.screen_stack if isinstance(s, TaskDetailScreen)]
        assert len(details) == 1  # the stale card was replaced, not stacked
        assert "t1!" in str(app.screen.query_one("#detail", Static).render())


@pytest.mark.anyio
async def test_cancelling_the_editor_returns_to_the_detail_card() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app.screen, TaskDetailScreen)
        assert repo.text_edits == []
