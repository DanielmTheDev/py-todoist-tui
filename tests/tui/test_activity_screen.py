import asyncio
import datetime
from collections.abc import Sequence
from typing import cast

import pytest
from textual.app import App
from textual.content import Content
from textual.widgets import Input, Static

from tests.tui.tiers import span_tiers
from tests.tui.waiting import settled
from todoist_tui.application.activity import ActivityRow
from todoist_tui.domain.activity import ActivityEvent, EventKind
from todoist_tui.tui.screens.activity import ActivityScreen
from todoist_tui.tui.screens.help import HelpScreen
from todoist_tui.tui.theme import TODOIST_THEME, Tier

_TODAY = datetime.date(2026, 8, 27)
_UTC = datetime.UTC


def _row(
    hour: int,
    kind: EventKind = EventKind.COMPLETED,
    content: str = "Buy milk",
    project_name: str | None = "Work",
    day: int = 27,
) -> ActivityRow:
    return ActivityRow(
        event=ActivityEvent(
            id=f"{day}-{hour}",
            at=datetime.datetime(2026, 8, day, hour, 24, tzinfo=_UTC),
            kind=kind,
            content=content,
            task_id="t1",
            project_id="9",
        ),
        project_name=project_name,
    )


_ROWS = (
    _row(11),
    _row(9, EventKind.ADDED, "Call Bob", None),
    _row(18, EventKind.MOVED, "Old thing", "Backlog", day=26),
)


class _FakeLoader:
    """Stands in for the app's page loader, recording what the feed asked for."""

    def __init__(
        self, pages: Sequence[tuple[tuple[ActivityRow, ...], str | None]]
    ) -> None:
        self.calls: list[tuple[EventKind | None, str | None]] = []
        self._pages = list(pages)

    async def __call__(
        self, event_type: EventKind | None, cursor: str | None
    ) -> tuple[tuple[ActivityRow, ...], str | None]:
        self.calls.append((event_type, cursor))
        return self._pages.pop(0) if self._pages else ((), None)


class _Host(App[None]):
    def __init__(
        self,
        rows: tuple[ActivityRow, ...] = _ROWS,
        dismissed: list[None] | None = None,
        cursor: str | None = None,
        loader: _FakeLoader | None = None,
    ) -> None:
        super().__init__()
        self._rows = rows
        self._dismissed = dismissed if dismissed is not None else []
        self._cursor = cursor
        self.loader = loader or _FakeLoader([])

    def on_mount(self) -> None:
        self.register_theme(TODOIST_THEME)
        self.theme = TODOIST_THEME.name
        self.push_screen(
            ActivityScreen(self._rows, _TODAY, self.loader, self._cursor, _UTC),
            lambda _result: self._dismissed.append(None),
        )


def _text(host: _Host) -> Content:
    return cast(Content, host.screen.query_one("#activity", Static).render())


def _hint(host: _Host) -> str:
    return cast(Content, host.screen.query_one("#activity-hint", Static).render()).plain


@pytest.mark.anyio
async def test_events_are_grouped_under_relative_day_headings() -> None:
    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        lines = [
            line.rstrip() for line in _text(host).plain.splitlines() if line.strip()
        ]

    assert lines.index("Today") < lines.index("Yesterday")
    assert any("11:24" in line and "completed" in line for line in lines)
    assert any("Buy milk" in line and "#Work" in line for line in lines)
    # a project-less event still renders, without a stray sigil
    assert any("Call Bob" in line and "#" not in line for line in lines)


@pytest.mark.anyio
async def test_typing_narrows_the_feed_and_drops_emptied_days() -> None:
    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m", "i", "l", "k")
        await pilot.pause()
        plain = _text(host).plain

    assert "Buy milk" in plain
    assert "Call Bob" not in plain
    assert "Yesterday" not in plain  # its only event no longer matches


@pytest.mark.anyio
async def test_filter_also_matches_the_verb_and_the_project() -> None:
    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("b", "a", "c", "k")
        await pilot.pause()
        plain = _text(host).plain

    assert "Old thing" in plain
    assert "Buy milk" not in plain


