import datetime

import pytest
from rich.style import Style
from textual.color import Color
from textual.widget import Widget

from tests.tui.test_app import FakeClock, FakeRepository
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.tui.app import TaskTable, TodoistApp
from todoist_tui.tui.format import MATCH_STYLE, render_links
from todoist_tui.tui.theme import ACCENT, TODOIST_THEME, Tier, tier_styles

_RAMP = (Tier.PRIMARY, Tier.SECONDARY, Tier.MUTED)  # leading to receding
_TODAY = datetime.date(2026, 7, 28)
_TASK = Task(
    id=TaskId("t"),
    content="A",
    priority=Priority.P4,
    due=Due(date=_TODAY),
    project_id="220",
)


def _color(style: Style) -> Color:
    assert style.color is not None and style.color.triplet is not None
    return Color(*style.color.triplet)


def _luminance(color: Color) -> float:
    """WCAG relative luminance."""

    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in (color.r, color.g, color.b))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(style: Style, background: Color) -> float:
    low, high = sorted((_luminance(_color(style)), _luminance(background)))
    return (high + 0.05) / (low + 0.05)


def _canvas(widget: Widget) -> Color:
    return widget.background_colors[1]


@pytest.mark.anyio
async def test_the_app_runs_on_its_own_theme() -> None:
    app = TodoistApp(FakeRepository([], []), clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == TODOIST_THEME.name


def test_the_accent_is_the_only_brand_colour() -> None:
    """One hex, reused wherever the accent shows: theme token, match, link."""
    assert TODOIST_THEME.accent == ACCENT
    assert MATCH_STYLE == ACCENT
    link = render_links("see https://example.com")
    assert any(ACCENT in str(span.style) for span in link.spans)


@pytest.mark.anyio
async def test_every_tier_resolves_to_a_distinct_colour() -> None:
    app = TodoistApp(FakeRepository([_TASK], []), clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        styles = tier_styles(app.query_one(TaskTable))
        assert set(styles) == set(Tier)
        assert len({_color(style) for style in styles.values()}) == len(Tier)


@pytest.mark.anyio
async def test_the_text_ramp_descends_in_contrast() -> None:
    app = TodoistApp(FakeRepository([_TASK], []), clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TaskTable)
        styles = tier_styles(table)
        contrasts = [_contrast(styles[tier], _canvas(table)) for tier in _RAMP]
        assert contrasts == sorted(contrasts, reverse=True)


@pytest.mark.anyio
async def test_the_ramp_stays_legible_on_a_light_theme() -> None:
    """The ramp is alpha over the widget's own background, so it inverts with the
    canvas instead of washing out — the reason no grey is hardcoded in Python."""
    app = TodoistApp(FakeRepository([_TASK], []), clock=FakeClock(_TODAY))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.theme = "textual-light"
        await pilot.pause()
        table = app.query_one(TaskTable)
        styles = tier_styles(table)
        canvas = _canvas(table)
        assert _contrast(styles[Tier.PRIMARY], canvas) >= 4.5
        assert _contrast(styles[Tier.SECONDARY], canvas) >= 3.0
        assert _contrast(styles[Tier.MUTED], canvas) >= 2.0
