import datetime
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import ClassVar, cast

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Static, TextArea

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.links import attach, sole_url
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.section import Section
from todoist_tui.tui.screens.description import VIM_KEYS, DescriptionArea
from todoist_tui.tui.screens.draft import Subtask, TaskDraft, attribute_strip
from todoist_tui.tui.screens.help import HelpScreen, shortcut_rows
from todoist_tui.tui.screens.labels import LabelsScreen
from todoist_tui.tui.screens.parent_picker import ParentPickerScreen, ParentTarget
from todoist_tui.tui.screens.project_picker import ProjectPickerScreen
from todoist_tui.tui.screens.reminders import ReminderRequest, RemindersScreen
from todoist_tui.tui.screens.schedule import ScheduleScreen, rescheduled
from todoist_tui.tui.screens.scrolling import ScrollBody
from todoist_tui.tui.screens.subtask_list import HINT, SubtaskList
from todoist_tui.tui.theme import (
    PALETTE_CLASSES,
    PALETTE_CSS,
    priority_styles,
    tier_styles,
)

_HELP_HINT = "f1 help · esc: normal mode"  # `?` is a character: the fields take it
# Declared, not bound: Textual moves the focus on tab itself, but help should
# still name the key that carries it between the fields.
_UNBOUND: list[BindingType] = [Binding("tab", "focus_next", "Editor: switch field")]


@dataclass(frozen=True, slots=True)
class Catalog:
    """What the editor's pickers choose from, fetched only once a chord asks —
    opening the editor should cost nothing."""

    move_targets: Callable[[], Awaitable[tuple[list[Project], list[Section]]]]
    parents: Callable[[], Awaitable[list[TaskRow]]]
    labels: Callable[[], Awaitable[list[str]]]


