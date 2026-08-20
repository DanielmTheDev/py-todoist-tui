import datetime
from collections.abc import Callable
from dataclasses import replace

import pytest
from textual import events
from textual.app import App
from textual.widgets import Input, Static, TextArea

from todoist_tui.application.views import TaskRow
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due, DueText
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import TaskId
from todoist_tui.tui.screens.draft import TaskDraft
from todoist_tui.tui.screens.edit import Catalog, TaskEditScreen
from todoist_tui.tui.screens.labels import LabelsScreen
from todoist_tui.tui.screens.parent_picker import ParentPickerScreen
from todoist_tui.tui.screens.project_picker import ProjectPickerScreen
from todoist_tui.tui.screens.reminders import RemindersScreen
from todoist_tui.tui.screens.schedule import ScheduleScreen
from todoist_tui.tui.screens.scrolling import ScrollBody

TODAY = datetime.date(2026, 8, 19)


def _paste(app: App[None], text: str) -> None:
    """A bracketed paste, as the terminal delivers it: to the app, which forwards
    it to whichever field has focus."""
    app.post_message(events.Paste(text))


def _link_hint(app: App[None]) -> str:
    return str(app.screen.query_one("#link", Static).content)


def _strip(app: App[None]) -> str:
    return str(app.screen.query_one("#attributes", Static).content)


def _hint(app: App[None]) -> str:
    return str(app.screen.query_one("#hint", Static).content)


def _row(content: str, **fields: object) -> TaskRow:
    return TaskRow(
        id=TaskId(content),
        content=content,
        priority=Priority.P4,
        due=None,
        **fields,  # pyright: ignore[reportArgumentType]
    )


def _catalog(
    projects: list[Project] | None = None,
    sections: list[Section] | None = None,
    parents: list[TaskRow] | None = None,
    labels: list[str] | None = None,
    fails: str | None = None,
) -> Catalog:
    async def move_targets() -> tuple[list[Project], list[Section]]:
        if fails == "projects":
            raise RuntimeError("offline")
        return projects or [], sections or []

    async def all_parents() -> list[TaskRow]:
        return parents or []

    async def all_labels() -> list[str]:
        return labels or []

    return Catalog(move_targets, all_parents, all_labels)


class _Host(App[None]):
    def __init__(
        self,
        content: str,
        description: str,
        on_result: Callable[[TaskDraft | None], None],
        draft: TaskDraft | None = None,
        catalog: Catalog | None = None,
    ) -> None:
        super().__init__()
        self._draft = draft or TaskDraft(content, description)
        self._catalog = catalog or _catalog()
        self._on_result = on_result

    def on_mount(self) -> None:
        self.push_screen(
            TaskEditScreen(self._draft, TODAY, self._catalog), self._on_result
        )


@pytest.mark.anyio
async def test_both_fields_are_prefilled() -> None:
    host = _Host("Buy milk", "oat, 2x", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.screen.query_one(Input).value == "Buy milk"
        assert host.screen.query_one(TextArea).text == "oat, 2x"


@pytest.mark.anyio
async def test_ctrl_s_returns_both_edited_values() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("!")  # appends to the title, does not replace it
        await pilot.press("tab")
        await pilot.press("2", "x")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milk!", "oat2x")]


@pytest.mark.anyio
async def test_typing_appends_instead_of_wiping_the_prefilled_title() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("s")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milks", "")]


@pytest.mark.anyio
async def test_tab_moves_focus_to_the_description() -> None:
    host = _Host("Buy milk", "oat", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.focused is host.screen.query_one(Input)
        await pilot.press("tab")
        await pilot.pause()
        assert host.focused is host.screen.query_one(TextArea)


@pytest.mark.anyio
async def test_enter_in_the_title_saves() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milk", "oat")]


@pytest.mark.anyio
async def test_enter_in_the_description_adds_a_line() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.press("enter", "2", "x")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milk", "oat\n2x")]


@pytest.mark.anyio
async def test_ctrl_backspace_in_the_title_deletes_the_word_to_the_left() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy oat milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+backspace")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy oat", "")]


@pytest.mark.anyio
async def test_ctrl_shift_a_in_the_description_selects_all_so_typing_replaces() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "oat\nand 2x", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.press("ctrl+shift+a")
        await pilot.press("s", "o", "y")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milk", "soy")]


@pytest.mark.anyio
async def test_escape_returns_none() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("x")
        await pilot.press("escape")
        await pilot.pause()
        assert edited == [None]


