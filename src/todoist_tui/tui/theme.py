"""The app's palette, as text-emphasis tiers.

Colours live in `app.tcss` only. A tier names a CSS class; `tier_styles` resolves
those classes against a widget's own background and hands back Rich styles, so a
`Text` never has to name a colour. That keeps the ramp in one place and lets it
invert with the canvas on a light theme.
"""

from collections.abc import Mapping
from enum import Enum

from rich.style import Style
from textual.theme import Theme
from textual.widget import Widget

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

TIER_CSS = "\n".join(
    f".{tier.value} {{ color: {token}; }}" for tier, token in _TIER_TOKENS.items()
)
"""Every tiered widget carries this as its `DEFAULT_CSS`, so the ramp resolves
wherever the widget is mounted — not only under the app that owns the stylesheet."""

TODOIST_THEME = Theme(
    name="todoist",
    primary=ACCENT,
    accent=ACCENT,
    # the app paints its own canvas, so the terminal's background never shows
    # through the status band's tint
    background="#181b20",
    surface="#1e2228",
    error="#ff6d6d",
    dark=True,
)


def tier_styles(widget: Widget) -> Mapping[Tier, Style]:
    """Every tier resolved against `widget`'s background. Call at render time —
    the styles are recomputed when the theme or stylesheet changes."""
    return {tier: widget.get_component_rich_style(tier.value) for tier in Tier}
