import contextlib
import datetime
from dataclasses import replace
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import DataTable, Footer, Static

from todoist_tui.application.complete import complete_task, uncomplete_task
from todoist_tui.application.delete import delete_task
from todoist_tui.application.move_task import move_task
from todoist_tui.application.set_deadline import set_deadline
from todoist_tui.application.set_due import set_due
from todoist_tui.application.set_labels import set_labels
from todoist_tui.application.set_priority import set_priority
from todoist_tui.application.views import (
    INBOX,
    TODAY,
    TaskRow,
    View,
    filter_view,
    load_view,
    project_view,
    query_for_key,
    search_view,
    view_from_key,
)
from todoist_tui.domain.arrange import (
    Arrangement,
    Field,
    GroupHeader,
    RenderRow,
    TaskLine,
    arrange,
)
from todoist_tui.domain.clock import Clock, SystemClock
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.humanize import humanize_date
from todoist_tui.domain.links import LinkOpener, XdgOpenLinkOpener
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import (
    ArrangementStore,
    HomeViewStore,
    TaskRepository,
)
from todoist_tui.domain.schedule import reschedule
from todoist_tui.domain.search import SearchTerm
from todoist_tui.domain.task import TaskId
from todoist_tui.tui.format import (
    format_deadline,
    format_due,
    format_labels,
    priority_dot,
    render_links,
    styled_date,
)
from todoist_tui.tui.screens.arrange import ArrangeScreen, Mode
from todoist_tui.tui.screens.confirm import ConfirmScreen
from todoist_tui.tui.screens.detail import TaskDetailScreen
from todoist_tui.tui.screens.filters import FilterScreen
from todoist_tui.tui.screens.help import HelpScreen
from todoist_tui.tui.screens.labels import LabelsScreen
from todoist_tui.tui.screens.project_list import ProjectListScreen
from todoist_tui.tui.screens.project_picker import MoveTarget, ProjectPickerScreen
from todoist_tui.tui.screens.schedule import DueResult, ScheduleScreen
from todoist_tui.tui.screens.search import SearchScreen

_SYNC_INTERVAL_SECONDS = 60.0  # Todoist has no push; poll incrementally
_INDENT = "  "  # per nesting level, for group headers and their tasks
_HEADER_WIDTH = 56  # target width of a group divider rule


def as_binding(entry: BindingType) -> Binding:
    """Normalize a Textual binding entry (tuple or `Binding`) to a `Binding`."""
    if isinstance(entry, Binding):
        return entry
    key, action, *rest = entry
    return Binding(key, action, rest[0] if rest else "")


def shortcut_rows(*binding_lists: list[BindingType]) -> list[tuple[str, str]]:
    """Flatten Textual binding definitions into (key, description) help rows,
    dropping entries with no description and the help binding itself."""
    rows: list[tuple[str, str]] = []
    for bindings in binding_lists:
        for binding in map(as_binding, bindings):
            if binding.action == "help" or not binding.description:
                continue
            rows.append((binding.key, binding.description))
    return rows


class InMemoryArrangements:
    """Session-only arrangement store (the default when none is injected)."""

    def __init__(self) -> None:
        self._by_key: dict[str, Arrangement] = {}

    async def get(
        self, view_key: str, default: Arrangement | None = None
    ) -> Arrangement:
        stored = self._by_key.get(view_key)
        if stored is not None:
            return stored
        return default if default is not None else Arrangement()

    async def save(self, view_key: str, arrangement: Arrangement) -> None:
        self._by_key[view_key] = arrangement


class InMemoryHome:
    """Session-only home-view store (the default when none is injected)."""

    def __init__(self) -> None:
        self._key: str | None = None

    async def get(self) -> str | None:
        return self._key

    async def save(self, view_key: str) -> None:
        self._key = view_key


