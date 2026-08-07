import datetime
from typing import cast

import pytest
from textual.app import App
from textual.content import Content
from textual.widgets import Static

from tests.tui.tiers import priority_at, span_tiers
from todoist_tui.application.views import TaskRow
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reminder import Reminder
from todoist_tui.domain.task import TaskId
from todoist_tui.tui.screens.detail import DetailCard, TaskDetailScreen
from todoist_tui.tui.theme import TODOIST_THEME, Tier

_TODAY = datetime.date(2026, 7, 28)
_DUE = Due(date=datetime.date(2026, 7, 29), time=datetime.time(9, 0))


def _row(
    content: str = "Buy milk",
    due: Due | None = _DUE,
    priority: Priority = Priority.P1,
    project_name: str | None = "Errands",
    section_name: str | None = "Planning",
    labels: tuple[str, ...] = ("home", "errand"),
    description: str = "2% from the corner store",
    deadline: Deadline | None = None,
    reminders: tuple[Reminder, ...] = (),
) -> TaskRow:
    return TaskRow(
        id=TaskId("6X4"),
        content=content,
        priority=priority,
        due=due,
        project_name=project_name,
        section_name=section_name,
        labels=labels,
        description=description,
        deadline=deadline,
        reminders=reminders,
    )


class _FakeOpener:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open(self, url: str) -> None:
        self.opened.append(url)


class _Host(App[None]):
    def __init__(
        self,
        row: TaskRow,
        dismissed: list[bool | None],
        opener: _FakeOpener | None = None,
        today: datetime.date = _TODAY,
    ) -> None:
        super().__init__()
        # the card only ever opens inside TodoistApp, so host it on the same
        # theme — the built-in default collapses $warning onto $accent
        self.register_theme(TODOIST_THEME)
        self.theme = TODOIST_THEME.name
        self._row = row
        self._dismissed = dismissed
        self._opener = opener or _FakeOpener()
        self._today = today

    def on_mount(self) -> None:
        self.push_screen(
            TaskDetailScreen(self._row, self._opener, self._today),
            self._dismissed.append,
        )


async def _shown(row: TaskRow) -> str:
    host = _Host(row, [])
    async with host.run_test() as pilot:
        await pilot.pause()
        return str(host.screen.query_one("#detail", Static).render())


async def _tiered(row: TaskRow, tier: Tier) -> list[str]:
    """The runs of the rendered card carrying `tier`."""
    host = _Host(row, [])
    async with host.run_test() as pilot:
        await pilot.pause()
        card = host.screen.query_one(DetailCard)
        content = cast(Content, card.render())
        return [text for found, text in span_tiers(card, content) if found is tier]


async def _result_of(row: TaskRow, key: str) -> list[bool | None]:
    """The values the card dismissed with after `key` — True asks for an edit."""
    dismissed: list[bool | None] = []
    host = _Host(row, dismissed)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
    return dismissed


async def _opened_after(row: TaskRow, *keys: str) -> list[str]:
    opener = _FakeOpener()
    host = _Host(row, [], opener)
    async with host.run_test() as pilot:
        await pilot.pause()
        for key in keys:
            await pilot.press(key)
        await pilot.pause()
    return opener.opened


@pytest.mark.anyio
async def test_renders_title_and_all_fields() -> None:
    shown = await _shown(_row())

    assert "Buy milk" in shown
    assert "Tomorrow 09:00" in shown
    assert "P1" in shown
    assert "Errands" in shown
    assert "Planning" in shown
    assert "@home" in shown
    assert "@errand" in shown
    assert "2% from the corner store" in shown


@pytest.mark.anyio
async def test_renders_deadline_when_set() -> None:
    shown = await _shown(_row(deadline=Deadline(date=datetime.date(2026, 8, 15))))

    assert "Deadline" in shown
    assert "15 Aug" in shown


@pytest.mark.anyio
async def test_an_overdue_due_and_deadline_sound_the_alarm() -> None:
    row = _row(
        due=Due(date=datetime.date(2026, 7, 27)),  # yesterday vs _TODAY
        deadline=Deadline(date=datetime.date(2026, 7, 20)),  # overdue
    )
    overdue = await _tiered(row, Tier.OVERDUE)

    assert any("Yesterday" in seg for seg in overdue)
    assert any("20 Jul" in seg for seg in overdue)


@pytest.mark.anyio
async def test_field_labels_recede_behind_their_values() -> None:
    muted = await _tiered(_row(), Tier.MUTED)
    primary = await _tiered(_row(), Tier.PRIMARY)

    assert any("Priority" in seg for seg in muted)
    assert any("P1" in seg for seg in primary)
    assert any("Errands" in seg for seg in primary)


