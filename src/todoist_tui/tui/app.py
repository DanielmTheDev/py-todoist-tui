import contextlib
import datetime
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import DataTable, Footer, Static

from todoist_tui.application.add_reminder import add_reminder
from todoist_tui.application.complete import complete_task, uncomplete_task
from todoist_tui.application.delete import delete_section, delete_task
from todoist_tui.application.delete_reminder import delete_reminder
from todoist_tui.application.duplicate import duplicate_project, duplicate_section
from todoist_tui.application.move_task import move_task
from todoist_tui.application.set_deadline import set_deadline
from todoist_tui.application.set_due import set_due
from todoist_tui.application.set_labels import set_labels
from todoist_tui.application.set_priority import set_priority
from todoist_tui.application.set_text import set_text
from todoist_tui.application.views import (
    INBOX,
    TODAY,
    TaskRow,
    View,
    filter_view,
    load_view,
    project_view,
    prune,
    query_for_key,
    search_view,
    view_from_key,
)
from todoist_tui.domain.arrange import (
    Arrangement,
    Field,
    GroupHeader,
    GroupPath,
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
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.repository import (
    ArrangementStore,
    HomeViewStore,
    TaskRepository,
)
from todoist_tui.domain.schedule import reschedule
from todoist_tui.domain.search import SearchTerm
from todoist_tui.domain.task import TaskId
from todoist_tui.tui.format import (
    date_tier,
    description_marker,
    due_tier,
    format_deadline,
    format_due,
    format_labels,
    format_reminder_badge,
    priority_dot,
    render_links,
)
from todoist_tui.tui.screens.arrange import ArrangeScreen, Mode
from todoist_tui.tui.screens.confirm import ConfirmScreen
from todoist_tui.tui.screens.detail import TaskDetailScreen
from todoist_tui.tui.screens.edit import TaskEditScreen, TaskText
from todoist_tui.tui.screens.filters import FilterScreen
from todoist_tui.tui.screens.help import HelpScreen
from todoist_tui.tui.screens.labels import LabelsScreen
from todoist_tui.tui.screens.project_list import ProjectListScreen
from todoist_tui.tui.screens.project_picker import MoveTarget, ProjectPickerScreen
from todoist_tui.tui.screens.reminders import ReminderRequest, RemindersScreen
from todoist_tui.tui.screens.schedule import DueResult, ScheduleScreen
from todoist_tui.tui.screens.search import SearchScreen
from todoist_tui.tui.screens.text_prompt import TextPromptScreen
from todoist_tui.tui.theme import (
    TIER_CLASSES,
    TIER_CSS,
    TODOIST_THEME,
    Tier,
    tier_styles,
)

_SYNC_INTERVAL_SECONDS = 60.0  # Todoist has no push; poll incrementally
_INDENT = "  "  # per nesting level, for group headers and their tasks
_MIN_FILL = 3  # so a label as wide as the titles still trails a visible rule
_GUTTER = 2  # shared by the status band's padding and the table's cell padding
_SUMMARY_GAP = 2  # least space between the status message and the arrangement
_FOLD_OPEN = "▾ "  # subtree shown — on a parent task or a group header
_FOLD_SHUT = "▸ "  # subtree folded away


def as_binding(entry: BindingType) -> Binding:
    """Normalize a Textual binding entry (tuple or `Binding`) to a `Binding`."""
    if isinstance(entry, Binding):
        return entry
    key, action, *rest = entry
    return Binding(key, action, rest[0] if rest else "")


def shortcut_rows(*binding_lists: list[BindingType]) -> list[tuple[str, str]]:
    """Flatten Textual binding definitions into (key, description) help rows,
    dropping entries with no description and the help binding itself. A binding
    holding several keys ("h,left") lists them all: "h / left"."""
    rows: list[tuple[str, str]] = []
    for bindings in binding_lists:
        for binding in map(as_binding, bindings):
            if binding.action == "help" or not binding.description:
                continue
            rows.append((" / ".join(binding.key.split(",")), binding.description))
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


class StatusBand(Static):
    """The band above the table: which view is open on the left, how it's arranged
    on the right. Also the app's error channel, so it holds arbitrary text."""

    COMPONENT_CLASSES: ClassVar[set[str]] = set(TIER_CLASSES)
    DEFAULT_CSS = TIER_CSS

    def __init__(self) -> None:
        super().__init__("Loading…", id="status", markup=False)
        self._message = "Loading…"
        self._tally = ""
        self._summary = ""

    def show(self, message: str, tally: str, summary: str) -> None:
        self._message, self._tally, self._summary = message, tally, summary
        self._paint()

    def on_resize(self) -> None:
        self._paint()  # the summary is right-aligned, so its padding is width-bound

    def _paint(self) -> None:
        styles = tier_styles(self)
        text = Text(self._message, style=styles[Tier.PRIMARY] + Style(bold=True))
        text.append(self._tally, style=styles[Tier.MUTED])
        gap = self.content_size.width - cell_len(text.plain) - cell_len(self._summary)
        if self._summary and gap >= _SUMMARY_GAP:  # else it would wrap the band
            text.append(" " * gap)
            text.append(self._summary, style=styles[Tier.MUTED])
        self.update(text)


class TaskTable(DataTable[object]):
    """DataTable with j/k or up/down row nav and h/l or left/right collapse/expand.

    The cursor rests on group headers too, since they fold. Collapse/expand don't
    move the column cursor (the table is row-mode); they ask the app to
    collapse/expand whatever the cursor sits on — a task's subtasks, or a group.
    Binding left/right here shadows DataTable's horizontal scroll, which is
    useless in row mode.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = DataTable.COMPONENT_CLASSES | TIER_CLASSES
    DEFAULT_CSS = TIER_CSS

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j,down", "cursor_down", "Down", show=False),
        Binding("k,up", "cursor_up", "Up", show=False),
        Binding("h,left", "collapse", "Collapse task/group", show=False),
        Binding("l,right", "expand", "Expand task/group", show=False),
    ]

    class Expand(Message):
        """Reveal the subtasks, or the folded group, under the cursor."""

    class Collapse(Message):
        """Fold the subtasks or group under the cursor, else step out to its parent."""

    def action_expand(self) -> None:
        self.post_message(self.Expand())

    def action_collapse(self) -> None:
        self.post_message(self.Collapse())


class TodoistApp(App[None]):
    """Row-highlighted task table over Today, Inbox, project, and filter views,
    opening on a persisted home view."""

    # absolute: a relative path resolves against the *subclass's* module, which
    # would send a test-local subclass looking in the tests directory
    CSS_PATH = Path(__file__).with_name("app.tcss")

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
        Binding("H", "set_home", "Set home", show=False),
        Binding("m", "go_home", "Home", show=False),
        Binding("g", "arrange_group", "Group", show=False),
        Binding("s", "arrange_sort", "Sort", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("t", "set_due", "Due", show=False),
        Binding("d", "set_deadline", "Deadline", show=False),
        Binding("v", "move_task", "Move", show=False),
        Binding("Y", "duplicate", "Duplicate project/section", show=False),
        Binding("D", "delete_section", "Delete section", show=False),
        Binding("at", "set_labels", "Labels", show=False),
        Binding("R", "reminders", "Reminders", show=False),
        Binding("enter", "open_detail", "Detail", show=False),
        Binding("ctrl+e", "edit_task", "Edit title + description", show=False),
        Binding("x", "toggle_select", "Select", show=False),
        Binding("asterisk", "select_all", "Select all", show=False),
        Binding("escape", "clear_selection", "Clear selection", show=False),
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
        self.register_theme(TODOIST_THEME)
        self.theme = TODOIST_THEME.name
        self._repo = repo
        self._arrangements = arrangements or InMemoryArrangements()
        self._home = home or InMemoryHome()
        self._clock = clock or SystemClock()
        self._link_opener = link_opener or XdgOpenLinkOpener()
        self._arrangement = Arrangement()  # current view's group/sort
        self._rows: list[TaskRow] = []  # last loaded rows, for local re-arrange
        self._expanded: set[TaskId] = set()  # tasks whose subtasks are shown
        self._collapsed: set[GroupPath] = set()  # groups folded to their header
        self._header_paths: dict[int, GroupPath] = {}  # header row index → its group
        self._selected: set[str] = set()  # tasks marked for the next bulk action
        self._view = TODAY
        self._syncing = False
        self._status_base = ""  # the band's left-hand line: view title, or an error
        self._status_tally = ""  # " · 9 task(s)", blank while an error is shown
        self._last_undo: list[tuple[TaskId, TaskRow]] = []  # last completed batch
        # tasks closed locally, kept hidden across reloads until the server's
        # snapshot reflects the change (gone, or a recurring task's new due)
        self._pending_close: dict[str, Due | None] = {}
        # fields edited locally, kept applied across reloads until the server
        # snapshot reflects them — so a lagging sync can't revert an optimistic edit
        self._pending_edits: dict[str, dict[str, object]] = {}
        self._picking_filter = False  # guards against stacking filter pickers
        self._picking_project = False  # guards against stacking project pickers
        self._picking_duplicate = False  # guards the duplicate picker + name prompt
        # guards the section-delete picker + its confirmation
        self._picking_delete_section = False
        self._picking_project_list = False  # guards against stacking the project list
        self._picking_labels = False  # guards against stacking the labels editor
        # the server query of the open view — a saved filter's, or a search's —
        # re-run on every sync so that view stays live
        self._active_server_query: str | None = None

    def compose(self) -> ComposeResult:
        yield StatusBand()
        yield TaskTable()
        yield Footer()

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return {"gutter": str(_GUTTER)}  # so the stylesheet shares the one constant

    async def on_mount(self) -> None:
        table = self.query_one(TaskTable)
        table.cursor_type = "row"
        # the cursor tints the background only, so each cell keeps its own tier
        table.cursor_foreground_priority = "renderable"
        # breathing room between columns, and the band's gutter under the first
        table.cell_padding = _GUTTER
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
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        cursor_row = table.cursor_row  # follow the highlight down to the neighbour
        undo: list[tuple[TaskId, TaskRow]] = []
        for task_id in ids:
            row = next((r for r in self._rows if str(r.id) == task_id), None)
            self._pending_close[task_id] = row.due if row is not None else None
            if row is not None:  # only a known row is restorable
                undo.append((TaskId(task_id), row))
        # optimistic: drop them from the model and repaint, sync in the background
        dropped = set(ids)
        self._rows = prune(self._rows, lambda r: str(r.id) in dropped)
        self._selected.clear()
        self._repaint()
        self._focus_task_at(table, cursor_row)
        self._complete([TaskId(i) for i in ids], undo)

    @work
    async def _complete(
        self, task_ids: list[TaskId], undo: list[tuple[TaskId, TaskRow]]
    ) -> None:
        undo_of = {str(task_id): (task_id, row) for task_id, row in undo}
        done: list[tuple[TaskId, TaskRow]] = []  # confirmed closes, reversible by z
        for task_id in task_ids:
            try:
                await complete_task(self._repo, task_id)
            except Exception as error:  # command rejected: unhide it, resync, report
                self._pending_close.pop(str(task_id), None)
                self._last_undo = done  # only what actually closed stays undoable
                await self._reload(self._view)
                self._set_status(f"Failed to complete task: {error}")
                return
            if str(task_id) in undo_of:
                done.append(undo_of[str(task_id)])
        self._last_undo = done  # the whole confirmed batch reverses as one undo
        self._sync_now()  # pull server delta so the view reflects the close

    def action_undo(self) -> None:
        if not self._last_undo:
            return
        batch = self._last_undo
        self._last_undo = []  # single-level: each undo reverses the last close
        for task_id, row in batch:
            self._pending_close.pop(str(task_id), None)  # reopened: stop filtering it
            if all(str(r.id) != str(task_id) for r in self._rows):
                self._rows = [*self._rows, row]
        self._repaint()
        self._uncomplete([task_id for task_id, _ in batch])

    @work
    async def _uncomplete(self, task_ids: list[TaskId]) -> None:
        for task_id in task_ids:
            try:
                await uncomplete_task(self._repo, task_id)
            except Exception as error:  # command rejected: resync, then report
                await self._reload(self._view)
                self._set_status(f"Failed to undo: {error}")
                return
        self._sync_now()  # pull server delta so the view reflects the reopen

    def action_delete(self) -> None:
        table = self.query_one(TaskTable)
        pairs = [
            (TaskId(task_id), row)
            for task_id in self._targets(table)
            if (row := next((r for r in self._rows if str(r.id) == task_id), None))
            is not None
        ]
        if not pairs:  # empty table or cursor on a group header
            return
        cursor_row = table.cursor_row  # follow the highlight down after the delete
        prompt = (
            f"Delete {len(pairs)} tasks?"
            if len(pairs) > 1
            else f"Delete “{pairs[0][1].content}”?"
        )
        self.push_screen(
            ConfirmScreen(prompt),
            lambda confirmed: self._on_delete_confirmed(pairs, cursor_row, confirmed),
        )

    def _on_delete_confirmed(
        self,
        pairs: list[tuple[TaskId, TaskRow]],
        cursor_row: int,
        confirmed: bool | None,
    ) -> None:
        if not confirmed:  # dialog cancelled: leave the tasks and selection untouched
            return
        table = self.query_one(TaskTable)
        # optimistic: hide them (delete is permanent — no undo) and sync in the bg;
        # keep them hidden across reloads until the server confirms they're gone
        dropped = {str(task_id) for task_id, _ in pairs}
        for task_id, row in pairs:
            self._pending_close[str(task_id)] = row.due
        self._rows = prune(self._rows, lambda r: str(r.id) in dropped)
        self._selected.clear()
        self._repaint()
        self._focus_task_at(table, cursor_row)
        self._delete([task_id for task_id, _ in pairs])

    @work
    async def _delete(self, task_ids: list[TaskId]) -> None:
        for task_id in task_ids:
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
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        priority = Priority[name]
        targets = set(ids)
        for task_id in ids:
            self._record_edit(task_id, priority=priority)
        # optimistic: re-arrange now so the tasks jump to their new priority group
        # (and their dots repaint), then sync in the background
        self._rows = [
            replace(row, priority=priority) if str(row.id) in targets else row
            for row in self._rows
        ]
        self._selected.clear()
        self._repaint()
        self._set_priority([TaskId(i) for i in ids], priority)

    @work
    async def _set_priority(self, task_ids: list[TaskId], priority: Priority) -> None:
        for task_id in task_ids:
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
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        # one target keeps its date prefilled; a selection opens on a blank date
        row = next((r for r in self._rows if str(r.id) == ids[0]), None)
        current = row.due.date if len(ids) == 1 and row and row.due else None
        current_time = row.due.time if len(ids) == 1 and row and row.due else None
        self.push_screen(
            ScheduleScreen(self._clock.today(), current, current_time),
            lambda result: self._on_scheduled([TaskId(i) for i in ids], result),
        )

    def action_set_deadline(self) -> None:
        table = self.query_one(TaskTable)
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        row = next((r for r in self._rows if str(r.id) == ids[0]), None)
        current = row.deadline.date if len(ids) == 1 and row and row.deadline else None
        self.push_screen(
            ScheduleScreen(self._clock.today(), current, kind="deadline"),
            lambda result: self._on_deadline([TaskId(i) for i in ids], result),
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # DataTable consumes Enter for row selection before the app binding can
        # fire, so open the detail view off its message instead (the binding
        # stays for the footer hint).
        self.action_open_detail()

    def action_toggle_select(self) -> None:
        table = self.query_one(TaskTable)
        task_id = self._cursor_task_id(table)
        if task_id is None:  # empty table or cursor on a group header
            return
        cursor_row = table.cursor_row
        if task_id in self._selected:
            self._selected.discard(task_id)
        else:
            self._selected.add(task_id)
        self._repaint()
        self._focus_task_at(table, cursor_row + 1)  # advance for rapid marking

    def action_select_all(self) -> None:
        table = self.query_one(TaskTable)
        for row in range(table.row_count):
            key = table.coordinate_to_cell_key(Coordinate(row, 0)).row_key
            task_id = _task_id_of(str(key.value))
            if task_id is not None:  # skip group-header rows
                self._selected.add(task_id)
        self._repaint()

    def action_clear_selection(self) -> None:
        if not self._selected:
            return
        self._selected.clear()
        self._repaint()

    def action_help(self) -> None:
        if isinstance(self.screen, HelpScreen):  # already open
            return
        rows = shortcut_rows(TodoistApp.BINDINGS, TaskTable.BINDINGS)
        self.push_screen(HelpScreen(rows))

    def action_open_detail(self) -> None:
        row = self._cursor_row()
        if row is None:  # empty table or cursor on a group header
            return
        self._open_detail(row)

    def _open_detail(self, row: TaskRow) -> None:
        self.push_screen(
            TaskDetailScreen(row, self._link_opener, self._clock.today()),
            lambda edit: self._on_detail_closed(row, edit),
        )

    def _on_detail_closed(self, row: TaskRow, edit: bool | None) -> None:
        if edit:  # the card asked for the editor (ctrl+e)
            self._open_editor(row, from_detail=True)

    def action_edit_task(self) -> None:
        row = self._cursor_row()
        if row is None:  # empty table or cursor on a group header
            return
        self._open_editor(row, from_detail=False)

    def _open_editor(self, row: TaskRow, from_detail: bool) -> None:
        self.push_screen(
            TaskEditScreen(row.content, row.description),
            lambda text: self._on_edited(row, text, from_detail),
        )

    def _on_edited(
        self, row: TaskRow, text: TaskText | None, from_detail: bool
    ) -> None:
        edited = row
        if text is not None and (
            text.content != row.content or text.description != row.description
        ):
            edited = replace(row, content=text.content, description=text.description)
            task_id = str(row.id)
            self._record_edit(
                task_id, content=text.content, description=text.description
            )
            self._rows = [  # optimistic: repaint the title cell now
                edited if str(r.id) == task_id else r for r in self._rows
            ]
            self._rows = self._drop_departed({task_id})
            self._repaint()
            self._set_text(task_id, text)
        if from_detail:  # came from the card: land back on it, showing the edit
            self._open_detail(edited)

    @work
    async def _set_text(self, task_id: str, text: TaskText) -> None:
        try:
            await set_text(self._repo, TaskId(task_id), text.content, text.description)
        except Exception as error:  # command rejected: resync, then report
            self._forget_edit(task_id, "content", "description")
            await self._reload(self._view)
            self._set_status(f"Failed to edit task: {error}")
            return
        self._sync_now()  # pull server delta; re-runs a live filter/search view

    def _cursor_row(self) -> TaskRow | None:
        task_id = self._cursor_task_id(self.query_one(TaskTable))
        if task_id is None:
            return None
        return next((r for r in self._rows if str(r.id) == task_id), None)

    def _on_scheduled(self, task_ids: list[TaskId], result: DueResult | None) -> None:
        if result is None:  # picker was cancelled
            return
        targets = {str(t) for t in task_ids}
        # graft the picked date onto each task's own rule so a recurring task keeps
        # recurring (moves its next occurrence) instead of losing the rule
        edits: list[tuple[TaskId, Due | None]] = []
        for task_id in task_ids:
            original = next(
                (row.due for row in self._rows if str(row.id) == str(task_id)), None
            )
            new_due = reschedule(original, result.due)
            self._record_edit(str(task_id), due=new_due)
            edits.append((task_id, new_due))
        # optimistic: repaint the due cells (and re-group if grouped by due) now
        by_id = {str(task_id): due for task_id, due in edits}
        self._rows = [
            replace(row, due=by_id[str(row.id)]) if str(row.id) in targets else row
            for row in self._rows
        ]
        self._rows = self._drop_departed(targets)
        self._selected.clear()
        self._repaint()
        self._set_due(edits)

    @work
    async def _set_due(self, edits: list[tuple[TaskId, Due | None]]) -> None:
        for task_id, due in edits:
            try:
                await set_due(self._repo, task_id, due)
            except Exception as error:  # command rejected: resync, then report
                self._forget_edit(str(task_id), "due")
                await self._reload(self._view)
                self._set_status(f"Failed to set due: {error}")
                return
        self._sync_now()  # pull server delta; re-arranges if grouped/sorted by due

    def _on_deadline(self, task_ids: list[TaskId], result: DueResult | None) -> None:
        if result is None:  # picker was cancelled
            return
        # the deadline screen carries a date-only Due; map it to a Deadline
        new_deadline = (
            Deadline(date=result.due.date) if result.due is not None else None
        )
        targets = {str(t) for t in task_ids}
        for task_id in task_ids:
            self._record_edit(str(task_id), deadline=new_deadline)
        self._rows = [  # optimistic: repaint the deadline cells now
            replace(row, deadline=new_deadline) if str(row.id) in targets else row
            for row in self._rows
        ]
        self._selected.clear()
        self._repaint()
        self._set_deadline(task_ids, new_deadline)

    @work
    async def _set_deadline(
        self, task_ids: list[TaskId], deadline: Deadline | None
    ) -> None:
        for task_id in task_ids:
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
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        # one target prefills its project/section; a selection opens unanchored
        row = next((r for r in self._rows if str(r.id) == ids[0]), None)
        single = row if len(ids) == 1 else None
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
                current_project=single.project_id if single else None,
                current_section=single.section_id if single else None,
            ),
            lambda target: self._on_moved([TaskId(i) for i in ids], target),
        )

    def _on_moved(self, task_ids: list[TaskId], target: MoveTarget | None) -> None:
        self._picking_project = False
        if target is None:  # picker was cancelled
            return
        targets = {str(t) for t in task_ids}
        for task_id in task_ids:
            self._record_edit(
                str(task_id),
                project_name=target.project_name,
                project_id=target.project_id,
                section_id=target.section_id,
                section_name=target.section_name,
            )
        # optimistic: repaint the project cells (and re-group if grouped by project)
        self._rows = [
            replace(
                row,
                project_name=target.project_name,
                project_id=target.project_id,
                section_id=target.section_id,
                section_name=target.section_name,
            )
            if str(row.id) in targets
            else row
            for row in self._rows
        ]
        if self._view.key == "inbox":  # moved out of Inbox: it no longer lists them
            self._rows = prune(self._rows, lambda r: str(r.id) in targets)
        else:
            self._rows = self._drop_departed(targets)
        self._selected.clear()
        self._repaint()
        self._move_task(task_ids, target.project_id, target.section_id)

    @work
    async def _move_task(
        self, task_ids: list[TaskId], project_id: str, section_id: str | None
    ) -> None:
        for task_id in task_ids:
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

    async def action_duplicate(self) -> None:
        if self._picking_duplicate:  # already loading or a step already open
            return
        self._picking_duplicate = True
        try:
            projects = await self._repo.projects()
            sections = await self._repo.sections()
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load projects: {error}")
            self._picking_duplicate = False
            return
        self.push_screen(
            ProjectPickerScreen(
                projects, sections, placeholder="Duplicate project or section…"
            ),
            self._on_duplicate_target,
        )

    def _on_duplicate_target(self, target: MoveTarget | None) -> None:
        if target is None:  # picker cancelled
            self._picking_duplicate = False
            return
        source = target.section_name or target.project_name
        self.push_screen(
            TextPromptScreen("Name the copy", f"{source} (copy)"),
            lambda name: self._on_duplicate_named(target, name),
        )

    def _on_duplicate_named(self, target: MoveTarget, name: str | None) -> None:
        self._picking_duplicate = False
        if name is None:  # naming cancelled
            return
        source = target.section_name or target.project_name
        self._set_status(f"Duplicating {source}…")
        self._duplicate(target, name)

    @work
    async def _duplicate(self, target: MoveTarget, name: str) -> None:
        try:
            if target.section_id is not None:
                sections = await self._repo.sections()
                section = next((s for s in sections if s.id == target.section_id), None)
                if section is None:
                    raise LookupError(f"section {target.section_id} not found")
                await duplicate_section(self._repo, section, name)
            else:
                await duplicate_project(self._repo, target.project_id, name)
        except Exception as error:  # command rejected: report, keep the view
            self._set_status(f"Failed to duplicate: {error}")
            return
        self._sync_now()  # pull the real new entities into the view

    async def action_delete_section(self) -> None:
        if self._picking_delete_section:  # already loading or a step already open
            return
        self._picking_delete_section = True
        try:
            projects = await self._repo.projects()
            sections = await self._repo.sections()
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load sections: {error}")
            self._picking_delete_section = False
            return
        self.push_screen(
            ProjectPickerScreen(
                projects,
                sections,
                placeholder="Delete section…",
                sections_only=True,
            ),
            self._on_delete_section_target,
        )

    def _on_delete_section_target(self, target: MoveTarget | None) -> None:
        if target is None or target.section_id is None:  # picker cancelled
            self._picking_delete_section = False
            return
        section_id, name = target.section_id, target.section_name
        self.push_screen(
            ConfirmScreen(f"Delete section “{name}” and its tasks?"),
            lambda confirmed: self._on_delete_section_confirmed(
                section_id, name, confirmed
            ),
        )

    def _on_delete_section_confirmed(
        self, section_id: str, name: str | None, confirmed: bool | None
    ) -> None:
        self._picking_delete_section = False
        if not confirmed:
            return
        self._set_status(f"Deleting {name}…")
        self._delete_section(section_id)

    @work
    async def _delete_section(self, section_id: str) -> None:
        try:
            await delete_section(self._repo, section_id)
        except Exception as error:  # command rejected: report, keep the view
            self._set_status(f"Failed to delete section: {error}")
            return
        self._sync_now()  # the section and its tasks leave the view with the delta

    async def action_set_labels(self) -> None:
        if self._picking_labels:  # already loading or editor already open
            return
        table = self.query_one(TaskTable)
        rows = [
            row
            for task_id in self._targets(table)
            if (row := next((r for r in self._rows if str(r.id) == task_id), None))
        ]
        if not rows:  # empty table or cursor on a group header
            return
        self._picking_labels = True
        try:
            catalog = await self._repo.labels()
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load labels: {error}")
            self._picking_labels = False
            return
        names = {label.name for label in catalog}
        task_ids = [row.id for row in rows]
        # one task: edit its labels in place (replace). A selection: the editor
        # opens blank and its result is *added* to each task's own labels.
        add = len(rows) > 1
        seed: tuple[str, ...] = () if add else rows[0].labels
        self.push_screen(
            LabelsScreen(sorted(names), seed),
            lambda chosen: self._on_labels(task_ids, names, chosen, add),
        )

    def _on_labels(
        self,
        task_ids: list[TaskId],
        catalog: set[str],
        chosen: tuple[str, ...] | None,
        add: bool,
    ) -> None:
        self._picking_labels = False
        if chosen is None:  # cancelled
            return
        targets = {str(t) for t in task_ids}
        new_labels: dict[str, tuple[str, ...]] = {}
        for row in self._rows:
            if str(row.id) not in targets:
                continue
            merged = (
                row.labels + tuple(n for n in chosen if n not in row.labels)
                if add
                else tuple(chosen)
            )
            if merged != row.labels:  # skip tasks the edit leaves unchanged
                new_labels[str(row.id)] = merged
        if not new_labels:  # nothing to add / unchanged
            return
        create = tuple(name for name in chosen if name not in catalog)
        for task_id, labels in new_labels.items():
            self._record_edit(task_id, labels=labels)
        self._rows = [  # optimistic: repaint the labels cells now
            replace(row, labels=new_labels[str(row.id)])
            if str(row.id) in new_labels
            else row
            for row in self._rows
        ]
        self._rows = self._drop_departed(set(new_labels))
        self._selected.clear()
        self._repaint()
        self._set_labels(list(new_labels.items()), create)

    @work
    async def _set_labels(
        self, edits: list[tuple[str, tuple[str, ...]]], create: tuple[str, ...]
    ) -> None:
        for index, (task_id, labels) in enumerate(edits):
            try:  # create any new labels once, on the first command
                await set_labels(
                    self._repo, TaskId(task_id), labels, create if index == 0 else ()
                )
            except Exception as error:  # command rejected: resync, then report
                self._forget_edit(task_id, "labels")
                await self._reload(self._view)
                self._set_status(f"Failed to set labels: {error}")
                return
        self._sync_now()  # pull server delta; re-runs a live filter/search view

    def action_reminders(self) -> None:
        table = self.query_one(TaskTable)
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        if len(ids) == 1:
            row = next((r for r in self._rows if str(r.id) == ids[0]), None)
            if row is None:
                return
            allow_relative = self._has_due_time(ids[0])
            screen = RemindersScreen(
                self._clock.today(), row.reminders, allow_relative, mode="manage"
            )
        else:  # a selection: add one reminder to each, no per-task list to show
            screen = RemindersScreen(
                self._clock.today(), allow_relative=True, mode="add"
            )
        self.push_screen(
            screen, lambda request: self._on_reminder_request(ids, request)
        )

    def _on_reminder_request(
        self, ids: list[str], request: ReminderRequest | None
    ) -> None:
        if request is None:  # cancelled
            return
        if request.add_absolute:  # finish by picking the date + time
            self.push_screen(
                ScheduleScreen(self._clock.today(), kind="due"),
                lambda result: self._on_reminder_absolute(ids, result),
            )
        elif request.delete_id is not None:
            self._delete_reminder(request.delete_id)
        elif request.add_relative is not None:
            # a relative reminder only fires on a task that has a due time, so drop
            # targets without one rather than let the server reject them mid-batch
            eligible = [task_id for task_id in ids if self._has_due_time(task_id)]
            if not eligible:
                self._set_status("Relative reminder needs a task with a due time")
                return
            template = Reminder(
                id="", item_id="", type="relative", minute_offset=request.add_relative
            )
            self._add_reminders(eligible, template)

    def _has_due_time(self, task_id: str) -> bool:
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        return row is not None and row.due is not None and row.due.time is not None

    def _on_reminder_absolute(self, ids: list[str], result: DueResult | None) -> None:
        if result is None or result.due is None:  # picker cancelled or cleared
            return
        template = Reminder(id="", item_id="", type="absolute", due=result.due)
        self._add_reminders(ids, template)

    @work
    async def _add_reminders(self, ids: list[str], template: Reminder) -> None:
        for task_id in ids:
            try:
                await add_reminder(self._repo, replace(template, item_id=task_id))
            except Exception as error:  # command rejected: resync, then report
                await self._reload(self._view)
                self._set_status(f"Failed to add reminder: {error}")
                return
        self._selected.clear()
        self._sync_now()  # pull the new reminders so the bell count updates

    @work
    async def _delete_reminder(self, reminder_id: str) -> None:
        try:
            await delete_reminder(self._repo, reminder_id)
        except Exception as error:  # command rejected: resync, then report
            await self._reload(self._view)
            self._set_status(f"Failed to delete reminder: {error}")
            return
        self._sync_now()

    async def _reload(self, view: View) -> None:
        try:
            rows = await load_view(self._repo, view)
        except Exception as error:  # surface any load failure to the user
            self._set_status(f"Failed to load tasks: {error}")
            return
        arrangement = await self._arrangements.get(view.key, view.default_arrangement)
        if arrangement != self._arrangement:
            self._collapsed.clear()  # regrouping makes the folded label paths stale
        self._arrangement = arrangement
        rows = self._drop_closed(rows)
        rows = self._apply_pending_edits(rows)
        self._rows = rows  # retained so a priority keypress can re-arrange locally
        self._selected &= {str(r.id) for r in rows}  # drop ids gone from the view
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
        return prune(rows, lambda row: str(row.id) in self._pending_close)

    def _arrange(self, rows: list[TaskRow]) -> list[RenderRow[TaskRow]]:
        return arrange(
            rows,
            self._arrangement,
            frozenset(self._expanded),
            frozenset(self._collapsed),
        )

    def on_task_table_expand(self, _message: TaskTable.Expand) -> None:
        table = self.query_one(TaskTable)
        group = self._cursor_group_path(table)
        if group is not None:  # on a group header: unfold it
            if group in self._collapsed:
                self._collapsed.discard(group)
                self._repaint()
            return
        task_id = self._cursor_task_id(table)
        if task_id is None or task_id in self._expanded:
            return
        if not self._has_children(task_id):  # nothing to reveal
            return
        self._expanded.add(TaskId(task_id))
        self._repaint()  # cursor stays on it

    def on_task_table_collapse(self, _message: TaskTable.Collapse) -> None:
        table = self.query_one(TaskTable)
        group = self._cursor_group_path(table)
        if group is not None:
            if group not in self._collapsed:  # an open group: fold it away
                self._collapsed.add(group)
                self._repaint()
            elif len(group) > 1:  # already folded: step out to the enclosing group
                self._move_cursor_to_group(table, group[:-1])
            return
        task_id = self._cursor_task_id(table)
        if task_id is None:
            return
        if task_id in self._expanded:  # an expanded parent: fold it away
            self._expanded.discard(TaskId(task_id))
            self._repaint()  # cursor stays on it
            return
        parent_id = self._parent_of(task_id)  # a leaf/child: step out to the parent
        if parent_id is not None:
            self._move_cursor_to_task(table, parent_id)

    def _drop_departed(self, edited: set[str]) -> list[TaskRow]:
        """The rows left after an edit to `edited`: those the view still wants.

        A filter's membership needs the server, so the edited tasks are assumed
        gone and the background refresh restores any that still match.
        """
        if self._view.keeps is not None:  # membership is decidable here and now
            today = self._clock.today()
            keeps = self._view.keeps
            return prune(self._rows, lambda row: not keeps(row, today))
        if self._active_server_query is not None:
            return prune(self._rows, lambda row: str(row.id) in edited)
        return self._rows

    def _has_children(self, task_id: str) -> bool:
        return any(row.parent_id == task_id for row in self._rows)

    def _parent_of(self, task_id: str) -> str | None:
        row = next((r for r in self._rows if str(r.id) == task_id), None)
        return row.parent_id if row is not None else None

    def _move_cursor_to_group(self, table: TaskTable, path: GroupPath) -> None:
        for row, group in self._header_paths.items():
            if group == path:
                table.move_cursor(row=row)
                return

    def _move_cursor_to_task(self, table: TaskTable, task_id: str) -> None:
        for row in range(table.row_count):
            key = table.coordinate_to_cell_key(Coordinate(row, 0)).row_key
            if _task_id_of(str(key.value)) == task_id:
                table.move_cursor(row=row)
                return

    def _repaint(self) -> None:
        """Redraw the open view from the rows already loaded."""
        self._render(self._arrange(self._rows), self._view)

    def _render(self, render_rows: list[RenderRow[TaskRow]], view: View) -> None:
        try:
            table = self.query_one(TaskTable)
        except NoMatches:  # background resync landed mid-teardown: nothing to draw
            return
        prior = self._cursor_task_id(table)  # survive the clear+rebuild below
        prior_group = self._cursor_group_path(table)
        # at render time, not import: the styles follow the live theme
        styles = tier_styles(table)
        today = self._clock.today()
        first_row_of: dict[str, int] = {}
        header_row_of: dict[GroupPath, int] = {}
        first_task_row: int | None = None
        # drop metadata columns empty for every visible task, so short lists don't
        # strand three near-blank columns beside the titles
        tasks = [item.row for item in render_rows if isinstance(item, TaskLine)]
        show_labels = any(t.labels for t in tasks)
        # a reminder rides in the due cell, so it alone keeps that column alive
        show_due = any(t.due or t.reminders for t in tasks)
        show_deadline = any(t.deadline for t in tasks)
        show_project = any(t.project_name for t in tasks)
        columns = ["", "TASK"]
        if show_labels:
            columns.append("LABELS")
        if show_due:
            columns.append("DUE")
        if show_deadline:
            columns.append("DEADLINE")
        if show_project:
            columns.append("PROJECT")
        table.clear(columns=True)
        table.add_columns(*columns)
        self._header_paths = {}
        titles = {
            index: _title_cell(item, styles)
            for index, item in enumerate(render_rows)
            if isinstance(item, TaskLine)
        }
        # a divider spans the titles it divides: running it to the terminal edge
        # would widen the title column and push the metadata into a scroll
        target_width = max((cell_len(t.plain) for t in titles.values()), default=0)
        for index, item in enumerate(render_rows):
            if isinstance(item, GroupHeader):
                divider = _header_text(item, today, target_width, styles)
                header = ["", divider] + [""] * (len(columns) - 2)
                table.add_row(*header, key=_header_key(index))
                self._header_paths[index] = item.path
                header_row_of[item.path] = index
                continue
            row = item.row
            title = titles[index]
            selected = str(row.id) in self._selected
            if selected:  # only the title lifts; its metadata keeps receding
                title.style = styles[Tier.ACCENT]
            cells: list[Text | str] = [
                _marker_cell(selected, row.priority, styles),
                title,
            ]
            if show_labels:
                cells.append(_labels_cell(row.labels, styles[Tier.MUTED]))
            if show_due:
                cells.append(_due_cell(row.due, row.reminders, today, styles))
            if show_deadline:
                cells.append(_deadline_cell(row.deadline, today, styles))
            if show_project:
                cells.append(_project_cell(row.project_name, styles[Tier.MUTED]))
            table.add_row(*cells, key=_task_key(index, row.id))
            if first_task_row is None:
                first_task_row = index
            first_row_of.setdefault(str(row.id), index)
        if prior_group is not None and prior_group in header_row_of:
            table.move_cursor(row=header_row_of[prior_group])  # keep it on the group
        elif prior is not None and prior in first_row_of:
            table.move_cursor(row=first_row_of[prior])  # keep highlight on the task
        elif first_task_row is not None:
            table.move_cursor(row=first_task_row)  # never rest on a leading header
        # the view's own tasks, not the visible lines: collapsing a parent or
        # revealing a subtask pulled in for context must not move the number
        matched = sum(1 for row in self._rows if row.matched)
        self._set_count_status(view.title, matched)

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

    def _targets(self, table: TaskTable) -> list[str]:
        """The task ids an action applies to: the selection if any (in display
        order), else the cursor row, else nothing."""
        if self._selected:
            return [str(r.id) for r in self._rows if str(r.id) in self._selected]
        task_id = self._cursor_task_id(table)
        return [task_id] if task_id is not None else []

    def _cursor_task_id(self, table: TaskTable) -> str | None:
        if table.row_count == 0:
            return None
        key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return _task_id_of(key)

    def _cursor_group_path(self, table: TaskTable) -> GroupPath | None:
        """The group whose header the cursor sits on, or None on a task row."""
        if table.row_count == 0:
            return None
        return self._header_paths.get(table.cursor_row)

    def _set_status(self, message: str) -> None:
        """A progress or error line, holding the band until the next paint."""
        self._status_base = message
        self._status_tally = ""
        self._render_status()

    def _set_count_status(self, title: str, count: int) -> None:
        self._status_base = title
        tally = "no tasks" if count == 0 else f"{count} task(s)"
        self._status_tally = f" · {tally}"
        self._render_status()

    def _set_syncing(self, syncing: bool) -> None:
        self._syncing = syncing
        self._render_status()

    def _render_status(self) -> None:
        try:
            band = self.query_one(StatusBand)
        except NoMatches:  # background resync landed mid-teardown: nothing to draw
            return
        selected = f"  · {len(self._selected)} selected" if self._selected else ""
        marker = "  ⟳" if self._syncing else ""
        band.show(
            self._status_base,
            f"{self._status_tally}{selected}{marker}",
            _arrangement_summary(self._arrangement),
        )


_RECURRING_GLYPH = " ↻"
_SELECT_MARKER = "▌"  # bar on a multi-selected row


def _marker_cell(
    selected: bool, priority: Priority, styles: Mapping[Tier, Style]
) -> Text:
    """The selection bar and the priority dot share the leading column, so
    selecting a row never shifts its title sideways."""
    bar = _SELECT_MARKER if selected else " "
    return Text.assemble((bar, styles[Tier.ACCENT]), priority_dot(priority))


def _title_cell(line: TaskLine[TaskRow], styles: Mapping[Tier, Style]) -> Text:
    """The task title, leading its row; only the description marker recedes."""
    row = line.row
    title = Text(_indent(line.level), style=styles[Tier.PRIMARY])
    title.append(_expand_marker(line))
    title.append_text(render_links(row.content))
    if marker := description_marker(row.description):
        title.append(marker, style=styles[Tier.MUTED])
    return title


def _due_cell(
    due: Due | None,
    reminders: tuple[Reminder, ...],
    today: datetime.date,
    styles: Mapping[Tier, Style],
) -> Text | str:
    """The due label graded by urgency, trailed by a bell when the task has
    reminders — they share the column so a rare reminder costs no width of its
    own. Both trailing marks recede, so only the due itself carries the grade.
    The detail card spells the reminders out."""
    muted = styles[Tier.MUTED]
    badge = format_reminder_badge(len(reminders)) if reminders else ""
    if due is None:
        return Text(badge, style=muted)
    cell = Text(format_due(due, today), style=styles[due_tier(due, today)])
    if due.is_recurring:  # detail card shows the full rule; here just a quiet mark
        cell.append(_RECURRING_GLYPH, style=muted)
    if badge:
        cell.append(f" {badge}", style=muted)
    return cell


def _deadline_cell(
    deadline: Deadline | None, today: datetime.date, styles: Mapping[Tier, Style]
) -> Text | str:
    if deadline is None:
        return ""
    label = format_deadline(deadline, today)
    return Text(label, style=styles[date_tier(deadline.date, today)])


def _project_cell(project_name: str | None, style: Style) -> Text | str:
    return Text(project_name, style=style) if project_name else ""


def _labels_cell(labels: tuple[str, ...], style: Style) -> Text | str:
    line = format_labels(labels)
    return Text(line, style=style) if line else ""


def _header_text(
    header: GroupHeader,
    today: datetime.date,
    target_width: int,
    styles: Mapping[Tier, Style],
) -> Text:
    """A divider carrying the group's label: the label leads in the accent, the
    rules on either side recede. `target_width` is the width of the titles the
    divider spans."""
    label = header.label
    if header.field is Field.DUE_DATE:
        # the bucket label is ISO (a stable grouping key) except "No due date"
        with contextlib.suppress(ValueError):
            label = humanize_date(datetime.date.fromisoformat(label), today)
    label = f"{label} ({header.count})"
    marker = _FOLD_SHUT if header.collapsed else _FOLD_OPEN
    lead = f"{_indent(header.level)}{marker}── "  # marker counted, so rules align
    rule = styles[Tier.MUTED]
    # top level is the boldest divider; deeper ones recede to a plain accent
    accent = styles[Tier.ACCENT] + Style(bold=header.level == 0)
    spanned = cell_len(lead) + cell_len(label) + 1  # +1 for the space before the fill
    fill = "─" * max(_MIN_FILL, target_width - spanned)
    text = Text(lead, style=rule)
    text.append(label, style=accent)
    text.append(f" {fill}", style=rule)
    return text


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
    return "    ".join(parts)  # the band right-aligns it; no lead-in needed


def _expand_marker(line: TaskLine[TaskRow]) -> str:
    if not line.has_children:
        return ""  # leaves carry no marker (and don't shift childless lists)
    return _FOLD_OPEN if line.expanded else _FOLD_SHUT