@pytest.mark.anyio
async def test_escape_closes_the_feed() -> None:
    dismissed: list[None] = []
    host = _Host(dismissed=dismissed)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert dismissed == [None]


@pytest.mark.anyio
async def test_the_task_leads_and_its_project_recedes() -> None:
    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        body = host.screen.query_one("#activity", Static)
        runs = span_tiers(body, _text(host))

    assert any(tier is Tier.PRIMARY and "Buy milk" in text for tier, text in runs)
    assert any(tier is Tier.MUTED and "#Work" in text for tier, text in runs)


@pytest.mark.anyio
async def test_the_filter_box_keeps_focus_so_typing_always_filters() -> None:
    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.screen.focused is host.screen.query_one(Input)


@pytest.mark.anyio
async def test_reaching_the_bottom_pulls_the_next_page() -> None:
    loader = _FakeLoader([((_row(7, content="Older"),), None)])
    host = _Host(cursor="page2", loader=loader)
    async with host.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        await pilot.press("pagedown")
        await pilot.pause()
        await settled(host)
        await pilot.pause()
        plain = _text(host).plain

    assert loader.calls == [(None, "page2")]
    assert "Older" in plain


@pytest.mark.anyio
async def test_the_last_page_stops_asking() -> None:
    loader = _FakeLoader([])
    host = _Host(cursor=None, loader=loader)
    async with host.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        await pilot.press("pagedown", "pagedown", "pagedown")
        await pilot.pause()
        await settled(host)
        hint = _hint(host)

    assert loader.calls == []
    assert "end of activity" in hint


@pytest.mark.anyio
async def test_tab_cycles_the_event_filter_and_reloads_from_the_top() -> None:
    loader = _FakeLoader([((_row(6, EventKind.ADDED, "Only added"),), "p2")])
    host = _Host(cursor="page2", loader=loader)
    async with host.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        await settled(host)
        await pilot.pause()
        plain = _text(host).plain
        hint = _hint(host)

    assert loader.calls == [(EventKind.ADDED, None)]  # fresh page, no cursor
    assert "Only added" in plain
    assert "Buy milk" not in plain  # the unfiltered rows are gone
    assert "added" in hint  # the hint names the active filter


@pytest.mark.anyio
async def test_cycling_past_the_last_kind_returns_to_the_whole_feed() -> None:
    kinds = [kind for kind in EventKind if kind is not EventKind.OTHER]
    loader = _FakeLoader([((), None) for _ in kinds] + [(_ROWS, None)])
    host = _Host(loader=loader)
    async with host.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        for _ in range(len(kinds) + 1):
            await pilot.press("tab")
            await pilot.pause()
            await settled(host)

    assert [kind for kind, _cursor in loader.calls] == [*kinds, None]


@pytest.mark.anyio
async def test_a_page_is_pulled_only_once_the_bottom_is_reached() -> None:
    many = tuple(_row(hour, content=f"Event {hour}") for hour in range(23, 0, -1))
    loader = _FakeLoader([((_row(0, content="Older"),), None)])
    host = _Host(rows=many, cursor="page2", loader=loader)
    async with host.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        await pilot.press("down")  # a nudge, nowhere near the end
        await pilot.pause()
        await settled(host)
        assert loader.calls == []

        for _ in range(10):
            await pilot.press("pagedown")
        await pilot.pause()
        await settled(host)

    assert loader.calls == [(None, "page2")]


class _FailingLoader:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(
        self, event_type: EventKind | None, cursor: str | None
    ) -> tuple[tuple[ActivityRow, ...], str | None]:
        self.calls += 1
        raise RuntimeError("offline")


