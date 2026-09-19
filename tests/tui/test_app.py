import asyncio
import datetime
import re
from collections.abc import Sequence
from dataclasses import replace
from functools import partial
from typing import cast

import pytest
from rich.cells import cell_len
from rich.color_triplet import ColorTriplet
from rich.text import Text
from textual.content import Content
from textual.coordinate import Coordinate
from textual.pilot import Pilot
from textual.widgets import (
    DataTable,
    Footer,
    Input,
    OptionList,
    Rule,
    Static,
    TextArea,
)

from tests.tui.tiers import (
    cell_tier,
    priority_of,
    selected,
    span_tiers,
    tier_at,
    title_cell,
)
from tests.tui.view_labels import view_label
from tests.tui.waiting import settled
from todoist_tui.application.views import TaskRow, View
from todoist_tui.domain.activity import ActivityEvent, ActivityPage, EventKind
from todoist_tui.domain.arrange import (
    Arrangement,
    Field,
    GroupPath,
    RenderRow,
    SortKey,
    TaskLine,
)
from todoist_tui.domain.comment import Comment
from todoist_tui.domain.creation import CreationPlan, NewTask
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.label import Label
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.domain.view_slots import ViewSlots
from todoist_tui.tui.app import (
    MARKER_SLOT,
    PENDING_MARK,
    ColumnHeader,
    InMemoryArrangements,
    InMemoryFolds,
    InMemoryViewSlots,
    StatusBand,
    TaskTable,
    TodoistApp,
    as_binding,
)
from todoist_tui.tui.screens.activity import ActivityScreen
from todoist_tui.tui.screens.arrange import ArrangeScreen
from todoist_tui.tui.screens.comments import CommentsScreen
from todoist_tui.tui.screens.confirm import ConfirmScreen
from todoist_tui.tui.screens.detail import FORWARDED, TaskDetailScreen
from todoist_tui.tui.screens.draft import (
    DEADLINE_ICON,
    DUE_ICON,
    LABELS_ICON,
    PROJECT_ICON,
    SUBTASKS_ICON,
)
from todoist_tui.tui.screens.edit import TaskEditScreen
from todoist_tui.tui.screens.help import HelpScreen
from todoist_tui.tui.screens.labels import LabelsScreen
from todoist_tui.tui.screens.parent_picker import ParentPickerScreen
from todoist_tui.tui.screens.project_picker import ProjectPickerScreen
from todoist_tui.tui.screens.reminders import RemindersScreen
from todoist_tui.tui.screens.schedule import ScheduleScreen
from todoist_tui.tui.screens.scrolling import ScrollBody
from todoist_tui.tui.screens.subtask_list import SubtaskList
from todoist_tui.tui.screens.text_prompt import TextPromptScreen
from todoist_tui.tui.screens.views import ViewsScreen
from todoist_tui.tui.theme import Tier


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
        events: tuple[ActivityEvent, ...] = (),
        comments: tuple[Comment, ...] = (),
    ) -> None:
        self._tasks = tasks
        self._projects = projects
        self._inbox = inbox or []
        self._pool = pool or []  # tasks no view returns, e.g. non-matching subtasks
        self._filters = filters or []
        self._sections = sections or []
        self._labels = labels or []
        self._reminders = reminders or []
        self._events = events
        self._comments = comments
        self.comment_reads: list[TaskId] = []
        self.added_reminders: list[Reminder] = []
        self.deleted_reminders: list[str] = []
        self.label_edits: list[tuple[TaskId, tuple[str, ...], tuple[str, ...]]] = []
        self.text_edits: list[tuple[TaskId, str, str]] = []
        self.completed: list[TaskId] = []
        self.uncompleted: list[TaskId] = []
        self.deleted: list[TaskId] = []
        self.deleted_sections: list[str] = []
        self.priorities: list[tuple[TaskId, Priority]] = []
        self.dues: list[tuple[TaskId, Due | DueText | None]] = []
        self.log: list[
            str
        ] = []  # write order, so a reminder can be shown to follow its due
        self.deadlines: list[tuple[TaskId, Deadline | None]] = []
        self.moves: list[tuple[TaskId, str, str | None]] = []
        self.parents: list[tuple[TaskId, str]] = []
        self.reorders: list[list[tuple[TaskId, int]]] = []
        self.section_reorders: list[list[tuple[str, int]]] = []
        self.day_orders: list[list[tuple[TaskId, int]]] = []
        self.applied: list[CreationPlan] = []
        self._removed: dict[TaskId, Task] = {}
        self._removed_pool: dict[TaskId, Task] = {}
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

    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        return ActivityPage(events=self._events, next_cursor=None)

    async def comments(self, task_id: TaskId) -> list[Comment]:
        self.comment_reads.append(task_id)
        return list(self._comments)

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
        closing = self._subtree(task_id)  # item_close takes the whole subtree
        self._removed.update({t.id: t for t in self._tasks if t.id in closing})
        self._removed_pool.update({t.id: t for t in self._pool if t.id in closing})
        self._tasks = [t for t in self._tasks if t.id not in closing]
        self._pool = [t for t in self._pool if t.id not in closing]

    def _subtree(self, task_id: TaskId) -> set[TaskId]:
        found = {task_id}
        while True:
            grown = found | {
                t.id
                for t in [*self._tasks, *self._inbox, *self._pool]
                if t.parent_id is not None and TaskId(t.parent_id) in found
            }
            if grown == found:
                return found
            found = grown

    async def uncomplete(self, task_id: TaskId) -> None:
        # item_uncomplete restores only the named task, never its descendants
        self.uncompleted.append(task_id)
        restored = self._removed.pop(task_id, None)
        if restored is not None:
            self._tasks = [*self._tasks, restored]
        pooled = self._removed_pool.pop(task_id, None)
        if pooled is not None:
            self._pool = [*self._pool, pooled]

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

    async def set_due(self, task_id: TaskId, due: Due | DueText | None) -> Due | None:
        self.dues.append((task_id, due))
        self.log.append("due")
        stored = _parsed(due) if isinstance(due, DueText) else due
        self._tasks = [
            replace(t, due=stored) if t.id == task_id else t for t in self._tasks
        ]
        return stored

    async def set_deadline(self, task_id: TaskId, deadline: Deadline | None) -> None:
        self.deadlines.append((task_id, deadline))
        self._tasks = [
            replace(t, deadline=deadline) if t.id == task_id else t for t in self._tasks
        ]

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        self.moves.append((task_id, project_id, section_id))
        # a project/section move also lifts the task out of any parent, as Todoist does
        self._tasks = [
            replace(t, project_id=project_id, section_id=section_id, parent_id=None)
            if t.id == task_id
            else t
            for t in self._tasks
        ]
        inbox_id = next((p.id for p in self._projects if p.is_inbox), None)
        if project_id != inbox_id:  # left the inbox: it no longer lists the task
            self._inbox = [t for t in self._inbox if t.id != task_id]

    async def set_parent(self, task_id: TaskId, parent_id: str) -> None:
        self.parents.append((task_id, parent_id))
        pool = [*self._tasks, *self._inbox, *self._pool]
        parent = next(t for t in pool if str(t.id) == parent_id)
        # as Todoist does it: the subtask inherits the parent's project + section
        nested = partial(
            replace,
            parent_id=parent_id,
            project_id=parent.project_id,
            section_id=parent.section_id,
        )
        self._tasks = [nested(t) if t.id == task_id else t for t in self._tasks]
        inbox_id = next((p.id for p in self._projects if p.is_inbox), None)
        if parent.project_id == inbox_id:
            self._inbox = [nested(t) if t.id == task_id else t for t in self._inbox]
        else:  # followed the parent out of the inbox, which no longer lists it
            self._inbox = [t for t in self._inbox if t.id != task_id]

    async def reorder(self, items: Sequence[tuple[TaskId, int]]) -> None:
        self.reorders.append(list(items))
        orders = dict(items)
        reordered = [
            replace(t, child_order=orders[t.id]) if t.id in orders else t
            for t in self._tasks
        ]
        self._tasks = reordered

    async def set_day_orders(self, items: Sequence[tuple[TaskId, int]]) -> None:
        self.day_orders.append(list(items))
        orders = dict(items)
        self._tasks = [
            replace(t, day_order=orders[t.id]) if t.id in orders else t
            for t in self._tasks
        ]

    async def reorder_sections(self, sections: Sequence[tuple[str, int]]) -> None:
        self.section_reorders.append(list(sections))
        orders = dict(sections)
        self._sections = [
            replace(s, order=orders[s.id]) if s.id in orders else s
            for s in self._sections
        ]

    async def reminders(self) -> list[Reminder]:
        return list(self._reminders)

    async def add_reminder(self, reminder: Reminder) -> None:
        self.added_reminders.append(reminder)
        self.log.append("reminder")
        stored = (
            reminder
            if reminder.id
            else replace(reminder, id=f"r{len(self._reminders) + 1}")
        )
        self._reminders = [*self._reminders, stored]

    async def delete_reminder(self, reminder_id: str) -> None:
        self.deleted_reminders.append(reminder_id)
        self._reminders = [r for r in self._reminders if r.id != reminder_id]

    async def apply_creation(self, plan: CreationPlan) -> None:
        self.applied.append(plan)
        # created tasks land where the server would put them: readable on the
        # next sync, under the temp id the plan named them by
        self._pool = [
            *self._pool,
            *(
                Task(
                    id=TaskId(task.temp_id),
                    content=task.content,
                    priority=task.priority,
                    # a typed phrase is Todoist's to parse; nothing here can
                    due=task.due if isinstance(task.due, Due) else None,
                    project_id=task.project_ref,
                    section_id=task.section_ref,
                    description=task.description,
                    parent_id=task.parent_ref,
                )
                for task in plan.tasks
            ),
        ]

    async def refresh(self) -> None:
        self.refresh_calls += 1


class FailingCommentsRepository(FakeRepository):
    async def comments(self, task_id: TaskId) -> list[Comment]:
        raise RuntimeError("offline")


class FailingActivityRepository(FakeRepository):
    async def activity(
        self, event_type: EventKind | None = None, cursor: str | None = None
    ) -> ActivityPage:
        raise RuntimeError("offline")


class FakeClock:
    def __init__(self, today: datetime.date) -> None:
        self._today = today

    def today(self) -> datetime.date:
        return self._today


_TODAY = datetime.date(2026, 7, 28)  # a Tuesday
_PARSED_DATE = datetime.date(2026, 8, 3)  # what the fake server makes of a typed due
_YESTERDAY = _TODAY - datetime.timedelta(days=1)
_TOMORROW = _TODAY + datetime.timedelta(days=1)


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
        assert not ({"e", "z", "t", "i", "p", "r", "v", "x", "asterisk"} & shown)


def _status(app: TodoistApp) -> str:
    return str(app.query_one("#status", Static).render())


async def open_view(pilot: Pilot[None], title: str) -> None:
    """Open a view by name through the Views screen — proof against its ordering."""
    await pilot.press("p")
    await pilot.pause()
    await pilot.press(*title)
    await pilot.press("enter")
    await pilot.pause()


