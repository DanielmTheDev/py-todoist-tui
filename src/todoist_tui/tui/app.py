import asyncio
import contextlib
import datetime
import uuid
from collections.abc import Callable, Coroutine, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import ClassVar

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Rule, Static

from todoist_tui.application.activity import ActivityRow, load_activity
from todoist_tui.application.add_reminder import add_reminder
from todoist_tui.application.add_task import add_task
from todoist_tui.application.complete import complete_task, uncomplete_task
from todoist_tui.application.delete import delete_section, delete_task
from todoist_tui.application.delete_reminder import delete_reminder
from todoist_tui.application.duplicate import duplicate_project, duplicate_section
from todoist_tui.application.move_task import move_task, move_to_parent
from todoist_tui.application.mutation import (
    Mutation,
    apply,
    edit,
    hide,
    restore,
    touched,
)
from todoist_tui.application.outbox import Command, Outbox
from todoist_tui.application.reorder import reorder, set_day_orders
from todoist_tui.application.set_deadline import set_deadline
from todoist_tui.application.set_due import set_due
from todoist_tui.application.set_labels import set_labels
from todoist_tui.application.set_priority import set_priority
from todoist_tui.application.set_text import set_text
from todoist_tui.application.views import (
    ALL,
    INBOX,
    TODAY,
    TaskRow,
    View,
    all_views,
    load_view,
    prune,
    query_for_key,
    search_view,
    view_from_key,
    with_subtrees,
)
from todoist_tui.domain.activity import EventKind
from todoist_tui.domain.arrange import (
    Arrangement,
    Field,
    GroupHeader,
    GroupPath,
    ManualOrder,
    RenderRow,
    TaskLine,
    arrange,
    group_path_of,
    group_paths,
)
from todoist_tui.domain.clock import Clock, SystemClock
from todoist_tui.domain.creation import NewChild
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.humanize import humanize_date
from todoist_tui.domain.links import LinkOpener, XdgOpenLinkOpener
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import (
    Reminder,
    default_reminder,
    wants_default_reminder,
)
from todoist_tui.domain.reorder import day_order_plan, swap_with_neighbour
from todoist_tui.domain.repository import (
    ArrangementStore,
    FoldStore,
    TaskRepository,
    ViewSlotStore,
)
from todoist_tui.domain.search import SearchTerm
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import TaskId
from todoist_tui.domain.view_slots import ViewSlots
from todoist_tui.tui.columns import (
    GUTTER,
    MARKER_SLOT,
    Column,
    fit_columns,
    fit_row,
)
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
from todoist_tui.tui.screens.activity import ActivityScreen
from todoist_tui.tui.screens.arrange import ArrangeScreen, Mode
from todoist_tui.tui.screens.confirm import ConfirmScreen
from todoist_tui.tui.screens.detail import (
    CARD_BINDINGS,
    FORWARDED,
    TaskDetailScreen,
)
from todoist_tui.tui.screens.draft import Subtask, TaskDraft, draft_of
from todoist_tui.tui.screens.edit import Catalog, TaskEditScreen
from todoist_tui.tui.screens.help import (
    HelpScreen,
    as_binding,
    pressed,
    shortcut_rows,
)
from todoist_tui.tui.screens.labels import LabelsScreen
from todoist_tui.tui.screens.parent_picker import ParentPickerScreen, ParentTarget
from todoist_tui.tui.screens.project_picker import MoveTarget, ProjectPickerScreen
from todoist_tui.tui.screens.reminders import ReminderRequest, RemindersScreen
from todoist_tui.tui.screens.schedule import DueResult, ScheduleScreen, rescheduled
from todoist_tui.tui.screens.search import SearchScreen
from todoist_tui.tui.screens.text_prompt import TextPromptScreen
from todoist_tui.tui.screens.views import ViewsOutcome, ViewsScreen
from todoist_tui.tui.theme import (
    PALETTE_CLASSES,
    PALETTE_CSS,
    TODOIST_THEME,
    Tier,
    priority_styles,
    tier_styles,
)

_SYNC_INTERVAL_SECONDS = 60.0  # Todoist has no push; poll incrementally
_INDENT = "  "  # per nesting level, for group headers and their tasks
_MIN_FILL = 3  # so a label as wide as the titles still trails a visible rule
_SUMMARY_GAP = 2  # least space between the status message and the arrangement
_FOLD_OPEN = "▾ "  # subtree shown — on a parent task or a group header
_FOLD_SHUT = "▸ "  # subtree folded away
_SELECT_MARKER = "▌"  # bar on a multi-selected row
PENDING_MARK = " ⟳"  # trails a row whose change Todoist hasn't confirmed yet
# leads the id this client gives a task Todoist has yet to name, so an action
# can tell one apart from a task the server would actually recognise
_PROVISIONAL = "new-"
_STILL_CREATING = "Still being created — try that again in a moment"


def card_rows(bindings: list[BindingType]) -> list[tuple[str, str]]:
    """The task card's shortcuts: the list actions it forwards, described as the
    list describes them but keyed as the card reaches them, then what only the
    card can do. Several keys onto one action list as one row."""
    described = {b.action: b.description for b in map(as_binding, bindings)}
    keys: dict[str, list[str]] = {}
    for key, action in FORWARDED.items():
        keys.setdefault(action, []).append(key)
    forwarded = [
        (pressed(*reached), described[action]) for action, reached in keys.items()
    ]
    return forwarded + shortcut_rows(CARD_BINDINGS)


@dataclass(frozen=True)
class Close:
    """One `item_close`, and everything it takes down with it.

    Todoist closes a task's whole subtree, so a single command hides several rows
    — `rows` holds them, parent first, to hide, unhide and reopen as one unit.
    """

    task_id: TaskId
    rows: list[TaskRow]


@dataclass(frozen=True, slots=True)
class Step:
    """One change on its way to Todoist: what it does to the open view, the
    command that carries it, and how a rejection is reported."""

    # None when nothing on screen changes yet; several where one command patches
    # several rows in different ways, as a swap does
    mutation: Mutation | Sequence[Mutation] | None
    command: Command
    label: str


# how many actions `z` can walk back; deep enough for a slip, not a history
_UNDO_DEPTH = 20


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


class InMemoryFolds:
    """Session-only fold store (the default when none is injected)."""

    def __init__(self) -> None:
        self._by_key: dict[str, frozenset[GroupPath]] = {}

    async def get(self, view_key: str) -> frozenset[GroupPath]:
        return self._by_key.get(view_key, frozenset())

    async def save(self, view_key: str, open_groups: frozenset[GroupPath]) -> None:
        self._by_key[view_key] = open_groups


class InMemoryViewSlots:
    """Session-only view-slot store (the default when none is injected)."""

    def __init__(self) -> None:
        self._slots = ViewSlots()

    async def get(self) -> ViewSlots:
        return self._slots

    async def save(self, slots: ViewSlots) -> None:
        self._slots = slots


class StatusBand(Static):
    """The band above the table: which view is open on the left, how it's arranged
    on the right. Also the app's error channel, so it holds arbitrary text."""

    COMPONENT_CLASSES: ClassVar[set[str]] = set(PALETTE_CLASSES)
    DEFAULT_CSS = PALETTE_CSS

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


class ColumnHeader(Static):
    """The column labels, as a widget rather than the table's own header row — so a
    separator can sit under them, and so they align to the widths `_render`
    computed rather than to whatever the table decided."""

    COMPONENT_CLASSES: ClassVar[set[str]] = set(PALETTE_CLASSES)
    DEFAULT_CSS = PALETTE_CSS

    def __init__(self) -> None:
        super().__init__(id="columns", markup=False)
        self._columns: list[Column] = []

    def show(self, columns: list[Column]) -> None:
        self._columns = columns
        self.update(self._content())

    def _content(self) -> Text:
        muted = tier_styles(self)[Tier.MUTED]
        labels = "".join(
            # the first column opens with the marker slot, so its label clears it
            (MARKER_SLOT + column.label if position == 0 else column.label).ljust(
                column.width
            )
            for position, column in enumerate(self._columns)
        )
        return Text(labels.rstrip(), style=muted)


