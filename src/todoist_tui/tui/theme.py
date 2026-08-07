"""The app's palette: a text-emphasis ramp plus the priority scale.

Colours live in `PALETTE_CSS` only. Each name is a CSS class; the resolver
functions below look those classes up against a widget's own background and hand
back Rich styles, so a `Text` never has to name a colour. That keeps the palette
in one place and lets it invert with the canvas on a light theme.
"""

from collections.abc import Mapping
from enum import Enum

from rich.style import Style
from textual.theme import Theme
from textual.widget import Widget

from todoist_tui.domain.priority import Priority

ACCENT = "#89ddff"  # the one brand colour: cursor, links, matches, group labels


class Tier(Enum):
    """How much emphasis a run of text carries. Each value is a CSS class."""

    PRIMARY = "tier--primary"  # task titles and field values: what the eye lands on
    SECONDARY = "tier--secondary"  # dates: read right after the title
    MUTED = "tier--muted"  # project, labels, glyphs, rules: present but receding
    ACCENT = "tier--accent"  # what to look at now: a due time, a group label
    OVERDUE = "tier--overdue"  # the one alarm colour


TIER_CLASSES: frozenset[str] = frozenset(tier.value for tier in Tier)
"""Seeds each widget's own `COMPONENT_CLASSES`.

Declared per concrete widget rather than via a mixin: `DOMNode._css_bases` walks
only the first DOMNode base, so a mixin ahead of `DataTable` would hide
`DataTable`'s own component classes.
"""

# Alpha over the widget's own background, so the ramp follows the canvas rather
# than assuming a dark one. Generated from `Tier` so the two can't drift.
_TIER_TOKENS = {
    Tier.PRIMARY: "$text",
    Tier.SECONDARY: "$text-muted",
    Tier.MUTED: "$text-disabled",
    Tier.ACCENT: "$accent",
    Tier.OVERDUE: "$text-error",
}

# Priority is a scale of its own, not a step on the emphasis ramp: the dot says
# how urgent the task is, the ramp says how much attention its text deserves.
_PRIORITY_TOKENS = {
    Priority.P1: "$text-error",
    Priority.P2: "$warning",
    Priority.P3: "$accent",
}

PRIORITY_CLASSES: Mapping[Priority, str] = {
    priority: f"priority--{priority.name.lower()}" for priority in _PRIORITY_TOKENS
}

PALETTE_CLASSES: frozenset[str] = TIER_CLASSES | frozenset(PRIORITY_CLASSES.values())
"""Seeds each widget's own `COMPONENT_CLASSES` — see `TIER_CLASSES` for why the
seeding is per widget rather than via a mixin."""

PALETTE_CSS = "\n".join(
    f".{name} {{ color: {token}; }}"
    for name, token in [
        *((tier.value, token) for tier, token in _TIER_TOKENS.items()),
        *((PRIORITY_CLASSES[p], token) for p, token in _PRIORITY_TOKENS.items()),
    ]
)
"""Every palette-aware widget carries this as its `DEFAULT_CSS`, so the colours
resolve wherever the widget is mounted — not only under the app that owns the
stylesheet."""

TODOIST_THEME = Theme(
    name="todoist",
    primary=ACCENT,
    accent=ACCENT,
    # the app paints its own canvas, so the terminal's background never shows
    # through the status band's tint
    background="#181b20",
    surface="#1e2228",
    error="#ff6d6d",
    # set explicitly: unset, $warning falls back to $accent, and the P2 dot would
    # then be indistinguishable from the P3 one
    warning="#e0a458",
    dark=True,
)


def tier_styles(widget: Widget) -> Mapping[Tier, Style]:
    """Every tier resolved against `widget`'s background. Call at render time —
    the styles are recomputed when the theme or stylesheet changes."""
    return {tier: _foreground(widget, tier.value) for tier in Tier}


def priority_styles(widget: Widget) -> Mapping[Priority, Style]:
    """The colour of each marked priority's dot; P4 is unmarked, so absent."""
    return {
        priority: _foreground(widget, name)
        for priority, name in PRIORITY_CLASSES.items()
    }


def _foreground(widget: Widget, name: str) -> Style:
    """A component class's colour, without the background it resolved against.

    The colour is alpha over `widget`'s background, so Textual hands back that
    background too. Keeping it would make every styled run repaint the canvas —
    punching a hole in any row highlight drawn underneath.
    """
    return Style(color=widget.get_component_rich_style(name).color)