@pytest.mark.anyio
async def test_surrounding_whitespace_is_trimmed() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("  Buy milk  ", "  oat  ", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milk", "oat")]


@pytest.mark.anyio
async def test_blank_title_does_not_dismiss() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("", "oat", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == []
        host.screen.query_one(Input)  # still mounted
        await pilot.press("escape")
        await pilot.pause()
        assert edited == [None]


@pytest.mark.anyio
async def test_a_url_pasted_onto_a_title_makes_the_title_the_link() -> None:
    host = _Host("review the PR", "", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, "https://example.com/pr/9")
        await pilot.pause()
        assert (
            host.screen.query_one(Input).value
            == "[review the PR](https://example.com/pr/9)"
        )
        assert _link_hint(host) == ""


@pytest.mark.anyio
async def test_a_url_pasted_onto_an_empty_title_waits_for_the_title() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, "https://example.com/pr/9")
        await pilot.pause()
        assert host.screen.query_one(Input).value == ""
        assert _link_hint(host) == "↳ link: https://example.com/pr/9"
        await pilot.press("p", "r")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("[pr](https://example.com/pr/9)", "")]


@pytest.mark.anyio
async def test_the_newest_pasted_url_replaces_a_waiting_one() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, "https://example.com/old")
        await pilot.pause()
        _paste(host, "https://example.com/new")
        await pilot.pause()
        await pilot.press("p", "r")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("[pr](https://example.com/new)", "")]


@pytest.mark.anyio
async def test_a_url_pasted_onto_an_already_linked_title_stays_bare() -> None:
    host = _Host("[a](https://example.com/a)", "", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, "https://example.com/b")
        await pilot.pause()
        assert (
            host.screen.query_one(Input).value
            == "[a](https://example.com/a) https://example.com/b"
        )