@pytest.mark.anyio
async def test_the_context_name_leads_and_its_count_recedes() -> None:
    repo = FakeRepository([_row("A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)

        band = app.query_one(StatusBand)
        content = band.render()
        assert isinstance(content, Content)
        assert content.plain == "Today · 1 task(s)"
        tiers = span_tiers(band, content)
        assert any(tier is Tier.PRIMARY and "Today" in t for tier, t in tiers)
        assert (Tier.MUTED, " · 1 task(s)") in tiers


@pytest.mark.anyio
async def test_the_arrangement_summary_sits_at_the_right_edge() -> None:
    repo = FakeRepository([_row("A")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await settled(app)

        band = app.query_one(StatusBand)
        content = band.render()
        assert isinstance(content, Content)
        assert content.plain.endswith("Group: Project ↑")
        assert cell_len(content.plain) == band.content_size.width  # flush right
        tiers = span_tiers(band, content)
        assert (Tier.MUTED, "Group: Project ↑") in tiers  # and it recedes


@pytest.mark.anyio
async def test_a_narrow_band_drops_the_summary_rather_than_wrapping() -> None:
    repo = FakeRepository([_row("A")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())
    async with app.run_test(size=(24, 24)) as pilot:
        await pilot.pause()
        await settled(app)

        assert "Group" not in _status(app)
        assert "Today · 1 task(s)" in _status(app)


@pytest.mark.anyio
async def test_the_band_and_the_first_column_share_a_gutter() -> None:
    """So the view name and the task titles under it start on the same column."""
    repo = FakeRepository([_row("A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()

        band = app.query_one(StatusBand)
        table = app.query_one(TaskTable)
        assert band.styles.padding.left == table.cell_padding
        assert band.styles.background != app.screen.styles.background  # tinted


@pytest.mark.anyio
async def test_a_long_message_keeps_the_band_one_line() -> None:
    """The band is chrome; wrapping it would shove the table down a row. Error
    text is arbitrary, so it has to clip."""
    name = "a project with a name far too long to fit across a narrow terminal"
    repo = FakeRepository([_row("A", project_id="9")], [Project(id="9", name=name)])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test(size=(40, 24)) as pilot:
        await pilot.pause()
        await open_view(pilot, "narrow")
        await settled(app)

        assert _status(app).startswith(
            name[:10]
        )  # the long-named view is the one shown
        assert app.query_one(StatusBand).size.height == 1


@pytest.mark.anyio
async def test_a_bracketed_project_name_reaches_the_status_line_verbatim() -> None:
    """The band shows names the user typed; Rich would read "[b]" as markup and
    swallow it."""
    repo = FakeRepository(
        [_row("A", project_id="9")], [Project(id="9", name="[b]Work")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "work")
        await settled(app)

        assert "[b]Work" in _status(app)


def _selected_rows(table: DataTable[object]) -> list[int]:
    """Row indices showing the selection bar."""
    return [i for i in range(table.row_count) if selected(table, i)]


@pytest.mark.anyio
async def test_selecting_a_row_bars_it_and_accents_only_its_title() -> None:
    """A bar in the marker slot plus an accented title, so the metadata keeps
    receding and nothing shifts sideways."""
    repo = FakeRepository(
        [_row("A"), _row("B", "9")],  # two projects, so the column stays
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.pause()

        table = app.query_one(TaskTable)
        assert selected(table, 0) and not selected(table, 1)
        assert tier_at(table, title_cell(table, 0), "A") is Tier.ACCENT
        assert cell_tier(table, _cell(table, 0, "Project")) is Tier.MUTED
        assert tier_at(table, title_cell(table, 1), "B") is Tier.PRIMARY


@pytest.mark.anyio
async def test_the_marker_slot_keeps_its_width_when_nothing_is_selected() -> None:
    """The bar shares column 0 with the priority dot, so selecting can't push the
    title rightwards."""
    repo = FakeRepository([_row("A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)

        table = app.query_one(TaskTable)
        before = str(table.get_row_at(0)[0])
        await pilot.press("x")
        await pilot.pause()
        assert cell_len(str(table.get_row_at(0)[0])) == cell_len(before)


@pytest.mark.anyio
async def test_x_selects_the_cursor_task_and_advances() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
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
        await settled(app)
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
        await settled(app)
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
        await settled(app)
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
        await settled(app)
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
        await settled(app)
        await pilot.press("x")  # select A, cursor -> B
        await pilot.press("j")  # cursor -> C
        await pilot.press("x")  # select C
        await pilot.press("e")  # complete the selection {A, C}
        await settled(app)
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
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("e")  # complete {A, C}
        await settled(app)
        await pilot.press("z")  # undo the batch
        await settled(app)
        await pilot.pause()

        assert set(repo.uncompleted) == {TaskId("A"), TaskId("C")}
        table = app.query_one(DataTable[object])
        assert set(_content_col(table)) == {"A", "B", "C"}


@pytest.mark.anyio
async def test_completing_a_parent_takes_its_matching_subtask_with_it() -> None:
    # Todoist's item_close closes the whole subtree, so the subtask goes too —
    # even though it matched the view on its own
    repo = FakeRepository([_row("A"), _row("sub", parent_id="A"), _row("B")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("e")  # complete A, the cursor row
        await settled(app)
        await pilot.pause()

        assert repo.completed == [TaskId("A")]  # one command closes the subtree
        table = app.query_one(DataTable[object])
        assert [c.strip() for c in _content_col(table)] == ["B"]


@pytest.mark.anyio
async def test_undo_reopens_the_subtasks_that_closed_with_the_parent() -> None:
    # item_uncomplete restores ancestors, never descendants: each one is reopened
    subtree = [_row("sub", parent_id="A"), _row("deep", parent_id="sub")]
    repo = FakeRepository([_row("A"), _row("B")], [], pool=subtree)
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("e")  # complete A, carrying its pulled-in subtree
        await settled(app)
        await pilot.press("z")
        await settled(app)
        await pilot.pause()

        assert repo.uncompleted == [TaskId("A"), TaskId("sub"), TaskId("deep")]
        table = app.query_one(DataTable[object])
        # the fold marker is back, so A carries its restored subtree again
        assert [c.strip() for c in _content_col(table)] == ["▸ A", "B"]


@pytest.mark.anyio
async def test_selecting_a_subtask_alongside_its_parent_closes_it_once() -> None:
    repo = FakeRepository([_row("A"), _row("sub", parent_id="A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()  # pyright: ignore[reportUnknownMemberType]
        await settled(app)
        await pilot.press("l")  # reveal the subtask so it can be selected
        await pilot.press("x")  # select A, cursor -> sub
        await pilot.press("x")  # select sub as well
        await pilot.press("e")
        await settled(app)
        await pilot.press("z")
        await settled(app)
        await pilot.pause()

        assert repo.completed == [TaskId("A")]  # the parent's close covers the subtask
        assert repo.uncompleted == [TaskId("A"), TaskId("sub")]  # each reopened once


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
        await settled(app)
        await pilot.press("j")  # cursor -> B
        await pilot.press("e")  # a prior single completion sets an earlier undo (B)
        await settled(app)
        # now a batch where C fails but A succeeds
        await pilot.press("x")  # select the current task (C)
        await pilot.press("k")  # -> A
        await pilot.press("x")  # select A
        await pilot.press("e")  # batch complete {A, C}; C rejected
        await settled(app)
        await pilot.press("z")  # undo must reverse A (the success), not the prior B
        await settled(app)
        await pilot.pause()

        assert TaskId("A") in repo.uncompleted  # the confirmed close is undoable
        assert TaskId("B") not in repo.uncompleted  # the stale prior undo is gone


@pytest.mark.anyio
async def test_a_rejected_close_unhides_the_whole_subtree() -> None:
    repo = FailingOnCompleteRepository(
        [_row("A"), _row("sub", parent_id="A")], [], fail_id=TaskId("A")
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("e")  # rejected: nothing closed, so nothing stays hidden
        await settled(app)
        await pilot.press("l")  # expand A to see its subtask
        await pilot.pause()

        table = app.query_one(DataTable[object])
        assert [c.strip() for c in _content_col(table)] == ["▾ A", "sub"]


@pytest.mark.anyio
async def test_a_rejected_close_does_not_hold_up_the_rest_of_the_batch() -> None:
    repo = FailingOnCompleteRepository([_row("A"), _row("B")], [], fail_id=TaskId("A"))
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()  # pyright: ignore[reportUnknownMemberType]
        await settled(app)
        await pilot.press("x")  # select A, cursor -> B
        await pilot.press("x")  # select B
        await pilot.press("e")  # A is rejected; B is independent and still closes
        await settled(app)
        await pilot.pause()

        assert repo.completed == [TaskId("B")]
        table = app.query_one(DataTable[object])
        assert [c.strip() for c in _content_col(table)] == ["A"]  # only A comes back


@pytest.mark.anyio
async def test_deleting_a_selection_confirms_with_the_count() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("delete")

        assert isinstance(app.screen, ConfirmScreen)
        assert "2 tasks" in str(app.screen.query_one("#confirm", Static).render())
        await pilot.press("y")  # confirm
        await settled(app)
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
        await settled(app)
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
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("1")  # set P1 on the selection
        await settled(app)
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
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("t")  # one schedule screen for the selection
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow: 2026-07-29
        await settled(app)
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
        await settled(app)
        await pilot.press("R")  # open the reminders manager
        await pilot.pause()
        assert isinstance(app.screen, RemindersScreen)
        await pilot.press("a", "r", "3", "0", "enter")  # add relative, 30 min before
        await settled(app)
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
        await settled(app)
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("d")  # delete the highlighted reminder
        await settled(app)
        await pilot.pause()

        assert repo.deleted_reminders == ["r1"]


@pytest.mark.anyio
async def test_reminder_add_over_a_selection_hits_each_task() -> None:
    repo = FakeRepository([_timed("A"), _timed("B"), _timed("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("R")  # add-only flow for the selection
        await pilot.pause()
        await pilot.press("r", "h")  # relative, 1 hour before
        await settled(app)
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
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("x")  # select B (cursor advanced onto B)
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("r", "h")  # relative, 1 hour before
        await settled(app)
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
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("x")  # select B
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("r", "h")  # relative, 1 hour before
        await settled(app)
        await pilot.pause()

        assert repo.added_reminders == []
        assert "due time" in _status(app)


@pytest.mark.anyio
async def test_reminder_add_absolute_picks_a_date() -> None:
    repo = FakeRepository([_row("A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("a", "a")  # add -> absolute -> opens the date picker
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow: 2026-07-29
        await settled(app)
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
        await settled(app)

        table = app.query_one(DataTable[object])
        assert "Rem" not in [str(c.label) for c in table.ordered_columns]
        assert "•" in str(_cell(table, 0, "Due"))


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
        await settled(app)

        table = app.query_one(DataTable[object])
        assert "•2" in str(_cell(table, 0, "Due"))


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
        await settled(app)

        table = app.query_one(DataTable[object])
        assert str(_cell(table, 0, "Due")) == "•"


@pytest.mark.anyio
async def test_setting_deadline_applies_to_the_whole_selection() -> None:
    repo = FakeRepository([_row("A"), _row("B"), _row("C")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("d")  # one deadline screen for the selection
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow
        await settled(app)
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
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("x")  # select B (cursor already on B)
        await pilot.press("v")  # one project picker for the selection
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await settled(app)
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
        await settled(app)
        await pilot.press("Y")  # open the duplicate picker
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)
        await pilot.press("enter")  # highlight + choose "Work"
        await pilot.pause()
        assert isinstance(app.screen, TextPromptScreen)
        await pilot.press("enter")  # accept the "Work (copy)" default
        await settled(app)
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
        await settled(app)
        await pilot.press("Y")
        await pilot.pause()
        await pilot.press("down")  # Work -> Work / Planning
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, TextPromptScreen)
        await pilot.press("enter")  # accept "Planning (copy)"
        await settled(app)
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
        await settled(app)
        await pilot.press("D")  # open the section picker
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)
        await pilot.press("enter")  # only "Work / Planning" is listed
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await settled(app)
        await pilot.pause()

        assert repo.deleted_sections == ["s1"]


@pytest.mark.anyio
async def test_delete_section_cancelled_at_the_confirmation_deletes_nothing() -> None:
    repo = _section_repo()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
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
        await settled(app)
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
        await settled(app)
        await pilot.press("D")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("y")
        await settled(app)
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
        await settled(app)
        await pilot.press("x")  # select A
        await pilot.press("j")
        await pilot.press("x")  # select C
        await pilot.press("at")  # one label editor for the selection
        await pilot.pause()
        assert isinstance(app.screen, LabelsScreen)
        await pilot.press("down")  # highlight "urgent" (sorted: home, urgent, work)
        await pilot.press("space")  # add it
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

        added = {task_id: labels for task_id, labels, _ in repo.label_edits}
        assert added == {  # existing labels kept, "urgent" unioned in
            TaskId("A"): ("home", "urgent"),
            TaskId("C"): ("work", "urgent"),
        }
        assert "selected" not in _status(app)


class FailingFiltersRepository(FakeRepository):
    async def filters(self) -> list[Filter]:
        raise RuntimeError("offline")


@pytest.mark.anyio
async def test_selecting_a_filter_from_views_revalidates_in_background() -> None:
    repo = FakeRepository(
        [], [], filters=[Filter(id="f1", name="My Filter", query="p1", order=1)]
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await open_view(pilot, "filter")
        await settled(app)
        await pilot.pause()
        assert "p1" in repo.refresh_filtered_queries
        assert "⟳" not in _status(app)  # sync indicator cleared after revalidation


@pytest.mark.anyio
async def test_leaving_filter_view_stops_background_filter_refresh() -> None:
    repo = FakeRepository(
        [], [], filters=[Filter(id="f1", name="My Filter", query="p1", order=1)]
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await open_view(pilot, "filter")
        await settled(app)
        await open_view(pilot, "today")  # back to Today clears the active filter
        await pilot.pause()
        repo.refresh_filtered_queries.clear()

        await pilot.press("r")  # force a sync
        await settled(app)
        await pilot.pause()
        assert repo.refresh_filtered_queries == []


@pytest.mark.anyio
async def test_p_while_the_views_screen_is_open_does_not_stack_screens() -> None:
    repo = FakeRepository([], [Project(id="9", name="Work")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("p")  # second press must not stack a second screen
        await pilot.pause()
        assert len([s for s in app.screen_stack if isinstance(s, ViewsScreen)]) == 1


@pytest.mark.anyio
async def test_the_views_screen_opens_on_the_view_being_shown() -> None:
    repo = FakeRepository([], [Project(id="9", name="Work")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await open_view(pilot, "work")
        await settled(app)

        await pilot.press("p")
        await pilot.pause()
        options = app.screen.query_one(OptionList)
        index = options.highlighted
        assert index is not None
        assert "Work" in str(options.get_option_at_index(index).prompt)


@pytest.mark.anyio
async def test_cancelling_the_views_screen_keeps_the_current_view() -> None:
    repo = FakeRepository([], [Project(id="9", name="Work")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, ViewsScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ViewsScreen)
        assert "Today" in _status(app)  # unchanged from the startup view


@pytest.mark.anyio
async def test_pressing_r_forces_resync() -> None:
    repo = FakeRepository([], [])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        before = repo.refresh_calls  # 1 from the startup sync
        await pilot.press("r")
        await settled(app)
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
        table = app.query_one(TaskTable)
        assert table.row_count == 1
        assert priority_of(table, 0) is Priority.P1
        assert _title(table, 0) == "Buy milk"  # title leads, right after the dot
        assert str(_cell(table, 0, "Due")) == "21 Jul 09:30"  # overdue vs _TODAY
        # every task in one project: the band carries it, not a column of repeats
        assert _status(app).startswith("Today · 1 task(s) · Errands")


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
        assert labels == ["TASK", "DUE"]  # Deadline + Project omitted


@pytest.mark.anyio
async def test_column_headers_recede_behind_their_data() -> None:
    """Headers name the columns; uppercased and unemphasised they stop competing
    with the tasks underneath."""
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 7, 30)),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], []), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert [str(c.label) for c in table.ordered_columns] == ["TASK", "DUE"]
        assert not table.show_header  # ColumnHeader draws them, so a rule can follow
        labels = app.query_one(ColumnHeader)
        content = labels.render()
        assert isinstance(content, Content)
        assert content.plain.split() == ["TASK", "DUE"]
        assert span_tiers(labels, content) == [(Tier.MUTED, content.plain)]


def _row_backgrounds(app: TodoistApp, row: int) -> set[ColorTriplet | None]:
    """The composited background behind every cell of a painted table row."""
    table = app.query_one(TaskTable)
    region = table.scrollable_content_region
    # else we would be sampling whatever sits below the table and calling it a row
    assert row < min(table.row_count, region.height)
    y = region.y + row
    return {
        bgcolor.triplet if (bgcolor := app.screen.get_style_at(x, y).bgcolor) else None
        for x in range(region.x, region.x + region.width)
    }


@pytest.mark.anyio
async def test_the_cursor_highlights_the_whole_line() -> None:
    """A styled cell must not paint its own background: the resolved tier styles
    carry one, and it punches holes in the highlight where the text sits."""
    tasks = [
        Task(
            id=TaskId(name),
            content=name,
            priority=Priority.P1,
            due=Due(date=_TODAY),
            project_id="220",
            labels=("home",),
        )
        for name in ("first", "second")
    ]
    app = TodoistApp(
        FakeRepository(tasks, [Project(id="220", name="Errands")]),
        clock=FakeClock(_TODAY),
    )

    async with app.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        await settled(app)

        cursor, plain = _row_backgrounds(app, 0), _row_backgrounds(app, 1)
        assert len(cursor) == 1  # one unbroken tint, edge to edge
        assert len(plain) == 1  # and the rows below stay flat
        assert cursor != plain  # but the cursor row is distinguishable


@pytest.mark.anyio
async def test_the_cursor_row_is_tinted_and_keeps_the_ramp() -> None:
    """A slab cursor would repaint every cell one colour and flatten the
    hierarchy on the very row being read."""
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 7, 30)),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], []), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        cursor = table.get_component_styles("datatable--cursor")
        assert cursor.background != table.styles.background  # tinted
        assert table.cursor_foreground_priority == "renderable"  # cells keep their tier


@pytest.mark.anyio
async def test_labels_render_in_their_own_receding_column() -> None:
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
        assert columns == ["TASK", "LABELS"]  # Labels sits right after the title
        cell = _cell(table, 0, "Labels")
        assert cell_tier(table, cell) is Tier.MUTED  # recedes behind the title
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
        assert "LABELS" not in columns


@pytest.mark.anyio
async def test_the_due_column_grades_urgency() -> None:
    """A clock time today pulls the eye; overdue sounds the alarm; a later date
    recedes with the rest of the metadata."""
    now = Task(
        id=TaskId("now"),
        content="now",
        priority=Priority.P4,
        due=Due(date=_TODAY, time=datetime.time(15, 0)),
        project_id="220",
    )
    late = replace(now, id=TaskId("late"), content="late", due=Due(date=_YESTERDAY))
    later = replace(now, id=TaskId("later"), content="later", due=Due(date=_TOMORROW))
    app = TodoistApp(FakeRepository([now, late, later], []), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        by_title = {_title(table, i): i for i in range(table.row_count)}
        assert cell_tier(table, _cell(table, by_title["now"], "Due")) is Tier.ACCENT
        assert cell_tier(table, _cell(table, by_title["late"], "Due")) is Tier.OVERDUE
        assert cell_tier(table, _cell(table, by_title["later"], "Due")) is Tier.MUTED


@pytest.mark.anyio
async def test_the_recurrence_mark_and_reminder_bell_recede_behind_the_due() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Stretching",
        priority=Priority.P4,
        due=Due(
            date=_TODAY,
            time=datetime.time(14, 0),
            is_recurring=True,
            string="every day 14:00",
        ),
        project_id="220",
    )
    reminder = Reminder(id="r1", item_id="6X4", type="relative", minute_offset=0)
    app = TodoistApp(
        FakeRepository([task], [], reminders=[reminder]), clock=FakeClock(_TODAY)
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        cell = _cell(table, 0, "Due")
        assert isinstance(cell, Text)
        assert cell_tier(table, cell) is Tier.ACCENT  # the due itself still leads
        assert span_tiers(table, cell) == [(Tier.MUTED, " ↻"), (Tier.MUTED, " •")]


@pytest.mark.anyio
async def test_the_deadline_column_grades_urgency() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P4,
        due=None,
        deadline=Deadline(date=_YESTERDAY),
        project_id="220",
    )
    app = TodoistApp(FakeRepository([task], []), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert cell_tier(table, _cell(table, 0, "Deadline")) is Tier.OVERDUE


@pytest.mark.anyio
async def test_the_title_leads_and_its_metadata_recedes() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 7, 30)),
        project_id="220",
        labels=("errand",),
    )
    app = TodoistApp(
        FakeRepository([task], [Project(id="220", name="Errands")]),
        clock=FakeClock(_TODAY),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert tier_at(table, title_cell(table, 0), "Buy milk") is Tier.PRIMARY
        assert cell_tier(table, _cell(table, 0, "Labels")) is Tier.MUTED


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
        assert _title(app.query_one(TaskTable), 0) == "Check calendar today"


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
        assert priority_of(app.query_one(TaskTable), 0) is None


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
        await settled(app)
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 1
        reloads = repo.today_calls
        syncs = repo.refresh_calls
        await pilot.press("e")
        # optimistic: row is gone before the network command resolves
        assert app.query_one(DataTable[object]).row_count == 0
        await settled(app)
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
        await settled(app)
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
        await settled(app)
        await pilot.pause()
        await pilot.press("delete")
        await pilot.press("y")  # confirm
        # optimistic: row is gone before the network command resolves
        assert app.query_one(DataTable[object]).row_count == 0
        await settled(app)
        await pilot.pause()

        assert repo.deleted == [TaskId("6X4")]
        assert app.query_one(DataTable[object]).row_count == 0


class TodayFilteringRepository(FakeRepository):
    """today() evaluates the due date, the way the real snapshot repository does,
    so a task rescheduled away actually leaves the view on the next load."""

    async def today(self) -> list[Task]:
        self.today_calls += 1
        return [t for t in self._tasks if t.due is not None and t.due.date == _TODAY]


class PaintRecordingApp(TodoistApp):
    """Records the ids on screen at every paint, so a one-frame flash shows up."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        self.paints: list[list[str]] = []

    def _render(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, render_rows: list[RenderRow[TaskRow]], view: View
    ) -> None:
        super()._render(render_rows, view)
        self.paints.append(
            [str(item.row.id) for item in render_rows if isinstance(item, TaskLine)]
        )


@pytest.mark.anyio
async def test_rescheduling_out_of_today_never_flashes_the_row_back() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=_TODAY),
        project_id="220",
    )
    repo = TodayFilteringRepository([task], [Project(id="220", name="Errands")])
    app = PaintRecordingApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")  # tomorrow: it leaves Today
        await settled(app)
        await pilot.pause()

        assert repo.dues == [(TaskId("6X4"), Due(date=_TOMORROW))]
        assert app.query_one(DataTable[object]).row_count == 0
        left = next(i for i, ids in enumerate(app.paints) if "6X4" not in ids)
        # once it has gone it must stay gone: no repaint may put it back
        assert all("6X4" not in ids for ids in app.paints[left:]), app.paints


@pytest.mark.anyio
async def test_completing_never_flashes_the_row_back() -> None:
    repo = TodayFilteringRepository(
        [_due_today("A"), _due_today("B")], [Project(id="220", name="Errands")]
    )
    app = PaintRecordingApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("e")
        await settled(app)
        await pilot.pause()

        assert repo.completed == [TaskId("A")]
        left = next(i for i, ids in enumerate(app.paints) if "A" not in ids)
        assert all("A" not in ids for ids in app.paints[left:]), app.paints


@pytest.mark.anyio
async def test_a_resync_paints_once_when_it_retires_a_change() -> None:
    repo = TodayFilteringRepository(
        [_due_today("A")], [Project(id="220", name="Errands")]
    )
    app = PaintRecordingApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        painted = len(app.paints)
        await pilot.press("1")
        await settled(app)  # the drain's resync reloads and retires the change
        await pilot.pause()

        # one paint for the keypress, one for the resync — not one more to retire
        assert len(app.paints) == painted + 2


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
        await settled(app)
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
        await settled(app)
        before = repo.refresh_calls  # 1 from the startup sync
        await pilot.pause(0.2)  # let a few poll ticks fire
        await settled(app)
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
        await settled(app)
        await pilot.pause()
        assert priority_of(app.query_one(TaskTable), 0) is None  # P4: no dot
        syncs = repo.refresh_calls

        await pilot.press("1")
        # optimistic: the dot repaints before the network command resolves
        assert priority_of(app.query_one(TaskTable), 0) is Priority.P1
        await settled(app)
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
        await settled(app)
        assert priority_of(app.query_one(TaskTable), 0) is Priority.P1

        await pilot.press("4")
        assert priority_of(app.query_one(TaskTable), 0) is None  # P4: no dot
        await settled(app)
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
        await settled(app)
        table = app.query_one(TaskTable)
        await pilot.press("L")  # unfold, so the task itself is on screen
        await pilot.pause()
        assert "P4" in _content_col(table)[0]  # starts under the P4 header
        await pilot.press("j")  # move cursor onto the task
        repo.release.clear()  # block the post-change sync

        await pilot.press("1")
        # optimistic, before the network resolves: it jumped to a fresh P1 group
        col2 = _content_col(table)
        assert "P1" in col2[0]
        # ⟳ trails it: the jump is local, the server hasn't confirmed the change
        assert col2[1].strip() == "Buy milk ⟳"
        assert not any("P4" in c for c in col2)
        assert _title(table, table.cursor_row).strip() == "Buy milk ⟳"  # <-

        repo.release.set()
        await settled(app)
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
        await settled(app)
        await pilot.pause()

        assert "Failed to set priority: boom" in str(
            app.query_one("#status", Static).render()
        )
        # failed command resyncs to server truth: the dot reverts to P4 (blank)
        assert priority_of(app.query_one(TaskTable), 0) is None


class HeldEditRepository(FakeRepository):
    """The edit is accepted but held in flight, so a sync can begin — and land —
    before the server has acknowledged it.

    Todoist is read-your-writes: a snapshot fetched *after* an ack always carries
    the change. So this interleaving, not a lagging snapshot, is the one that can
    revert an optimistic edit.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        self.hold = asyncio.Event()

    async def set_priority(self, task_id: TaskId, priority: Priority) -> None:
        await self.hold.wait()
        await super().set_priority(task_id, priority)

    async def set_due(self, task_id: TaskId, due: Due | DueText | None) -> None:
        await self.hold.wait()
        await super().set_due(task_id, due)

    async def set_deadline(self, task_id: TaskId, deadline: Deadline | None) -> None:
        await self.hold.wait()
        await super().set_deadline(task_id, deadline)

    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        await self.hold.wait()
        await super().set_project(task_id, project_id, section_id)


async def _settle(pilot: Pilot[None], turns: int = 12) -> None:
    """Run the scheduled workers out. Nothing behind the fakes does real I/O, so
    a fixed number of turns drains them deterministically — unlike
    `wait_for_complete`, this does not block on a command still being held."""
    for _ in range(turns):
        await pilot.pause()


@pytest.mark.anyio
async def test_priority_survives_a_sync_that_began_before_the_command_landed() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = HeldEditRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        await pilot.press("1")
        assert priority_of(app.query_one(TaskTable), 0) is Priority.P1

        await pilot.press("r")  # a whole sync lands while the command is in flight
        await _settle(pilot)
        assert priority_of(app.query_one(TaskTable), 0) is Priority.P1

        repo.hold.set()
        await settled(app)
        await pilot.pause()
        assert repo.priorities == [(TaskId("6X4"), Priority.P1)]
        assert priority_of(app.query_one(TaskTable), 0) is Priority.P1


@pytest.mark.anyio
async def test_rapid_priority_sets_settle_on_the_last_value() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
    )
    repo = HeldEditRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        await pilot.press("1")
        await pilot.press("2")  # second set before the first's command resolves
        assert priority_of(app.query_one(TaskTable), 0) is Priority.P2

        repo.hold.set()
        await settled(app)
        await pilot.pause()

        assert repo.priorities == [  # in the order they were pressed, never swapped
            (TaskId("6X4"), Priority.P1),
            (TaskId("6X4"), Priority.P2),
        ]
        assert priority_of(app.query_one(TaskTable), 0) is Priority.P2


@pytest.mark.anyio
async def test_due_survives_a_sync_that_began_before_the_command_landed() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="9",
    )
    repo = HeldEditRepository([task], [Project(id="9", name="Work")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        # the Work project view: a due change cannot evict a row from it
        await open_view(pilot, "work")
        await settled(app)
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")  # tomorrow

        await pilot.press("r")  # a sync lands while the command is in flight
        await _settle(pilot)
        assert str(_cell(app.query_one(DataTable[object]), 0, "Due")) == "Tomorrow"

        repo.hold.set()
        await settled(app)
        await pilot.pause()
        assert repo.dues == [(TaskId("6X4"), Due(date=datetime.date(2026, 7, 29)))]


@pytest.mark.anyio
async def test_deadline_survives_a_sync_that_began_before_the_command_landed() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Ship it",
        priority=Priority.P2,
        due=Due(date=_TODAY),  # stays in Today regardless of the deadline
        project_id="220",
    )
    repo = HeldEditRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("m")  # tomorrow

        await pilot.press("r")
        await _settle(pilot)
        assert str(_cell(app.query_one(DataTable[object]), 0, "Deadline")) == "Tomorrow"

        repo.hold.set()
        await settled(app)
        await pilot.pause()
        assert repo.deadlines == [(TaskId("6X4"), Deadline(date=_TOMORROW))]


@pytest.mark.anyio
async def test_move_survives_a_sync_that_began_before_the_command_landed() -> None:
    repo = HeldEditRepository(
        [_row("t1", "220"), _unmoved()],
        _MOVE_PROJECTS,
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")

        await pilot.press("r")
        await _settle(pilot)
        assert str(_cell(app.query_one(DataTable[object]), 0, "Project")) == "Work"

        repo.hold.set()
        await settled(app)
        await pilot.pause()
        assert repo.moves == [(TaskId("t1"), "9", None)]
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
        await settled(app)
        await pilot.press("e")
        await settled(app)
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 0

        await pilot.press("z")
        # optimistic: the row is back before the reopen command resolves
        assert app.query_one(DataTable[object]).row_count == 1
        await settled(app)
        await pilot.pause()

        assert repo.uncompleted == [TaskId("6X4")]
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert _title(table, 0) == "Buy milk"
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
        await settled(app)
        await pilot.press("e")
        await settled(app)
        await pilot.press("z")
        await settled(app)
        await pilot.press("z")  # nothing left to undo
        await settled(app)
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
        await settled(app)
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
        await settled(app)
        await pilot.pause()

        assert "Failed to delete task: boom" in str(
            app.query_one("#status", Static).render()
        )
        assert app.query_one(DataTable[object]).row_count == 1  # unhidden


class HeldCloseRepository(FakeRepository):
    """complete() is accepted but held in flight, so a sync can begin — and land —
    before the server has acknowledged the close."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        self.hold = asyncio.Event()

    async def complete(self, task_id: TaskId) -> None:
        await self.hold.wait()
        await super().complete(task_id)


@pytest.mark.anyio
async def test_a_completed_task_stays_gone_while_its_close_is_in_flight() -> None:
    repo = HeldCloseRepository([_row("Buy milk")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("e")
        assert app.query_one(DataTable[object]).row_count == 0

        await pilot.press("r")  # a sync that still lists the task lands
        await _settle(pilot)
        assert app.query_one(DataTable[object]).row_count == 0  # must not flash back

        repo.hold.set()
        await settled(app)
        await pilot.pause()
        assert repo.completed == [TaskId("Buy milk")]
        assert app.query_one(DataTable[object]).row_count == 0


class HeldUncompleteRepository(FakeRepository):
    """The reopen is held in flight, so what undo puts back stands on its own."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        self.hold = asyncio.Event()

    async def uncomplete(self, task_id: TaskId) -> None:
        await self.hold.wait()
        await super().uncomplete(task_id)


@pytest.mark.anyio
async def test_undo_puts_back_a_row_the_views_own_rule_would_turn_away() -> None:
    """Todoist's "today" is wider than the rule reproducible here — it hands back
    everything overdue — so a row undo restores is the server's to place, not the
    rule's, even while the reopen is in flight."""
    repo = HeldUncompleteRepository([_row("A")], [])  # due 21 Jul: overdue, not today
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("e")  # complete A
        await settled(app)
        await pilot.press("z")  # undo, the reopen still in flight
        await _settle(pilot)

        assert _content_col(app.query_one(TaskTable)) == ["A" + PENDING_MARK]

        repo.hold.set()
        await settled(app)


@pytest.mark.anyio
async def test_rapid_completes_do_not_reappear() -> None:
    repo = HeldCloseRepository(
        [_row("First"), _row("Second")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        assert app.query_one(DataTable[object]).row_count == 2
        await pilot.press("e")
        await pilot.press("e")  # second close before the first's command resolves
        assert app.query_one(DataTable[object]).row_count == 0

        await pilot.press("r")  # a sync that still lists both lands
        await _settle(pilot)
        assert app.query_one(DataTable[object]).row_count == 0  # neither reappears

        repo.hold.set()
        await settled(app)
        await pilot.pause()
        assert repo.completed == [TaskId("First"), TaskId("Second")]  # in press order
        assert app.query_one(DataTable[object]).row_count == 0


@pytest.mark.anyio
async def test_undo_restores_a_completed_task_the_server_has_already_dropped() -> None:
    repo = FakeRepository([_row("Buy milk")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("e")
        await settled(app)
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 0

        await pilot.press("z")  # the row comes back from the undo, not from a sync
        assert app.query_one(DataTable[object]).row_count == 1
        await settled(app)
        await pilot.pause()

        assert repo.uncompleted == [TaskId("Buy milk")]
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert _title(table, 0) == "Buy milk"


@pytest.mark.anyio
async def test_undo_walks_back_one_action_at_a_time() -> None:
    repo = FakeRepository(
        [_row("First"), _row("Second")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("e")  # close First
        await settled(app)
        await pilot.press("e")  # close Second
        await settled(app)
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 0

        await pilot.press("z")  # most recent first
        await settled(app)
        await pilot.pause()
        assert repo.uncompleted == [TaskId("Second")]

        await pilot.press("z")  # and then the one before it
        await settled(app)
        await pilot.pause()
        assert repo.uncompleted == [TaskId("Second"), TaskId("First")]
        assert app.query_one(DataTable[object]).row_count == 2

        await pilot.press("z")  # nothing left to walk back
        await settled(app)
        await pilot.pause()
        assert repo.uncompleted == [TaskId("Second"), TaskId("First")]


@pytest.mark.anyio
async def test_undo_reverses_a_reschedule() -> None:
    task = Task(
        id=TaskId("6X4"),
        content="Buy milk",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="9",
    )
    repo = FakeRepository([task], [Project(id="9", name="Work")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "work")
        await settled(app)
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")  # tomorrow
        await settled(app)
        await pilot.pause()

        await pilot.press("z")
        await settled(app)
        await pilot.pause()

        assert repo.dues == [
            (TaskId("6X4"), Due(date=datetime.date(2026, 7, 29))),
            (TaskId("6X4"), Due(date=datetime.date(2026, 7, 21))),  # put back
        ]


@pytest.mark.anyio
async def test_undo_reverses_a_priority_change_per_task() -> None:
    first = Task(
        id=TaskId("a"),
        content="a",
        priority=Priority.P4,
        due=Due(date=_TODAY),
        project_id="220",
    )
    second = Task(
        id=TaskId("b"),
        content="b",
        priority=Priority.P2,
        due=Due(date=_TODAY),
        project_id="220",
    )
    repo = FakeRepository([first, second], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("x")  # select a, cursor -> b
        await pilot.press("x")  # select b
        await pilot.press("1")  # both to P1
        await settled(app)
        await pilot.pause()

        await pilot.press("z")
        await settled(app)
        await pilot.pause()

        # each task goes back to the priority it had, not to a shared one
        assert repo.priorities[-2:] == [
            (TaskId("b"), Priority.P2),
            (TaskId("a"), Priority.P4),
        ]


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
        await open_view(pilot, "work")
        await settled(app)
        await pilot.pause()
        assert app.query_one(DataTable[object]).row_count == 1

        await pilot.press("e")
        await settled(app)
        await pilot.pause()

        # its next occurrence has a new due: it must come back, not stay hidden
        table = app.query_one(DataTable[object])
        assert table.row_count == 1
        assert _title(table, 0) == "Water plants"


@pytest.mark.anyio
async def test_completing_moves_cursor_to_the_task_below() -> None:
    repo = FakeRepository(
        [_row("A"), _row("B"), _row("C")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("j")  # cursor: A -> B
        await pilot.press("e")  # complete B
        await settled(app)
        await pilot.pause()

        table = app.query_one(DataTable[object])
        assert table.row_count == 2
        assert _title(table, table.cursor_row) == "C"  # not back up to A


@pytest.mark.anyio
async def test_completing_the_last_task_moves_cursor_up() -> None:
    repo = FakeRepository(
        [_row("A"), _row("B"), _row("C")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("j")
        await pilot.press("j")  # cursor: A -> B -> C (last)
        await pilot.press("e")  # complete C
        await settled(app)
        await pilot.pause()

        table = app.query_one(DataTable[object])
        assert table.row_count == 2
        assert _title(table, table.cursor_row) == "B"  # up to the one above


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
        await settled(app)
        await pilot.press("e")
        await settled(app)
        await pilot.press("z")
        await settled(app)
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
        await settled(app)
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
        await settled(app)
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
        await settled(app)
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow (quick key)
        await settled(app)
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
        await settled(app)
        assert str(_cell(app.query_one(DataTable[object]), 0, "Deadline")) == "Tomorrow"
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("x")  # clear
        await settled(app)
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
        await settled(app)
        await pilot.pause()
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")  # tomorrow: it no longer belongs in Today
        # optimistic: the row leaves Today before the network command resolves
        assert app.query_one(DataTable[object]).row_count == 0

        repo.release.set()
        await settled(app)
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
        await settled(app)

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
        await settled(app)
        assert str(_cell(app.query_one(DataTable[object]), 0, "Due")) == "Today"
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("x")  # clear: an undated task no longer belongs in Today
        assert app.query_one(DataTable[object]).row_count == 0

        repo.release.set()
        await settled(app)
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
        await settled(app)
        await pilot.pause()
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("l")  # calendar: move cursor to tomorrow
        await pilot.press("enter")  # pick it: task leaves Today
        # optimistic: the row is gone before the network command resolves
        assert app.query_one(DataTable[object]).row_count == 0

        repo.release.set()
        await settled(app)
        assert repo.dues == [(TaskId("6X4"), Due(date=datetime.date(2026, 7, 29)))]


@pytest.mark.anyio
async def test_reschedule_on_filter_view_keeps_the_task_until_the_server_answers() -> (
    None
):
    task = Task(
        id=TaskId("6X4"),
        content="Overdue thing",
        priority=Priority.P2,
        due=Due(date=_TODAY),
        project_id="220",
    )
    # a filter's membership can only be evaluated by the server, so the edited row
    # holds its place — marked unconfirmed — until the refresh answers. Dropping it
    # on spec would make it blink out and straight back in whenever it still fits.
    repo = GatedRefreshRepository(
        [task],
        [Project(id="220", name="Errands")],
        filters=[Filter(id="f1", name="Overdue", query="overdue", order=1)],
    )
    repo.release.set()  # let the startup sync through
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await open_view(pilot, "overdue")
        await settled(app)
        assert app.query_one(DataTable[object]).row_count == 1
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")  # reschedule: the row stays, pending the answer
        table = app.query_one(TaskTable)
        assert table.row_count == 1
        assert _title(table, 0).strip() == "Overdue thing ⟳"

        repo.release.set()
        await settled(app)
        await pilot.pause()
        assert repo.dues == [(TaskId("6X4"), Due(date=datetime.date(2026, 7, 29)))]
        # the refresh answered and confirmed it: the mark clears
        assert _title(app.query_one(TaskTable), 0).strip() == "Overdue thing"


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
        await settled(app)
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
        await settled(app)
        await pilot.pause()

        assert repo.dues[-1] == (
            TaskId("6X4"),
            # next occurrence moved, rule kept
            Due(date=datetime.date(2026, 7, 29), is_recurring=True, string="every day"),
        )


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
    async def set_due(self, task_id: TaskId, due: Due | DueText | None) -> None:
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
        await settled(app)
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
    repo = FakeRepository([_row("t1", "220"), _unmoved()], _MOVE_PROJECTS)
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await settled(app)
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
        await settled(app)
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
        await settled(app)
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


@pytest.mark.anyio
async def test_shift_v_opens_parent_picker() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        assert isinstance(app.screen, ParentPickerScreen)


@pytest.mark.anyio
async def test_shift_v_pick_nests_the_task_under_the_parent() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("p", "a", "r")  # narrow to "parent"
        await pilot.press("down")  # past the top-level entry
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

        assert repo.parents == [(TaskId("kid"), "parent")]
        table = app.query_one(TaskTable)
        # the parent expanded to show its new child, indented beneath it
        assert _content_col(table) == ["▾ parent", "  kid"]


@pytest.mark.anyio
async def test_shift_v_moves_every_selected_task() -> None:
    repo = FakeRepository(
        [_row("kid1"), _row("kid2"), _row("parent")],
        [Project(id="220", name="Errands")],
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("x", "x")  # mark t1 and t2
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("p", "a", "r")
        await pilot.press("down")
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

        assert repo.parents == [(TaskId("kid1"), "parent"), (TaskId("kid2"), "parent")]


@pytest.mark.anyio
async def test_shift_v_top_level_entry_un_parents_a_subtask() -> None:
    repo = FakeRepository(
        [_row("parent"), _row("kid", parent_id="parent")],
        [Project(id="220", name="Errands")],
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # expand the parent
        await pilot.pause()
        await pilot.press("j")  # cursor onto the subtask
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("enter")  # the top-level entry heads the list
        await settled(app)
        await pilot.pause()

        assert repo.moves == [(TaskId("kid"), "220", None)]
        assert _content_col(app.query_one(TaskTable)) == ["kid", "parent"]


@pytest.mark.anyio
async def test_the_parent_picker_offers_neither_the_task_nor_its_subtasks() -> None:
    repo = FakeRepository(
        [_row("boss"), _row("its kid", parent_id="boss"), _row("other")],
        [Project(id="220", name="Errands")],
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()  # cursor rests on "boss", the first row
        await pilot.press("V")
        await pilot.pause()
        options = app.screen.query_one(OptionList)
        labels = [
            str(options.get_option_at_index(i).prompt)
            for i in range(options.option_count)
        ]
        names = [label.split(" ", 1)[1] for label in labels]  # drop the pick number
        # a task cannot nest under itself or under its own subtask
        assert [name for name in names if name.startswith(("boss", "its kid"))] == []
        assert any(name.startswith("other") for name in names)


@pytest.mark.anyio
async def test_undo_returns_a_re_parented_task_to_the_top_level() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("p", "a", "r")
        await pilot.press("down")
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()
        await pilot.press("z")
        await settled(app)
        await pilot.pause()

        assert repo.moves == [(TaskId("kid"), "220", None)]
        assert _content_col(app.query_one(TaskTable)) == ["kid", "parent"]


@pytest.mark.anyio
async def test_undo_returns_an_un_parented_task_under_its_old_parent() -> None:
    repo = FakeRepository(
        [_row("parent"), _row("kid", parent_id="parent")],
        [Project(id="220", name="Errands")],
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("enter")  # top level
        await settled(app)
        await pilot.pause()
        await pilot.press("z")
        await settled(app)
        await pilot.pause()

        assert repo.parents == [(TaskId("kid"), "parent")]
        assert _content_col(app.query_one(TaskTable)) == ["▾ parent", "  kid"]


@pytest.mark.anyio
async def test_shift_v_on_a_group_header_does_nothing() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        table.move_cursor(row=0)  # cursor never rests here; force it for the guard
        await pilot.press("V")
        await pilot.pause()
        assert not isinstance(app.screen, ParentPickerScreen)


@pytest.mark.anyio
async def test_shift_v_while_picker_open_does_not_stack_screens() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("V")  # second press must not stack a second picker
        await pilot.pause()
        pickers = [s for s in app.screen_stack if isinstance(s, ParentPickerScreen)]
        assert len(pickers) == 1


@pytest.mark.anyio
async def test_cancelling_the_parent_picker_leaves_the_task_unchanged() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ParentPickerScreen)
        assert repo.parents == []


@pytest.mark.anyio
async def test_shift_v_in_the_detail_card_opens_the_parent_picker() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, TaskDetailScreen)
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("p", "a", "r")
        await pilot.press("down")
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

        assert repo.parents == [(TaskId("kid"), "parent")]


class FailingParentRepository(FakeRepository):
    async def set_parent(self, task_id: TaskId, parent_id: str) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_re_parent_failure_is_surfaced_and_the_row_snaps_back() -> None:
    repo = FailingParentRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("p", "a", "r")
        await pilot.press("down")
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

        assert "Failed to move task: boom" in str(
            app.query_one("#status", Static).render()
        )
        assert _content_col(app.query_one(TaskTable)) == ["kid", "parent"]


class FailingMoveRepository(FakeRepository):
    async def set_project(
        self, task_id: TaskId, project_id: str, section_id: str | None = None
    ) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_move_failure_is_surfaced_and_resyncs() -> None:
    repo = FailingMoveRepository([_row("t1", "220"), _unmoved()], _MOVE_PROJECTS)
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await settled(app)
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
        await settled(app)
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
        await settled(app)
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
        await settled(app)
        await pilot.pause()

        assert "Failed to set labels: boom" in str(
            app.query_one("#status", Static).render()
        )
        # failed command resyncs to server truth: the cell reverts to just "@work"
        assert str(_cell(app.query_one(DataTable[object]), 0, "Labels")) == "@work"


@pytest.mark.anyio
async def test_typed_due_text_goes_to_the_server_to_parse() -> None:
    repo = FakeRepository([_row("A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("s", *_typing("every mon until Dec 31"), "enter")
        await settled(app)
        await pilot.pause()

        assert repo.dues == [(TaskId("A"), DueText("every mon until Dec 31"))]


@pytest.mark.anyio
async def test_typed_due_holds_the_old_date_until_the_server_answers() -> None:
    # Todoist parses the phrase, so the new date is unknowable locally: the row
    # keeps what it had and only carries the unconfirmed mark.
    repo = GatedRefreshRepository([_row("A")], [Project(id="220", name="Errands")])
    repo.release.set()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        repo.release.clear()  # block the sync that follows the change

        await pilot.press("t")
        await pilot.pause()
        await pilot.press("s", *_typing("every mon"), "enter")
        await pilot.pause()

        table = app.query_one(TaskTable)
        assert _title(table, 0).strip() == "A ⟳"
        assert str(_cell(table, 0, "Due")) == "21 Jul"

        repo.release.set()
        await settled(app)
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert _title(table, 0).strip() == "A"  # the answer retired the change
        assert str(_cell(table, 0, "Due")) == "Monday ↻"  # the parsed rule


@pytest.mark.anyio
async def test_undoing_a_typed_due_restores_the_previous_one() -> None:
    repo = FakeRepository([_row("A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("s", *_typing("every mon"), "enter")
        await settled(app)
        await pilot.press("z")
        await settled(app)
        await pilot.pause()

        assert repo.dues[-1] == (TaskId("A"), Due(date=datetime.date(2026, 7, 21)))


def _typing(text: str) -> list[str]:
    """Textual key names for typing `text` into a field."""
    return ["space" if character == " " else character for character in text]


def _parsed(due: DueText) -> Due:
    """Todoist's answer to a typed phrase: it resolves the date server-side, and
    a phrase naming a clock time resolves to a timed due."""
    named = re.search(r"(\d{1,2}):(\d{2})$", due.text)
    return Due(
        date=_PARSED_DATE,
        time=datetime.time(int(named[1]), int(named[2])) if named else None,
        is_recurring=True,
        string=due.text,
    )


def _row(
    content: str,
    project_id: str = "220",
    parent_id: str | None = None,
    section_id: str | None = None,
    child_order: int = 0,
    day_order: int = -1,
) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id=project_id,
        parent_id=parent_id,
        section_id=section_id,
        child_order=child_order,
        day_order=day_order,
    )


# A move empties t1's project, and one project across the view drops the PROJECT
# column — this third-project row keeps two in play so the cell stays assertable.
_MOVE_PROJECTS = [
    Project(id="220", name="Errands"),
    Project(id="9", name="Work"),
    Project(id="5", name="Home"),
]


def _unmoved() -> Task:
    """Sorts after t1, so the moved task stays row 0."""
    return _row("unmoved", "5")


async def _grouped_by_project() -> InMemoryArrangements:
    store = InMemoryArrangements()
    await store.save("today", Arrangement(group_by=(Field.PROJECT,)))
    return store


def _is_divider(table: DataTable[object], row: int) -> bool:
    """Group dividers are keyed apart from task rows, and carry no marker slot."""
    key = table.coordinate_to_cell_key(Coordinate(row, 0)).row_key
    return str(key.value).startswith("h:")


def _title(table: DataTable[object], row: int) -> str:
    """A row's title text, past the marker slot that opens the cell."""
    return str(table.get_row_at(row)[0])[len(MARKER_SLOT) :]


def _content_col(table: DataTable[object]) -> list[str]:
    """Column 0 of every row: task titles past their marker slot, group dividers
    whole, since a divider starts at the true left edge."""
    return [
        str(table.get_row_at(i)[0]) if _is_divider(table, i) else _title(table, i)
        for i in range(table.row_count)
    ]


def _cell(table: DataTable[object], row: int, label: str) -> object:
    """A cell by column label, or None when that column is hidden (all-empty)."""
    labels = [str(c.label).casefold() for c in table.ordered_columns]
    if label.casefold() not in labels:
        return None
    return table.get_row_at(row)[labels.index(label.casefold())]


def _divider_row(table: TaskTable) -> str:
    """The group divider as it is painted: every cell of the row, joined. Valid
    because the table carries no cell padding of its own."""
    assert table.cell_padding == 0
    row = next(i for i in range(table.row_count) if "──" in str(table.get_row_at(i)[0]))
    return "".join(str(cell) for cell in table.get_row_at(row))


@pytest.mark.anyio
async def test_the_group_divider_runs_unbroken_to_the_right_edge() -> None:
    """The rule is the section boundary, so it has to read as one line — a gap at
    each column join, or a stop short of the edge, reads as debris."""
    repo = FakeRepository([_row("a"), _row("b")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()
        await settled(app)

        table = app.query_one(TaskTable)
        divider = _divider_row(table)
        assert cell_len(divider) == table.scrollable_content_region.width
        tail = divider.split("Errands (2) ")[1]  # one space sets the label off
        assert set(tail) == {"─"}  # then unbroken to the edge, column joins and all


@pytest.mark.anyio
async def test_the_group_divider_follows_the_terminal_width() -> None:
    repo = FakeRepository([_row("a")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test(size=(70, 24)) as pilot:
        await pilot.pause()
        await settled(app)
        narrow = cell_len(_divider_row(app.query_one(TaskTable)))

        await pilot.resize_terminal(120, 24)
        await pilot.pause()
        assert cell_len(_divider_row(app.query_one(TaskTable))) > narrow


def _crowded(content: str, project_id: str = "220") -> Task:
    """A task that fills every column: labels, due, deadline, project."""
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 29)),
        deadline=Deadline(date=datetime.date(2026, 7, 30)),
        project_id=project_id,
        labels=("home",),
    )


@pytest.mark.anyio
async def test_a_narrow_terminal_cuts_the_title_then_drops_columns() -> None:
    """Squeezed, the list gives up title text before it gives up a column, and
    the column it does give up is the one the view says least about."""
    repo = FakeRepository(
        # two projects, so PROJECT is dropped for want of room, not for repeating
        [_crowded("Buy milk and bread on the way home tonight"), _crowded("cut", "9")],
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test(size=(60, 24)) as pilot:
        await pilot.pause()
        await settled(app)

        table = app.query_one(TaskTable)
        assert _title(table, 0).endswith("…")
        assert _cell(table, 0, "PROJECT") is None
        assert _cell(table, 0, "DUE") is not None  # the dates are worth the room

        await pilot.resize_terminal(120, 24)
        await pilot.pause()

        assert not _title(table, 0).endswith("…")
        assert _cell(table, 0, "PROJECT") is not None


@pytest.mark.anyio
async def test_the_column_labels_clear_the_marker_slot() -> None:
    """TASK has to start where the titles start, not where their marker slot does."""
    repo = FakeRepository([_row("Buy milk")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)

        header = app.query_one(ColumnHeader).render()
        assert isinstance(header, Content)
        title = title_cell(app.query_one(TaskTable), 0)
        assert header.plain.index("TASK") == title.plain.index("Buy milk")


@pytest.mark.anyio
async def test_the_chrome_is_ruled_apart_rather_than_tinted() -> None:
    """Stacked background bands were the noise; a rule under each reads quieter."""
    repo = FakeRepository([_row("a")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()

        assert len(app.query(Rule)) == 2  # under the band, under the labels
        canvas = app.screen.background_colors[1]
        for widget in (StatusBand, ColumnHeader, TaskTable):
            # composited, not declared: no section paints a tint of its own, so
            # nothing ends in a hard edge where the section stops
            assert app.query_one(widget).background_colors[1] == canvas


@pytest.mark.anyio
async def test_the_group_label_leads_over_a_receding_rule() -> None:
    repo = FakeRepository([_row("a")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)

        table = app.query_one(TaskTable)
        header = next(
            cell
            for i in range(table.row_count)
            if isinstance(cell := table.get_row_at(i)[0], Text) and "──" in cell.plain
        )
        assert cell_tier(table, header) is Tier.MUTED  # the rules recede
        accented = [
            text for tier, text in span_tiers(table, header) if tier is Tier.ACCENT
        ]
        assert accented == ["Errands (1)"]  # only the label is accented


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
        await open_view(pilot, "work")
        await settled(app)
        await pilot.press("L")  # sections open folded
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
        await open_view(pilot, "work")
        await settled(app)
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
        await pilot.press("L")
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
        await settled(app)
        await pilot.press("L")  # unfold, so the task is on screen
        await pilot.pause()
        await pilot.press("j")  # move off the header onto the task
        await pilot.press("e")
        await settled(app)
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
        await pilot.press("L")
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
        await settled(app)
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
        """complete() is held in flight, so a reload lands before the ack."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # pyright: ignore[reportArgumentType]
            self.hold = asyncio.Event()

        async def complete(self, task_id: TaskId) -> None:
            await self.hold.wait()
            await super().complete(task_id)

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
        await settled(app)
        table = app.query_one(TaskTable)
        await pilot.press("l")  # reveal the subtask
        await pilot.pause()
        await pilot.press("e")  # close the parent
        await pilot.pause()
        await pilot.press("r")  # a reload lands before the close is acknowledged
        await _settle(pilot)

        assert [c.strip() for c in _content_col(table)] == ["b other"]

        repo.hold.set()
        await settled(app)
        await pilot.pause()
        assert [c.strip() for c in _content_col(table)] == ["b other"]


@pytest.mark.anyio
async def test_a_pulled_in_subtask_leaves_with_the_parent_that_carried_it() -> None:
    repo = _today_view_with_a_pulled_in_subtask()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
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
async def test_initial_cursor_lands_on_the_leading_header_when_all_is_folded() -> None:
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert "──" in _content_col(table)[0]  # every group starts folded
        assert table.cursor_row == 0  # the only row there is


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
        await pilot.press("L")
        await pilot.pause()
        await pilot.press("j")  # onto h1, under the Home header
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
        table = app.query_one(TaskTable)
        assert _content_col(table)[0].startswith("▸ ──")  # folded
        await pilot.press("L")
        await pilot.pause()
        assert _content_col(table)[0].startswith("▾ ──")  # open


@pytest.mark.anyio
async def test_h_folds_the_group_under_the_cursor() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("L")  # open both groups; the cursor rests on Home's header
        await pilot.pause()
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
        await pilot.press("L")
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
        await pilot.press("L")
        await pilot.pause()
        assert "Today · 2 task(s)" in str(status.render())
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
        await pilot.press("L")  # the cursor rests on the Home header at row 0
        await pilot.pause()
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
        await pilot.press("L")
        await pilot.pause()
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
        await pilot.press("L")
        await pilot.pause()
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
        await pilot.press("h")  # already folded
        await pilot.pause()
        await pilot.press("h")  # no outer group to step out to
        await pilot.pause()
        assert table.cursor_row == 0


@pytest.mark.anyio
async def test_h_on_a_task_folds_the_group_holding_it() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("L")
        await pilot.pause()
        await pilot.press("j")  # onto the task under Home's header
        assert _cursor_content(table).strip() == "h1"
        await pilot.press("h")
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert "h1" not in contents  # the group it lives in folded away
        assert contents[0].startswith("▸ ──") and "Home (1)" in contents[0]
        assert table.cursor_row == 0  # cursor rides along onto the header
        assert "w1" in contents


@pytest.mark.anyio
async def test_h_on_a_task_folds_only_its_innermost_group() -> None:
    app = TodoistApp(
        _two_project_repo(), arrangements=await _grouped_by_project_and_priority()
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("L")
        await pilot.pause()
        table.move_cursor(row=2)  # the task under Home's priority header
        assert _cursor_content(table).strip() == "h1"
        await pilot.press("h")
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert contents[0].startswith("▾ ──") and "Home (1)" in contents[0]
        assert contents[1].startswith("▸ ──")  # only the inner group folded
        assert "h1" not in contents
        assert table.cursor_row == 1


@pytest.mark.anyio
async def test_h_on_an_ungrouped_task_stays_put() -> None:
    app = TodoistApp(_two_project_repo())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        before = _content_col(table)
        await pilot.press("h")  # no header to fold onto
        await pilot.pause()
        assert _content_col(table) == before
        assert table.cursor_row == 0


@pytest.mark.anyio
async def test_h_walks_a_subtask_out_to_its_parent_then_folds_the_group() -> None:
    app = TodoistApp(_parent_and_child(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("L")  # unfold the group and the subtask tree
        await pilot.pause()
        table.move_cursor(row=2)
        assert _cursor_content(table).strip() == "child"
        await pilot.press("h")  # a child: step out to the parent
        await pilot.pause()
        assert _cursor_content(table).strip() == "▾ parent"
        await pilot.press("h")  # an expanded parent: fold its subtree
        await pilot.pause()
        assert _cursor_content(table).strip() == "▸ parent"
        await pilot.press("h")  # a root task: fold the group holding it
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert "parent" not in contents[0] and contents[0].startswith("▸ ──")
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
async def test_regrouping_folds_everything() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("L")  # open both project groups
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("r")  # group by Priority: the old label paths are stale
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)
        await pilot.pause()
        contents = [c.strip() for c in _content_col(table)]
        assert all(c.startswith("▸ ──") for c in contents)
        assert "h1" not in contents and "w1" not in contents


@pytest.mark.anyio
async def test_L_unfolds_every_group_and_subtask_tree() -> None:
    repo = FakeRepository(
        [_row("w1", "220"), _row("sub", "220", parent_id="w1"), _row("h1", "9")],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)

        await pilot.press("L")
        await pilot.pause()

        contents = [c.strip() for c in _content_col(table)]
        assert not any(c.startswith("\u25b8") for c in contents)
        assert all(any(name in c for c in contents) for name in ("w1", "sub", "h1"))


@pytest.mark.anyio
async def test_H_folds_every_group_and_subtask_tree() -> None:
    repo = FakeRepository(
        [_row("w1", "220"), _row("sub", "220", parent_id="w1"), _row("h1", "9")],
        [Project(id="220", name="Work"), Project(id="9", name="Home")],
    )
    app = TodoistApp(repo, arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("L")
        await pilot.pause()

        await pilot.press("H")
        await pilot.pause()

        contents = [c.strip() for c in _content_col(table)]
        # the counts tally visible lines, so Work's folded subtask is not one
        assert [c.split("\u2500\u2500 ")[1].split(" \u2500")[0] for c in contents] == [
            "Home (1)",
            "Work (1)",
        ]


@pytest.mark.anyio
async def test_H_folds_subtasks_when_nothing_is_grouped() -> None:
    repo = FakeRepository([_row("A"), _row("sub", parent_id="A")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("l")  # reveal the subtask
        await pilot.pause()
        assert table.row_count == 2

        await pilot.press("H")
        await pilot.pause()

        assert table.row_count == 1


@pytest.mark.anyio
async def test_folding_everything_keeps_the_cursor_on_a_visible_row() -> None:
    app = TodoistApp(_two_project_repo(), arrangements=await _grouped_by_project())

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("L")
        await pilot.pause()
        table.move_cursor(row=table.row_count - 1)  # onto a task, which H hides

        await pilot.press("H")
        await pilot.pause()

        assert table.cursor_row < table.row_count
        assert _cursor_content(table).startswith("\u25b8")  # a surviving header


@pytest.mark.anyio
async def test_a_change_unfolds_the_group_it_moves_the_task_into() -> None:
    store = InMemoryArrangements()
    await store.save("today", Arrangement(group_by=(Field.PRIORITY,)))
    repo = FakeRepository([_row("w1", "220")], [Project(id="220", name="Work")])
    app = TodoistApp(repo, arrangements=store)

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        await pilot.press("L")
        await pilot.press("j")  # onto the task, under the P4 header
        await pilot.pause()

        await pilot.press("1")
        await settled(app)
        await pilot.pause()

        # the task moved into a P1 group that was never opened: it must not vanish
        contents = [c.strip() for c in _content_col(table)]
        assert "w1" in contents
        assert contents[0].startswith("\u25be \u2500\u2500") and "P1" in contents[0]


@pytest.mark.anyio
async def test_a_saved_open_group_is_unfolded_when_the_view_opens() -> None:
    folds = InMemoryFolds()
    await folds.save("today", frozenset({("Home",)}))
    app = TodoistApp(
        _two_project_repo(), arrangements=await _grouped_by_project(), folds=folds
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)

        contents = [c.strip() for c in _content_col(table)]
        assert contents[0].startswith("\u25be \u2500\u2500")  # Home, as it was left
        assert "h1" in contents
        assert "w1" not in contents  # Work was never opened
        assert table.cursor_row == 1  # a task, not the leading header


@pytest.mark.anyio
async def test_unfolding_a_group_is_remembered_for_the_view() -> None:
    folds = InMemoryFolds()
    app = TodoistApp(
        _two_project_repo(), arrangements=await _grouped_by_project(), folds=folds
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # unfold Home, under the cursor
        await settled(app)
        await pilot.pause()

    assert await folds.get("today") == frozenset({("Home",)})


@pytest.mark.anyio
async def test_folds_are_kept_apart_per_view() -> None:
    folds = InMemoryFolds()
    repo = FakeRepository(
        [_row("w1", "9")],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
    )
    app = TodoistApp(repo, arrangements=await _grouped_by_project(), folds=folds)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # unfold Today's only group
        await settled(app)
        await open_view(pilot, "work")
        await settled(app)
        await pilot.pause()

        assert await folds.get("today") == frozenset({("Work",)})
        assert await folds.get("project:9") == frozenset()  # its sections stay folded


@pytest.mark.anyio
async def test_regrouping_drops_the_saved_folds() -> None:
    folds = InMemoryFolds()
    app = TodoistApp(
        _two_project_repo(), arrangements=await _grouped_by_project(), folds=folds
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("L")
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("r")  # group by Priority: the old label paths are stale
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

    assert await folds.get("today") == frozenset()


class StalledFolds(InMemoryFolds):
    """Holds the first save open, as a slow disk write would."""

    def __init__(self) -> None:
        super().__init__()
        self.released = asyncio.Event()
        self.calls = 0

    async def save(self, view_key: str, open_groups: frozenset[GroupPath]) -> None:
        self.calls += 1
        if self.calls == 1:
            await self.released.wait()
        await super().save(view_key, open_groups)


@pytest.mark.anyio
async def test_a_fold_save_lands_on_the_view_it_was_made_in() -> None:
    folds = StalledFolds()
    app = TodoistApp(
        _two_project_repo(), arrangements=await _grouped_by_project(), folds=folds
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # unfold Home; this save stalls
        await pilot.pause()
        await pilot.press("j", "j")  # onto the Work header
        await pilot.press("l")  # a second unfold, queued behind the first
        await pilot.pause()
        await open_view(pilot, "work")  # switch away before either write lands
        while "Work" not in _status(app):  # the stalled save blocks `settled`
            await pilot.pause()

        folds.released.set()
        await settled(app)
        await pilot.pause()

    assert await folds.get("today") == frozenset({("Home",), ("Work",)})
    assert await folds.get("project:220") == frozenset()


class ReorderedFolds(InMemoryFolds):
    """Makes the first save finish last, as a slower disk write would."""

    def __init__(self) -> None:
        super().__init__()
        self.overtaken = asyncio.Event()
        self.calls = 0

    async def save(self, view_key: str, open_groups: frozenset[GroupPath]) -> None:
        self.calls += 1
        if self.calls == 1:
            await self.overtaken.wait()
        await super().save(view_key, open_groups)


@pytest.mark.anyio
async def test_a_slow_fold_save_cannot_undo_a_later_one() -> None:
    folds = ReorderedFolds()
    app = TodoistApp(
        _two_project_repo(), arrangements=await _grouped_by_project(), folds=folds
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # unfold Home; its save stalls
        await pilot.pause()
        await pilot.press("h")  # fold it back up again
        await pilot.pause()

        folds.overtaken.set()
        await settled(app)
        await pilot.pause()

    assert await folds.get("today") == frozenset()


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
        await settled(app)
        await pilot.press("j")  # move off the top row
        table = app.query_one(TaskTable)
        assert table.cursor_row == 1

        await pilot.press("r")  # background resync re-renders the table
        await settled(app)
        await pilot.pause()

        assert table.cursor_row == 1  # cursor stayed on "Second", not reset to top
        assert _title(table, table.cursor_row) == "Second"


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
        assert _title(app.query_one(TaskTable), 0) == "Today thing"

        await pilot.press("i")
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert _title(table, 0) == "Inbox thing"
        assert "Inbox · 1 task(s)" in str(app.query_one("#status", Static).render())


@pytest.mark.anyio
async def test_today_is_reachable_from_the_views_screen() -> None:
    """Today has no key of its own any more — every key is the user's to bind."""
    repo = FakeRepository([_row("Today thing")], [], inbox=[_row("Inbox thing")])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        await open_view(pilot, "today")
        await settled(app)
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert _title(table, 0) == "Today thing"
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
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")  # group by Project
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)
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
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("s")  # group by Section
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)
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
        await settled(app)
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("d")  # sort by Due date (ascending)
        await pilot.press("d")  # tapping again flips to descending
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)

        assert await store.get("today") == Arrangement(
            sort_by=(SortKey(Field.DUE_DATE, ascending=False),)
        )


@pytest.mark.anyio
async def test_s_then_e_sorts_by_deadline() -> None:
    store = InMemoryArrangements()
    repo = FakeRepository(
        [
            replace(_row("later"), deadline=Deadline(date=datetime.date(2026, 8, 15))),
            _row("none"),
            replace(_row("soon"), deadline=Deadline(date=datetime.date(2026, 8, 9))),
        ],
        [Project(id="220", name="Work")],
    )
    app = TodoistApp(repo, arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("e")  # sort by Deadline
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert _content_col(app.query_one(DataTable[object])) == [
            "soon",
            "later",
            "none",
        ]
        assert await store.get("today") == Arrangement(
            sort_by=(SortKey(Field.DEADLINE),)
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
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        for key in ("p", "r", "d", "t"):  # four fields; the fourth is ignored
            await pilot.press(key)
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)

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
        await pilot.press("p")  # must not open the views screen underneath
        await pilot.pause()
        assert len([s for s in app.screen_stack if isinstance(s, ArrangeScreen)]) == 1
        assert not any(isinstance(s, ViewsScreen) for s in app.screen_stack)


@pytest.mark.anyio
async def test_backspace_removes_last_group_field() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")  # Project
        await pilot.press("r")  # Priority
        await pilot.press("backspace")  # drop Priority
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)

        assert await store.get("today") == Arrangement(group_by=(Field.PROJECT,))


@pytest.mark.anyio
async def test_shift_g_clears_the_group_chain() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")
        await pilot.press("r")
        await pilot.press("G")  # shift+G clears
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)

        assert await store.get("today") == Arrangement()


@pytest.mark.anyio
async def test_re_tapping_a_group_field_flips_its_direction() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")  # Project ascending
        await pilot.press("p")  # re-tap → descending
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)

        assert await store.get("today") == Arrangement(
            group_by=(Field.PROJECT,), group_desc=frozenset({Field.PROJECT})
        )


@pytest.mark.anyio
async def test_re_tapping_a_group_field_twice_returns_to_ascending() -> None:
    store = InMemoryArrangements()
    app = TodoistApp(_two_project_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")  # asc
        await pilot.press("p")  # desc
        await pilot.press("p")  # asc again
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)

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
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("p")
        await pilot.press("enter")  # schedules the apply worker for Today
        await pilot.press("i")  # switch to Inbox before it runs
        await pilot.pause()
        await settled(app)

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
        await settled(app)
        await pilot.press("g")  # group Today by project
        await pilot.pause()
        await pilot.press("p")
        await pilot.press("enter")
        await pilot.pause()
        await settled(app)

        await pilot.press("i")  # Inbox has no arrangement → flat
        await pilot.pause()
        await settled(app)
        assert not any(
            "──" in c for c in _content_col(app.query_one(DataTable[object]))
        )

        await open_view(pilot, "today")  # its grouping returns
        await pilot.pause()
        await settled(app)
        assert any("──" in c for c in _content_col(app.query_one(DataTable[object])))


@pytest.mark.anyio
async def test_pressing_p_opens_the_views_screen() -> None:
    repo = FakeRepository(
        [_row("w1", "9")],
        [
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
        ],
        filters=[Filter(id="f1", name="My Filter", query="p1", order=1)],
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, ViewsScreen)
        options = app.screen.query_one(OptionList)
        labels = [
            str(options.get_option_at_index(i).prompt)
            for i in range(options.option_count)
        ]
        assert labels == [
            view_label("My Filter", sigil="⚑"),
            view_label("Work", sigil="#"),
            view_label("Today"),
            view_label("Inbox"),
        ]


@pytest.mark.anyio
async def test_opening_a_project_from_the_views_screen_switches_to_it() -> None:
    repo = FakeRepository([_row("w1", "9")], [Project(id="9", name="Work")])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "work")
        await settled(app)
        assert "Work" in _status(app)


@pytest.mark.anyio
async def test_opening_a_filter_from_the_views_screen_refreshes_it_live() -> None:
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands")],
        filters=[Filter(id="f1", name="My Filter", query="p1", order=1)],
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "filter")
        await settled(app)
        assert "My Filter" in _status(app)
        assert "p1" in repo.refresh_filtered_queries


def _section_jump_repo() -> FakeRepository:
    """A Work project with a sectioned and a loose task, plus an empty section."""
    return FakeRepository(
        [_row("planned", "9", section_id="s1"), _row("loose", "9")],
        [Project(id="9", name="Work")],
        sections=[
            Section(id="s1", project_id="9", name="Planning", order=1),
            Section(id="s2", project_id="9", name="Someday", order=2),
        ],
    )


@pytest.mark.anyio
async def test_the_views_screen_lists_a_projects_sections() -> None:
    app = TodoistApp(_section_jump_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        options = app.screen.query_one(OptionList)
        labels = [
            str(options.get_option_at_index(i).prompt)
            for i in range(options.option_count)
        ]
        assert labels == [
            view_label("Work", sigil="#"),
            view_label("Work / Planning", sigil="§"),
            view_label("Work / Someday", sigil="§"),
            view_label("Today"),
            view_label("Inbox"),
        ]


@pytest.mark.anyio
async def test_opening_a_section_lands_the_cursor_on_its_header() -> None:
    app = TodoistApp(_section_jump_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "planning")
        await settled(app)
        await pilot.pause()
        assert "Work" in _status(app)  # the project view opened, not a new one
        table = app.query_one(TaskTable)
        assert "Planning" in _content_col(table)[table.cursor_row]


@pytest.mark.anyio
async def test_opening_a_section_leaves_it_folded() -> None:
    app = TodoistApp(_section_jump_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "planning")
        await settled(app)
        await pilot.pause()
        assert not any("planned" in c for c in _content_col(app.query_one(TaskTable)))


@pytest.mark.anyio
async def test_opening_a_section_that_is_not_grouped_lands_nowhere() -> None:
    store = InMemoryArrangements()
    await store.save("project:9", Arrangement())  # user ungrouped the project
    app = TodoistApp(_section_jump_repo(), arrangements=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "planning")
        await settled(app)
        await pilot.pause()
        assert "Work" in _status(app)
        assert app.query_one(TaskTable).cursor_row == 0


@pytest.mark.anyio
async def test_opening_an_empty_section_lands_on_its_header() -> None:
    app = TodoistApp(_section_jump_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "someday")
        await settled(app)
        await pilot.pause()
        assert "Work" in _status(app)
        table = app.query_one(TaskTable)
        assert "Someday" in _content_col(table)[table.cursor_row]


@pytest.mark.anyio
async def test_a_project_shows_a_header_for_a_section_holding_no_tasks() -> None:
    app = TodoistApp(_section_jump_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "work")
        await settled(app)
        await pilot.pause()
        content = _content_col(app.query_one(TaskTable))
        assert any("Someday" in c and "(0)" in c for c in content)


@pytest.mark.anyio
async def test_a_cross_project_view_shows_no_empty_section_headers() -> None:
    app = TodoistApp(_section_jump_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("s", "enter")  # Today, grouped by section
        await pilot.pause()
        await settled(app)
        await pilot.pause()
        # section_order is per project, so a view spanning them seeds nothing
        assert not any("Someday" in c for c in _content_col(app.query_one(TaskTable)))


@pytest.mark.anyio
async def test_a_key_bound_in_the_views_screen_is_persisted() -> None:
    slots = InMemoryViewSlots()
    repo = FakeRepository([_row("w1", "9")], [Project(id="9", name="Work")])
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("w", "o", "r")  # narrow to Work, then bind it a key
        await pilot.pause()
        await pilot.press("ctrl+b", "w")
        await pilot.press("escape")
        await pilot.pause()
    assert (await slots.get()).view_key_for("w") == "project:9"


class ReorderedViewSlots(InMemoryViewSlots):
    """Makes the first save finish last, as a slower disk write would."""

    def __init__(self) -> None:
        super().__init__()
        self.overtaken = asyncio.Event()
        self.calls = 0

    async def save(self, slots: ViewSlots) -> None:
        self.calls += 1
        if self.calls == 1:
            await self.overtaken.wait()
        await super().save(slots)


@pytest.mark.anyio
async def test_a_slow_save_cannot_undo_a_later_edit() -> None:
    slots = ReorderedViewSlots()
    repo = FakeRepository([_row("w1", "9")], [Project(id="9", name="Work")])
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("w", "o", "r")  # narrow to Work, then bind it a key
        await pilot.pause()
        await pilot.press("ctrl+b", "w")
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("p")  # edit again while the first save is still in flight
        await pilot.pause()
        await pilot.press("w", "o", "r")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.press("escape")
        await pilot.pause()

        slots.overtaken.set()
        await settled(app)
        await pilot.pause()

    assert await slots.get() == ViewSlots().assign("w", "project:9").with_startup(
        "project:9"
    )


@pytest.mark.anyio
async def test_a_bound_key_jumps_straight_to_its_view() -> None:
    slots = InMemoryViewSlots()
    await slots.save(ViewSlots().assign("w", "project:9"))
    repo = FakeRepository([_row("w1", "9")], [Project(id="9", name="Work")])
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Today" in _status(app)

        await pilot.press("w")
        await pilot.pause()
        await settled(app)
        assert "Work" in _status(app)


@pytest.mark.anyio
async def test_full_stop_is_free_to_bind_like_any_other_key() -> None:
    slots = InMemoryViewSlots()
    await slots.save(ViewSlots().assign(".", "project:9"))
    repo = FakeRepository([_row("w1", "9")], [Project(id="9", name="Work")])
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("full_stop")
        await pilot.pause()
        await settled(app)
        assert "Work" in _status(app)


@pytest.mark.anyio
async def test_a_bound_filter_key_refreshes_it_live() -> None:
    slots = InMemoryViewSlots()
    await slots.save(ViewSlots().assign("n", "filter:f1"))
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands")],
        filters=[Filter(id="f1", name="My Filter", query="p1", order=1)],
    )
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        repo.refresh_filtered_queries.clear()

        await pilot.press("n")
        await pilot.pause()
        await settled(app)
        assert "My Filter" in _status(app)
        assert "p1" in repo.refresh_filtered_queries


@pytest.mark.anyio
async def test_a_bound_key_whose_view_is_gone_reports_instead_of_jumping() -> None:
    slots = InMemoryViewSlots()
    await slots.save(ViewSlots().assign("w", "project:999"))
    repo = FakeRepository([_row("t1", "220")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        assert "w no longer opens anything" in _status(app)


@pytest.mark.anyio
async def test_a_bound_key_does_nothing_while_a_modal_is_open() -> None:
    """App-level key handling runs even under a modal, so it has to stand down."""
    slots = InMemoryViewSlots()
    await slots.save(ViewSlots().assign("w", "project:9"))
    repo = FakeRepository([_row("w1", "9")], [Project(id="9", name="Work")])
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")  # any modal will do
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        await settled(app)
        assert isinstance(app.screen, HelpScreen)
        assert _status(app).startswith("Today")  # the bound view never opened


@pytest.mark.anyio
async def test_startup_opens_the_view_marked_in_the_slots() -> None:
    slots = InMemoryViewSlots()
    await slots.save(ViewSlots().with_startup("inbox"))
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands")],
        inbox=[_row("i1", "220")],
    )
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable[object])
        assert _title(table, 0) == "i1"
        assert "Inbox" in _status(app)


@pytest.mark.anyio
async def test_startup_falls_back_to_today_when_its_view_is_gone() -> None:
    slots = InMemoryViewSlots()
    await slots.save(ViewSlots().with_startup("project:999"))
    repo = FakeRepository([_row("t1", "220")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Today" in _status(app)


@pytest.mark.anyio
async def test_a_startup_filter_view_refreshes_live() -> None:
    slots = InMemoryViewSlots()
    await slots.save(ViewSlots().with_startup("filter:f1"))
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands")],
        filters=[Filter(id="f1", name="My Filter", query="p1", order=1)],
    )
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        assert "My Filter" in _status(app)
        assert "p1" in repo.refresh_filtered_queries


def _trail_repo(projects: list[Project] | None = None) -> FakeRepository:
    """Two tasks in Today, a Work project of its own, and an Inbox task."""
    return FakeRepository(
        [_row("t1", "220"), _row("t2", "220"), _row("w1", "9")],
        [Project(id="9", name="Work")] if projects is None else projects,
        inbox=[_row("i1", "220")],
    )


@pytest.mark.anyio
async def test_alt_h_goes_back_to_the_view_before() -> None:
    app = TodoistApp(_trail_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "work")
        await settled(app)
        assert "Work" in _status(app)

        await pilot.press("alt+h")
        await settled(app)
        await pilot.pause()
        assert "Today" in _status(app)


@pytest.mark.anyio
async def test_alt_l_walks_the_trail_forward_again() -> None:
    app = TodoistApp(_trail_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "work")
        await settled(app)
        await pilot.press("alt+h")
        await settled(app)

        await pilot.press("alt+l")
        await settled(app)
        await pilot.pause()
        assert "Work" in _status(app)


@pytest.mark.anyio
async def test_going_back_puts_the_cursor_where_it_was_left() -> None:
    app = TodoistApp(_trail_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")  # leave Today with the cursor on its second task
        await open_view(pilot, "work")
        await settled(app)

        await pilot.press("alt+h")
        await settled(app)
        await pilot.pause()
        table = app.query_one(TaskTable)
        assert _title(table, table.cursor_row) == "t2"


@pytest.mark.anyio
async def test_the_first_view_has_nothing_behind_it() -> None:
    app = TodoistApp(_trail_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+h")
        await settled(app)
        await pilot.pause()
        assert "nothing to go back to" in _status(app)
        assert _titles(app.query_one(TaskTable)) == ["t1", "t2", "w1"]


@pytest.mark.anyio
async def test_the_newest_view_has_nothing_ahead_of_it() -> None:
    app = TodoistApp(_trail_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+l")
        await settled(app)
        await pilot.pause()
        assert "nothing to go forward to" in _status(app)


@pytest.mark.anyio
async def test_opening_a_view_after_going_back_drops_the_way_forward() -> None:
    app = TodoistApp(_trail_repo())
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "work")
        await settled(app)
        await pilot.press("alt+h")  # back to Today
        await settled(app)

        await pilot.press("i")  # a new branch: Work is no longer ahead
        await settled(app)
        await pilot.press("alt+l")
        await settled(app)
        await pilot.pause()
        assert "nothing to go forward to" in _status(app)
        assert _titles(app.query_one(TaskTable)) == ["i1"]  # still on Inbox


@pytest.mark.anyio
async def test_a_view_whose_project_is_gone_is_skipped_on_the_way_back() -> None:
    projects = [Project(id="9", name="Work")]
    app = TodoistApp(_trail_repo(projects))
    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "work")
        await settled(app)
        await pilot.press("i")
        await settled(app)
        projects.clear()  # Work is deleted while the trail still names it

        await pilot.press("alt+h")
        await settled(app)
        await pilot.pause()
        assert "Today" in _status(app)


class HeldProjects(FakeRepository):
    """Holds project lookups open until both navigations are waiting on one."""

    def __init__(self, tasks: list[Task], projects: list[Project]) -> None:
        super().__init__(tasks, projects, inbox=[_row("i1", "220")])
        self.held = asyncio.Event()
        self.both_waiting = asyncio.Event()
        self.hold = False
        self.waiting = 0

    async def projects(self) -> list[Project]:
        if self.hold:
            self.waiting += 1
            if self.waiting == 2:
                self.both_waiting.set()
            await self.held.wait()
        return await super().projects()


@pytest.mark.anyio
async def test_a_jump_that_overtakes_a_step_back_keeps_the_view_it_opened() -> None:
    """Both resolve against the repository, so the one that lands second must not
    paint over the view the other opened, nor drop its visit from the trail."""
    repo = HeldProjects(
        [_row("t1", "220"), _row("w1", "9")], [Project(id="9", name="Work")]
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")  # trail: Today, Inbox
        await settled(app)

        repo.hold = True
        jumping = asyncio.create_task(app._go_to("project:9"))  # pyright: ignore[reportPrivateUsage]
        stepping = asyncio.create_task(app.action_back())
        await repo.both_waiting.wait()
        repo.hold = False
        repo.held.set()
        await jumping
        await stepping
        await settled(app)
        await pilot.pause()
        assert _titles(app.query_one(TaskTable)) == ["w1"]  # the jump won

        await pilot.press("alt+h")  # and its visit is the one the trail steps off
        await settled(app)
        await pilot.pause()
        assert _titles(app.query_one(TaskTable)) == ["i1"]


@pytest.mark.anyio
async def test_the_help_screen_lists_the_bound_keys() -> None:
    slots = InMemoryViewSlots()
    await slots.save(ViewSlots().assign("w", "project:9"))
    repo = FakeRepository([_row("w1", "9")], [Project(id="9", name="Work")])
    app = TodoistApp(repo, slots=slots)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        rendered = str(app.screen.query_one("#help", Static).render())
        assert "Work" in rendered


def _noted(content: str, description: str = "") -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 21)),
        project_id="220",
        description=description,
    )


def _commented(content: str, note_count: int) -> Task:
    return replace(_noted(content), note_count=note_count)


def _attribute_strip(app: TodoistApp) -> str:
    return str(app.screen.query_one("#attributes", Static).content)


@pytest.mark.anyio
async def test_a_description_marks_the_title_and_a_bare_task_stays_clean() -> None:
    repo = FakeRepository([_noted("t1", "a note"), _noted("t2")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)

        assert _content_col(app.query_one(TaskTable)) == ["t1 ≡", "t2"]


@pytest.mark.anyio
async def test_a_commented_task_is_marked_and_a_second_comment_is_counted() -> None:
    repo = FakeRepository(
        [_commented("t1", 1), _commented("t2", 3), _commented("t3", 0)], []
    )
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)

        assert _content_col(app.query_one(TaskTable)) == ["t1 ❞", "t2 ❞3", "t3"]


@pytest.mark.anyio
async def test_the_description_marker_recedes_behind_the_title() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)

        table = app.query_one(TaskTable)
        cell = title_cell(table, 0)
        assert isinstance(cell, Text)
        assert (Tier.MUTED, " ≡") in span_tiers(table, cell)
        assert tier_at(table, cell, "t1") is Tier.PRIMARY  # the title still leads


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
        await settled(app)
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
async def test_ctrl_e_seeds_the_strip_from_the_cursor_row() -> None:
    task = Task(
        id=TaskId("t1"),
        content="t1",
        priority=Priority.P2,
        due=Due(date=_TODAY),
        deadline=Deadline(date=datetime.date(2026, 8, 30)),
        labels=("errand",),
        project_id="9",
        section_id="s1",
    )
    repo = FakeRepository(
        [task],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Now", order=1)],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert _attribute_strip(app) == (
            f"{DUE_ICON} Today · {DEADLINE_ICON} 30 Aug"
            f" · {PROJECT_ICON} Work / Now · {LABELS_ICON} @errand · ● P2"
        )


@pytest.mark.anyio
async def test_a_seeds_the_strip_with_where_the_new_task_would_land() -> None:
    repo = FakeRepository(
        [_sectioned("t1", section_id="s1")],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Now", order=1)],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        # Today's view dates the task, and it keeps the cursor row's company
        assert _attribute_strip(app) == (
            f"{DUE_ICON} Today · {PROJECT_ICON} Work / Now · P4"
        )


@pytest.mark.anyio
async def test_q_seeds_a_blank_draft_bound_for_the_inbox() -> None:
    """The capture key takes nothing from where the cursor stands."""
    repo = FakeRepository(
        [_sectioned("t1", section_id="s1")],
        [Project(id="220", name="Inbox", is_inbox=True), Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Now", order=1)],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()

        assert _attribute_strip(app) == f"{PROJECT_ICON} Inbox · P4"


class HeldCreationRepository(FakeRepository):
    """The create is held in flight, so what the list shows meanwhile is visible."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        self.hold = asyncio.Event()

    async def apply_creation(self, plan: CreationPlan) -> None:
        await self.hold.wait()
        await super().apply_creation(plan)

    async def today(self) -> list[Task]:
        # a task written into Today comes back in it, the way the server answers
        return await self.all_tasks()


class FailingCreationRepository(HeldCreationRepository):
    async def apply_creation(self, plan: CreationPlan) -> None:
        await self.hold.wait()
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_a_new_task_shows_before_the_server_has_it() -> None:
    repo = HeldCreationRepository([], [Project(id="220", name="Inbox", is_inbox=True)])
    app = PaintRecordingApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "Buy milk")
        await pilot.press("ctrl+s")
        await _settle(pilot)

        assert repo.applied == []  # still in flight
        assert _content_col(app.query_one(TaskTable)) == ["Buy milk" + PENDING_MARK]

        repo.hold.set()
        await settled(app)
        await pilot.pause()

        # the server's own row takes its place: one row, no longer pending
        assert _content_col(app.query_one(TaskTable)) == ["Buy milk"]
        # and never alongside it — the snapshot and the retirement share a frame
        assert max(len(ids) for ids in app.paints) == 1


class HeldCaptureRepository(HeldCreationRepository):
    """A capture goes to the Inbox, so Today answers with Today's tasks alone —
    the created task is never handed back here."""

    async def today(self) -> list[Task]:
        return await FakeRepository.today(self)


@pytest.mark.anyio
async def test_a_task_captured_into_the_inbox_stays_out_of_todays_list() -> None:
    """It belongs to the Inbox, not to the view it was written from, so it must
    not flash in here only for the next sync to take it away again."""
    repo = HeldCaptureRepository(
        [_row("t1")], [Project(id="220", name="Inbox", is_inbox=True)]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        await _type(pilot, "Buy milk")
        await pilot.press("ctrl+s")
        await _settle(pilot)

        assert _content_col(app.query_one(TaskTable)) == ["t1"]

        repo.hold.set()
        await settled(app)
        await pilot.pause()

        assert _content_col(app.query_one(TaskTable)) == ["t1"]  # nor once it lands


@pytest.mark.anyio
async def test_the_band_says_where_a_captured_task_went() -> None:
    """The list can't show it, so the band is the only word that it was saved."""
    repo = HeldCaptureRepository(
        [_row("t1")], [Project(id="220", name="Inbox", is_inbox=True)]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        await _type(pilot, "Buy milk")
        await pilot.press("ctrl+s")
        await _settle(pilot)

        assert "Added to Inbox" in _status(app)

        repo.hold.set()
        await settled(app)


@pytest.mark.anyio
async def test_an_added_task_the_view_shows_needs_no_word_from_the_band() -> None:
    repo = HeldCreationRepository([], [Project(id="220", name="Inbox", is_inbox=True)])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(
            "a"
        )  # dated today: it lands in view, where it is its own word
        await pilot.pause()
        await _type(pilot, "Buy milk")
        await pilot.press("ctrl+s")
        await _settle(pilot)

        assert "Added to" not in _status(app)

        repo.hold.set()
        await settled(app)


@pytest.mark.anyio
async def test_a_task_still_being_created_takes_no_action() -> None:
    """Todoist named it nothing yet, so a command aimed at it could only be
    refused. The row stands, and the band says why the key did nothing."""
    repo = HeldCreationRepository([], [Project(id="220", name="Inbox", is_inbox=True)])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "Buy milk")
        await pilot.press("ctrl+s")
        await _settle(pilot)
        for key in ("e", "ctrl+e", "A"):  # the cursor sits on the only row there is
            await pilot.press(key)
            await _settle(pilot)

            assert len(app.screen_stack) == 1, key  # no editor opened over it
            assert "Still being created" in str(
                app.query_one("#status", Static).render()
            ), key

        assert repo.completed == []
        assert _content_col(app.query_one(TaskTable)) == ["Buy milk" + PENDING_MARK]

        repo.hold.set()
        await settled(app)


@pytest.mark.anyio
async def test_a_rejected_create_takes_its_row_back_off() -> None:
    repo = FailingCreationRepository(
        [], [Project(id="220", name="Inbox", is_inbox=True)]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "Buy milk")
        await pilot.press("ctrl+s")
        await _settle(pilot)

        assert _content_col(app.query_one(TaskTable)) == ["Buy milk" + PENDING_MARK]

        repo.hold.set()
        await settled(app)
        await pilot.pause()

        assert _content_col(app.query_one(TaskTable)) == []
        assert "Failed to add task: boom" in str(
            app.query_one("#status", Static).render()
        )


@pytest.mark.anyio
async def test_the_editor_carries_a_due_and_a_deadline_into_the_new_task() -> None:
    repo = FakeRepository([], [Project(id="220", name="Inbox", is_inbox=True)])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "new")
        await pilot.press("alt+t")
        await pilot.pause()
        await pilot.press("m")  # due tomorrow
        await pilot.pause()
        await pilot.press("alt+d")
        await pilot.pause()
        await pilot.press("t")  # deadline today
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        task = _added(repo)
        assert task.due == Due(date=_TODAY + datetime.timedelta(days=1))
        assert task.deadline == Deadline(date=_TODAY)


@pytest.mark.anyio
async def test_the_editor_carries_a_typed_phrase_into_the_new_task() -> None:
    repo = FakeRepository([], [Project(id="220", name="Inbox", is_inbox=True)])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "new")
        await pilot.press("alt+t")
        await pilot.pause()
        await pilot.press("s")  # focus the phrase box
        await _type(pilot, "every friday")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert _added(repo).due == DueText("every friday")


@pytest.mark.anyio
async def test_one_save_changing_due_and_deadline_undoes_as_one_batch() -> None:
    task = Task(
        id=TaskId("t1"),
        content="t1",
        priority=Priority.P4,
        due=Due(date=_TODAY),
        deadline=Deadline(date=datetime.date(2026, 8, 30)),
        project_id="220",
    )
    repo = FakeRepository([task], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("alt+t")
        await pilot.pause()
        await pilot.press("m")  # due moves to tomorrow
        await pilot.pause()
        await pilot.press("alt+d")
        await pilot.pause()
        await pilot.press("x")  # deadline cleared
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        tomorrow = _TODAY + datetime.timedelta(days=1)
        assert repo.dues == [(TaskId("t1"), Due(date=tomorrow))]
        assert repo.deadlines == [(TaskId("t1"), None)]

        await pilot.press("z")  # one undo puts both back
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert repo.dues[-1] == (TaskId("t1"), Due(date=_TODAY))
        assert repo.deadlines[-1] == (
            TaskId("t1"),
            Deadline(date=datetime.date(2026, 8, 30)),
        )


@pytest.mark.anyio
async def test_the_editor_leaves_untouched_attributes_alone() -> None:
    task = Task(
        id=TaskId("t1"),
        content="t1",
        priority=Priority.P4,
        due=Due(date=_TODAY),
        deadline=Deadline(date=datetime.date(2026, 8, 30)),
        project_id="220",
    )
    repo = FakeRepository([task], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("!")  # only the title changes
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert repo.text_edits == [(TaskId("t1"), "t1!", "")]
        assert repo.dues == []
        assert repo.deadlines == []


@pytest.mark.anyio
async def test_the_editor_carries_a_project_priority_and_labels_into_the_new_task() -> (
    None
):
    repo = FakeRepository(
        [],
        [Project(id="220", name="Inbox", is_inbox=True), Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Now", order=1)],
        labels=[Label(id="l1", name="errand")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "new")
        await pilot.press("alt+v")
        await pilot.pause()
        await pilot.press("2")  # the Inbox root is no target: 1 Work, 2 Work / Now
        await pilot.pause()
        await pilot.press("alt+l")
        await pilot.pause()
        await _type(pilot, "err")  # filters down to the one known label
        await pilot.press("space", "enter")
        await pilot.pause()
        assert isinstance(app.screen, TaskEditScreen)  # every picker handed back
        await pilot.press("alt+2")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        task = _added(repo)
        assert task.project_ref == "9"
        assert task.section_ref == "s1"
        assert task.labels == ("errand",)
        assert task.priority is Priority.P2


@pytest.mark.anyio
async def test_the_editor_moves_an_edited_task_to_the_project_it_picked() -> None:
    repo = FakeRepository(
        [_sectioned("t1")],
        [Project(id="9", name="Work"), Project(id="7", name="Home")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("alt+v")
        await pilot.pause()
        await pilot.press("2")  # Home
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert repo.moves == [(TaskId("t1"), "7", None)]


@pytest.mark.anyio
async def test_the_editor_nests_an_edited_task_and_skips_a_plain_move() -> None:
    repo = FakeRepository(
        [_sectioned("t1"), _sectioned("t2")],
        [Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")  # editing t1
        await pilot.pause()
        await pilot.press("alt+n")
        await pilot.pause()
        await pilot.press("2")  # 1 is top level, so this is t2
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        # the re-parent carries the project, so no separate move goes out
        assert repo.parents == [(TaskId("t1"), "t2")]
        assert repo.moves == []


@pytest.mark.anyio
async def test_the_editor_cannot_nest_a_task_under_itself() -> None:
    repo = FakeRepository([_sectioned("t1")], [Project(id="9", name="Work")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("alt+n")
        await pilot.pause()

        assert isinstance(app.screen, ParentPickerScreen)
        options = app.screen.query_one(OptionList).option_count
        assert options == 1  # the top-level entry alone


@pytest.mark.anyio
async def test_lifting_a_subtask_out_keeps_the_project_the_editor_picked() -> None:
    """A plain move is what un-parents a task, so the move has to carry the
    project the editor was left holding, not the one the subtask came from."""
    parent = Task(
        id=TaskId("p1"), content="p1", priority=Priority.P4, due=None, project_id="9"
    )
    child = Task(
        id=TaskId("c1"),
        content="c1",
        priority=Priority.P4,
        due=None,
        project_id="9",
        parent_id="p1",
    )
    repo = FakeRepository(
        [parent, child], [Project(id="9", name="Work"), Project(id="7", name="Home")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # expand p1 to reach its subtask
        await pilot.press("down")
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("alt+v")
        await pilot.pause()
        await pilot.press("2")  # Home, which also lifts it out of p1
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert repo.moves == [(TaskId("c1"), "7", None)]
        assert repo.parents == []


@pytest.mark.anyio
async def test_the_editor_registers_a_label_todoist_does_not_know_yet() -> None:
    repo = FakeRepository([_sectioned("t1")], [Project(id="9", name="Work")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("alt+l")
        await pilot.pause()
        await _type(pilot, "new")
        await pilot.press("space", "enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert repo.label_edits == [(TaskId("t1"), ("new",), ("new",))]


@pytest.mark.anyio
async def test_the_editor_sets_the_priority_of_an_edited_task() -> None:
    repo = FakeRepository([_sectioned("t1")], [Project(id="9", name="Work")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("alt+3")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert repo.priorities == [(TaskId("t1"), Priority.P3)]


@pytest.mark.anyio
async def test_the_editor_hangs_a_reminder_off_the_task_it_creates() -> None:
    repo = FakeRepository([], [Project(id="220", name="Inbox", is_inbox=True)])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "new")
        await pilot.press("alt+t")
        await pilot.pause()
        await pilot.press("t")  # today, so a relative reminder is allowed…
        await pilot.pause()
        await pilot.press("alt+t")
        await pilot.pause()
        await pilot.press("0", "9", "0", "0", "enter")  # …once it has a time
        await pilot.pause()
        await pilot.press("alt+m")
        await pilot.pause()
        await pilot.press("a", "r", "h")  # add, relative, 1 hour before
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        plan = repo.applied[0]
        assert len(plan.reminders) == 1
        assert plan.reminders[0].item_ref == plan.tasks[0].temp_id
        assert plan.reminders[0].reminder.minute_offset == 60


@pytest.mark.anyio
async def test_the_editor_adds_and_drops_reminders_on_an_edited_task() -> None:
    task = Task(
        id=TaskId("t1"),
        content="t1",
        priority=Priority.P4,
        due=Due(date=_TODAY, time=datetime.time(9, 0)),
        project_id="220",
    )
    gone = Reminder("r1", "t1", "relative", minute_offset=0)
    repo = FakeRepository([task], [], reminders=[gone])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("alt+m")
        await pilot.pause()
        await pilot.press("d")  # drops the one it had
        await pilot.pause()
        await pilot.press("alt+m")
        await pilot.pause()
        await pilot.press("a", "r", "h")  # adds one an hour before
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert repo.deleted_reminders == ["r1"]
        assert [(r.item_id, r.minute_offset) for r in repo.added_reminders] == [
            ("t1", 60)
        ]


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
        await settled(app)
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
        await settled(app)

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
        await settled(app)
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
        await settled(app)
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


def test_every_forwarded_card_key_matches_a_list_binding() -> None:
    """The card names app actions by hand, so nothing stops the two drifting
    apart but this. `a` is a deliberate alias for the list's `A`."""
    listed = list(map(as_binding, TodoistApp.BINDINGS))
    bound = {b.action: b.key.split(",") for b in listed}
    described = {b.action: b.description for b in listed}

    for key, action in FORWARDED.items():
        assert action in bound, f"{key} names {action}, which no list binding runs"
        assert key in bound[action] or key == "a"
        # the card's help names actions by their list description
        assert described[action], f"{key} names {action}, which has no description"


def test_every_editor_chord_matches_the_list_key_for_that_attribute() -> None:
    """The editor's chords are the list's keys held with alt, so a rebinding on
    one side has to move the other. Labels are the one exception: the list
    reaches them by `@`, and a remapper between here and the terminal can eat
    the shift that needs, so the editor spells them `alt+l`."""
    listed = {
        key for b in map(as_binding, TodoistApp.BINDINGS) for key in b.key.split(",")
    }

    for binding in map(as_binding, TaskEditScreen.BINDINGS):
        for key in binding.key.split(","):
            if not key.startswith("alt+"):
                continue  # ctrl+s / escape are the editor's own
            bare = key.removeprefix("alt+")
            assert bare in listed or key == "alt+l", (
                f"{key} has no list binding on {bare}"
            )


def _card(app: TodoistApp) -> str:
    """What the open detail card is showing."""
    return str(app.screen.query_one("#detail", Static).render())


@pytest.mark.anyio
async def test_v_in_the_detail_card_moves_the_open_task_and_reopens_it() -> None:
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        assert isinstance(app.screen, ProjectPickerScreen)
        await pilot.press("w", "o")  # narrow to "Work"
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

        assert repo.moves == [(TaskId("t1"), "9", None)]
        assert isinstance(app.screen, TaskDetailScreen)
        assert "Work" in _card(app)  # the card came back showing the move


@pytest.mark.anyio
async def test_a_priority_digit_in_the_detail_card_reopens_it_at_once() -> None:
    repo = FakeRepository([_row("t1")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("3")
        await settled(app)
        await pilot.pause()

        assert repo.priorities == [(TaskId("t1"), Priority.P3)]
        assert isinstance(app.screen, TaskDetailScreen)
        assert "P3" in _card(app)


@pytest.mark.anyio
async def test_completing_from_the_detail_card_lands_in_the_list() -> None:
    repo = FakeRepository([_row("t1")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("e")
        await settled(app)
        await pilot.pause()

        assert repo.completed == [TaskId("t1")]
        # the task is gone, so there is no card to come back to
        assert not [s for s in app.screen_stack if isinstance(s, TaskDetailScreen)]


@pytest.mark.anyio
async def test_a_card_action_ignores_a_selection_made_in_the_list() -> None:
    repo = FakeRepository(
        [_row("A"), _row("B"), _row("C")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("x", "x")  # select A and B, cursor lands on C
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("3")
        await settled(app)
        await pilot.pause()

        assert repo.priorities == [(TaskId("C"), Priority.P3)]


class BoomingCompleteApp(TodoistApp):
    def action_complete(self) -> None:
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_an_action_that_blows_up_still_releases_the_card_scope() -> None:
    """The card aims actions at the task it holds. A scope left behind by a
    failed action would silently aim every later list action there too."""
    repo = FakeRepository([_row("A"), _row("B")], [Project(id="220", name="Errands")])
    app = BoomingCompleteApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        # what the card does when it dismisses asking for an action, minus the
        # worker: run_test would turn the worker's crash into a test failure
        app._detail_scope = "A"  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(RuntimeError):
            await app._act_from_detail("complete")  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()

        await pilot.press("escape")  # the card came back; close it
        await pilot.pause()
        await pilot.press("j")  # cursor down to B
        await pilot.press("3")
        await settled(app)
        await pilot.pause()

        assert repo.priorities == [(TaskId("B"), Priority.P3)]


@pytest.mark.anyio
async def test_a_card_action_that_chains_a_modal_waits_for_the_inner_one() -> None:
    """Reminders hands off to the schedule picker. The card must not slide back
    in under the second modal."""
    repo = FakeRepository([_row("t1")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("R")
        await pilot.pause()
        assert isinstance(app.screen, RemindersScreen)
        await pilot.press("a")  # add
        await pilot.press("a")  # …at an absolute time: hands off to the date picker
        await pilot.pause()

        assert isinstance(app.screen, ScheduleScreen)  # not the card
        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app.screen, TaskDetailScreen)  # only now


@pytest.mark.anyio
async def test_cancelling_a_card_action_returns_to_the_card_unchanged() -> None:
    repo = FakeRepository(
        [_row("t1", "220")],
        [Project(id="220", name="Errands"), Project(id="9", name="Work")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert repo.moves == []
        assert isinstance(app.screen, TaskDetailScreen)


@pytest.mark.anyio
async def test_shift_v_from_the_card_reopens_it_under_the_new_parent() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("p", "a", "r")
        await pilot.press("down")
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

        assert repo.parents == [(TaskId("kid"), "parent")]
        assert isinstance(app.screen, TaskDetailScreen)


def _sectioned(content: str, section_id: str | None = None) -> Task:
    return Task(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=Due(date=_TODAY),
        project_id="9",
        section_id=section_id,
    )


def _added(repo: FakeRepository) -> NewTask:
    assert len(repo.applied) == 1
    plan = repo.applied[0]
    assert len(plan.tasks) == 1
    return plan.tasks[0]


async def _type(pilot: Pilot[None], text: str) -> None:
    for character in text:
        await pilot.press(character)


@pytest.mark.anyio
async def test_a_opens_an_empty_editor() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        assert isinstance(app.screen, TaskEditScreen)
        assert app.screen.query_one(Input).value == ""
        assert app.screen.query_one(TextArea).text == ""


@pytest.mark.anyio
async def test_a_adds_the_task_beside_the_cursor_row() -> None:
    repo = FakeRepository(
        [_sectioned("t1", section_id="s1")],
        [
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
        ],
        sections=[Section(id="s1", project_id="9", name="Now", order=1)],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "new")
        await pilot.press("tab")
        await _type(pilot, "why")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        task = _added(repo)
        assert (task.content, task.description) == ("new", "why")
        assert (task.project_ref, task.section_ref) == ("9", "s1")
        assert task.parent_ref is None


@pytest.mark.anyio
async def test_a_in_today_gives_the_new_task_todays_date() -> None:
    repo = FakeRepository([_noted("t1")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "new")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert _added(repo).due == Due(date=_TODAY)


@pytest.mark.anyio
async def test_a_on_an_empty_view_falls_back_to_the_inbox() -> None:
    repo = FakeRepository([], [Project(id="220", name="Eingang", is_inbox=True)])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "new")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert _added(repo).project_ref == "220"


@pytest.mark.anyio
async def test_shift_a_adds_a_subtask_under_the_cursor_task() -> None:
    repo = FakeRepository(
        [_sectioned("t1", section_id="s1")],
        [
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
        ],
        sections=[Section(id="s1", project_id="9", name="Now", order=1)],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("A")
        await pilot.pause()
        await _type(pilot, "step")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        task = _added(repo)
        assert (task.content, task.parent_ref) == ("step", "t1")
        assert task.section_ref is None  # inherited from the parent
        assert task.due is None  # a subtask does not take the view's date


@pytest.mark.anyio
async def test_a_subtask_unfolds_its_parent_so_it_will_be_seen() -> None:
    parent = _row("p1")
    repo = FakeRepository([parent], [], pool=[_row("c1", parent_id="p1")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("h")  # fold the parent away
        await pilot.pause()
        assert _content_col(app.query_one(TaskTable)) == ["▸ p1"]

        await pilot.press("A")
        await pilot.pause()
        await _type(pilot, "c2")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        shown = _content_col(app.query_one(TaskTable))
        assert shown[0] == "▾ p1"  # unfolded, so the new subtask is in sight
        assert sorted(shown[1:]) == ["  c1", "  c2"]


@pytest.mark.anyio
async def test_a_on_the_detail_card_adds_a_subtask_of_the_open_task() -> None:
    repo = FakeRepository([_noted("t1", "a note")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        assert isinstance(app.screen, TaskEditScreen)
        await _type(pilot, "step")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert _added(repo).parent_ref == "t1"
        assert isinstance(app.screen, TaskDetailScreen)  # back on the parent's card


@pytest.mark.anyio
async def test_cancelling_the_add_editor_creates_nothing() -> None:
    repo = FakeRepository([_noted("t1")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "new")
        await pilot.press("escape")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert repo.applied == []


@pytest.mark.anyio
async def test_a_numbered_row_moves_the_task_straight_from_the_picker() -> None:
    repo = FakeRepository([_row("t1", "220"), _unmoved()], _MOVE_PROJECTS)
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("2")  # 1 Errands, 2 Work
        await settled(app)
        await pilot.pause()

        assert repo.moves == [(TaskId("t1"), "9", None)]
        assert str(_cell(app.query_one(DataTable[object]), 0, "Project")) == "Work"


@pytest.mark.anyio
async def test_a_numbered_row_nests_the_task_under_that_parent() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")  # cursor on "kid"
        await pilot.pause()
        await pilot.press("2")  # 1 un-parents, 2 is "parent", the only candidate
        await settled(app)
        await pilot.pause()

        assert repo.parents == [(TaskId("kid"), "parent")]


@pytest.mark.anyio
async def test_the_arrange_overlay_scrolls_on_a_short_terminal() -> None:
    """Its field list is longer than a short terminal, and a field nobody can
    see is a field nobody can group by."""
    app = TodoistApp(FakeRepository([_row("a")], []), clock=FakeClock(_TODAY))

    async with app.run_test(size=(80, 8)) as pilot:
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()

        body = app.screen.query_one(ScrollBody)
        assert body.region.bottom <= 8
        assert body.max_scroll_y > 0

        await pilot.press("pagedown")
        await pilot.pause()
        assert body.scroll_y > 0


@pytest.mark.anyio
async def test_a_wide_terminal_gets_a_centred_column_not_a_banner() -> None:
    """Past ~120 cells the eye loses the line, and the last column's stretch
    turns into a gap — so the body caps and sits in the middle."""
    app = TodoistApp(FakeRepository([_row("Buy milk")], []), clock=FakeClock(_TODAY))

    async with app.run_test(size=(200, 24)) as pilot:
        await pilot.pause()

        for widget in (app.query_one(StatusBand), app.query_one(TaskTable)):
            assert widget.region.width == 120
            assert widget.region.x == (200 - 120) // 2


@pytest.mark.anyio
async def test_a_terminal_under_the_cap_keeps_every_cell() -> None:
    app = TodoistApp(FakeRepository([_row("Buy milk")], []), clock=FakeClock(_TODAY))

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        table = app.query_one(TaskTable)
        assert (table.region.x, table.region.width) == (0, 80)


@pytest.mark.anyio
async def test_one_project_across_the_view_moves_from_column_to_band() -> None:
    """A column repeating the same word on every row says nothing about any of
    them — but the view still has to say which project it is."""
    repo = FakeRepository([_row("a"), _row("b")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)

        assert _cell(app.query_one(TaskTable), 0, "PROJECT") is None
        assert _status(app).startswith("Today · 2 task(s) · Errands")


@pytest.mark.anyio
async def test_projects_that_differ_keep_their_column() -> None:
    app = TodoistApp(_two_project_repo(), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)

        assert _cell(app.query_one(TaskTable), 0, "PROJECT") is not None
        assert "Work" not in _status(app)


@pytest.mark.anyio
async def test_a_project_view_does_not_repeat_its_own_name() -> None:
    repo = FakeRepository([_row("a")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "Errands")
        await settled(app)

        assert _cell(app.query_one(TaskTable), 0, "PROJECT") is None
        assert _status(app).startswith("Errands · 1 task(s)")
        assert _status(app).count("Errands") == 1


@pytest.mark.anyio
async def test_nesting_a_task_clears_its_due_date() -> None:
    """A dated subtask still shows on its own in the phone app's dated views."""
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("p", "a", "r")
        await pilot.press("down")
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

        assert repo.parents == [(TaskId("kid"), "parent")]
        assert repo.dues == [(TaskId("kid"), None)]
        assert str(_cell(app.query_one(TaskTable), 1, "DUE")) == ""


@pytest.mark.anyio
async def test_nesting_clears_the_due_date_of_every_selected_dated_task() -> None:
    dateless = replace(_row("kid2"), due=None)
    repo = FakeRepository(
        [_row("kid1"), dateless, _row("parent")],
        [Project(id="220", name="Errands")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await open_view(pilot, "Errands")  # Today would hide the dateless task
        await settled(app)
        await pilot.pause()
        await pilot.press("x", "x")  # select both kids: each mark moves on a row
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("2")  # the only candidate left is the parent
        await settled(app)
        await pilot.pause()

        assert repo.parents == [(TaskId("kid1"), "parent"), (TaskId("kid2"), "parent")]
        assert repo.dues == [(TaskId("kid1"), None)]  # the dateless one is left alone


@pytest.mark.anyio
async def test_the_picker_toggle_nests_without_touching_the_due_date() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.press("p", "a", "r")
        await pilot.press("down")
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()

        assert repo.parents == [(TaskId("kid"), "parent")]
        assert repo.dues == []


@pytest.mark.anyio
async def test_un_parenting_keeps_the_due_date() -> None:
    """A top-level task without a date shows in no dated view at all."""
    repo = FakeRepository(
        [_row("parent"), _row("kid", parent_id="parent")],
        [Project(id="220", name="Errands")],
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("enter")  # top level
        await settled(app)
        await pilot.pause()

        assert repo.moves == [(TaskId("kid"), "220", None)]
        assert repo.dues == []


@pytest.mark.anyio
async def test_undo_brings_a_cleared_due_date_back_with_the_task() -> None:
    repo = FakeRepository(
        [_row("kid"), _row("parent")], [Project(id="220", name="Errands")]
    )
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.press("p", "a", "r")
        await pilot.press("down")
        await pilot.press("enter")
        await settled(app)
        await pilot.pause()
        await pilot.press("z")
        await settled(app)
        await pilot.pause()

        was = _row("kid").due
        assert repo.dues == [(TaskId("kid"), None), (TaskId("kid"), was)]
        assert repo.moves == [(TaskId("kid"), "220", None)]  # lifted back out
        assert str(_cell(app.query_one(TaskTable), 0, "DUE")) != ""


@pytest.mark.anyio
async def test_scheduling_a_due_time_adds_the_default_reminder() -> None:
    task = Task(
        id=TaskId("A"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 28)),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("0", "9", "3", "0", "enter")
        await settled(app)
        await pilot.pause()

        assert repo.dues == [
            (
                TaskId("A"),
                Due(date=datetime.date(2026, 7, 28), time=datetime.time(9, 30)),
            )
        ]
        assert [(r.item_id, r.type, r.minute_offset) for r in repo.added_reminders] == [
            ("A", "relative", 0)
        ]
        # a relative reminder needs the due time to be on the server already
        assert repo.log == ["due", "reminder"]


@pytest.mark.anyio
async def test_scheduling_a_task_that_already_reminds_adds_no_default() -> None:
    existing = Reminder(id="r1", item_id="A", type="relative", minute_offset=30)
    repo = FakeRepository([_timed("A")], [], reminders=[existing])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("0", "9", "3", "0", "enter")
        await settled(app)
        await pilot.pause()

        assert repo.added_reminders == []


@pytest.mark.anyio
async def test_moving_a_timed_task_to_another_time_still_earns_the_default() -> None:
    """What counts is that the task now has a time and nothing reminds about it —
    a task walked from one time to the next would otherwise stay silent."""
    repo = FakeRepository([_timed("A")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("1", "1", "0", "0", "enter")
        await settled(app)
        await pilot.pause()

        assert [(r.item_id, r.type, r.minute_offset) for r in repo.added_reminders] == [
            ("A", "relative", 0)
        ]


@pytest.mark.anyio
async def test_an_all_day_reschedule_adds_no_reminder() -> None:
    task = Task(
        id=TaskId("A"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 28)),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("m")
        await settled(app)
        await pilot.pause()

        assert repo.added_reminders == []


@pytest.mark.anyio
async def test_a_typed_due_phrase_naming_a_time_earns_the_default_reminder() -> None:
    """Todoist parses the phrase, so only the due it lands on says whether a
    reminder is due — the phrase itself never did."""
    repo = FakeRepository([_row("Buy milk")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("s")  # type the due instead of picking it
        await pilot.pause()
        await pilot.press("1", "0", "colon", "0", "0", "enter")
        await settled(app)
        await pilot.pause()

        assert repo.dues == [(TaskId("Buy milk"), DueText("10:00"))]
        assert [(r.item_id, r.type, r.minute_offset) for r in repo.added_reminders] == [
            ("Buy milk", "relative", 0)
        ]
        assert repo.log == ["due", "reminder"]


@pytest.mark.anyio
async def test_a_typed_due_phrase_landing_all_day_earns_no_reminder() -> None:
    repo = FakeRepository([_row("Buy milk")], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        await pilot.press(*"tomorrow", "enter")
        await settled(app)
        await pilot.pause()

        assert repo.added_reminders == []


@pytest.mark.anyio
async def test_the_editor_giving_a_due_time_adds_the_default_reminder() -> None:
    task = Task(
        id=TaskId("A"),
        content="Buy milk",
        priority=Priority.P4,
        due=Due(date=datetime.date(2026, 7, 28)),
        project_id="220",
    )
    repo = FakeRepository([task], [Project(id="220", name="Errands")])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("alt+t")
        await pilot.pause()
        await pilot.press("0", "9", "3", "0", "enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await settled(app)
        await pilot.pause()

        assert [(r.item_id, r.type, r.minute_offset) for r in repo.added_reminders] == [
            ("A", "relative", 0)
        ]
        assert repo.log == ["due", "reminder"]


@pytest.mark.anyio
async def test_the_editor_dropping_a_reminder_does_not_re_add_the_default() -> None:
    existing = Reminder(id="r1", item_id="A", type="relative", minute_offset=0)
    repo = FakeRepository([_timed("A")], [], reminders=[existing])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("alt+m")
        await pilot.pause()
        await pilot.press("d")  # delete the only reminder
        await pilot.pause()
        await pilot.press("ctrl+s")
        await settled(app)
        await pilot.pause()

        assert repo.deleted_reminders == ["r1"]
        assert repo.added_reminders == []


def _sub_lines(app: TodoistApp) -> list[str]:
    options = app.screen.query_one(SubtaskList)
    return [
        str(options.get_option_at_index(i).prompt) for i in range(options.option_count)
    ]


async def _write_subtask(pilot: Pilot[None], title: str, *keys: str) -> None:
    """alt+a in the editor, then the subtask's own editor: title, extras, save."""
    await pilot.press("alt+a")
    await pilot.pause()
    await _type(pilot, title)
    for key in keys:
        await pilot.press(key)
        await pilot.pause()
    await pilot.press("ctrl+s")
    await pilot.pause()


def _parented() -> FakeRepository:
    return FakeRepository(
        [_row("p1")], [], pool=[_row("c1", parent_id="p1"), _row("c2", parent_id="p1")]
    )


@pytest.mark.anyio
async def test_a_new_task_and_its_subtasks_are_created_in_one_batch() -> None:
    repo = FakeRepository([], [Project(id="220", name="Inbox", is_inbox=True)])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "Ship release")
        await _write_subtask(pilot, "tag version", "alt+1")
        await _write_subtask(pilot, "push tag")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await settled(app)
        await pilot.pause()

        assert len(repo.applied) == 1
        parent, *children = repo.applied[0].tasks
        assert parent.content == "Ship release"
        assert [(c.content, c.parent_ref) for c in children] == [
            ("tag version", parent.temp_id),
            ("push tag", parent.temp_id),
        ]
        # the subtask's own editor gave it a priority the parent does not carry
        assert (children[0].priority, parent.priority) == (Priority.P1, Priority.P4)


@pytest.mark.anyio
async def test_the_new_subtasks_show_nested_before_the_server_has_them() -> None:
    repo = HeldCreationRepository([], [Project(id="220", name="Inbox", is_inbox=True)])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _type(pilot, "Ship release")
        await _write_subtask(pilot, "tag version")
        await pilot.press("ctrl+s")
        await _settle(pilot)

        assert _content_col(app.query_one(TaskTable)) == [
            "▾ Ship release" + PENDING_MARK,
            "  tag version" + PENDING_MARK,
        ]


@pytest.mark.anyio
async def test_the_editor_lists_the_task_s_own_subtasks() -> None:
    app = TodoistApp(_parented(), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert _sub_lines(app) == ["c1", "c2"]
        assert f"{SUBTASKS_ICON} 2" in _attribute_strip(app)


@pytest.mark.anyio
async def test_editing_a_subtask_in_the_editor_edits_that_task() -> None:
    repo = _parented()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        app.screen.query_one(SubtaskList).focus()
        await pilot.press("ctrl+e")  # the highlighted subtask's own editor
        await pilot.pause()
        app.screen.query_one(Input).value = "c1 renamed"
        await pilot.press("alt+1")  # and every attribute it offers
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press("ctrl+s")  # save the parent
        await settled(app)
        await pilot.pause()

        assert repo.text_edits == [(TaskId("c1"), "c1 renamed", "")]
        assert repo.priorities == [(TaskId("c1"), Priority.P1)]


@pytest.mark.anyio
async def test_marking_a_subtask_done_in_the_editor_completes_it() -> None:
    repo = _parented()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # unfold, so the subtasks are on screen
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        app.screen.query_one(SubtaskList).focus()
        await pilot.press("e")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await settled(app)
        await pilot.pause()

        assert repo.completed == [TaskId("c1")]
        assert _content_col(app.query_one(TaskTable)) == ["▾ p1", "  c2"]


@pytest.mark.anyio
async def test_adding_a_subtask_in_the_editor_hangs_it_off_the_open_task() -> None:
    repo = _parented()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        await _write_subtask(pilot, "c3")
        await pilot.press("ctrl+s")
        await settled(app)
        await pilot.pause()

        task = _added(repo)
        assert (task.content, task.parent_ref) == ("c3", "p1")


@pytest.mark.anyio
async def test_dropping_a_subtask_deletes_it_once_confirmed() -> None:
    repo = _parented()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        app.screen.query_one(SubtaskList).focus()
        await pilot.press("delete")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await settled(app)
        await pilot.pause()

        assert repo.deleted == [TaskId("c1")]


@pytest.mark.anyio
async def test_a_refused_confirmation_deletes_no_subtask() -> None:
    repo = _parented()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # unfold, so the subtasks are on screen
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        app.screen.query_one(SubtaskList).focus()
        await pilot.press("delete")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press("n")
        await settled(app)
        await pilot.pause()

        assert repo.deleted == []
        assert _content_col(app.query_one(TaskTable)) == ["▾ p1", "  c1", "  c2"]


@pytest.mark.anyio
async def test_a_subtask_todoist_has_yet_to_name_is_not_offered_for_editing() -> None:
    """Nothing can be hung off an id only this client knows, so a child still
    being created stays out of the list until its own id arrives."""
    repo = HeldCreationRepository([_row("p1")], [])
    app = TodoistApp(repo, clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("A")  # a subtask whose create is held in flight
        await pilot.pause()
        await _type(pilot, "c1")
        await pilot.press("ctrl+s")
        await _settle(pilot)

        await pilot.press("ctrl+e")  # the parent's editor
        await pilot.pause()

        assert _sub_lines(app) == ["No subtasks — alt+a adds one."]


@pytest.mark.anyio
async def test_the_detail_card_lists_the_open_task_s_subtasks() -> None:
    app = TodoistApp(_parented(), clock=FakeClock(_TODAY))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        shown = str(app.screen.query_one("#detail", Static).render())
        assert "SUBTASKS" in shown
        assert "c1" in shown and "c2" in shown


_EVENT = ActivityEvent(
    id="e1",
    at=datetime.datetime(2026, 7, 28, 9, 15, tzinfo=datetime.UTC),
    kind=EventKind.COMPLETED,
    content="Something that happened",
    task_id="t1",
    project_id="9",
)


@pytest.mark.anyio
async def test_c_opens_the_activity_feed() -> None:
    repo = FakeRepository([], [Project(id="9", name="Work")], events=(_EVENT,))
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        assert isinstance(app.screen, ActivityScreen)
        feed = cast(Content, app.screen.query_one("#activity", Static).render())
        assert "Something that happened" in feed.plain
        assert "#Work" in feed.plain

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ActivityScreen)


@pytest.mark.anyio
async def test_a_failed_activity_load_is_reported_and_stays_put() -> None:
    repo = FailingActivityRepository([], [])
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        assert not isinstance(app.screen, ActivityScreen)
        assert "Failed to load activity" in _status(app)


@pytest.mark.anyio
async def test_the_feed_can_be_reopened_after_it_was_closed() -> None:
    """The re-entrancy guard has to clear, or `c` works exactly once."""
    repo = FakeRepository([], [], events=(_EVENT,))
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        assert isinstance(app.screen, ActivityScreen)


# --- manual reordering ---


def _ordered_repo() -> FakeRepository:
    """A Work project whose section holds three tasks in a deliberate order."""
    return FakeRepository(
        [
            _row("first", "9", section_id="s1", child_order=1),
            _row("second", "9", section_id="s1", child_order=2),
            _row("third", "9", section_id="s1", child_order=3),
        ],
        [Project(id="9", name="Work")],
        sections=[Section(id="s1", project_id="9", name="Planning", order=1)],
    )


async def _open_planning(app: TodoistApp, pilot: Pilot[None]) -> DataTable[object]:
    await pilot.pause()
    await open_view(pilot, "Work")
    await settled(app)
    await pilot.press("L")  # unfold the section so its tasks are on screen
    await pilot.pause()
    return app.query_one(TaskTable)


def _notifications(app: TodoistApp) -> list[str]:
    """Messages the app has raised. Toasts never mount headless, so read the
    collection they would render."""
    return [note.message for note in app._notifications]  # pyright: ignore[reportPrivateUsage]


def _section_titles(table: DataTable[object]) -> list[str]:
    """The section's task titles, past the group header and the nesting indent."""
    return [title.strip() for title in _content_col(table)[1:]]


async def _sorted_by_content() -> InMemoryArrangements:
    store = InMemoryArrangements()
    await store.save(
        "project:9",
        Arrangement(group_by=(Field.SECTION,), sort_by=(SortKey(Field.CONTENT),)),
    )
    return store


@pytest.mark.anyio
async def test_shift_j_swaps_the_task_with_the_one_below() -> None:
    repo = _ordered_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_planning(app, pilot)
        await pilot.press("j")  # off the section header, onto "first"
        await pilot.press("J")
        await pilot.pause()

        assert _section_titles(table) == ["second", "first", "third"]
        # one command, so the two never trade places by halves
        assert repo.reorders == [[(TaskId("first"), 2), (TaskId("second"), 1)]]


@pytest.mark.anyio
async def test_shift_k_swaps_the_task_with_the_one_above() -> None:
    repo = _ordered_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_planning(app, pilot)
        await pilot.press("j", "j")  # onto "second"
        await pilot.press("K")
        await pilot.pause()

        assert _section_titles(table) == ["second", "first", "third"]


@pytest.mark.anyio
async def test_the_cursor_follows_the_moved_task() -> None:
    repo = _ordered_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_planning(app, pilot)
        await pilot.press("j")
        await pilot.press("J")
        await pilot.pause()

        assert _title(table, table.cursor_row).strip() == "first"


@pytest.mark.anyio
async def test_the_last_task_of_a_section_does_not_leave_it() -> None:
    repo = _ordered_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_planning(app, pilot)
        await pilot.press("j", "j", "j")  # onto "third", the last one
        await pilot.press("J")
        await pilot.pause()

        assert _section_titles(table) == ["first", "second", "third"]
        assert repo.reorders == []


@pytest.mark.anyio
async def test_a_refused_move_says_there_is_nothing_to_swap_with() -> None:
    """Silence reads as a broken key."""
    repo = _ordered_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await _open_planning(app, pilot)
        await pilot.press("j", "j", "j")  # onto "third", the last one
        await pilot.press("J")
        await pilot.pause()

        assert any("below" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_a_refused_move_up_says_so_too() -> None:
    repo = _ordered_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await _open_planning(app, pilot)
        await pilot.press("j")  # onto "first"
        await pilot.press("K")
        await pilot.pause()

        assert any("above" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_a_move_that_lands_says_nothing() -> None:
    repo = _ordered_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await _open_planning(app, pilot)
        await pilot.press("j")
        await pilot.press("J")
        await pilot.pause()

        assert _notifications(app) == []


@pytest.mark.anyio
async def test_reordering_under_a_sort_says_to_clear_it() -> None:
    repo = _ordered_repo()
    app = TodoistApp(repo, arrangements=await _sorted_by_content())
    async with app.run_test() as pilot:
        table = await _open_planning(app, pilot)
        await pilot.press("j")
        await pilot.press("J")
        await pilot.pause()

        assert _section_titles(table) == ["first", "second", "third"]
        assert repo.reorders == []
        assert any("sort" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_undo_puts_the_moved_task_back() -> None:
    repo = _ordered_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_planning(app, pilot)
        await pilot.press("j")
        await pilot.press("J")
        await pilot.pause()
        await pilot.press("z")
        await pilot.pause()

        assert _section_titles(table) == ["first", "second", "third"]


@pytest.mark.anyio
async def test_a_move_survives_the_next_sync() -> None:
    """The swap is retired against the server's own order, not reverted by it."""
    repo = _ordered_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_planning(app, pilot)
        await pilot.press("j")
        await pilot.press("J")
        await pilot.pause()
        await settled(app)
        await pilot.press("r")
        await settled(app)
        await pilot.pause()

        assert _section_titles(table) == ["second", "first", "third"]


# --- moving a section ---


def _three_section_repo() -> FakeRepository:
    """A Work project with three sections, the middle one holding no task."""
    return FakeRepository(
        [_row("planned", "9", section_id="s1"), _row("later", "9", section_id="s3")],
        [Project(id="9", name="Work")],
        sections=[
            Section(id="s1", project_id="9", name="Planning", order=1),
            Section(id="s2", project_id="9", name="Waiting", order=2),
            Section(id="s3", project_id="9", name="Backlog", order=3),
        ],
    )


def _headers(table: DataTable[object]) -> list[str]:
    """The section names, in the order their headers sit on screen."""
    return [
        name
        for cell in _content_col(table)
        for name in ("Planning", "Waiting", "Backlog")
        if name in cell
    ]


async def _open_work(app: TodoistApp, pilot: Pilot[None]) -> DataTable[object]:
    await pilot.pause()
    await open_view(pilot, "Work")
    await settled(app)
    await pilot.pause()
    return app.query_one(TaskTable)


@pytest.mark.anyio
async def test_shift_j_swaps_the_section_with_the_one_below() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_work(app, pilot)
        await pilot.press("J")  # the cursor opens on the first header
        await pilot.pause()

        assert _headers(table) == ["Waiting", "Planning", "Backlog"]
        # one command renumbering the whole run, so the sections never trade
        # places by halves and never come out sharing an order
        assert repo.section_reorders == [[("s2", 1), ("s1", 2), ("s3", 3)]]


@pytest.mark.anyio
async def test_a_section_sharing_its_order_with_another_still_moves() -> None:
    """Todoist hands back duplicate `section_order`s; trading two equal values
    would write nothing, so the move renumbers the run from 1."""
    repo = FakeRepository(
        [_row("planned", "9", section_id="s1")],
        [Project(id="9", name="Work")],
        sections=[
            Section(id="s1", project_id="9", name="Planning", order=9),
            Section(id="s2", project_id="9", name="Waiting", order=9),
        ],
    )
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_work(app, pilot)
        await pilot.press("J")
        await pilot.pause()

        assert _headers(table) == ["Waiting", "Planning"]
        assert repo.section_reorders == [[("s2", 1), ("s1", 2)]]


@pytest.mark.anyio
async def test_shift_k_swaps_the_section_with_the_one_above() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_work(app, pilot)
        await pilot.press("j")  # onto the Waiting header
        await pilot.press("K")
        await pilot.pause()

        assert _headers(table) == ["Waiting", "Planning", "Backlog"]


@pytest.mark.anyio
async def test_a_section_holding_no_task_moves_like_any_other() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_work(app, pilot)
        await pilot.press("j")  # onto Waiting, which holds nothing
        await pilot.press("J")
        await pilot.pause()

        assert _headers(table) == ["Planning", "Backlog", "Waiting"]


@pytest.mark.anyio
async def test_the_cursor_follows_the_moved_section() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_work(app, pilot)
        await pilot.press("J")
        await pilot.pause()

        assert "Planning" in _content_col(table)[table.cursor_row]


@pytest.mark.anyio
async def test_the_last_section_says_there_is_nothing_below_it() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_work(app, pilot)
        await pilot.press("j", "j")  # onto Backlog, the last section
        await pilot.press("J")
        await pilot.pause()

        assert _headers(table) == ["Planning", "Waiting", "Backlog"]
        assert repo.section_reorders == []
        assert any("below" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_the_first_section_says_there_is_nothing_above_it() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        app_pilot = await _open_work(app, pilot)
        assert app_pilot is not None
        await pilot.press("K")
        await pilot.pause()

        assert any("above" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_a_section_move_under_a_sort_still_lands() -> None:
    """A sort orders the rows inside a group; it never decides where the headers
    sit, so it must not refuse the move the way a task reorder does."""
    repo = _three_section_repo()
    app = TodoistApp(repo, arrangements=await _sorted_by_content())
    async with app.run_test() as pilot:
        table = await _open_work(app, pilot)
        await pilot.press("J")
        await pilot.pause()

        assert _headers(table) == ["Waiting", "Planning", "Backlog"]
        assert not any("sort" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_a_section_will_not_move_in_a_view_spanning_projects() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("s", "enter")  # Today, grouped by section
        await pilot.pause()
        await settled(app)
        await pilot.pause()
        await pilot.press("J")
        await pilot.pause()

        # section_order is per project; the same name in two projects is one group
        assert repo.section_reorders == []
        assert any("project" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_a_section_nested_under_another_group_will_not_move() -> None:
    repo = _three_section_repo()
    store = InMemoryArrangements()
    await store.save("project:9", Arrangement(group_by=(Field.PRIORITY, Field.SECTION)))
    app = TodoistApp(repo, arrangements=store)
    async with app.run_test() as pilot:
        await _open_work(app, pilot)
        await pilot.press("l")  # unfold the priority group to reach a section header
        await pilot.press("j")
        await pilot.press("J")
        await pilot.pause()

        assert repo.section_reorders == []
        assert any("section" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_a_group_that_is_not_a_section_will_not_move() -> None:
    repo = _three_section_repo()
    store = InMemoryArrangements()
    await store.save("project:9", Arrangement(group_by=(Field.PRIORITY,)))
    app = TodoistApp(repo, arrangements=store)
    async with app.run_test() as pilot:
        await _open_work(app, pilot)
        await pilot.press("J")
        await pilot.pause()

        assert repo.section_reorders == []
        assert any("section" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_undo_puts_the_moved_section_back() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_work(app, pilot)
        await pilot.press("J")
        await pilot.pause()
        await pilot.press("z")
        await pilot.pause()

        assert _headers(table) == ["Planning", "Waiting", "Backlog"]


@pytest.mark.anyio
async def test_a_section_move_survives_the_next_sync() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        table = await _open_work(app, pilot)
        await pilot.press("J")
        await pilot.pause()
        await settled(app)
        await pilot.press("r")
        await settled(app)
        await pilot.pause()

        assert _headers(table) == ["Waiting", "Planning", "Backlog"]


# --- deleting a section from its header ---


@pytest.mark.anyio
async def test_delete_on_a_section_header_removes_that_section() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await _open_work(app, pilot)
        await pilot.press("j")  # onto the Waiting header
        await pilot.press("delete")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await settled(app)
        await pilot.pause()

        assert repo.deleted_sections == ["s2"]


@pytest.mark.anyio
async def test_delete_on_a_section_header_cancelled_deletes_nothing() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await _open_work(app, pilot)
        await pilot.press("delete")
        await pilot.pause()
        await pilot.press("n")
        await settled(app)
        await pilot.pause()

        assert repo.deleted_sections == []


@pytest.mark.anyio
async def test_a_selection_outranks_the_section_header_the_cursor_sits_on() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo)
    async with app.run_test() as pilot:
        await _open_work(app, pilot)
        await pilot.press("l")  # unfold Planning
        await pilot.press("j")  # onto "planned", the task it holds
        await pilot.press("x")  # select it
        await pilot.press("k")  # back onto the Planning header
        await pilot.press("delete")
        await pilot.pause()
        await pilot.press("y")
        await settled(app)
        await pilot.pause()

        assert repo.deleted_sections == []
        assert [str(task_id) for task_id in repo.deleted] == ["planned"]


@pytest.mark.anyio
async def test_a_section_header_in_a_view_spanning_projects_will_not_delete() -> None:
    repo = _three_section_repo()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("s", "enter")  # Today, grouped by section
        await pilot.pause()
        await settled(app)
        await pilot.pause()
        await pilot.press("delete")
        await pilot.pause()

        # the same name in two projects is one header, naming no single section
        assert not isinstance(app.screen, ConfirmScreen)
        assert repo.deleted_sections == []
        assert any("project" in note.lower() for note in _notifications(app))


@pytest.mark.anyio
async def test_a_group_that_is_not_a_section_will_not_delete() -> None:
    repo = _three_section_repo()
    store = InMemoryArrangements()
    await store.save("project:9", Arrangement(group_by=(Field.PRIORITY,)))
    app = TodoistApp(repo, arrangements=store)
    async with app.run_test() as pilot:
        await _open_work(app, pilot)
        await pilot.press("delete")
        await pilot.pause()

        assert not isinstance(app.screen, ConfirmScreen)
        assert repo.deleted_sections == []
        assert any("section" in note.lower() for note in _notifications(app))


# --- manual reordering in a view that spans projects ---


def _cross_project_repo(day_orders: tuple[int, int, int] = (-1, -1, -1)):
    """Three tasks due today in three different projects — no two are siblings."""
    a, b, c = day_orders
    return FakeRepository(
        [
            _row("alpha", "9", day_order=a),
            _row("beta", "10", day_order=b),
            _row("gamma", "11", day_order=c),
        ],
        [
            Project(id="9", name="Work"),
            Project(id="10", name="Home"),
            Project(id="11", name="Errands"),
        ],
    )


def _titles(table: DataTable[object]) -> list[str]:
    return [title.strip() for title in _content_col(table)]


@pytest.mark.anyio
async def test_the_first_move_in_a_day_view_numbers_the_whole_list() -> None:
    """Every task starts unplaced, so trading two values would move nothing."""
    repo = _cross_project_repo()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        table = app.query_one(TaskTable)
        await pilot.press("J")
        await pilot.pause()

        assert _titles(table) == ["beta", "alpha", "gamma"]
        assert repo.day_orders == [
            [(TaskId("beta"), 1), (TaskId("alpha"), 2), (TaskId("gamma"), 3)]
        ]


@pytest.mark.anyio
async def test_a_placed_day_list_only_trades_the_two() -> None:
    repo = _cross_project_repo((1, 2, 3))
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        table = app.query_one(TaskTable)
        await pilot.press("J")
        await pilot.pause()

        assert _titles(table) == ["beta", "alpha", "gamma"]
        assert repo.day_orders == [[(TaskId("alpha"), 2), (TaskId("beta"), 1)]]


@pytest.mark.anyio
async def test_a_day_move_never_touches_child_order() -> None:
    repo = _cross_project_repo()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("J")
        await pilot.pause()

        assert repo.reorders == []


@pytest.mark.anyio
async def test_a_day_move_survives_the_next_sync() -> None:
    repo = _cross_project_repo()
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        table = app.query_one(TaskTable)
        await pilot.press("J")
        await pilot.pause()
        await settled(app)
        await pilot.press("r")
        await settled(app)
        await pilot.pause()

        assert _titles(table) == ["beta", "alpha", "gamma"]


@pytest.mark.anyio
async def test_undo_puts_a_day_move_back() -> None:
    repo = _cross_project_repo((1, 2, 3))
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        table = app.query_one(TaskTable)
        await pilot.press("J")
        await pilot.pause()
        await pilot.press("z")
        await pilot.pause()

        assert _titles(table) == ["alpha", "beta", "gamma"]


@pytest.mark.anyio
async def test_the_last_task_in_a_day_view_says_it_cannot_move() -> None:
    repo = _cross_project_repo((1, 2, 3))
    app = TodoistApp(repo, clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("j", "j")  # onto "gamma", the last one
        await pilot.press("J")
        await pilot.pause()

        assert repo.day_orders == []
        assert any("below" in note.lower() for note in _notifications(app))


_A_COMMENT = Comment(
    id="c1",
    task_id="t1",
    content="ship it",
    posted_at=datetime.datetime(2026, 7, 21, 9, 30, tzinfo=datetime.UTC),
)


@pytest.mark.anyio
async def test_c_opens_the_thread_of_the_task_under_the_cursor() -> None:
    repo = FakeRepository([_noted("t1")], [], comments=(_A_COMMENT,))
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("C")
        await pilot.pause()

        assert isinstance(app.screen, CommentsScreen)
        assert repo.comment_reads == [TaskId("t1")]
        assert "ship it" in str(app.screen.query_one("#comments", Static).content)


@pytest.mark.anyio
async def test_a_thread_that_cannot_be_read_is_reported_not_opened() -> None:
    repo = FailingCommentsRepository([_noted("t1")], [])
    app = TodoistApp(repo)

    async with app.run_test() as pilot:
        await pilot.pause()
        await settled(app)
        await pilot.press("C")
        await pilot.pause()

        assert not isinstance(app.screen, CommentsScreen)
        assert "Failed to load comments" in _status(app)
