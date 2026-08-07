"""Read the emphasis tier back off rendered cells.

Lets tests assert what a run of text *means* — leading, receding, overdue — rather
than the colour value it happens to carry, so retuning the palette doesn't rewrite
the suite.
"""

from rich.style import Style
from rich.text import Text
from textual.content import Content
from textual.style import Style as VisualStyle
from textual.widget import Widget
from textual.widgets import DataTable

from todoist_tui.tui.theme import Tier


def tier_of(widget: Widget, style: Style | str | None) -> Tier | None:
    """The tier `style`'s colour came from, as resolved against `widget`.

    Colour only: a rendered cell's style also carries the background it was
    resolved over, which the bare component style does not.
    """
    if style is None:
        return None
    parsed = Style.parse(style) if isinstance(style, str) else style
    if parsed.color is None:
        return None
    return next(
        (
            tier
            for tier in Tier
            if widget.get_component_rich_style(tier.value).color == parsed.color
        ),
        None,
    )


def cell_tier(widget: Widget, cell: object) -> Tier | None:
    """Tier of a cell's base style; None for a plain string or an unstyled cell."""
    return tier_of(widget, cell.style) if isinstance(cell, Text) else None


def dot(table: DataTable[object], row: int) -> str:
    """The priority dot in the row's leading column, past the selection slot."""
    return str(table.get_row_at(row)[0])[1:]


def selected(table: DataTable[object], row: int) -> bool:
    """Whether the row shows the selection bar in its slot, whatever glyph it is."""
    return bool(str(table.get_row_at(row)[0])[:1].strip())


def span_tiers(widget: Widget, text: Text | Content) -> list[tuple[Tier | None, str]]:
    """Each styled run of `text` as (tier, the text it covers).

    Takes both a Rich `Text` — what the table's cells hold — and a Textual
    `Content`, what a `Static` renders, whose spans carry visual styles instead
    and fold the base style into a run of its own.
    """
    return [
        (tier_of(widget, _as_rich(span.style)), text.plain[span.start : span.end])
        for span in text.spans
    ]


def _as_rich(style: Style | VisualStyle | str) -> Style:
    if isinstance(style, Style):
        return style
    return (VisualStyle.parse(style) if isinstance(style, str) else style).rich_style