@pytest.mark.anyio
async def test_pasted_text_that_is_not_a_url_is_inserted_as_typed() -> None:
    host = _Host("Buy", "", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        _paste(host, " oat milk")
        await pilot.pause()
        assert host.screen.query_one(Input).value == "Buy oat milk"
        assert _link_hint(host) == ""


@pytest.mark.anyio
async def test_a_url_pasted_into_the_description_stays_a_plain_paste() -> None:
    host = _Host("Buy milk", "", lambda _result: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        _paste(host, "https://example.com/x")
        await pilot.pause()
        assert host.screen.query_one(TextArea).text == "https://example.com/x"
        assert _link_hint(host) == ""


@pytest.mark.anyio
async def test_the_fields_scroll_on_a_terminal_too_short_for_them() -> None:
    host = _Host("Buy milk", "\n".join(f"line {n}" for n in range(30)), lambda _r: None)

    async with host.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        body = host.screen.query_one(ScrollBody)
        assert body.region.bottom <= 10
        assert body.max_scroll_y > 0


@pytest.mark.anyio
async def test_the_strip_shows_every_attribute_the_draft_carries() -> None:
    draft = TaskDraft(
        "Buy milk",
        "",
        priority=Priority.P2,
        due=Due(date=datetime.date(2026, 8, 20)),
        deadline=Deadline(date=datetime.date(2026, 9, 30)),
        labels=("errand",),
        project_id="7",
        project_name="Work",
        section_id="9",
        section_name="Backlog",
    )
    host = _Host("", "", lambda _r: None, draft=draft)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert _strip(host) == (
            "Due Tomorrow · Deadline 30 Sep · Project Work / Backlog"
            " · Parent — · Reminders — · Labels @errand · Priority P2"
        )


@pytest.mark.anyio
async def test_the_strip_dashes_what_the_draft_leaves_unset() -> None:
    host = _Host("Buy milk", "", lambda _r: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        assert (
            _strip(host) == "Due — · Deadline — · Project — · Parent —"
            " · Reminders — · Labels — · Priority P4"
        )


@pytest.mark.anyio
async def test_saving_carries_the_untouched_attributes_back() -> None:
    draft = TaskDraft(
        "Buy milk",
        "oat",
        priority=Priority.P1,
        due=Due(date=datetime.date(2026, 8, 20)),
        labels=("errand",),
        project_id="7",
        project_name="Work",
    )
    edited: list[TaskDraft | None] = []
    host = _Host("", "", edited.append, draft=draft)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("!")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [replace(draft, content="Buy milk!")]


@pytest.mark.anyio
async def test_alt_t_picks_a_due_date_into_the_draft() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+t")
        await pilot.pause()
        assert isinstance(host.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow
        await pilot.pause()

        assert _strip(host).startswith("Due Tomorrow ·")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [
            TaskDraft("Buy milk", "", due=Due(date=datetime.date(2026, 8, 20)))
        ]


@pytest.mark.anyio
async def test_alt_t_keeps_a_recurring_rule_when_it_moves_the_date() -> None:
    recurring = Due(
        date=datetime.date(2026, 8, 19), is_recurring=True, string="every monday"
    )
    edited: list[TaskDraft | None] = []
    host = _Host("", "", edited.append, draft=TaskDraft("Buy milk", "", due=recurring))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+t")
        await pilot.pause()
        await pilot.press("m")  # tomorrow
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [
            TaskDraft(
                "Buy milk",
                "",
                due=replace(recurring, date=datetime.date(2026, 8, 20)),
            )
        ]


@pytest.mark.anyio
async def test_a_typed_phrase_is_carried_as_written() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+t")
        await pilot.pause()
        await pilot.press("s")  # focus the phrase box
        for key in "every friday":
            await pilot.press(key if key != " " else "space")
        await pilot.press("enter")
        await pilot.pause()

        assert _strip(host).startswith("Due every friday ·")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milk", "", due=DueText("every friday"))]


@pytest.mark.anyio
async def test_alt_d_picks_a_deadline_into_the_draft() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+d")
        await pilot.pause()
        await pilot.press("m")  # tomorrow
        await pilot.pause()

        assert "Deadline Tomorrow" in _strip(host)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [
            TaskDraft(
                "Buy milk", "", deadline=Deadline(date=datetime.date(2026, 8, 20))
            )
        ]


@pytest.mark.anyio
async def test_cancelling_a_picker_leaves_the_draft_alone() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+t")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert _strip(host).startswith("Due — ·")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milk", "")]


@pytest.mark.anyio
async def test_alt_1_sets_the_priority_without_leaving_the_editor() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+1")
        await pilot.pause()

        assert "Priority P1" in _strip(host)
        assert host.screen.query_one(Input).value == "Buy milk"  # not typed into
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milk", "", priority=Priority.P1)]


@pytest.mark.anyio
async def test_alt_v_moves_the_draft_to_a_section() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host(
        "Buy milk",
        "",
        edited.append,
        catalog=_catalog(
            projects=[Project(id="9", name="Work")],
            sections=[Section(id="s1", project_id="9", name="Now", order=1)],
        ),
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+v")
        await pilot.pause()
        assert isinstance(host.screen, ProjectPickerScreen)
        await pilot.press("2")  # the section under its project
        await pilot.pause()

        assert "Project Work / Now" in _strip(host)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [
            TaskDraft(
                "Buy milk",
                "",
                project_id="9",
                project_name="Work",
                section_id="s1",
                section_name="Now",
            )
        ]


@pytest.mark.anyio
async def test_alt_n_nests_the_draft_and_takes_the_parents_project() -> None:
    parent = _row("chores", project_name="Work", project_id="9", section_id="s1")
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append, catalog=_catalog(parents=[parent]))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+n")
        await pilot.pause()
        assert isinstance(host.screen, ParentPickerScreen)
        await pilot.press("2")  # 1 is the top-level entry
        await pilot.pause()

        assert "Parent chores" in _strip(host)
        assert "Project Work" in _strip(host)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [
            TaskDraft(
                "Buy milk",
                "",
                project_id="9",
                project_name="Work",
                section_id="s1",
                parent_id="chores",
                parent=parent,
            )
        ]


@pytest.mark.anyio
async def test_nesting_drops_the_due_date_the_parent_picker_offers_to_drop() -> None:
    parent = _row("chores", project_id="9", project_name="Work")
    edited: list[TaskDraft | None] = []
    host = _Host(
        "",
        "",
        edited.append,
        draft=TaskDraft("Buy milk", "", due=Due(date=TODAY)),
        catalog=_catalog(parents=[parent]),
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+n")
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()

        assert _strip(host).startswith("Due — ·")


@pytest.mark.anyio
async def test_alt_l_replaces_the_labels_and_flags_a_new_one() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host(
        "",
        "",
        edited.append,
        draft=TaskDraft("Buy milk", "", labels=("errand",)),
        catalog=_catalog(labels=["errand", "home"]),
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+l")
        await pilot.pause()
        assert isinstance(host.screen, LabelsScreen)
        await pilot.press("h", "o")  # filters down to "home"
        await pilot.press("space")  # adds it
        await pilot.press("enter")
        await pilot.pause()

        assert "Labels @errand @home" in _strip(host)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [TaskDraft("Buy milk", "", labels=("errand", "home"))]


@pytest.mark.anyio
async def test_a_label_the_catalog_does_not_know_is_marked_for_creation() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append, catalog=_catalog(labels=["errand"]))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+l")
        await pilot.pause()
        await pilot.press("n", "e", "w")  # no match: offers to create it
        await pilot.press("space")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [
            TaskDraft("Buy milk", "", labels=("new",), new_labels=("new",))
        ]


@pytest.mark.anyio
async def test_a_catalog_that_cannot_load_is_reported_and_the_editor_stays() -> None:
    host = _Host("Buy milk", "", lambda _r: None, catalog=_catalog(fails="projects"))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+v")
        await pilot.pause()

        assert isinstance(host.screen, TaskEditScreen)
        assert _hint(host) == "Failed to load projects: offline"


@pytest.mark.anyio
async def test_alt_r_adds_a_relative_reminder_to_a_dated_draft() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host(
        "",
        "",
        edited.append,
        draft=TaskDraft("Buy milk", "", due=Due(date=TODAY, time=datetime.time(9, 0))),
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+m")
        await pilot.pause()
        assert isinstance(host.screen, RemindersScreen)
        await pilot.press("a", "r")  # add, relative
        await pilot.pause()
        await pilot.press("h")  # the 1-hour-before preset
        await pilot.pause()

        assert "Reminders 60 min before" in _strip(host)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited[0] is not None
        assert edited[0].reminders == (Reminder("", "", "relative", minute_offset=60),)


@pytest.mark.anyio
async def test_alt_r_drops_a_reminder_the_draft_already_had() -> None:
    reminder = Reminder("r1", "t1", "relative", minute_offset=0)
    edited: list[TaskDraft | None] = []
    host = _Host(
        "",
        "",
        edited.append,
        draft=TaskDraft(
            "Buy milk",
            "",
            due=Due(date=TODAY, time=datetime.time(9, 0)),
            reminders=(reminder,),
        ),
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+m")
        await pilot.pause()
        await pilot.press("d")  # deletes the highlighted reminder
        await pilot.pause()
        await pilot.pause()

        assert "Reminders —" in _strip(host)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [
            TaskDraft("Buy milk", "", due=Due(date=TODAY, time=datetime.time(9, 0)))
        ]


@pytest.mark.anyio
async def test_an_absolute_reminder_finishes_in_the_date_picker() -> None:
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+m")
        await pilot.pause()
        await pilot.press("a", "a")  # add, absolute
        await pilot.pause()
        assert isinstance(host.screen, ScheduleScreen)
        await pilot.press("m")  # tomorrow
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited[0] is not None
        assert edited[0].reminders == (
            Reminder("", "", "absolute", Due(date=datetime.date(2026, 8, 20))),
        )


@pytest.mark.anyio
async def test_naming_a_project_lifts_the_draft_out_of_its_parent() -> None:
    parent = _row("chores", project_name="Work", project_id="9")
    edited: list[TaskDraft | None] = []
    host = _Host(
        "",
        "",
        edited.append,
        draft=TaskDraft("Buy milk", "", parent_id="chores", parent=parent),
        catalog=_catalog(projects=[Project(id="7", name="Home")]),
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("alt+v")
        await pilot.pause()
        await pilot.press("1")  # Home
        await pilot.pause()

        assert "Parent —" in _strip(host)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert edited == [
            TaskDraft("Buy milk", "", project_id="7", project_name="Home")
        ]


@pytest.mark.anyio
async def test_f1_lays_the_editors_shortcuts_over_it() -> None:
    """The chords used to be spelled out under the fields; they live behind a
    help overlay now, as every other screen's keys do."""
    host = _Host("Buy milk", "", lambda _r: None)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        shown = str(host.screen.query_one("#help", Static).render())

        assert "alt+t" in shown
        assert "tab" in shown  # Textual owns the key; help still names it
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(host.screen, TaskEditScreen)


@pytest.mark.anyio
async def test_the_editor_carries_no_key_strip_of_its_own() -> None:
    host = _Host("Buy milk", "", lambda _r: None)
    async with host.run_test() as pilot:
        await pilot.pause()

        assert not host.screen.query("#chords")
        assert _hint(host) == "f1 help"


@pytest.mark.anyio
async def test_a_question_mark_is_typed_into_the_title() -> None:
    """Why the help key is f1 and not `?`: the title field takes the character."""
    edited: list[TaskDraft | None] = []
    host = _Host("Buy milk", "", edited.append)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert edited == [TaskDraft("Buy milk?", "")]
