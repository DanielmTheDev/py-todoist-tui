from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.css.query import NoMatches
from textual.widgets import DataTable, Footer, Static

from todoist_tui.application.complete import complete_task, uncomplete_task
from todoist_tui.application.views import (
    INBOX,
    TODAY,
    TaskRow,
    View,
    filter_view,
    load_view,
)
from todoist_tui.domain.arrange import Arrangement, GroupHeader, RenderRow, arrange
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.repository import ArrangementStore, TaskRepository
from todoist_tui.domain.task import TaskId
from todoist_tui.tui.screens.filters import FilterScreen

_SYNC_INTERVAL_SECONDS = 60.0  # Todoist has no push; poll incrementally
_COLUMNS = ("", "Time", "Task", "Project")  # priority dot needs no header
_PRIORITY_DOTS = {Priority.P1: "🔴", Priority.P2: "🟠", Priority.P3: "🔵"}
_INDENT = "  "  # per nesting level, for group headers and their tasks


class InMemoryArrangements:
    """Session-only arrangement store (the default when none is injected)."""

    def __init__(self) -> None:
        self._by_key: dict[str, Arrangement] = {}

    async def get(self, view_key: str) -> Arrangement:
        return self._by_key.get(view_key, Arrangement())

    async def save(self, view_key: str, arrangement: Arrangement) -> None:
        self._by_key[view_key] = arrangement


class TaskTable(DataTable[object]):
    """DataTable with vim h/j/k/l aliases for the built-in cursor moves."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "cursor_left", "Left", show=False),
        Binding("l", "cursor_right", "Right", show=False),
    ]


class TodoistApp(App[None]):
    """Row-highlighted task table; switch between the Today and Inbox views."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("e", "complete", "Complete"),
        ("z", "undo", "Undo"),
        ("t", "view_today", "Today"),
        ("i", "view_inbox", "Inbox"),
        ("f", "view_filters", "Filters"),
        ("r", "refresh", "Refresh"),
    ]
    SYNC_INTERVAL: ClassVar[float] = _SYNC_INTERVAL_SECONDS

    def __init__(
        self, repo: TaskRepository, arrangements: ArrangementStore | None = None
    ) -> None:
        super().__init__()
        self._repo = repo
        self._arrangements = arrangements or InMemoryArrangements()
        self._arrangement = Arrangement()  # current view's group/sort
        self._view = TODAY
        self._syncing = False
        self._status_base = ""
        self._last_undo: tuple[TaskId, list[object]] | None = None
        self._picking_filter = False  # guards against stacking filter pickers
        self._active_filter_query: str | None = None  # set while a filter view shows

    def compose(self) -> ComposeResult:
        yield Static("Loading…", id="status")
        yield TaskTable()
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one(TaskTable)
        table.cursor_type = "row"
        table.add_columns(*_COLUMNS)
        await self._reload(self._view)  # instant: served from cache when present
        self._sync_now()
        self.set_interval(self.SYNC_INTERVAL, self._sync_now)

    @work(exclusive=True, group="reload")
    async def _sync_now(self) -> None:
        self._set_syncing(True)
        try:
            await self._repo.refresh()
            if self._active_filter_query is not None:  # keep the open filter live
                await self._repo.refresh_filtered(self._active_filter_query)
            await self._reload(self._view)
        except Exception:  # offline or sync failed: keep the cached view
            pass
        finally:  # also runs on worker cancellation, so ⟳ never sticks
            self._set_syncing(False)

    def action_refresh(self) -> None:
        self._sync_now()

    def action_view_today(self) -> None:
        self._active_filter_query = None
        self._switch_to(TODAY)

    def action_view_inbox(self) -> None:
        self._active_filter_query = None
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
        self._active_filter_query = chosen.query
        self._view = filter_view(chosen)
        self._open_filter(self._view, chosen.query)

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
        cells = table.get_row(row_key)  # kept to restore the row on undo
        table.remove_row(row_key)  # optimistic: drop it now, sync in the background
        self._set_status(_count_status(self._view.title, _visible_task_count(table)))
        self._complete(TaskId(task_id), cells)

    @work
    async def _complete(self, task_id: TaskId, cells: list[object]) -> None:
        try:
            await complete_task(self._repo, task_id)
        except Exception as error:  # command rejected: resync, then report
            await self._reload(self._view)
            self._set_status(f"Failed to complete task: {error}")
            return
        self._last_undo = (task_id, cells)  # only a confirmed close is undoable
        self._sync_now()  # pull server delta so the view reflects the close

    def action_undo(self) -> None:
        if self._last_undo is None:
            return
        task_id, cells = self._last_undo
        self._last_undo = None  # single-level: each undo reverses one close
        table = self.query_one(TaskTable)
        table.add_row(*cells, key=_task_key(table.row_count, task_id))  # lands at end
        self._set_status(_count_status(self._view.title, _visible_task_count(table)))
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

    async def _reload(self, view: View) -> None:
        try:
            rows = await load_view(self._repo, view)
        except Exception as error:  # surface any load failure to the user
            self._set_status(f"Failed to load tasks: {error}")
            return
        self._arrangement = await self._arrangements.get(view.key)
        self._render(arrange(rows, self._arrangement), view)

    def _render(self, render_rows: list[RenderRow[TaskRow]], view: View) -> None:
        try:
            table = self.query_one(TaskTable)
        except NoMatches:  # background resync landed mid-teardown: nothing to draw
            return
        prior = self._cursor_task_id(table)  # survive the clear+rebuild below
        table.clear()
        first_row_of: dict[str, int] = {}
        task_ids: set[str] = set()
        for index, item in enumerate(render_rows):
            if isinstance(item, GroupHeader):
                table.add_row("", "", _header_text(item), "", key=_header_key(index))
                continue
            row = item.row
            table.add_row(
                _priority_dot(row.priority),
                _format_time(row),
                _indent(item.level) + row.content,
                Text(row.project_name, style="dim") if row.project_name else "",
                key=_task_key(index, row.id),
            )
            first_row_of.setdefault(str(row.id), index)
            task_ids.add(str(row.id))
        if prior is not None and prior in first_row_of:
            table.move_cursor(row=first_row_of[prior])  # keep highlight on the task
        self._set_status(_count_status(view.title, len(task_ids)))

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


def _header_text(header: GroupHeader) -> str:
    return f"{_indent(header.level)}▾ {header.label}"


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


def _visible_task_count(table: TaskTable) -> int:
    ids = {_task_id_of(str(key.value)) for key in table.rows}
    ids.discard(None)
    return len(ids)


def _arrangement_summary(arrangement: Arrangement) -> str:
    parts: list[str] = []
    if arrangement.group_by:
        fields = " › ".join(f.label for f in arrangement.group_by)
        parts.append(f"Group: {fields}")
    if arrangement.sort_by:
        keys = " › ".join(
            f"{s.field.label} {'↑' if s.ascending else '↓'}"
            for s in arrangement.sort_by
        )
        parts.append(f"Sort: {keys}")
    return "   ·   " + "    ".join(parts) if parts else ""


def _priority_dot(priority: Priority) -> str:
    return _PRIORITY_DOTS.get(priority, "")  # P4 (default) stays blank


def _format_time(row: TaskRow) -> str:
    if row.due is None or row.due.time is None:
        return ""
    return row.due.time.strftime("%H:%M")
