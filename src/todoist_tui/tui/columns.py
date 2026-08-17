"""How the task table's columns share the width it has.

The table's widths are explicit — `cell_padding` has to be zero for a group
divider to run unbroken across the columns — so the fitting is ours to do. On a
terminal too narrow for everything, the title gives way first (capped, then
truncated by the caller) and only then do metadata columns drop, least useful
first.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

GUTTER = 2  # shared by the status band's padding and the table's cell padding
# The selection bar, the priority dot, and the space setting them off from the
# title. They open the title cell, so the column label has to clear the same
# width for TASK to sit above the titles rather than above their markers.
MARKER_SLOT = "   "
TITLE_MIN = 24  # a title column narrower than this reads as noise, not a title
_TITLE_SHARE = 0.5  # of the table, the most a squeezed title may take
# Least to most worth keeping: a project is implied by the view far more often
# than a due date is.
_DROP_ORDER = ("PROJECT", "DEADLINE", "LABELS", "DUE")


@dataclass(frozen=True)
class Column:
    """A column that survived the fit, and where its cells sit in the row."""

    index: int  # position in the caller's unfitted cell lists
    label: str
    width: int


def fit_columns(
    labels: Sequence[str],
    rows: Sequence[Sequence[Text | str]],
    available: int,
    first_minimum: int,
) -> list[Column]:
    """Each column as wide as its widest cell plus a gutter, the last stretched
    to the right edge.

    `first_minimum` keeps the title column wide enough for the group labels,
    which would otherwise be truncated by their own column — but a title cap
    outranks it, since a terminal that can't hold both is better off showing
    tasks than headers.
    """
    natural = _natural_widths(labels, rows, first_minimum)
    kept = list(range(len(labels)))
    widths = [natural[index] for index in kept]
    while available > 0 and sum(widths) > available:
        cap = max(TITLE_MIN, int(available * _TITLE_SHARE))
        if widths[0] > cap:
            widths[0] = cap
            if sum(widths) <= available:
                break
        droppable = _next_drop(labels, kept)
        if droppable is None:
            break
        kept.remove(droppable)
        widths = [natural[index] for index in kept]  # a drop may free the cap
    if (slack := available - sum(widths)) > 0:
        widths[-1] += slack
    return [
        Column(index, labels[index], width)
        for index, width in zip(kept, widths, strict=True)
    ]


def fit_row(cells: Sequence[Text | str], fitted: Sequence[Column]) -> list[Text | str]:
    """The row's cells for the columns that survived, title first and cut to fit
    its own — a title left whole would wrap the row or run into the next cell."""
    kept = [cells[column.index] for column in fitted]
    first = kept[0]
    if isinstance(first, Text):
        first = first.copy()
        first.truncate(max(0, fitted[0].width - GUTTER), overflow="ellipsis")
        kept[0] = first
    return kept


def _natural_widths(
    labels: Sequence[str], rows: Sequence[Sequence[Text | str]], first_minimum: int
) -> list[int]:
    # the first label is drawn past the marker slot, so it needs room for both
    widths = [
        cell_len(label) + (len(MARKER_SLOT) if column == 0 else 0)
        for column, label in enumerate(labels)
    ]
    for cells in rows:
        for column, cell in enumerate(cells):
            text = cell if isinstance(cell, str) else cell.plain
            widths[column] = max(widths[column], cell_len(text))
    widths = [width + GUTTER for width in widths]
    widths[0] = max(widths[0], first_minimum)
    return widths


def _next_drop(labels: Sequence[str], kept: Sequence[int]) -> int | None:
    for label in _DROP_ORDER:
        for index in kept:
            if labels[index] == label:
                return index
    return None
