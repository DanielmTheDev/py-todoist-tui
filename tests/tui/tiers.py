"""Read the palette back off rendered cells.

Lets tests assert what a run of text *means* — leading, receding, overdue, P1 —
rather than the colour value it happens to carry, so retuning the palette doesn't
rewrite the suite.
"""

from rich.style import Style
from rich.text import Text
from textual.content import Content
from textual.style import Style as VisualStyle
from textual.widget import Widget
from textual.widgets import DataTable

from todoist_tui.domain.priority import Priority
from todoist_tui.tui.theme import Tier, priority_styles


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
            if _rgb(widget.get_component_rich_style(tier.value)) == _rgb(parsed)
        ),
        None,
    )


def _rgb(style: Style) -> tuple[int, int, int] | None:
    """A style's colour as a plain triplet.

    Rich `Color` equality includes the colour's *name*, which a style loses on the
    way through Textual's own `Style` — so two identical colours can compare
    unequal. The triplet is what actually reaches the terminal.
    """
    return None if style.color is None else style.color.triplet


def cell_tier(widget: Widget, cell: object) -> Tier | None:
    """Tier of a cell's base style; None for a plain string or an unstyled cell."""
    return tier_of(widget, cell.style) if isinstance(cell, Text) else None


def tier_at(widget: Widget, text: Text, needle: str) -> Tier | None:
    """Tier of the innermost run covering `needle` — for cells that carry several,
    like the title cell with its marker slot."""
    at = text.plain.index(needle)
    covering = [span for span in text.spans if span.start <= at < span.end]
    return tier_of(widget, covering[-1].style) if covering else cell_tier(widget, text)


def title_cell(table: DataTable[object], row: int) -> Text:
    """The leading cell: selection bar, priority dot, then the task title."""
    cell = table.get_row_at(row)[0]
    assert isinstance(cell, Text)
    return cell


def dot(table: DataTable[object], row: int) -> str:
    """The priority glyph in the row's marker slot, past the selection bar."""
    return title_cell(table, row).plain[1:2].strip()


def selected(table: DataTable[object], row: int) -> bool:
    """Whether the row shows the selection bar, whatever glyph it is."""
    return bool(title_cell(table, row).plain[:1].strip())


def priority_at(widget: Widget, text: Text | Content, needle: str) -> Priority | None:
    """The priority whose colour the run covering `needle` carries."""
    at = text.plain.index(needle)
    covering = [span for span in text.spans if span.start <= at < span.end]
    if not covering:
        return None
    colour = _rgb(_as_rich(covering[-1].style))
    return {
        _rgb(style): priority for priority, style in priority_styles(widget).items()
    }.get(colour)


def priority_of(table: DataTable[object], row: int) -> Priority | None:
    """The priority the row's dot marks, read back from its colour."""
    glyph = dot(table, row)
    return priority_at(table, title_cell(table, row), glyph) if glyph else None


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