@pytest.mark.anyio
async def test_a_failed_page_is_reported_and_can_be_retried() -> None:
    loader = _FailingLoader()
    host = _Host(cursor="page2", loader=loader)  # pyright: ignore[reportArgumentType]
    async with host.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        await pilot.press("pagedown")
        await pilot.pause()
        await settled(host)
        await pilot.pause()
        plain = _text(host).plain

        assert "offline" in _hint(host)
        assert "Buy milk" in plain  # what was loaded stays on screen

        await pilot.press("pagedown")  # the failure must not wedge the feed
        await pilot.pause()
        await settled(host)

    assert loader.calls == 2


class _BlockingLoader:
    """First page waits on a gate, so a filter change lands mid-flight."""

    def __init__(self, gate: asyncio.Event, rows: tuple[ActivityRow, ...]) -> None:
        self.calls: list[tuple[EventKind | None, str | None]] = []
        self._gate = gate
        self._rows = rows

    async def __call__(
        self, event_type: EventKind | None, cursor: str | None
    ) -> tuple[tuple[ActivityRow, ...], str | None]:
        self.calls.append((event_type, cursor))
        if len(self.calls) == 1:
            await self._gate.wait()
            return (), None
        return self._rows, None


@pytest.mark.anyio
async def test_switching_filter_mid_load_still_fills_the_feed() -> None:
    gate = asyncio.Event()
    loader = _BlockingLoader(gate, (_row(6, EventKind.ADDED, "Only added"),))
    host = _Host(cursor="page2", loader=loader)  # pyright: ignore[reportArgumentType]
    async with host.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        await pilot.press("pagedown")  # starts the page that will hang
        await pilot.pause()
        await pilot.press("tab")  # ADDED, while that page is still in flight
        await pilot.pause()
        gate.set()
        await settled(host)
        await pilot.pause()
        plain = _text(host).plain

    assert [kind for kind, _cursor in loader.calls] == [None, EventKind.ADDED]
    assert "Only added" in plain
    assert "Buy milk" not in plain  # the abandoned filter's rows stay gone


@pytest.mark.anyio
async def test_the_hint_names_every_key_and_stays_put_while_the_feed_scrolls() -> None:
    """Scrolled out of sight, `tab` would be secret knowledge."""
    many = tuple(_row(hour, content=f"Event {hour}") for hour in range(23, 0, -1))
    host = _Host(rows=many)
    async with host.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        for _ in range(10):
            await pilot.press("pagedown")
        await pilot.pause()
        hint = _hint(host)

    assert "tab" in hint
    assert "f1" in hint
    assert "esc" in hint
    assert "filter: all" in hint


@pytest.mark.anyio
async def test_f1_lists_the_feeds_own_keys() -> None:
    host = _Host()
    async with host.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()

        assert isinstance(host.screen, HelpScreen)
        listed = cast(Content, host.screen.query_one("#help", Static).render()).plain

    assert "Next event filter" in listed
    assert "tab" in listed


@pytest.mark.anyio
async def test_the_hint_survives_a_short_terminal() -> None:
    """A percentage cap is measured against the screen, not against siblings."""
    many = tuple(_row(hour, content=f"Event {hour}") for hour in range(23, 0, -1))
    host = _Host(rows=many)
    async with host.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        bar = host.screen.query_one("#activity-hint", Static)

        assert bar.region.bottom <= host.size.height


@pytest.mark.anyio
async def test_two_filter_changes_in_one_frame_leave_one_filters_rows() -> None:
    """Both fetches are queued before either runs; only the last one counts."""
    gate = asyncio.Event()
    loader = _BlockingLoader(gate, (_row(6, EventKind.UPDATED, "Only updated"),))
    host = _Host(loader=loader)  # pyright: ignore[reportArgumentType]
    async with host.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        feed = cast(ActivityScreen, host.screen)
        feed.action_cycle_filter()  # ADDED
        feed.action_cycle_filter()  # UPDATED, before either page runs
        gate.set()
        await settled(host)
        await pilot.pause()
        plain = _text(host).plain

    assert [kind for kind, _cursor in loader.calls] == [
        EventKind.ADDED,
        EventKind.UPDATED,
    ]
    assert plain.count("Only updated") == 1