class TaskTable(DataTable[object]):
    """DataTable with vim j/k row nav and h/l subtask collapse/expand.

    The cursor skips group headers. h/l don't move the column cursor (the table
    is row-mode); they ask the app to collapse/expand the subtasks of the row
    under the cursor.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "collapse", "Collapse", show=False),
        Binding("l", "expand", "Expand", show=False),
    ]

    class Expand(Message):
        """Reveal the subtasks of the row under the cursor."""

    class Collapse(Message):
        """Hide the subtasks of the row under the cursor, or jump to its parent."""

    def action_cursor_down(self) -> None:
        self._skip_to_task(step=1)

    def action_cursor_up(self) -> None:
        self._skip_to_task(step=-1)

    def action_expand(self) -> None:
        self.post_message(self.Expand())

    def action_collapse(self) -> None:
        self.post_message(self.Collapse())

    def _skip_to_task(self, step: int) -> None:
        target = self._task_row_after(self.cursor_row, step)
        if target is not None:  # None => no task that way: stay put
            self.move_cursor(row=target)

    def _task_row_after(self, start: int, step: int) -> int | None:
        row = start + step
        while 0 <= row < self.row_count:
            if self._is_task_row(row):
                return row
            row += step  # traverse consecutive headers (nested grouping)
        return None

    def _is_task_row(self, row: int) -> bool:
        key = self.coordinate_to_cell_key(Coordinate(row, 0)).row_key
        return _task_id_of(str(key.value)) is not None


class TodoistApp(App[None]):
    """Row-highlighted task table over Today, Inbox, project, and filter views,
    opening on a persisted home view."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("question_mark", "help", "Help"),  # the only footer entry
        Binding("e", "complete", "Complete", show=False),
        Binding("delete", "delete", "Delete", show=False),
        Binding("z", "undo", "Undo", show=False),
        Binding(".", "view_today", "Today", show=False),
        Binding("i", "view_inbox", "Inbox", show=False),
        Binding("f", "view_filters", "Filters", show=False),
        Binding("slash", "search", "Search", show=False),
        Binding("p", "view_project_list", "Projects", show=False),
        Binding("H", "go_home", "Home", show=False),
        Binding("m", "set_home", "Set home", show=False),
        Binding("g", "arrange_group", "Group", show=False),
        Binding("s", "arrange_sort", "Sort", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("t", "set_due", "Due", show=False),
        Binding("d", "set_deadline", "Deadline", show=False),
        Binding("v", "move_task", "Move", show=False),
        Binding("at", "set_labels", "Labels", show=False),
        Binding("enter", "open_detail", "Detail", show=False),
        Binding("1", "set_priority('P1')", "P1", show=False),
        Binding("2", "set_priority('P2')", "P2", show=False),
        Binding("3", "set_priority('P3')", "P3", show=False),
        Binding("4", "set_priority('P4')", "P4", show=False),
    ]
    SYNC_INTERVAL: ClassVar[float] = _SYNC_INTERVAL_SECONDS

    def __init__(
        self,
        repo: TaskRepository,
        arrangements: ArrangementStore | None = None,
        clock: Clock | None = None,
        link_opener: LinkOpener | None = None,
        home: HomeViewStore | None = None,
    ) -> None:
        super().__init__()
        self._repo = repo
        self._arrangements = arrangements or InMemoryArrangements()
        self._home = home or InMemoryHome()
        self._clock = clock or SystemClock()
        self._link_opener = link_opener or XdgOpenLinkOpener()
        self._arrangement = Arrangement()  # current view's group/sort
        self._rows: list[TaskRow] = []  # last loaded rows, for local re-arrange
        self._expanded: set[TaskId] = set()  # tasks whose subtasks are shown
        self._view = TODAY
        self._syncing = False
        self._status_base = ""
        self._last_undo: tuple[TaskId, TaskRow] | None = None
        # tasks closed locally, kept hidden across reloads until the server's
        # snapshot reflects the change (gone, or a recurring task's new due)
        self._pending_close: dict[str, Due | None] = {}
        # fields edited locally, kept applied across reloads until the server
        # snapshot reflects them — so a lagging sync can't revert an optimistic edit
        self._pending_edits: dict[str, dict[str, object]] = {}
        self._picking_filter = False  # guards against stacking filter pickers
        self._picking_project = False  # guards against stacking project pickers
        self._picking_project_list = False  # guards against stacking the project list
        self._picking_labels = False  # guards against stacking the labels editor
        # the server query of the open view — a saved filter's, or a search's —
        # re-run on every sync so that view stays live
        self._active_server_query: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("Loading…", id="status")
        yield TaskTable()
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one(TaskTable)
        table.cursor_type = "row"
        table.cell_padding = 2  # breathing room between columns; _render owns columns
        self._view, self._active_server_query = await self._resolve_home()
        await self._reload(self._view)  # instant: served from cache when present
        self._sync_now()  # for a filter home, this also refreshes it live
        self.set_interval(self.SYNC_INTERVAL, self._sync_now)

    @work(exclusive=True, group="reload")
    async def _sync_now(self) -> None:
        self._set_syncing(True)
        try:
            await self._repo.refresh()
            if self._active_server_query is not None:  # keep the open filter live
                await self._repo.refresh_filtered(self._active_server_query)
            await self._reload(self._view)
        except Exception:  # offline or sync failed: keep the cached view
            pass
        finally:  # also runs on worker cancellation, so ⟳ never sticks
            self._set_syncing(False)

    def action_refresh(self) -> None:
        self._sync_now()

    def action_arrange_group(self) -> None:
        self._open_arrange("group")

    def action_arrange_sort(self) -> None:
        self._open_arrange("sort")

    def _open_arrange(self, mode: Mode) -> None:
        self.push_screen(ArrangeScreen(self._arrangement, mode), self._on_arranged)

    def _on_arranged(self, arrangement: Arrangement | None) -> None:
        if arrangement is None:  # transient cancelled
            return
        self.run_worker(self._apply_arrangement(self._view, arrangement))

    async def _apply_arrangement(self, view: View, arrangement: Arrangement) -> None:
        await self._arrangements.save(view.key, arrangement)
        if self._view is view:  # user may have switched away before this ran
            await self._reload(view)  # picks the saved arrangement back up

    async def action_set_home(self) -> None:
        await self._home.save(self._view.key)
        self._set_status(f"Home set to {self._view.title}")

    async def action_go_home(self) -> None:
        view, query = await self._resolve_home()
        self._active_server_query = query
        if query is not None:  # a filter home: revalidate it live like the picker
            self._view = view
            self._open_filter(view, query)
        else:
            self._switch_to(view)

    async def _resolve_home(self) -> tuple[View, str | None]:
        """The startup/home view and its server query (None unless a filter or a
        search), falling back to Today when unset or its target no longer exists."""
        key = await self._home.get()
        if key is None:
            return TODAY, None
        try:
            projects = await self._repo.projects()
            filters = await self._repo.filters()
        except Exception:  # offline before the first sync: open Today
            return TODAY, None
        view = view_from_key(key, projects, filters)
        if view is None:  # the saved project/filter is gone
            return TODAY, None
        return view, query_for_key(key, filters)

    def action_view_today(self) -> None:
        self._active_server_query = None
        self._switch_to(TODAY)

    def action_view_inbox(self) -> None:
        self._active_server_query = None
        self._switch_to(INBOX)

    async def action_view_filters(self) -> None:
        if self._picking_filter:  # already loading or picker already open
            return
        self._picking_filter = True
        try:
            filters = await self._repo.filters()
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load filters: {error}")
            self._picking_filter = False
            return
        if not filters:
            self._set_status("No saved filters")
            self._picking_filter = False
            return
        self.push_screen(FilterScreen(filters), self._on_filter_chosen)

    def _on_filter_chosen(self, chosen: Filter | None) -> None:
        self._picking_filter = False
        if chosen is None:  # picker was cancelled
            return
        self._active_server_query = chosen.query
        self._view = filter_view(chosen)
        self._open_filter(self._view, chosen.query)

    def action_search(self) -> None:
        screen = SearchScreen(self._search, self._clock.today())
        self.push_screen(screen, self._on_search_term)

    async def _search(self, term: SearchTerm) -> list[TaskRow]:
        # cache-first, so promoting the term paints from what the preview loaded
        return await load_view(self._repo, search_view(term))

    def _on_search_term(self, term: SearchTerm | None) -> None:
        if term is None:  # search was cancelled
            return
        self._active_server_query = term.query
        self._view = search_view(term)
        self._open_filter(self._view, term.query)

    async def action_view_project_list(self) -> None:
        if self._picking_project_list:  # already loading or picker already open
            return
        self._picking_project_list = True
        try:
            projects = await self._repo.projects()
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load projects: {error}")
            self._picking_project_list = False
            return
        if not any(not p.is_inbox for p in projects):
            self._set_status("No projects")
            self._picking_project_list = False
            return
        self.push_screen(ProjectListScreen(projects), self._on_project_list_chosen)

    def _on_project_list_chosen(self, chosen: Project | None) -> None:
        self._picking_project_list = False
        if chosen is None:  # picker was cancelled
            return
        self._active_server_query = None  # a project view isn't a saved filter
        self._switch_to(project_view(chosen))

    @work(exclusive=True, group="reload")
    async def _open_filter(self, view: View, query: str) -> None:
        await self._reload(view)  # instant when the query is cached
        self._set_syncing(True)
        try:
            await self._repo.refresh_filtered(query)  # revalidate live
            if self._view is view:  # user may have switched away meanwhile
                await self._reload(view)  # cache now fresh
        except Exception:  # offline: keep the cached view
            pass
        finally:  # also runs on worker cancellation, so ⟳ never sticks
            self._set_syncing(False)

    def _switch_to(self, view: View) -> None:
        if view is self._view:
            return
        self._view = view
        self.run_worker(self._reload(view), exclusive=True, group="reload")

    def action_complete(self) -> None:
        table = self.query_one(TaskTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        task_id = _task_id_of(str(row_key.value))
        if task_id is None:  # cursor is on a group header: nothing to complete
            return
        cursor_row = table.cursor_row  # follow the highlight down to the neighbour
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        self._pending_close[task_id] = row.due if row is not None else None
        # optimistic: drop it from the model and repaint, sync in the background
        self._rows = [r for r in self._rows if str(r.id) != task_id]
        self._render(self._arrange(self._rows), self._view)
        self._focus_task_at(table, cursor_row)
        self._complete(TaskId(task_id), row)

    @work
    async def _complete(self, task_id: TaskId, row: TaskRow | None) -> None:
        try:
            await complete_task(self._repo, task_id)
        except Exception as error:  # command rejected: unhide it, resync, report
            self._pending_close.pop(str(task_id), None)
            await self._reload(self._view)
            self._set_status(f"Failed to complete task: {error}")
            return
        if row is not None:  # only a confirmed close of a known row is undoable
            self._last_undo = (task_id, row)
        self._sync_now()  # pull server delta so the view reflects the close

    def action_undo(self) -> None:
        if self._last_undo is None:
            return
        task_id, row = self._last_undo
        self._last_undo = None  # single-level: each undo reverses one close
        self._pending_close.pop(str(task_id), None)  # reopened: no longer filter it out
        # restore into the model and repaint; columns/placement rebuild naturally
        if all(str(r.id) != str(task_id) for r in self._rows):
            self._rows = [*self._rows, row]
        self._render(self._arrange(self._rows), self._view)
        self._uncomplete(task_id)

    @work
    async def _uncomplete(self, task_id: TaskId) -> None:
        try:
            await uncomplete_task(self._repo, task_id)
        except Exception as error:  # command rejected: resync, then report
            await self._reload(self._view)
            self._set_status(f"Failed to undo: {error}")
            return
        self._sync_now()  # pull server delta so the view reflects the reopen

    def action_delete(self) -> None:
        table = self.query_one(TaskTable)
        task_id = self._cursor_task_id(table)
        if task_id is None:  # empty table or cursor on a group header
            return
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        if row is None:
            return
        cursor_row = table.cursor_row  # follow the highlight down after the delete
        self.push_screen(
            ConfirmScreen(f"Delete “{row.content}”?"),
            lambda confirmed: self._on_delete_confirmed(
                TaskId(task_id), row.due, cursor_row, confirmed
            ),
        )

    def _on_delete_confirmed(
        self, task_id: TaskId, due: Due | None, cursor_row: int, confirmed: bool | None
    ) -> None:
        if not confirmed:  # dialog cancelled: leave the task untouched
            return
        table = self.query_one(TaskTable)
        # optimistic: hide it (delete is permanent — no undo) and sync in the bg;
        # keep it hidden across reloads until the server confirms it's gone
        self._pending_close[str(task_id)] = due
        self._rows = [r for r in self._rows if str(r.id) != str(task_id)]
        self._render(self._arrange(self._rows), self._view)
        self._focus_task_at(table, cursor_row)
        self._delete(task_id)

    @work
    async def _delete(self, task_id: TaskId) -> None:
        try:
            await delete_task(self._repo, task_id)
        except Exception as error:  # command rejected: unhide it, resync, report
            self._pending_close.pop(str(task_id), None)
            await self._reload(self._view)
            self._set_status(f"Failed to delete task: {error}")
            return
        self._sync_now()  # pull server delta so the view reflects the delete

    def action_set_priority(self, name: str) -> None:
        table = self.query_one(TaskTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        task_id = _task_id_of(str(row_key.value))
        if task_id is None:  # cursor is on a group header: nothing to set
            return
        priority = Priority[name]
        self._record_edit(task_id, priority=priority)
        # optimistic: re-arrange now so the task jumps to its new priority group
        # (and its dot repaints), then sync in the background
        self._rows = [
            replace(row, priority=priority) if str(row.id) == task_id else row
            for row in self._rows
        ]
        self._render(self._arrange(self._rows), self._view)
        self._set_priority(TaskId(task_id), priority)

    @work
    async def _set_priority(self, task_id: TaskId, priority: Priority) -> None:
        try:
            await set_priority(self._repo, task_id, priority)
        except Exception as error:  # command rejected: resync, then report
            self._forget_edit(str(task_id), "priority")
            await self._reload(self._view)
            self._set_status(f"Failed to set priority: {error}")
            return
        self._sync_now()  # pull server delta; re-arranges if grouped/sorted by priority

    def action_set_due(self) -> None:
        table = self.query_one(TaskTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        task_id = _task_id_of(str(row_key.value))
        if task_id is None:  # cursor is on a group header: nothing to schedule
            return
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        if row is None:
            return
        current = row.due.date if row.due is not None else None
        current_time = row.due.time if row.due is not None else None
        self.push_screen(
            ScheduleScreen(self._clock.today(), current, current_time),
            lambda result: self._on_scheduled(TaskId(task_id), result),
        )

    def action_set_deadline(self) -> None:
        table = self.query_one(TaskTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        task_id = _task_id_of(str(row_key.value))
        if task_id is None:  # cursor is on a group header: nothing to set
            return
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        if row is None:
            return
        current = row.deadline.date if row.deadline is not None else None
        self.push_screen(
            ScheduleScreen(self._clock.today(), current, kind="deadline"),
            lambda result: self._on_deadline(TaskId(task_id), result),
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # DataTable consumes Enter for row selection before the app binding can
        # fire, so open the detail view off its message instead (the binding
        # stays for the footer hint).
        self.action_open_detail()

    def action_help(self) -> None:
        if isinstance(self.screen, HelpScreen):  # already open
            return
        rows = shortcut_rows(TodoistApp.BINDINGS, TaskTable.BINDINGS)
        self.push_screen(HelpScreen(rows))

    def action_open_detail(self) -> None:
        table = self.query_one(TaskTable)
        task_id = self._cursor_task_id(table)
        if task_id is None:  # empty table or cursor on a group header
            return
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        if row is None:
            return
        self.push_screen(TaskDetailScreen(row, self._link_opener, self._clock.today()))

    def _on_scheduled(self, task_id: TaskId, result: DueResult | None) -> None:
        if result is None:  # picker was cancelled
            return
        # graft the picked date onto the existing rule so a recurring task keeps
        # recurring (moves its next occurrence) instead of losing the rule
        original = next(
            (row.due for row in self._rows if str(row.id) == str(task_id)), None
        )
        new_due = reschedule(original, result.due)
        self._record_edit(str(task_id), due=new_due)
        # optimistic: repaint the due cell (and re-group if grouped by due) now
        self._rows = [
            replace(row, due=new_due) if str(row.id) == str(task_id) else row
            for row in self._rows
        ]
        if self._view.keeps is not None:  # drop it now if it left the view
            today = self._clock.today()
            self._rows = [row for row in self._rows if self._view.keeps(row, today)]
        elif self._active_server_query is not None:
            # a filter's membership needs the server; assume the reschedule drops
            # it and let the background refresh restore it if it still matches
            self._rows = [row for row in self._rows if str(row.id) != str(task_id)]
        self._render(self._arrange(self._rows), self._view)
        self._set_due(task_id, new_due)

    @work
    async def _set_due(self, task_id: TaskId, due: Due | None) -> None:
        try:
            await set_due(self._repo, task_id, due)
        except Exception as error:  # command rejected: resync, then report
            self._forget_edit(str(task_id), "due")
            await self._reload(self._view)
            self._set_status(f"Failed to set due: {error}")
            return
        self._sync_now()  # pull server delta; re-arranges if grouped/sorted by due

    def _on_deadline(self, task_id: TaskId, result: DueResult | None) -> None:
        if result is None:  # picker was cancelled
            return
        # the deadline screen carries a date-only Due; map it to a Deadline
        new_deadline = (
            Deadline(date=result.due.date) if result.due is not None else None
        )
        self._record_edit(str(task_id), deadline=new_deadline)
        self._rows = [  # optimistic: repaint the deadline cell now
            replace(row, deadline=new_deadline) if str(row.id) == str(task_id) else row
            for row in self._rows
        ]
        self._render(self._arrange(self._rows), self._view)
        self._set_deadline(task_id, new_deadline)

    @work
    async def _set_deadline(self, task_id: TaskId, deadline: Deadline | None) -> None:
        try:
            await set_deadline(self._repo, task_id, deadline)
        except Exception as error:  # command rejected: resync, then report
            self._forget_edit(str(task_id), "deadline")
            await self._reload(self._view)
            self._set_status(f"Failed to set deadline: {error}")
            return
        self._sync_now()

    async def action_move_task(self) -> None:
        if self._picking_project:  # already loading or picker already open
            return
        table = self.query_one(TaskTable)
        task_id = self._cursor_task_id(table)
        if task_id is None:  # empty table or cursor on a group header
            return
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        if row is None:
            return
        self._picking_project = True
        try:
            projects = await self._repo.projects()
            sections = await self._repo.sections()
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load projects: {error}")
            self._picking_project = False
            return
        self.push_screen(
            ProjectPickerScreen(
                projects,
                sections,
                current_project=row.project_id,
                current_section=row.section_id,
            ),
            lambda target: self._on_moved(TaskId(task_id), target),
        )

    def _on_moved(self, task_id: TaskId, target: MoveTarget | None) -> None:
        self._picking_project = False
        if target is None:  # picker was cancelled
            return
        self._record_edit(
            str(task_id),
            project_name=target.project_name,
            project_id=target.project_id,
            section_id=target.section_id,
            section_name=target.section_name,
        )
        # optimistic: repaint the project cell (and re-group if grouped by project)
        self._rows = [
            replace(
                row,
                project_name=target.project_name,
                project_id=target.project_id,
                section_id=target.section_id,
                section_name=target.section_name,
            )
            if str(row.id) == str(task_id)
            else row
            for row in self._rows
        ]
        if self._view.key == "inbox":  # moved out of Inbox: it no longer lists the task
            self._rows = [r for r in self._rows if str(r.id) != str(task_id)]
        elif self._view.keeps is not None:  # membership is decidable here and now
            today = self._clock.today()
            self._rows = [r for r in self._rows if self._view.keeps(r, today)]
        elif self._active_server_query is not None:
            # a filter's membership needs the server; assume the move drops it and
            # let the background refresh restore it if it still matches
            self._rows = [r for r in self._rows if str(r.id) != str(task_id)]
        self._render(self._arrange(self._rows), self._view)
        self._move_task(task_id, target.project_id, target.section_id)

    @work
    async def _move_task(
        self, task_id: TaskId, project_id: str, section_id: str | None
    ) -> None:
        try:
            await move_task(self._repo, task_id, project_id, section_id)
        except Exception as error:  # command rejected: resync, then report
            self._forget_edit(
                str(task_id),
                "project_name",
                "project_id",
                "section_id",
                "section_name",
            )
            await self._reload(self._view)
            self._set_status(f"Failed to move task: {error}")
            return
        self._sync_now()  # pull server delta; re-arranges if grouped by project

    async def action_set_labels(self) -> None:
        if self._picking_labels:  # already loading or editor already open
            return
        table = self.query_one(TaskTable)
        task_id = self._cursor_task_id(table)
        if task_id is None:  # empty table or cursor on a group header
            return
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        if row is None:
            return
        self._picking_labels = True
        try:
            catalog = await self._repo.labels()
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load labels: {error}")
            self._picking_labels = False
            return
        names = {label.name for label in catalog}
        self.push_screen(
            LabelsScreen(sorted(names), row.labels),
            lambda chosen: self._on_labels(TaskId(task_id), row.labels, names, chosen),
        )

    def _on_labels(
        self,
        task_id: TaskId,
        previous: tuple[str, ...],
        catalog: set[str],
        chosen: tuple[str, ...] | None,
    ) -> None:
        self._picking_labels = False
        if chosen is None or chosen == previous:  # cancelled or unchanged
            return
        create = tuple(name for name in chosen if name not in catalog)
        self._record_edit(str(task_id), labels=chosen)
        self._rows = [  # optimistic: repaint the labels cell now
            replace(row, labels=chosen) if str(row.id) == str(task_id) else row
            for row in self._rows
        ]
        if self._view.keeps is not None:  # membership is decidable here and now
            today = self._clock.today()
            self._rows = [r for r in self._rows if self._view.keeps(r, today)]
        elif self._active_server_query is not None:
            # a filter/search's membership needs the server; assume the label edit
            # drops it and let the background refresh restore it if it still matches
            self._rows = [r for r in self._rows if str(r.id) != str(task_id)]
        self._render(self._arrange(self._rows), self._view)
        self._set_labels(task_id, chosen, create)

    @work
    async def _set_labels(
        self, task_id: TaskId, labels: tuple[str, ...], create: tuple[str, ...]
    ) -> None:
        try:
            await set_labels(self._repo, task_id, labels, create)
        except Exception as error:  # command rejected: resync, then report
            self._forget_edit(str(task_id), "labels")
            await self._reload(self._view)
            self._set_status(f"Failed to set labels: {error}")
            return
        self._sync_now()  # pull server delta; re-runs a live filter/search view

    async def _reload(self, view: View) -> None:
        try:
            rows = await load_view(self._repo, view)
        except Exception as error:  # surface any load failure to the user
            self._set_status(f"Failed to load tasks: {error}")
            return
        self._arrangement = await self._arrangements.get(
            view.key, view.default_arrangement
        )
        rows = self._drop_closed(rows)
        rows = self._apply_pending_edits(rows)
        self._rows = rows  # retained so a priority keypress can re-arrange locally
        self._render(self._arrange(rows), view)

    def _record_edit(self, task_id: str, **fields: object) -> None:
        self._pending_edits.setdefault(task_id, {}).update(fields)  # last write wins

    def _forget_edit(self, task_id: str, *fields: str) -> None:
        pending = self._pending_edits.get(task_id)
        if pending is None:
            return
        for name in fields:
            pending.pop(name, None)
        if not pending:
            del self._pending_edits[task_id]

    def _apply_pending_edits(self, rows: list[TaskRow]) -> list[TaskRow]:
        """Re-apply locally-edited fields the server hasn't confirmed yet, and
        forget a field once the snapshot matches it — or the task leaves the
        view — so an edit isn't held forever."""
        present = {str(row.id) for row in rows}
        self._pending_edits = {
            tid: fields for tid, fields in self._pending_edits.items() if tid in present
        }
        result: list[TaskRow] = []
        for row in rows:
            pending = self._pending_edits.get(str(row.id))
            if not pending:
                result.append(row)
                continue
            unconfirmed = {
                name: value
                for name, value in pending.items()
                if getattr(row, name) != value
            }
            if unconfirmed:
                self._pending_edits[str(row.id)] = unconfirmed
                row = replace(row, **unconfirmed)
            else:
                del self._pending_edits[str(row.id)]
            result.append(row)
        return result

    def _drop_closed(self, rows: list[TaskRow]) -> list[TaskRow]:
        """Hide locally-closed tasks the server hasn't confirmed yet, and forget
        a closed task once the snapshot reflects it — gone, or (recurring) with a
        changed due — so it isn't hidden forever."""
        present = {str(row.id): row.due for row in rows}
        self._pending_close = {
            tid: due
            for tid, due in self._pending_close.items()
            if tid in present and present[tid] == due
        }
        return [row for row in rows if str(row.id) not in self._pending_close]

    def _arrange(self, rows: list[TaskRow]) -> list[RenderRow[TaskRow]]:
        return arrange(rows, self._arrangement, frozenset(self._expanded))

    def on_task_table_expand(self, _message: TaskTable.Expand) -> None:
        table = self.query_one(TaskTable)
        task_id = self._cursor_task_id(table)
        if task_id is None or task_id in self._expanded:
            return
        if not self._has_children(task_id):  # nothing to reveal
            return
        self._expanded.add(TaskId(task_id))
        self._render(self._arrange(self._rows), self._view)  # cursor stays on it

    def on_task_table_collapse(self, _message: TaskTable.Collapse) -> None:
        table = self.query_one(TaskTable)
        task_id = self._cursor_task_id(table)
        if task_id is None:
            return
        if task_id in self._expanded:  # an expanded parent: fold it away
            self._expanded.discard(TaskId(task_id))
            self._render(self._arrange(self._rows), self._view)  # cursor stays on it
            return
        parent_id = self._parent_of(task_id)  # a leaf/child: step out to the parent
        if parent_id is not None:
            self._move_cursor_to_task(table, parent_id)

    def _has_children(self, task_id: str) -> bool:
        return any(row.parent_id == task_id for row in self._rows)

    def _parent_of(self, task_id: str) -> str | None:
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        return row.parent_id if row is not None else None

    def _move_cursor_to_task(self, table: TaskTable, task_id: str) -> None:
        for row in range(table.row_count):
            key = table.coordinate_to_cell_key(Coordinate(row, 0)).row_key
            if _task_id_of(str(key.value)) == task_id:
                table.move_cursor(row=row)
                return

    def _render(self, render_rows: list[RenderRow[TaskRow]], view: View) -> None:
        try:
            table = self.query_one(TaskTable)
        except NoMatches:  # background resync landed mid-teardown: nothing to draw
            return
        prior = self._cursor_task_id(table)  # survive the clear+rebuild below
        today = self._clock.today()
        first_row_of: dict[str, int] = {}
        first_task_row: int | None = None
        task_ids: set[str] = set()
        # drop metadata columns empty for every visible task, so short lists don't
        # strand three near-blank columns beside the titles
        tasks = [item.row for item in render_rows if isinstance(item, TaskLine)]
        show_labels = any(t.labels for t in tasks)
        show_due = any(t.due for t in tasks)
        show_deadline = any(t.deadline for t in tasks)
        show_project = any(t.project_name for t in tasks)
        columns = ["", "Task"]
        if show_labels:
            columns.append("Labels")
        if show_due:
            columns.append("Due")
        if show_deadline:
            columns.append("Deadline")
        if show_project:
            columns.append("Project")
        table.clear(columns=True)
        table.add_columns(*columns)
        for index, item in enumerate(render_rows):
            if isinstance(item, GroupHeader):
                header = ["", _header_text(item, today)] + [""] * (len(columns) - 2)
                table.add_row(*header, key=_header_key(index))
                continue
            row = item.row
            # bold (no color) so the title leads on any theme; dim metadata recedes
            content = Text(_indent(item.level), style="bold")
            content.append(_expand_marker(item))
            content.append_text(render_links(row.content))
            cells: list[Text | str] = [priority_dot(row.priority), content]
            if show_labels:
                cells.append(_labels_cell(row.labels))
            if show_due:
                cells.append(_due_cell(row.due, today))
            if show_deadline:
                cells.append(_deadline_cell(row.deadline, today))
            if show_project:
                cells.append(_project_cell(row.project_name))
            table.add_row(*cells, key=_task_key(index, row.id))
            if first_task_row is None:
                first_task_row = index
            first_row_of.setdefault(str(row.id), index)
            task_ids.add(str(row.id))
        if prior is not None and prior in first_row_of:
            table.move_cursor(row=first_row_of[prior])  # keep highlight on the task
        elif first_task_row is not None:
            table.move_cursor(row=first_task_row)  # never rest on a leading header
        self._set_status(_count_status(view.title, len(task_ids)))

    def _focus_task_at(self, table: TaskTable, row: int) -> None:
        """Put the cursor on the task at or after `row`, else the last task —
        so completing a task follows the highlight down to its neighbour rather
        than jumping to the top."""

        def is_task(r: int) -> bool:
            key = table.coordinate_to_cell_key(Coordinate(r, 0)).row_key
            return _task_id_of(str(key.value)) is not None

        task_rows = [r for r in range(table.row_count) if is_task(r)]
        if task_rows:
            target = next((r for r in task_rows if r >= row), task_rows[-1])
            table.move_cursor(row=target)

    def _cursor_task_id(self, table: TaskTable) -> str | None:
        if table.row_count == 0:
            return None
        key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return _task_id_of(key)

    def _set_status(self, message: str) -> None:
        self._status_base = message
        self._render_status()

    def _set_syncing(self, syncing: bool) -> None:
        self._syncing = syncing
        self._render_status()

    def _render_status(self) -> None:
        try:
            status = self.query_one("#status", Static)
        except NoMatches:  # background resync landed mid-teardown: nothing to draw
            return
        summary = _arrangement_summary(self._arrangement)
        marker = "  ⟳" if self._syncing else ""
        status.update(f"{self._status_base}{summary}{marker}")


def _count_status(title: str, count: int) -> str:
    return f"{title} · no tasks" if count == 0 else f"{title} · {count} task(s)"


_RECURRING_GLYPH = " ↻"


def _due_cell(due: Due | None, today: datetime.date) -> Text | str:
    if due is None:
        return ""
    label = format_due(due, today)
    if due.is_recurring:  # detail card shows the full rule; here just a quiet mark
        label += _RECURRING_GLYPH
    return styled_date(label, due.date, today)


def _deadline_cell(deadline: Deadline | None, today: datetime.date) -> Text | str:
    if deadline is None:
        return ""
    return styled_date(format_deadline(deadline, today), deadline.date, today)


def _project_cell(project_name: str | None) -> Text | str:
    return Text(project_name, style="dim") if project_name else ""


def _labels_cell(labels: tuple[str, ...]) -> Text | str:
    line = format_labels(labels)
    return Text(line, style="dim") if line else ""


def _header_text(header: GroupHeader, today: datetime.date) -> Text:
    indent = _indent(header.level)
    label = header.label
    if header.field is Field.DUE_DATE:
        # the bucket label is ISO (a stable grouping key) except "No due date"
        with contextlib.suppress(ValueError):
            label = humanize_date(datetime.date.fromisoformat(label), today)
    label = f"{label} ({header.count})"
    lead = f"{indent}── {label} "
    fill = "─" * max(3, _HEADER_WIDTH - len(lead))
    # deeper levels recede a little; top level is the boldest divider
    style = "bold cyan" if header.level == 0 else "bold blue"
    return Text(f"{lead}{fill}", style=style)


def _indent(level: int) -> str:
    return _INDENT * level


def _header_key(index: int) -> str:
    return f"h:{index}"


def _task_key(index: int, task_id: str) -> str:
    return f"t:{index}:{task_id}"


def _task_id_of(row_key: str) -> str | None:
    """The task id encoded in a row key, or None for a group-header row."""
    if row_key.startswith("t:"):
        return row_key.split(":", 2)[2]
    return None


def _arrangement_summary(arrangement: Arrangement) -> str:
    parts: list[str] = []
    if arrangement.group_by:
        fields = " › ".join(
            f"{f.label} {'↑' if arrangement.group_ascending(f) else '↓'}"
            for f in arrangement.group_by
        )
        parts.append(f"Group: {fields}")
    if arrangement.sort_by:
        keys = " › ".join(
            f"{s.field.label} {'↑' if s.ascending else '↓'}"
            for s in arrangement.sort_by
        )
        parts.append(f"Sort: {keys}")
    return "   ·   " + "    ".join(parts) if parts else ""


def _expand_marker(line: TaskLine[TaskRow]) -> str:
    if not line.has_children:
        return ""  # leaves carry no marker (and don't shift childless lists)
    return "▾ " if line.expanded else "▸ "