class TitleInput(Input):
    """Textual maps ctrl+backspace to delete_right_word; every other editor
    deletes the word to the left. A pasted URL is folded into the title so the
    whole title reads as the link instead of the URL eating the row."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+backspace,alt+backspace", "delete_left_word", show=False),
    ]

    class LinkPasted(Message):
        """A URL arrived with no title yet to hang it on; hold it until there is
        one."""

        def __init__(self, url: str) -> None:
            super().__init__()
            self.url = url

    def _on_paste(self, event: events.Paste) -> None:
        url = sole_url(event.text)
        if url is None:
            return  # Input's own handler, next in the MRO, inserts it verbatim
        event.prevent_default()  # only this stops that handler running too
        event.stop()
        if self.value.strip():
            self.value = attach(self.value, url)
            self.cursor_position = len(self.value)
        else:
            self.post_message(self.LinkPasted(url))


class TaskEditScreen(ModalScreen["TaskDraft | None"]):
    """Edit a task's title and description together, over a strip naming the rest
    of its attributes. Tab moves between the fields, ctrl+s (or enter in the
    title) dismisses the draft with both values trimmed, escape dismisses None. A
    blank title keeps the prompt open."""

    # Each attribute answers to the key the list uses for it, held with alt so it
    # stays out of the way of typing. Lowercase throughout: a keyboard remapper
    # between here and the terminal can swallow alt+shift.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("f1", "shortcuts", "Editor: shortcuts"),
        Binding("ctrl+s", "save", "Editor: save"),
        Binding("escape", "cancel", "Editor: cancel"),
        Binding("alt+t", "set_due", "Editor: due", show=False),
        Binding("alt+d", "set_deadline", "Editor: deadline", show=False),
        Binding("alt+v", "move", "Editor: project / section", show=False),
        Binding("alt+n", "move_parent", "Editor: parent", show=False),
        Binding("alt+a", "subtasks", "Editor: subtasks", show=False),
        # the list reaches labels by @, which needs a shift alt cannot join here
        Binding("alt+l", "set_labels", "Editor: labels", show=False),
        Binding("alt+m", "reminders", "Editor: reminders", show=False),
        Binding("alt+1", "set_priority('P1')", "Editor: P1", show=False),
        Binding("alt+2", "set_priority('P2')", "Editor: P2", show=False),
        Binding("alt+3", "set_priority('P3')", "Editor: P3", show=False),
        Binding("alt+4", "set_priority('P4')", "Editor: P4", show=False),
    ]

    COMPONENT_CLASSES: ClassVar[set[str]] = set(PALETTE_CLASSES)
    DEFAULT_CSS = (
        PALETTE_CSS
        + """
    TaskEditScreen { align: center middle; }
    TaskEditScreen #fields { width: 70%; max-width: 80; height: auto; }
    TaskEditScreen #heading { padding: 0 1; text-style: bold; }
    TaskEditScreen .label { padding: 0 1; }
    TaskEditScreen Input { border: round $primary; }
    TaskEditScreen TextArea { height: 8; border: round $primary; }
    TaskEditScreen #hint { padding: 0 1; color: $text-muted; }
    TaskEditScreen #link { padding: 0 1; color: $text-muted; }
    TaskEditScreen #attributes { padding: 0 1; }
    TaskEditScreen SubtaskList { border: round $primary; }
    TaskEditScreen #subtask-hint { padding: 0 1; color: $text-muted; }
    """
    )

    def __init__(
        self,
        draft: TaskDraft,
        today: datetime.date,
        catalog: Catalog,
        heading: str | None = None,
        nests: bool = True,
    ) -> None:
        super().__init__()
        self._nests = nests
        self._draft = draft
        self._today = today
        self._catalog = catalog
        self._heading = heading
        self._pending_url: str | None = None
        self._loading = False  # a chord is fetching what its picker chooses from

    def compose(self) -> ComposeResult:
        # the description box alone is taller than a short terminal
        with ScrollBody(id="fields"):
            if self._heading is not None:  # so an add does not read as an edit
                yield Static(self._heading, id="heading")
            yield Static("Title", classes="label")
            # select_on_focus would make the first keystroke wipe the title
            yield TitleInput(value=self._draft.content.strip(), select_on_focus=False)
            yield Static("", id="link")
            yield Static("Description", classes="label")
            yield DescriptionArea(self._draft.description.strip())
            if self._nests:  # a subtask's own editor stops the nesting here
                yield Static("Subtasks", classes="label")
                yield SubtaskList()
                yield Static(HINT, id="subtask-hint")
            # painted by `_repaint` once mounted, when the palette can resolve
            yield Static(id="attributes", markup=False)
            yield Static(_HELP_HINT, id="hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        description = self.query_one(TextArea)
        description.move_cursor(description.document.end)  # append, don't prepend
        self._repaint()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def on_title_input_link_pasted(self, event: TitleInput.LinkPasted) -> None:
        event.stop()
        self._pending_url = event.url  # a second paste means the first was wrong
        self.query_one("#link", Static).update(f"↳ link: {event.url}")

    def action_save(self) -> None:
        content = self.query_one(Input).value.strip()
        if not content:  # a task must keep a title: stay open
            return
        if self._pending_url is not None:
            content = attach(content, self._pending_url)
        self.dismiss(
            replace(
                self._draft,
                content=content,
                description=self.query_one(TextArea).text.strip(),
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_shortcuts(self) -> None:
        rows = shortcut_rows(self.BINDINGS, _UNBOUND, VIM_KEYS)
        self._app.push_screen(HelpScreen(rows))

    def action_set_due(self) -> None:
        due = self._draft.due if isinstance(self._draft.due, Due) else None
        self._pick(
            ScheduleScreen(
                self._today,
                due.date if due else None,
                due.time if due else None,
                allow_text=True,
                current_text=due.string if due and due.is_recurring else None,
            ),
            lambda result: replace(
                self._draft, due=rescheduled(result, self._draft.due)
            ),
        )

    def action_set_deadline(self) -> None:
        current = self._draft.deadline
        self._pick(
            ScheduleScreen(
                self._today,
                current.date if current else None,
                kind="deadline",
            ),
            # the deadline screen carries a date-only Due; map it to a Deadline
            lambda result: replace(
                self._draft,
                deadline=Deadline(date=result.due.date) if result.due else None,
            ),
        )

    def action_set_priority(self, name: str) -> None:
        self._draft = replace(self._draft, priority=Priority[name])
        self._repaint()

    async def action_move(self) -> None:
        loaded = await self._load(self._catalog.move_targets, "projects")
        if loaded is None:
            return
        projects, sections = loaded
        self._pick(
            ProjectPickerScreen(projects, sections),
            lambda target: replace(
                self._draft,
                project_id=target.project_id,
                project_name=target.project_name,
                section_id=target.section_id,
                section_name=target.section_name,
                # a subtask lives in its parent's project, so naming a project of
                # its own lifts it out — as the same move does in the list
                parent_id=None,
                parent=None,
            ),
        )

    async def action_move_parent(self) -> None:
        candidates = await self._load(self._catalog.parents, "tasks")
        if candidates is None:
            return
        self._pick(ParentPickerScreen(candidates), self._under)

    def _under(self, target: ParentTarget) -> TaskDraft:
        """Nest the draft under the picked task — Todoist hands a subtask its
        parent's project and section — or lift it back to the top level."""
        if target.row is None:
            return replace(self._draft, parent_id=None, parent=None)
        return replace(
            self._draft,
            parent_id=str(target.row.id),
            parent=target.row,
            project_id=target.row.project_id,
            project_name=target.row.project_name or "",
            section_id=target.row.section_id,
            section_name=target.row.section_name,
            due=None if target.clear_due else self._draft.due,
        )

    def action_subtasks(self) -> None:
        """Write a subtask in an editor of its own: a subtask is a task, so it
        gets every attribute one has."""
        if not self._nests:
            return
        self._edit_subtask(TaskDraft("", ""), "New subtask", self._appended)

    def on_subtask_list_acted(self, event: SubtaskList.Acted) -> None:
        event.stop()
        subtask = self._draft.subtasks[event.index]
        if event.action == "edit":
            self._edit_subtask(
                subtask.draft,
                "Edit subtask",
                lambda draft: self._replaced(
                    event.index, replace(subtask, draft=draft)
                ),
            )
        elif event.action == "complete":
            self._replaced(event.index, replace(subtask, done=not subtask.done))
        else:
            self._dropped(event.index)

    def _edit_subtask(
        self, draft: TaskDraft, heading: str, onto: Callable[[TaskDraft], None]
    ) -> None:
        def written(saved: TaskDraft | None) -> None:
            if saved is not None:  # a cancelled editor changes nothing
                onto(saved)

        self._app.push_screen(
            TaskEditScreen(draft, self._today, self._catalog, heading, nests=False),
            written,
        )

    def _appended(self, draft: TaskDraft) -> None:
        self._draft = replace(
            self._draft, subtasks=(*self._draft.subtasks, Subtask(draft))
        )
        self._repaint()

    def _replaced(self, index: int, subtask: Subtask) -> None:
        subtasks = list(self._draft.subtasks)
        subtasks[index] = subtask
        self._draft = replace(self._draft, subtasks=tuple(subtasks))
        self._repaint()

    def _dropped(self, index: int) -> None:
        subtasks = list(self._draft.subtasks)
        del subtasks[index]
        self._draft = replace(self._draft, subtasks=tuple(subtasks))
        self._repaint()

    async def action_set_labels(self) -> None:
        known = await self._load(self._catalog.labels, "labels")
        if known is None:
            return
        self._pick(
            LabelsScreen(sorted(known), self._draft.labels),
            lambda chosen: replace(
                self._draft,
                labels=chosen,
                new_labels=tuple(name for name in chosen if name not in known),
            ),
        )

    def action_reminders(self) -> None:
        due = self._draft.due
        self._pick(
            RemindersScreen(
                self._today,
                self._draft.reminders,
                # a relative reminder fires off the task's own due time
                allow_relative=isinstance(due, Due) and due.time is not None,
                mode="manage",
            ),
            self._remembered,
        )

    def _remembered(self, request: ReminderRequest) -> TaskDraft:
        if request.delete_id is not None:
            return replace(
                self._draft,
                reminders=tuple(
                    r for r in self._draft.reminders if r.id != request.delete_id
                ),
            )
        if request.add_relative is not None:
            return self._remembering(
                Reminder("", "", "relative", minute_offset=request.add_relative)
            )
        # an absolute reminder needs a datetime, which the next picker collects
        self.call_after_refresh(self._pick_reminder_time)
        return self._draft

    def _pick_reminder_time(self) -> None:
        self._pick(
            ScheduleScreen(self._today),
            lambda result: (
                self._remembering(Reminder("", "", "absolute", result.due))
                if result.due is not None
                else self._draft
            ),
        )

    def _remembering(self, reminder: Reminder) -> TaskDraft:
        return replace(self._draft, reminders=(*self._draft.reminders, reminder))

    async def _load[T](self, fetch: Callable[[], Awaitable[T]], what: str) -> T | None:
        """Fetch what a picker chooses from, reporting a failure on the hint line
        rather than the list's status band, which is out of sight from here."""
        if self._loading:  # a chord already has one in flight
            return None
        self._loading = True
        try:
            return await fetch()
        except Exception as error:
            self.query_one("#hint", Static).update(f"Failed to load {what}: {error}")
            return None
        finally:
            self._loading = False

    def _repaint(self) -> None:
        self.query_one("#attributes", Static).update(
            attribute_strip(
                self._draft, self._today, tier_styles(self), priority_styles(self)
            )
        )
        if self._nests:
            self.query_one(SubtaskList).show(self._draft.subtasks)

    def _pick[T](
        self, screen: ModalScreen[T | None], onto: Callable[[T], TaskDraft]
    ) -> None:
        """Open a picker over the editor and fold its answer into the draft; a
        cancelled picker leaves the draft as it was."""

        def taken(result: T | None) -> None:
            if result is None:
                return
            self._draft = onto(result)
            self._repaint()

        self._app.push_screen(screen, taken)

    @property
    def _app(self) -> App[object]:
        """Textual types `self.app` as App[Unknown]; a pushed screen owns its own
        result type, so nothing here depends on the app's."""
        return cast(
            App[object],
            self.app,  # pyright: ignore[reportUnknownMemberType]
        )