@pytest.mark.anyio
async def test_the_priority_carries_its_own_coloured_dot() -> None:
    """Same mark as the list, so the card reads as the same language."""
    assert "● P1" in await _shown(_row(priority=Priority.P1))
    assert "P4" in await _shown(_row(priority=Priority.P4))  # P4 needs no marking
    assert "●" not in await _shown(_row(priority=Priority.P4))

    host = _Host(_row(priority=Priority.P2), [])
    async with host.run_test() as pilot:
        await pilot.pause()
        card = host.screen.query_one(DetailCard)
        content = cast(Content, card.render())
        assert priority_at(card, content, "●") is Priority.P2


@pytest.mark.anyio
async def test_section_headings_are_uppercase_and_recede() -> None:
    shown = await _shown(_LINKED)
    muted = await _tiered(_LINKED, Tier.MUTED)

    assert "DESCRIPTION" in shown
    assert "LINKS" in shown
    assert any("DESCRIPTION" in seg for seg in muted)


@pytest.mark.anyio
async def test_a_rule_separates_the_hint_from_the_body() -> None:
    shown = await _shown(_row())
    rule = next(line for line in shown.splitlines() if set(line) == {"─"})

    assert shown.splitlines().index(rule) < shown.splitlines().index(
        next(line for line in shown.splitlines() if "esc close" in line)
    )


@pytest.mark.anyio
async def test_no_deadline_renders_a_dash() -> None:
    shown = await _shown(_row(deadline=None))

    assert "Deadline" in shown
    assert "—" in shown


@pytest.mark.anyio
async def test_renders_every_reminder() -> None:
    row = _row(
        reminders=(
            Reminder(id="r1", item_id="6X4", type="relative", minute_offset=30),
            Reminder(
                id="r2",
                item_id="6X4",
                type="absolute",
                due=Due(date=datetime.date(2026, 7, 29), time=datetime.time(11, 0)),
            ),
        )
    )

    shown = await _shown(row)

    assert "Reminders" in shown
    assert "30 min before, Tomorrow 11:00" in shown


@pytest.mark.anyio
async def test_no_reminders_renders_a_dash() -> None:
    shown = await _shown(_row(reminders=()))

    assert "Reminders" in shown
    assert "—" in shown


@pytest.mark.anyio
async def test_no_section_renders_a_dash() -> None:
    shown = await _shown(_row(section_name=None))

    assert "Section" in shown
    assert "—" in shown


@pytest.mark.anyio
async def test_recurring_due_shows_the_rule() -> None:
    due = Due(date=datetime.date(2026, 7, 29), is_recurring=True, string="every day")

    shown = await _shown(_row(due=due))

    assert "every day" in shown


@pytest.mark.anyio
async def test_missing_description_shows_placeholder() -> None:
    shown = await _shown(_row(description=""))

    assert "No description" in shown


@pytest.mark.anyio
async def test_no_project_and_no_labels_render_a_dash() -> None:
    shown = await _shown(_row(project_name=None, labels=()))

    assert "@" not in shown  # no labels rendered
    assert "—" in shown


@pytest.mark.anyio
async def test_no_due_renders_a_dash() -> None:
    shown = await _shown(_row(due=None))

    assert "Due" in shown
    assert "—" in shown


@pytest.mark.anyio
@pytest.mark.parametrize("key", ["escape", "enter", "q"])
async def test_escape_enter_and_q_close_the_view(key: str) -> None:
    assert await _result_of(_row(), key) == [False]


@pytest.mark.anyio
async def test_ctrl_e_closes_the_view_asking_for_an_edit() -> None:
    assert await _result_of(_row(), "ctrl+e") == [True]


@pytest.mark.anyio
async def test_hint_advertises_the_edit_key() -> None:
    assert "ctrl+e edit" in await _shown(_row())


_LINKED = _row(
    description="see [spec](https://example.com/spec) and https://tracker/T-42",
)


@pytest.mark.anyio
async def test_renders_link_labels_and_numbered_refs() -> None:
    shown = await _shown(_LINKED)

    assert "spec [1]" in shown
    assert "https://tracker/T-42 [2]" in shown
    assert "[1] https://example.com/spec" in shown
    assert "[2] https://tracker/T-42" in shown


@pytest.mark.anyio
async def test_digit_opens_the_matching_link() -> None:
    assert await _opened_after(_LINKED, "1") == ["https://example.com/spec"]
    assert await _opened_after(_LINKED, "2") == ["https://tracker/T-42"]


@pytest.mark.anyio
async def test_o_opens_the_first_link() -> None:
    assert await _opened_after(_LINKED, "o") == ["https://example.com/spec"]


@pytest.mark.anyio
async def test_digit_out_of_range_opens_nothing() -> None:
    assert await _opened_after(_LINKED, "9") == []


@pytest.mark.anyio
async def test_link_numbering_spans_content_then_description() -> None:
    row = _row(
        content="review [pr](http://pr)",
        description="also [doc](http://doc)",
    )

    assert await _opened_after(row, "1") == ["http://pr"]
    assert await _opened_after(row, "2") == ["http://doc"]


@pytest.mark.anyio
async def test_a_task_without_links_opens_nothing_on_o() -> None:
    assert await _opened_after(_row(description="plain prose"), "o") == []