class TaskTable(DataTable[object]):
    """DataTable with j/k or up/down row nav and h/l or left/right collapse/expand.

    The cursor rests on group headers too, since they fold. Collapse/expand don't
    move the column cursor (the table is row-mode); they ask the app to
    collapse/expand whatever the cursor sits on — a task's subtasks, or a group.
    Binding left/right here shadows DataTable's horizontal scroll, which is
    useless in row mode.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = (
        DataTable.COMPONENT_CLASSES | PALETTE_CLASSES
    )
    DEFAULT_CSS = PALETTE_CSS

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j,down", "cursor_down", "Down", show=False),
        Binding("k,up", "cursor_up", "Up", show=False),
        Binding("h,left", "collapse", "Collapse task/group", show=False),
        Binding("l,right", "expand", "Expand task/group", show=False),
        Binding("H", "collapse_all", "Fold every group and subtask", show=False),
        Binding("L", "expand_all", "Unfold every group and subtask", show=False),
        Binding("J", "move_down", "Move task down", show=False),
        Binding("K", "move_up", "Move task up", show=False),
    ]

    class Expand(Message):
        """Reveal the subtasks, or the folded group, under the cursor."""

    class Collapse(Message):
        """Fold the subtasks or group under the cursor, else step out to its parent."""

    class ExpandAll(Message):
        """Unfold every group and subtask tree in the list."""

    class CollapseAll(Message):
        """Fold every group and subtask tree in the list."""

    class MoveDown(Message):
        """Trade the task under the cursor with the sibling below it."""

    class MoveUp(Message):
        """Trade the task under the cursor with the sibling above it."""

    class Resized(Message):
        """The table got wider or narrower, so the column stretch needs redoing."""

    def on_resize(self) -> None:
        self.post_message(self.Resized())

    def action_expand(self) -> None:
        self.post_message(self.Expand())

    def action_collapse(self) -> None:
        self.post_message(self.Collapse())

    def action_expand_all(self) -> None:
        self.post_message(self.ExpandAll())

    def action_collapse_all(self) -> None:
        self.post_message(self.CollapseAll())

    def action_move_down(self) -> None:
        self.post_message(self.MoveDown())

    def action_move_up(self) -> None:
        self.post_message(self.MoveUp())


class TodoistApp(App[None]):
    """Row-highlighted task table over Today, Inbox, project, and filter views,
    opening on a persisted home view."""

    # absolute: a relative path resolves against the *subclass's* module, which
    # would send a test-local subclass looking in the tests directory
    CSS_PATH = Path(__file__).with_name("app.tcss")

    BINDINGS: ClassVar[list[BindingType]] = [
        # f1 too: inside the editor `?` is a character the fields take
        Binding("question_mark,f1", "help", "Help"),  # the only footer entry
        Binding("e", "complete", "Complete", show=False),
        Binding("delete", "delete", "Delete", show=False),
        Binding("z", "undo", "Undo", show=False),
        Binding("i", "view_inbox", "Inbox", show=False),
        Binding("slash", "search", "Search", show=False),
        Binding("p", "views", "Views", show=False),
        Binding("c", "activity", "Activity", show=False),
        Binding("g", "arrange_group", "Group", show=False),
        Binding("s", "arrange_sort", "Sort", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("t", "set_due", "Due", show=False),
        Binding("d", "set_deadline", "Deadline", show=False),
        Binding("v", "move_task", "Move", show=False),
        # `n` for nest; `V` stays bound for the fingers that learned it
        Binding("n,V", "move_parent", "Move under parent", show=False),
        Binding("Y", "duplicate", "Duplicate project/section", show=False),
        Binding("D", "delete_section", "Delete section", show=False),
        Binding("at", "set_labels", "Labels", show=False),
        Binding("m,R", "reminders", "Reminders", show=False),
        Binding("enter", "open_detail", "Detail", show=False),
        Binding("ctrl+e", "edit_task", "Edit title + description", show=False),
        Binding("a", "add_task", "Add task", show=False),
        Binding("A", "add_subtask", "Add subtask", show=False),
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
        slots: ViewSlotStore | None = None,
        folds: FoldStore | None = None,
    ) -> None:
        super().__init__()
        self.register_theme(TODOIST_THEME)
        self.theme = TODOIST_THEME.name
        self._repo = repo
        self._arrangements = arrangements or InMemoryArrangements()
        self._slots = slots or InMemoryViewSlots()
        self._folds = folds or InMemoryFolds()
        self._clock = clock or SystemClock()
        self._link_opener = link_opener or XdgOpenLinkOpener()
        self._arrangement = Arrangement()  # current view's group/sort
        self._rows: list[TaskRow] = []  # last loaded rows, as the server has them
        self._visible: list[TaskRow] = []  # `_rows` with the outbox replayed on top
        self._expanded: set[TaskId] = set()  # tasks whose subtasks are shown
        self._open_groups: set[GroupPath] = set()  # groups unfolded to show members
        self._folds_key: str | None = None  # the view `_open_groups` was loaded for
        self._header_paths: dict[int, GroupPath] = {}  # header row index → its group
        # the view key + group the next load of that view opens at, from a picked
        # section — keyed so an interleaved reload of another view drops it
        self._pending_land: tuple[str, GroupPath] | None = None
        self._selected: set[str] = set()  # tasks marked for the next bulk action
        self._view = TODAY
        self._syncing = False
        self._status_base = ""  # the band's left-hand line: view title, or an error
        self._status_tally = ""  # " · 9 task(s)", blank while an error is shown
        # the project every visible task shares, which the column drops as noise
        self._shared_project: str | None = None
        self._laid_out = -1  # table width the current column stretch was sized for
        # local changes the server hasn't confirmed: replayed over every reload,
        # so a sync already in flight can't revert what the user just did
        self._outbox = Outbox(
            resync=self._resync,
            on_change=self._repaint,
            on_error=self._set_status,
            spawn=self._spawn,
        )
        self._undo: list[list[Step]] = []  # reversals, one batch per action
        self._batching = False  # a batch paints once, when all of it is queued
        self._syncs = asyncio.Lock()  # one snapshot fetch at a time
        self._slot_writes = asyncio.Lock()  # one jump-key write at a time
        self._fold_writes = asyncio.Lock()  # one fold-state write at a time
        self._inbox_id: str | None = None  # so a move out of the Inbox drops the row
        self._picking_project = False  # guards against stacking project pickers
        self._picking_parent = False  # guards against stacking parent pickers
        self._picking_duplicate = False  # guards the duplicate picker + name prompt
        # guards the section-delete picker + its confirmation
        self._picking_delete_section = False
        self._picking_views = False  # guards against stacking the views screen
        self._bound = ViewSlots()  # jump keys, reloaded from the store on mount
        self._picking_labels = False  # guards against stacking the labels editor
        self._reading_activity = False  # guards against stacking the activity feed
        # the server query of the open view — a saved filter's, or a search's —
        # re-run on every sync so that view stays live
        self._active_server_query: str | None = None
        # the task whose card started the action now running, and which the card
        # will show again once that action has settled
        self._detail_scope: str | None = None

    def compose(self) -> ComposeResult:
        yield StatusBand()
        yield Rule(line_style="solid")
        yield ColumnHeader()
        yield Rule(line_style="solid")
        yield TaskTable()
        yield Footer()

    def on_task_table_resized(self, _: TaskTable.Resized) -> None:
        """The last column stretches to the right edge, so a width change has to
        redraw. Guarded on the width actually differing: repainting adds rows,
        which can move the scrollbar, which would resize us again."""
        if self.query_one(TaskTable).scrollable_content_region.width != self._laid_out:
            self._repaint()

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return {"gutter": str(GUTTER)}  # so the stylesheet shares the one constant

    async def on_mount(self) -> None:
        table = self.query_one(TaskTable)
        table.cursor_type = "row"
        # the cursor tints the background only, so each cell keeps its own tier
        table.cursor_foreground_priority = "renderable"
        table.show_header = False  # ColumnHeader draws them, so a rule can follow
        table.cell_padding = 0  # so a group divider runs unbroken across columns
        self._bound = await self._slots.get()
        self._view, self._active_server_query = await self._resolve_startup()
        await self._reload(self._view)  # instant: served from cache when present
        self._sync_now()  # for a filter home, this also refreshes it live
        self.set_interval(self.SYNC_INTERVAL, self._sync_now)

    @work(exclusive=True, group="reload")
    async def _sync_now(self) -> None:
        await self._resync()

    async def _resync(self) -> None:
        """Fetch a fresh snapshot and redraw. Confirms every local change the
        server had already acknowledged when the fetch started — one begun
        earlier could still be carrying a snapshot from before them.

        The load happens *inside* the confirmation, so the rows it takes in are
        already in place when the changes retire. Retiring first would leave the
        pre-change snapshot with nothing on top of it, flashing a departed row
        back. Only the paint waits until after, so the fresh rows and the
        retirement reach the screen as one frame instead of two.
        """
        async with self._syncs:
            self._set_syncing(True)
            try:
                async with self._outbox.syncing():
                    await self._repo.refresh()
                    if self._active_server_query is not None:  # keep the filter live
                        await self._repo.refresh_filtered(self._active_server_query)
                    loaded = await self._load_rows(self._view)
                if loaded:
                    self._repaint()
            except Exception:  # offline or sync failed: keep the cached view
                pass
            finally:  # also runs on worker cancellation, so ⟳ never sticks
                self._set_syncing(False)

    def _spawn(self, coroutine: Coroutine[object, object, None]) -> None:
        self.run_worker(coroutine, group="outbox")

    def _queue(self, work: list[tuple[Step, Step | None]]) -> None:
        """Apply `work` to the view at once and send it in order, newest last.

        Each entry pairs a change with its reversal, or None where there is none
        to make (a delete is permanent). The reversals go on the undo stack as one
        batch; a step the server rejects takes its own reversal back out.
        """
        undo = [back for _, back in work if back is not None]
        self._batching = True
        try:
            for forward, back in work:
                self._outbox.queue(
                    forward.mutation,
                    forward.command,
                    forward.label,
                    partial(_forget, undo, back) if back is not None else None,
                )
        finally:
            self._batching = False
        if undo:
            self._undo.append(undo)
            del self._undo[:-_UNDO_DEPTH]
        self._repaint()

    def _send(self, command: Command, label: str) -> None:
        """Queue a command that changes nothing on screen until the next sync."""
        self._queue([(Step(None, command, label), None)])

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

    async def _resolve_startup(self) -> tuple[View, str | None]:
        """The view the slots open on and its server query (None unless a filter or
        a search), falling back to Today when unmarked or its target is gone."""
        key = self._bound.startup
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

    def action_view_inbox(self) -> None:
        self._active_server_query = None
        self._switch_to(INBOX)

    async def action_views(self) -> None:
        if self._picking_views:  # already loading or the screen is already open
            return
        self._picking_views = True
        try:
            projects = await self._repo.projects()
            filters = await self._repo.filters()
            sections = await self._repo.sections()
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load views: {error}")
            self._picking_views = False
            return
        self.push_screen(
            ViewsScreen(
                all_views(projects, filters, sections),
                self._bound,
                self._taken_keys(),
                self._view.key,
            ),
            self._on_views_closed,
        )

    async def action_activity(self) -> None:
        if self._reading_activity:  # already loading or the feed is already open
            return
        self._reading_activity = True
        try:
            rows, cursor = await self._activity_page(None, None)
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load activity: {error}")
            self._reading_activity = False
            return
        self.push_screen(
            ActivityScreen(rows, self._clock.today(), self._activity_page, cursor),
            self._on_activity_closed,
        )

    async def _activity_page(
        self, event_type: EventKind | None, cursor: str | None
    ) -> tuple[tuple[ActivityRow, ...], str | None]:
        return await load_activity(self._repo, event_type, cursor)

    def _on_activity_closed(self, _result: None) -> None:
        self._reading_activity = False

    def _taken_keys(self) -> dict[str, str]:
        """Every key a binding already owns, named by what it does — a jump key that
        shadowed one would silently disable it, so the screen refuses those."""
        return {
            key: active.binding.description or active.binding.action
            for key, active in self.active_bindings.items()
        }

    def _on_views_closed(self, outcome: ViewsOutcome | None) -> None:
        self._picking_views = False
        if outcome is None:  # dismissed with no result
            return
        if outcome.slots != self._bound:
            self._bound = outcome.slots
            self.run_worker(self._save_bound())
        if outcome.jump is not None:
            self.run_worker(self._go_to(outcome.jump.key, outcome.jump.land_section))

    async def _save_bound(self) -> None:
        """One write at a time, each carrying what is bound when it starts: writes
        that overtook each other would put an earlier edit's slots back."""
        async with self._slot_writes:
            await self._slots.save(self._bound)

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

    def on_key(self, event: events.Key) -> None:
        """Jump keys are bound at runtime rather than declared, so they are matched
        here. App-level keys also arrive under a modal, where they must stand down."""
        if self.screen is not self.screen_stack[0]:
            return
        if event.character is None:  # only printable keys can be bound
            return
        view_key = self._bound.view_key_for(event.character)
        if view_key is None:
            return
        event.stop()
        event.prevent_default()
        self.run_worker(self._jump(event.character, view_key))

    async def _jump(self, key: str, view_key: str) -> None:
        if not await self._go_to(view_key):
            self._set_status(f"{key} no longer opens anything")

    async def _go_to(self, view_key: str, land_section: str | None = None) -> bool:
        """Open the view a stored key names; False when its target is gone."""
        try:
            projects = await self._repo.projects()
            filters = await self._repo.filters()
        except Exception:  # offline before the first sync
            return False
        view = view_from_key(view_key, projects, filters)
        if view is None:  # the project or filter it named was deleted
            return False
        # unconditionally, so a plain jump clears the pending of an earlier one
        self._pending_land = (
            None if land_section is None else (view.key, (land_section,))
        )
        query = query_for_key(view_key, filters)
        self._active_server_query = query
        if query is None:
            self._switch_to(view)
        else:  # a filter or search: revalidate it live
            self._view = view
            self._open_filter(view, query)
        return True

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
        closes: list[Close] = []
        claimed: set[str] = set()
        for task_id in ids:
            if task_id in claimed:  # a selected subtask closes with its parent, once
                continue
            subtree = with_subtrees(self._visible, {task_id}) - claimed
            # view order, so a parent precedes the subtasks it takes with it
            rows = [row for row in self._visible if str(row.id) in subtree]
            claimed |= subtree
            closes.append(Close(TaskId(task_id), rows))
        self._selected.clear()
        self._queue(
            [(_close_step(self._repo, c), self._reopen_step(c)) for c in closes]
        )
        self._focus_task_at(table, cursor_row)

    def _reopen_step(self, close: Close) -> Step:
        return Step(
            restore(close.rows), partial(self._reopen, close.rows), "Failed to undo"
        )

    async def _reopen(self, rows: list[TaskRow]) -> None:
        # item_uncomplete restores ancestors only, so each closed child reopens itself
        for row in rows:
            await uncomplete_task(self._repo, TaskId(str(row.id)))

    def action_undo(self) -> None:
        while self._undo:
            batch = self._undo.pop()
            if batch:  # a batch the server rejected outright has nothing left to undo
                self._queue([(step, None) for step in reversed(batch)])
                return

    def action_delete(self) -> None:
        table = self.query_one(TaskTable)
        pairs = [
            (TaskId(task_id), row)
            for task_id in self._targets(table)
            if (row := next((r for r in self._visible if str(r.id) == task_id), None))
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
        self._push(
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
        self._selected.clear()
        self._queue(  # delete is permanent, so there is no reversal to record
            [
                (
                    Step(
                        hide([str(task_id)]),
                        partial(delete_task, self._repo, task_id),
                        "Failed to delete task",
                    ),
                    None,
                )
                for task_id, _ in pairs
            ]
        )
        self._focus_task_at(table, cursor_row)

    def action_set_priority(self, name: str) -> None:
        table = self.query_one(TaskTable)
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        priority = Priority[name]
        rows = self._rows_of(ids)
        self._selected.clear()
        self._queue(
            [
                (
                    self._priority_step(str(row.id), priority),
                    self._priority_step(str(row.id), row.priority),
                )
                for row in rows
            ]
        )

    def _priority_step(self, task_id: str, priority: Priority) -> Step:
        return Step(
            edit([task_id], priority=priority),
            partial(set_priority, self._repo, TaskId(task_id), priority),
            "Failed to set priority",
        )

    def action_set_due(self) -> None:
        table = self.query_one(TaskTable)
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        # one target keeps its date prefilled; a selection opens on a blank date
        row = next((r for r in self._visible if str(r.id) == ids[0]), None)
        single = row.due if len(ids) == 1 and row else None
        self._push(
            ScheduleScreen(
                self._clock.today(),
                single.date if single else None,
                single.time if single else None,
                allow_text=True,
                current_text=single.string if single and single.is_recurring else None,
            ),
            lambda result: self._on_scheduled([TaskId(i) for i in ids], result),
        )

    def action_set_deadline(self) -> None:
        table = self.query_one(TaskTable)
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        row = next((r for r in self._visible if str(r.id) == ids[0]), None)
        current = row.deadline.date if len(ids) == 1 and row and row.deadline else None
        self._push(
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

    async def action_help(self) -> None:
        if isinstance(self.screen, HelpScreen):  # already open
            return
        # the editor's chords too: they are only live inside it, which the
        # descriptions say, and nothing else lists them
        rows = shortcut_rows(
            TodoistApp.BINDINGS, TaskTable.BINDINGS, TaskEditScreen.BINDINGS
        )
        self.push_screen(HelpScreen(rows + await self._jump_rows()))

    def on_task_detail_screen_help_requested(self) -> None:
        """`?` over the card answers with the card's keys, laid over it — the
        list's own shortcuts do not reach the task underneath."""
        self.push_screen(HelpScreen(card_rows(TodoistApp.BINDINGS)))

    async def _jump_rows(self) -> list[tuple[str, str]]:
        """The jump keys, so `?` lists them beside the built-in shortcuts."""
        try:
            projects = await self._repo.projects()
            filters = await self._repo.filters()
        except Exception:  # offline: the built-in shortcuts still stand
            return []
        rows: list[tuple[str, str]] = []
        for key, view_key in self._bound.by_key.items():
            view = view_from_key(view_key, projects, filters)
            if view is not None:  # a deleted project's key has nothing to name
                rows.append((key, f"Open {view.title}"))
        return rows

    def action_open_detail(self) -> None:
        row = self._cursor_row()
        if row is None:  # empty table or cursor on a group header
            return
        self._open_detail(row)

    def _open_detail(self, row: TaskRow) -> None:
        self.push_screen(
            TaskDetailScreen(
                row, self._link_opener, self._clock.today(), self._children_of(row)
            ),
            lambda action: self._on_detail_closed(row, action),
        )

    def _on_detail_closed(self, row: TaskRow, action: str | None) -> None:
        if not action:  # the card was simply closed
            return
        # every action reads its subject off the cursor, which the card has left
        # behind; scope it to the open task until the flow it starts is done
        self._detail_scope = str(row.id)
        self.run_worker(self._act_from_detail(action))

    async def _act_from_detail(self, action: str) -> None:
        try:
            await self.run_action(action)
        finally:
            # an action that opened nothing (a priority, a complete) is over
            # already; one that blew up must not leave the scope behind it
            self.call_after_refresh(self._restore_detail)

    def _restore_detail(self) -> None:
        """Show the card again once the action it started has run its course,
        carrying the task as it now stands. A task the action completed or
        deleted has no card to come back to."""
        if self._detail_scope is None or len(self.screen_stack) > 1:
            return  # nothing pending, or a modal of the flow is still open
        task_id, self._detail_scope = self._detail_scope, None
        row = next((r for r in self._visible if str(r.id) == task_id), None)
        if row is not None:
            self._open_detail(row)

    def _push[T](self, screen: Screen[T], callback: Callable[[T | None], None]) -> None:
        """Push a modal a card may have opened, so the card returns once the flow
        is done — including any modal this one goes on to push itself."""

        def settled(result: T | None) -> None:
            callback(result)
            self.call_after_refresh(self._restore_detail)

        self.push_screen(screen, settled)

    def action_add_task(self) -> None:
        row = self._cursor_row()
        self._open_add(
            "New task",
            replace(
                self._lands_beside(row),
                # so the task the user just wrote in Today actually shows up there
                due=Due(date=self._clock.today())
                if self._view.key == TODAY.key
                else None,
            ),
        )

    def action_add_subtask(self) -> None:
        row = self._named_cursor_row()
        if row is None:  # empty table, a group header, or a task not yet named
            return
        # a subtask inherits its parent's section, so only the project is carried
        self._open_add(
            "New subtask",
            TaskDraft(
                "",
                "",
                project_id=row.project_id,
                project_name=row.project_name or "",
                parent_id=str(row.id),
                parent=row,
            ),
        )

    def _lands_beside(self, row: TaskRow | None) -> TaskDraft:
        """Where a new task goes: the cursor row's company; on an empty view the
        view's own project; past that the Inbox the service falls back to."""
        if row is not None:
            return TaskDraft(
                "",
                "",
                project_id=row.project_id,
                project_name=row.project_name or "",
                section_id=row.section_id,
                section_name=row.section_name,
            )
        return TaskDraft(
            "",
            "",
            project_id=self._view.project_id,
            project_name=self._view.title if self._view.project_id else INBOX.title,
        )

    def _open_add(self, heading: str, draft: TaskDraft) -> None:
        self._push(
            TaskEditScreen(draft, self._clock.today(), self._catalog(), heading),
            self._on_new_task,
        )

    def _catalog(self, editing: str | None = None) -> Catalog:
        """What the editor's pickers choose from. A task being edited can nest
        under neither itself nor anything already beneath it."""
        return Catalog(
            move_targets=self._move_targets,
            parents=partial(self._parent_candidates, {editing} if editing else set()),
            labels=self._label_names,
        )

    async def _move_targets(self) -> tuple[list[Project], list[Section]]:
        return await self._repo.projects(), await self._repo.sections()

    async def _parent_candidates(self, blocked_by: set[str]) -> list[TaskRow]:
        candidates = await load_view(self._repo, ALL)
        blocked = with_subtrees(candidates, blocked_by)
        return [row for row in candidates if str(row.id) not in blocked]

    async def _label_names(self) -> list[str]:
        return [label.name for label in await self._repo.labels()]

    def _on_new_task(self, draft: TaskDraft | None) -> None:
        if draft is None:  # editor was cancelled
            return
        parent_id = draft.parent_id
        if parent_id is not None:  # else the new subtask lands out of sight
            self._expanded.add(TaskId(parent_id))
        # the create returns no id, so the row stands in under one of its own
        # until the drain's sync brings back the task the server actually made
        row = self._provisional_row(draft)
        if draft.subtasks:  # same again, one level down
            self._expanded.add(row.id)
        self._queue([(self._add_step(draft, row), None)])

    def _add_step(self, draft: TaskDraft, row: TaskRow) -> Step:
        children = tuple(s.draft for s in draft.subtasks if s.row is None)
        return Step(
            restore([row, *(self._provisional_child(row, c) for c in children)]),
            partial(
                add_task,
                self._repo,
                draft.content,
                draft.description,
                project_id=draft.project_id,
                section_id=draft.section_id,
                parent_id=draft.parent_id,
                due=draft.due,
                deadline=draft.deadline,
                priority=draft.priority,
                labels=draft.labels,
                reminders=draft.reminders,
                subtasks=tuple(_child_of(c) for c in children),
            ),
            "Failed to add task",
        )

    def _provisional_child(self, parent: TaskRow, draft: TaskDraft) -> TaskRow:
        """A subtask of a task the server has yet to name: it hangs off the id
        only this client knows, and both rows retire together."""
        return replace(
            self._provisional_row(draft),
            project_id=parent.project_id,
            project_name=parent.project_name,
            section_id=parent.section_id,
            section_name=parent.section_name,
            section_order=parent.section_order,
            parent_id=str(parent.id),
        )

    def _provisional_row(self, draft: TaskDraft) -> TaskRow:
        """The new task as the list can already draw it, under an id only this
        client knows. A typed phrase is Todoist's to parse, so its date arrives
        with the sync that replaces this row."""
        return TaskRow(
            id=TaskId(f"{_PROVISIONAL}{uuid.uuid4()}"),
            content=draft.content,
            priority=draft.priority,
            due=draft.due if isinstance(draft.due, Due) else None,
            project_name=draft.project_name or None,
            project_id=draft.project_id,
            section_id=draft.section_id,
            section_name=draft.section_name,
            section_order=self._section_order(draft.section_id),
            labels=draft.labels,
            description=draft.description,
            deadline=draft.deadline,
            parent_id=draft.parent_id,
        )

    def _section_order(self, section_id: str | None) -> int:
        """A sibling's, so the row groups with the section it was written into."""
        sibling = next((r for r in self._visible if r.section_id == section_id), None)
        return sibling.section_order if sibling is not None else 0

    def action_edit_task(self) -> None:
        row = self._named_cursor_row()
        if row is None:  # empty table, a group header, or a task not yet named
            return
        task_id = str(row.id)
        parent = next(
            (r for r in self._visible if str(r.id) == row.parent_id), None
        )  # not every parent is on screen; the id alone still drives the save
        self._push(
            TaskEditScreen(
                draft_of(row, parent, self._children_of(row)),
                self._clock.today(),
                self._catalog(task_id),
            ),
            lambda saved: self._on_edited(row, saved),
        )

    def _children_of(self, row: TaskRow) -> list[TaskRow]:
        """The task's own subtasks. A view grafts every match's subtree into its
        rows, so they are here whether or not the parent is folded open. One
        Todoist has yet to name is left out: nothing can be hung off an id only
        this client knows."""
        return [
            r
            for r in self._visible
            if r.parent_id == str(row.id) and not _is_provisional(str(r.id))
        ]

    def _on_edited(self, row: TaskRow, draft: TaskDraft | None) -> None:
        if draft is None:  # editor was cancelled
            return
        work = self._draft_steps(row, draft) + self._subtask_steps(row, draft.subtasks)
        if work:  # a save that changed nothing queues nothing, and so undoes nothing
            self._queue(work)
        self._apply_reminders(row, draft)
        self._drop_subtasks(row, draft.subtasks)

    def _subtask_steps(
        self, row: TaskRow, subtasks: tuple[Subtask, ...]
    ) -> list[tuple[Step, Step | None]]:
        """What the editor did to the task's children, bar the deletions: those
        are permanent, so they wait for their own confirmation. An edited subtask
        travels the same attribute-by-attribute path its own editor would."""
        before = {str(child.id): child for child in self._children_of(row)}
        work: list[tuple[Step, Step | None]] = []
        for subtask in subtasks:
            if subtask.row is None:
                work.append((self._add_subtask_step(row, subtask.draft), None))
                continue
            was = before.get(str(subtask.row.id))
            if was is None:  # a sync took the child away while the editor was open
                continue
            work.extend(self._draft_steps(was, subtask.draft))
            if subtask.done:
                close = Close(TaskId(str(was.id)), self._subtree_rows(str(was.id)))
                work.append((_close_step(self._repo, close), self._reopen_step(close)))
        return work

    def _add_subtask_step(self, parent: TaskRow, draft: TaskDraft) -> Step:
        self._expanded.add(parent.id)  # else the new subtask lands out of sight
        return Step(
            restore([self._provisional_child(parent, draft)]),
            partial(
                add_task,
                self._repo,
                draft.content,
                draft.description,
                parent_id=str(parent.id),
                project_id=parent.project_id,
                due=draft.due,
                deadline=draft.deadline,
                priority=draft.priority,
                labels=draft.labels,
                reminders=draft.reminders,
            ),
            "Failed to add subtask",
        )

    def _drop_subtasks(self, row: TaskRow, subtasks: tuple[Subtask, ...]) -> None:
        """Deleting a subtask takes its own subtree with it and cannot be undone,
        so the save asks before it goes — as the list's own delete does."""
        kept = {str(s.row.id) for s in subtasks if s.row is not None}
        gone = [c for c in self._children_of(row) if str(c.id) not in kept]
        if not gone:
            return
        prompt = (
            f"Delete {len(gone)} subtasks?"
            if len(gone) > 1
            else f"Delete “{gone[0].content}”?"
        )
        self._push(
            ConfirmScreen(prompt),
            lambda confirmed: self._delete_subtasks(gone) if confirmed else None,
        )

    def _delete_subtasks(self, gone: list[TaskRow]) -> None:
        self._queue(
            [
                (
                    Step(
                        hide([str(r.id) for r in self._subtree_rows(str(child.id))]),
                        partial(delete_task, self._repo, TaskId(str(child.id))),
                        "Failed to delete task",
                    ),
                    None,  # delete is permanent, so there is no reversal to record
                )
                for child in gone
            ]
        )

    def _subtree_rows(self, task_id: str) -> list[TaskRow]:
        """The task and everything under it, in view order."""
        subtree = with_subtrees(self._visible, {task_id})
        return [row for row in self._visible if str(row.id) in subtree]

    def _apply_reminders(self, row: TaskRow, draft: TaskDraft) -> None:
        """Reminders are their own resources, added and deleted one by one — the
        same fire-and-forget path the `R` key takes, so neither is undoable."""
        kept = {r.id for r in draft.reminders}
        for gone in (r for r in row.reminders if r.id not in kept):
            self._delete_reminder(gone.id)
        for added in (r for r in draft.reminders if not r.id):  # no id: never sent
            self._add_reminders([str(row.id)], added)
        if wants_default_reminder(row.due, draft.due, draft.reminders):
            self._add_reminders([str(row.id)], default_reminder())

    def _draft_steps(
        self, row: TaskRow, draft: TaskDraft
    ) -> list[tuple[Step, Step | None]]:
        """One step pair per attribute the editor changed, so the whole save is a
        single undoable batch and each attribute travels the same path the list
        key for it does."""
        was = draft_of(row)
        task_id = str(row.id)
        work: list[tuple[Step, Step | None]] = []
        if (draft.content, draft.description) != (was.content, was.description):
            work.append(
                (
                    self._text_step(task_id, draft.content, draft.description),
                    self._text_step(task_id, was.content, was.description),
                )
            )
        if draft.due != was.due:
            work.append(
                (
                    self._due_change_step(task_id, draft.due),
                    self._due_step(task_id, row.due),
                )
            )
        if draft.deadline != was.deadline:
            work.append(
                (
                    self._deadline_step(task_id, draft.deadline),
                    self._deadline_step(task_id, was.deadline),
                )
            )
        if draft.priority is not was.priority:
            work.append(
                (
                    self._priority_step(task_id, draft.priority),
                    self._priority_step(task_id, was.priority),
                )
            )
        if draft.labels != was.labels:
            work.append(
                (
                    self._labels_step(task_id, draft.labels, draft.new_labels),
                    self._labels_step(task_id, was.labels, ()),
                )
            )
        work.extend(self._where_it_goes(row, draft))
        return work

    def _where_it_goes(
        self, row: TaskRow, draft: TaskDraft
    ) -> list[tuple[Step, Step | None]]:
        """Where the task ends up, as the one `item_move` Todoist allows.

        Nesting drags the task's project and section along, so a picked parent
        stands for all three. Everything else is a plain move — which is also how
        a task is lifted out of a parent, so the draft's project carries an
        un-parenting rather than the parent step doing it.
        """
        unparented = draft.parent_id != row.parent_id
        if unparented and draft.parent is not None:
            forward = self._parent_step(row, draft.parent)
            return [(forward, self._restore_parent_step(row))]
        if draft.project_id is None or (
            not unparented
            and (draft.project_id, draft.section_id) == (row.project_id, row.section_id)
        ):
            return []
        return [
            (
                self._move_step(
                    str(row.id),
                    draft.project_id,
                    draft.project_name,
                    draft.section_id,
                    draft.section_name,
                ),
                # lifting it out has a parent to hang back on; a move has not
                self._restore_parent_step(row)
                if unparented
                else self._move_step(
                    str(row.id),
                    row.project_id,
                    row.project_name,
                    row.section_id,
                    row.section_name,
                )
                if row.project_id is not None
                else None,
            )
        ]

    def _text_step(self, task_id: str, content: str, description: str) -> Step:
        return Step(
            edit([task_id], content=content, description=description),
            partial(set_text, self._repo, TaskId(task_id), content, description),
            "Failed to edit task",
        )

    def _named_cursor_row(self) -> TaskRow | None:
        """The cursor's task, unless it is one Todoist has yet to name: nothing
        can be hung off an id only this client knows."""
        row = self._cursor_row()
        if row is not None and _is_provisional(str(row.id)):
            self._set_status(_STILL_CREATING)
            return None
        return row

    def _cursor_row(self) -> TaskRow | None:
        task_id = self._detail_scope or self._cursor_task_id(self.query_one(TaskTable))
        if task_id is None:
            return None
        return next((r for r in self._visible if str(r.id) == task_id), None)

    def _on_scheduled(self, task_ids: list[TaskId], result: DueResult | None) -> None:
        if result is None:  # picker was cancelled
            return
        rows = self._rows_of(str(t) for t in task_ids)
        self._selected.clear()
        # graft the picked date onto each task's own rule so a recurring task keeps
        # recurring (moves its next occurrence) instead of losing the rule
        moved = [(row, rescheduled(result, row.due)) for row in rows]
        self._queue(
            [
                (
                    self._due_change_step(str(row.id), due),
                    self._due_step(str(row.id), row.due),
                )
                for row, due in moved
            ]
        )
        # queued second, and the outbox keeps issue order all the way to Todoist,
        # so the due time is set by the time its relative reminder is added
        gained = [
            str(row.id)
            for row, due in moved
            if wants_default_reminder(row.due, due, row.reminders)
        ]
        if gained:
            self._add_reminders(gained, default_reminder())

    def _due_change_step(self, task_id: str, due: Due | DueText | None) -> Step:
        if isinstance(due, DueText):
            return self._due_text_step(task_id, due.text)
        return self._due_step(task_id, due)

    def _due_step(self, task_id: str, due: Due | None) -> Step:
        return Step(
            edit([task_id], due=due),
            partial(set_due, self._repo, TaskId(task_id), due),
            "Failed to set due",
        )

    def _due_text_step(self, task_id: str, text: str) -> Step:
        # Todoist parses the phrase, so the resulting date is unknowable here: the
        # empty patch changes nothing and only marks the row as unconfirmed.
        return Step(
            edit([task_id]),
            partial(set_due, self._repo, TaskId(task_id), DueText(text)),
            "Failed to set due",
        )

    def _on_deadline(self, task_ids: list[TaskId], result: DueResult | None) -> None:
        if result is None:  # picker was cancelled
            return
        # the deadline screen carries a date-only Due; map it to a Deadline
        new_deadline = (
            Deadline(date=result.due.date) if result.due is not None else None
        )
        rows = self._rows_of(str(t) for t in task_ids)
        self._selected.clear()
        self._queue(
            [
                (
                    self._deadline_step(str(row.id), new_deadline),
                    self._deadline_step(str(row.id), row.deadline),
                )
                for row in rows
            ]
        )

    def _deadline_step(self, task_id: str, deadline: Deadline | None) -> Step:
        return Step(
            edit([task_id], deadline=deadline),
            partial(set_deadline, self._repo, TaskId(task_id), deadline),
            "Failed to set deadline",
        )

    async def action_move_task(self) -> None:
        if self._picking_project:  # already loading or picker already open
            return
        table = self.query_one(TaskTable)
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        self._picking_project = True
        try:
            projects, sections = await self._move_targets()
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load projects: {error}")
            self._picking_project = False
            return
        self._push(
            ProjectPickerScreen(
                projects,
                sections,
            ),
            lambda target: self._on_moved([TaskId(i) for i in ids], target),
        )

    def _on_moved(self, task_ids: list[TaskId], target: MoveTarget | None) -> None:
        self._picking_project = False
        if target is None:  # picker was cancelled
            return
        rows = self._rows_of(str(t) for t in task_ids)
        self._selected.clear()
        self._queue(
            [
                (
                    self._move_step(
                        str(row.id),
                        target.project_id,
                        target.project_name,
                        target.section_id,
                        target.section_name,
                    ),
                    self._move_step(
                        str(row.id),
                        row.project_id,
                        row.project_name,
                        row.section_id,
                        row.section_name,
                    )
                    if row.project_id is not None
                    else None,
                )
                for row in rows
            ]
        )

    def _move_step(
        self,
        task_id: str,
        project_id: str,
        project_name: str | None,
        section_id: str | None,
        section_name: str | None,
    ) -> Step:
        return Step(
            edit(
                [task_id],
                project_id=project_id,
                project_name=project_name,
                section_id=section_id,
                section_name=section_name,
            ),
            partial(move_task, self._repo, TaskId(task_id), project_id, section_id),
            "Failed to move task",
        )

    async def action_move_parent(self) -> None:
        table = self.query_one(TaskTable)
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        await self._open_parent_picker(ids)

    async def _open_parent_picker(self, ids: list[str]) -> None:
        if self._picking_parent:  # already loading or picker already open
            return
        self._picking_parent = True
        try:
            candidates = await self._parent_candidates(set(ids))
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load tasks: {error}")
            self._picking_parent = False
            return
        self._push(
            ParentPickerScreen(candidates),
            lambda target: self._on_parent_chosen(ids, target),
        )

    def _on_parent_chosen(
        self, task_ids: list[str], target: ParentTarget | None
    ) -> None:
        self._picking_parent = False
        if target is None:  # picker was cancelled
            return
        parent = target.row
        if parent is not None:  # else the new subtask lands out of sight
            self._expanded.add(parent.id)
        rows = self._rows_of(task_ids)
        self._selected.clear()
        work: list[tuple[Step, Step | None]] = []
        for row in rows:
            forward = (
                self._parent_step(row, parent)
                if parent is not None
                else self._where_it_was_step(row)
            )
            if forward is None:
                continue
            work.append((forward, self._restore_parent_step(row)))
            # a dated subtask still surfaces on its own in the phone app's dated
            # views; un-parenting is left alone — dateless, it would show nowhere
            if parent is not None and target.clear_due and row.due is not None:
                task_id = str(row.id)
                work.append(
                    (self._due_step(task_id, None), self._due_step(task_id, row.due))
                )
        self._queue(work)

    def _parent_step(self, row: TaskRow, parent: TaskRow) -> Step:
        """Nest `row` under `parent`. Todoist hands the subtask — and its own
        subtree — the parent's project and section."""
        return Step(
            edit(
                [str(row.id)],
                parent_id=str(parent.id),
                project_id=parent.project_id,
                project_name=parent.project_name,
                section_id=parent.section_id,
                section_name=parent.section_name,
            ),
            partial(move_to_parent, self._repo, row.id, str(parent.id)),
            "Failed to move task",
        )

    def _where_it_was_step(self, row: TaskRow) -> Step | None:
        """Put `row` at the top level of the project and section it names — a
        plain move un-parents a task, so this both lifts and restores it."""
        if row.project_id is None:  # nowhere to move it to
            return None
        return Step(
            edit(
                [str(row.id)],
                parent_id=None,
                project_id=row.project_id,
                project_name=row.project_name,
                section_id=row.section_id,
                section_name=row.section_name,
            ),
            partial(move_task, self._repo, row.id, row.project_id, row.section_id),
            "Failed to move task",
        )

    def _restore_parent_step(self, row: TaskRow) -> Step | None:
        """The reversal of a re-parent: back under the parent `row` hung from,
        or back to where it stood on its own."""
        old_parent = self._rows_of([row.parent_id]) if row.parent_id else []
        if old_parent:
            return self._parent_step(row, old_parent[0])
        return self._where_it_was_step(row)

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
        # the copies only appear once the drain's sync pulls them in
        self._send(partial(self._duplicate, target, name), "Failed to duplicate")

    async def _duplicate(self, target: MoveTarget, name: str) -> None:
        if target.section_id is None:
            await duplicate_project(self._repo, target.project_id, name)
            return
        sections = await self._repo.sections()
        section = next((s for s in sections if s.id == target.section_id), None)
        if section is None:
            raise LookupError(f"section {target.section_id} not found")
        await duplicate_section(self._repo, section, name)

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
        # the section and its tasks leave the view with the drain's sync
        self._send(
            partial(delete_section, self._repo, section_id),
            "Failed to delete section",
        )

    async def action_set_labels(self) -> None:
        if self._picking_labels:  # already loading or editor already open
            return
        table = self.query_one(TaskTable)
        rows = [
            row
            for task_id in self._targets(table)
            if (row := next((r for r in self._visible if str(r.id) == task_id), None))
        ]
        if not rows:  # empty table or cursor on a group header
            return
        self._picking_labels = True
        try:
            names = set(await self._label_names())
        except Exception as error:  # offline / sync failed: report, stay put
            self._set_status(f"Failed to load labels: {error}")
            self._picking_labels = False
            return
        task_ids = [row.id for row in rows]
        # one task: edit its labels in place (replace). A selection: the editor
        # opens blank and its result is *added* to each task's own labels.
        add = len(rows) > 1
        seed: tuple[str, ...] = () if add else rows[0].labels
        self._push(
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
        edited: list[tuple[TaskRow, tuple[str, ...]]] = []
        for row in self._rows_of(str(t) for t in task_ids):
            merged = (
                row.labels + tuple(n for n in chosen if n not in row.labels)
                if add
                else tuple(chosen)
            )
            if merged != row.labels:  # skip tasks the edit leaves unchanged
                edited.append((row, merged))
        if not edited:  # nothing to add / unchanged
            return
        create = tuple(name for name in chosen if name not in catalog)
        self._selected.clear()
        self._queue(
            [
                (  # any new labels are registered once, with the first command
                    self._labels_step(
                        str(row.id), merged, create if index == 0 else ()
                    ),
                    self._labels_step(str(row.id), row.labels, ()),
                )
                for index, (row, merged) in enumerate(edited)
            ]
        )

    def _labels_step(
        self, task_id: str, labels: tuple[str, ...], create: tuple[str, ...]
    ) -> Step:
        return Step(
            edit([task_id], labels=labels),
            partial(set_labels, self._repo, TaskId(task_id), labels, create),
            "Failed to set labels",
        )

    def action_reminders(self) -> None:
        table = self.query_one(TaskTable)
        ids = self._targets(table)
        if not ids:  # empty table or cursor on a group header
            return
        if len(ids) == 1:
            row = next((r for r in self._visible if str(r.id) == ids[0]), None)
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
        self._push(screen, lambda request: self._on_reminder_request(ids, request))

    def _on_reminder_request(
        self, ids: list[str], request: ReminderRequest | None
    ) -> None:
        if request is None:  # cancelled
            return
        if request.add_absolute:  # finish by picking the date + time
            self._push(
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
        row = next((r for r in self._visible if str(r.id) == task_id), None)
        return row is not None and row.due is not None and row.due.time is not None

    def _on_reminder_absolute(self, ids: list[str], result: DueResult | None) -> None:
        if result is None or result.due is None:  # picker cancelled or cleared
            return
        template = Reminder(id="", item_id="", type="absolute", due=result.due)
        self._add_reminders(ids, template)

    def _add_reminders(self, ids: list[str], template: Reminder) -> None:
        self._selected.clear()
        # the bell count only updates once the drain's sync brings the reminders in
        for task_id in ids:
            self._send(
                partial(add_reminder, self._repo, replace(template, item_id=task_id)),
                "Failed to add reminder",
            )

    def _delete_reminder(self, reminder_id: str) -> None:
        self._send(
            partial(delete_reminder, self._repo, reminder_id),
            "Failed to delete reminder",
        )

    async def _reload(self, view: View) -> None:
        if await self._load_rows(view):
            self._repaint()
            self._land(view)

    def _land(self, view: View) -> None:
        """Put the cursor on the group a picked section named, once its view has
        painted. A missing header (empty section, regrouped view) lands nowhere."""
        if self._pending_land is None:
            return
        key, path = self._pending_land
        if key != view.key:
            return
        self._pending_land = None
        try:
            table = self.query_one(TaskTable)
        except NoMatches:  # reload landed mid-teardown: nothing to move
            return
        self._move_cursor_to_group(table, path)

    async def _load_rows(self, view: View) -> bool:
        """Take `view`'s rows and arrangement in without drawing them, so a caller
        that is about to change what sits on top of them can paint once. False
        when the load failed and there is nothing new to draw."""
        try:
            rows = await load_view(self._repo, view)
            projects = await self._repo.projects()
        except Exception as error:  # surface any load failure to the user
            self._set_status(f"Failed to load tasks: {error}")
            return False
        self._inbox_id = next((p.id for p in projects if p.is_inbox), None)
        arrangement = await self._arrangements.get(view.key, view.default_arrangement)
        if view.key != self._folds_key:  # a new view opens folded as it was left
            self._folds_key = view.key
            self._open_groups = set(await self._folds.get(view.key))
        elif arrangement != self._arrangement:
            self._open_groups.clear()  # regrouping makes the open label paths stale
            self._remember_folds()
        self._arrangement = arrangement
        self._rows = rows
        return True

    def _rows_of(self, task_ids: Iterable[str]) -> list[TaskRow]:
        """The named rows as they look now, in display order."""
        wanted = set(task_ids)
        return [row for row in self._visible if str(row.id) in wanted]

    def _members(self, rows: list[TaskRow]) -> list[TaskRow]:
        """The rows the open view still wants once the local changes are on.

        A row leaves only if the change is what took it out — it belonged before
        and doesn't after. Judging the result alone would evict rows the server
        put here despite the rule, since a Todoist query is wider than anything
        reproducible client-side ("today" also hands back everything overdue).

        A saved filter's membership only the server can decide, so a row changed
        there keeps its place until the next refresh answers — it must never blink
        out and back in.
        """
        changed = touched(self._outbox.pending)
        belongs = self._membership()
        if not changed or belongs is None:
            return rows
        before = {str(row.id): row for row in self._rows}

        def departed(row: TaskRow) -> bool:
            was = before.get(str(row.id))
            if str(row.id) not in changed or was is None:
                return False
            return belongs(was) and not belongs(row)

        return prune(rows, departed)

    def _membership(self) -> Callable[[TaskRow], bool] | None:
        """The open view's own rule, where it has one it can apply itself."""
        keeps = self._view.keeps
        if keeps is not None:
            today = self._clock.today()
            return lambda row: keeps(row, today)
        if self._view.key == INBOX.key and self._inbox_id is not None:
            inbox_id = self._inbox_id
            return lambda row: row.project_id == inbox_id
        return None

    def _arrange(self, rows: list[TaskRow]) -> list[RenderRow[TaskRow]]:
        return arrange(
            rows,
            self._arrangement,
            frozenset(self._expanded),
            frozenset(self._open_groups),
            manual=self._manual_order,
        )

    @property
    def _manual_order(self) -> ManualOrder:
        """A view spanning projects has no one sibling set, so it orders by day."""
        return ManualOrder.DAY if self._view.day_ordered else ManualOrder.CHILD

    def on_task_table_expand(self, _message: TaskTable.Expand) -> None:
        table = self.query_one(TaskTable)
        group = self._cursor_group_path(table)
        if group is not None:  # on a group header: unfold it
            if group not in self._open_groups:
                self._open_groups.add(group)
                self._fold_changed()
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
            if group in self._open_groups:  # an open group: fold it away
                self._open_groups.discard(group)
                self._fold_changed()
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
        parent_id = self._parent_of(task_id)  # a child: step out to the parent
        if parent_id is not None:
            self._move_cursor_to_task(table, parent_id)
            return
        path = group_path_of(self._visible, self._arrangement, task_id)
        if not path:  # nothing groups it: no header to fold onto
            return
        self._open_groups.discard(path)  # a root task: fold its group away
        self._fold_changed()
        self._move_cursor_to_group(table, path)

    def on_task_table_move_down(self, _message: TaskTable.MoveDown) -> None:
        self._move_task(down=True)

    def on_task_table_move_up(self, _message: TaskTable.MoveUp) -> None:
        self._move_task(down=False)

    def _move_task(self, *, down: bool) -> None:
        """Trade the cursor's task with the sibling one step away, if there is one."""
        if self._arrangement.sort_by:
            # a sort decides the order, so a reordered task would snap straight back
            self.notify("Clear the sort (s) to reorder by hand")
            return
        table = self.query_one(TaskTable)
        task_id = self._cursor_task_id(table)
        if task_id is None:  # empty table or cursor on a group header
            return
        rendered = self._arrange(self._visible)
        work = self._day_move(rendered, task_id, down=down) or self._sibling_move(
            rendered, task_id, down=down
        )
        if work is None:
            where = "below" if down else "above"
            self.notify(f"Nothing {where} to swap with")
            return
        self._queue([work])

    def _day_move(
        self, rendered: list[RenderRow[TaskRow]], task_id: str, *, down: bool
    ) -> tuple[Step, Step] | None:
        """The step trading places in a day-scoped list, if this view keeps one."""
        if self._manual_order is not ManualOrder.DAY:
            return None
        plan = day_order_plan(rendered, task_id, down=down)
        if plan is None:
            return None
        return (
            self._day_order_step([(row.id, order) for row, order in plan]),
            self._day_order_step([(row.id, row.day_order) for row, _ in plan]),
        )

    def _sibling_move(
        self, rendered: list[RenderRow[TaskRow]], task_id: str, *, down: bool
    ) -> tuple[Step, Step] | None:
        """The step trading two siblings' places among the tasks they share a
        parent, project and section with."""
        pair = swap_with_neighbour(rendered, task_id, down=down)
        if pair is None:
            return None
        moved, neighbour = pair
        return (
            self._order_step(
                [
                    (moved.id, neighbour.child_order),
                    (neighbour.id, moved.child_order),
                ]
            ),
            self._order_step(  # each back where it started
                [
                    (moved.id, moved.child_order),
                    (neighbour.id, neighbour.child_order),
                ]
            ),
        )

    def _day_order_step(self, orders: Sequence[tuple[TaskId, int]]) -> Step:
        return Step(
            [edit([str(task_id)], day_order=order) for task_id, order in orders],
            partial(set_day_orders, self._repo, list(orders)),
            "Failed to reorder",
        )

    def _order_step(self, orders: Sequence[tuple[TaskId, int]]) -> Step:
        """One command placing every task in `orders`, so a swap never lands by
        halves and leaves two siblings sharing a `child_order`."""
        return Step(
            [edit([str(task_id)], child_order=order) for task_id, order in orders],
            partial(reorder, self._repo, list(orders)),
            "Failed to reorder",
        )

    def on_task_table_expand_all(self, _message: TaskTable.ExpandAll) -> None:
        self._open_groups = group_paths(self._visible, self._arrangement)
        # every id that parents a visible row; arrange ignores the childless ones
        self._expanded = {
            TaskId(row.parent_id) for row in self._visible if row.parent_id is not None
        }
        self._fold_changed()

    def on_task_table_collapse_all(self, _message: TaskTable.CollapseAll) -> None:
        self._open_groups.clear()
        self._expanded.clear()
        self._fold_changed()

    def _fold_changed(self) -> None:
        self._repaint()
        self._remember_folds()

    def _remember_folds(self) -> None:
        """Write the folds down under the view they were made in, one at a time:
        the view can change before the write runs, and writes that overtook each
        other would put an earlier fold back."""
        if self._folds_key is not None:
            self.run_worker(
                self._save_folds(self._folds_key, frozenset(self._open_groups))
            )

    async def _save_folds(self, key: str, open_groups: frozenset[GroupPath]) -> None:
        async with self._fold_writes:
            await self._folds.save(key, open_groups)

    def _has_children(self, task_id: str) -> bool:
        return any(row.parent_id == task_id for row in self._visible)

    def _parent_of(self, task_id: str) -> str | None:
        row = next((r for r in self._visible if str(r.id) == task_id), None)
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
        """Redraw the open view: the loaded rows with the outbox replayed on top."""
        if self._batching:  # a batch of changes paints once, when all of it is in
            return
        self._visible = self._members(apply(self._rows, self._outbox.pending))
        self._selected &= {str(r.id) for r in self._visible}  # drop ids now gone
        self._unfold_to_the_changed_task()
        self._render(self._arrange(self._visible), self._view)

    def _unfold_to_the_changed_task(self) -> None:
        """Open the groups hiding the task under the cursor once a change has moved
        it — a task must not vanish because the edit sent it into a folded group.

        Only a task the outbox is still carrying counts, so folding the list keeps
        the cursor's task folded away like every other.
        """
        try:
            table = self.query_one(TaskTable)
        except NoMatches:
            return
        task_id = self._cursor_task_id(table)
        if task_id is None or task_id not in touched(self._outbox.pending):
            return
        path = group_path_of(self._visible, self._arrangement, task_id)
        opened = {path[:depth] for depth in range(1, len(path) + 1)} - self._open_groups
        if opened:
            self._open_groups |= opened
            self._remember_folds()

    def _render(self, render_rows: list[RenderRow[TaskRow]], view: View) -> None:
        try:
            table = self.query_one(TaskTable)
        except NoMatches:  # background resync landed mid-teardown: nothing to draw
            return
        prior = self._cursor_task_id(table)  # survive the clear+rebuild below
        prior_group = self._cursor_group_path(table)
        # at render time, not import: the styles follow the live theme
        styles = tier_styles(table)
        priorities = priority_styles(table)
        unconfirmed = touched(self._outbox.pending)
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
        # one project across the whole view is the view's own, not news about a
        # row — the band carries it instead of every line repeating it
        projects = {t.project_name for t in tasks}
        show_project = len(projects) > 1
        sole = next(iter(projects)) if len(projects) == 1 else None
        # a project view's title already says it
        self._shared_project = sole if view.project_id is None else None
        columns = ["TASK"]
        if show_labels:
            columns.append("LABELS")
        if show_due:
            columns.append("DUE")
        if show_deadline:
            columns.append("DEADLINE")
        if show_project:
            columns.append("PROJECT")
        self._header_paths = {}
        # every cell is built before any is added, so the column widths — and the
        # group dividers that have to span them — follow the content
        built: list[tuple[str, Text | list[Text | str]]] = []
        for index, item in enumerate(render_rows):
            if isinstance(item, GroupHeader):
                built.append((_header_key(index), _header_lead(item, today, styles)))
                self._header_paths[index] = item.path
                header_row_of[item.path] = index
                continue
            row = item.row
            marked = str(row.id) in self._selected
            cells: list[Text | str] = [
                _title_cell(
                    item, marked, str(row.id) in unconfirmed, styles, priorities
                )
            ]
            if show_labels:
                cells.append(_labels_cell(row.labels, styles[Tier.MUTED]))
            if show_due:
                cells.append(_due_cell(row.due, row.reminders, today, styles))
            if show_deadline:
                cells.append(_deadline_cell(row.deadline, today, styles))
            if show_project:
                cells.append(_project_cell(row.project_name, styles[Tier.MUTED]))
            built.append((_task_key(index, row.id), cells))
            if first_task_row is None:
                first_task_row = index
            first_row_of.setdefault(str(row.id), index)
        leads = [entry for _, entry in built if isinstance(entry, Text)]
        self._laid_out = table.scrollable_content_region.width
        fitted = fit_columns(
            columns,
            [entry for _, entry in built if isinstance(entry, list)],
            table.scrollable_content_region.width,
            max((cell_len(lead.plain) + _MIN_FILL for lead in leads), default=0),
        )
        table.clear(columns=True)
        for column in fitted:
            table.add_column(column.label, width=column.width)
        self.query_one(ColumnHeader).show(fitted)
        for key, entry in built:
            cells = (
                _divider_cells(entry, fitted, styles)
                if isinstance(entry, Text)
                else fit_row(entry, fitted)
            )
            table.add_row(*cells, key=key)
        if prior_group is not None and prior_group in header_row_of:
            table.move_cursor(row=header_row_of[prior_group])  # keep it on the group
        elif prior is not None and prior in first_row_of:
            table.move_cursor(row=first_row_of[prior])  # keep highlight on the task
        elif first_task_row is not None:
            table.move_cursor(row=first_task_row)  # never rest on a leading header
        # the view's own tasks, not the visible lines: collapsing a parent or
        # revealing a subtask pulled in for context must not move the number
        matched = sum(1 for row in self._visible if row.matched)
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
        """The task ids an action applies to, leaving out any task Todoist has yet
        to name — a command aimed at one of those could only be refused."""
        picked = self._picked(table)
        named = [task_id for task_id in picked if not _is_provisional(task_id)]
        if len(named) != len(picked):
            self._set_status(_STILL_CREATING)
        return named

    def _picked(self, table: TaskTable) -> list[str]:
        """The open card's task if one started the action, else the selection (in
        display order), else the cursor row, else nothing."""
        if self._detail_scope is not None:
            return [self._detail_scope]
        if self._selected:
            return [str(r.id) for r in self._visible if str(r.id) in self._selected]
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
        self._shared_project = None  # the line is no longer about the view
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
        project = f" · {self._shared_project}" if self._shared_project else ""
        band.show(
            self._status_base,
            f"{self._status_tally}{project}{selected}{marker}",
            _arrangement_summary(self._arrangement),
        )


_RECURRING_GLYPH = " ↻"


def _title_cell(
    line: TaskLine[TaskRow],
    marked: bool,
    unconfirmed: bool,
    styles: Mapping[Tier, Style],
    priorities: Mapping[Priority, Style],
) -> Text:
    """The row's whole left side: selection bar, priority dot, then the title.

    All one cell, so selecting a row can't shift its text and the group dividers
    can start at the very left edge instead of after a column of their own."""
    row = line.row
    cell = Text(_SELECT_MARKER if marked else " ", style=styles[Tier.ACCENT])
    dot = priority_dot(row.priority)
    cell.append(dot or " ", style=priorities.get(row.priority))
    cell.append(" ")
    tier = Tier.ACCENT if marked else Tier.PRIMARY
    title = Text(_indent(line.level), style=styles[tier])
    title.append(_expand_marker(line))
    title.append_text(render_links(row.content))
    if marker := description_marker(row.description):
        title.append(marker, style=styles[Tier.MUTED])
    if unconfirmed:  # this row's change is still on its way to Todoist
        title.append(PENDING_MARK, style=styles[Tier.MUTED])
    cell.append_text(title)
    return cell


def _child_of(draft: TaskDraft) -> NewChild:
    """A subtask draft as the create takes it: everything but where it goes,
    which its parent supplies."""
    return NewChild(
        content=draft.content,
        description=draft.description,
        priority=draft.priority,
        due=draft.due,
        deadline=draft.deadline,
        labels=draft.labels,
        reminders=draft.reminders,
    )


def _close_step(repo: TaskRepository, close: Close) -> Step:
    return Step(
        hide([str(row.id) for row in close.rows]),
        partial(complete_task, repo, close.task_id),
        "Failed to complete task",
    )


def _forget(undo: list[Step], step: Step) -> None:
    """Drop a reversal the server never gave us anything to reverse."""
    if step in undo:
        undo.remove(step)


def _divider_cells(
    lead: Text, fitted: list[Column], styles: Mapping[Tier, Style]
) -> list[Text | str]:
    """The group's label on a rule running the table's full width: the label rides
    in the first column, every later column is rule to the edge. A narrow table
    cuts the label rather than let it run past its column."""
    rule = styles[Tier.MUTED]
    first = lead.copy()
    first.truncate(max(0, fitted[0].width - _MIN_FILL), overflow="ellipsis")
    first.append(
        "─" * max(_MIN_FILL, fitted[0].width - cell_len(first.plain)), style=rule
    )
    return [first, *(Text("─" * column.width, style=rule) for column in fitted[1:])]


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


def _header_lead(
    header: GroupHeader, today: datetime.date, styles: Mapping[Tier, Style]
) -> Text:
    """The divider's opening rule and its label, without the fill that carries it
    across the column — measured first, so the column can be sized to hold it."""
    label = header.label
    if header.field is Field.DUE_DATE:
        # the bucket label is ISO (a stable grouping key) except "No due date"
        with contextlib.suppress(ValueError):
            label = humanize_date(datetime.date.fromisoformat(label), today)
    marker = _FOLD_SHUT if header.collapsed else _FOLD_OPEN
    rule = styles[Tier.MUTED]
    lead = Text(f"{_indent(header.level)}{marker}── ", style=rule)  # marker counted
    # top level is the boldest divider; deeper ones recede to a plain accent
    accent = styles[Tier.ACCENT] + Style(bold=header.level == 0)
    lead.append(f"{label} ({header.count})", style=accent)
    lead.append(" ", style=rule)
    return lead


def _indent(level: int) -> str:
    return _INDENT * level


def _header_key(index: int) -> str:
    return f"h:{index}"


def _task_key(index: int, task_id: str) -> str:
    return f"t:{index}:{task_id}"


def _is_provisional(task_id: str) -> bool:
    return task_id.startswith(_PROVISIONAL)


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
