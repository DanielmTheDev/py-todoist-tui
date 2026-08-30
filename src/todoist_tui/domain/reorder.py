"""Which task a manual move swaps with. Pure domain logic, no I/O.

Todoist scopes `child_order` to a sibling set — the tasks sharing a parent, or
sharing a project and section at the top level — so a move is only meaningful
inside one. This module names the neighbour a move lands on, or nothing where the
task is already at its set's edge.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from todoist_tui.domain.arrange import ArrangeRow, RenderRow, TaskLine


class OrderedRow(ArrangeRow, Protocol):
    """An `ArrangeRow` that also carries what a sibling is identified by."""

    @property
    def project_id(self) -> str | None: ...
    @property
    def section_id(self) -> str | None: ...


def swap_with_neighbour[T: OrderedRow](
    rendered: Sequence[RenderRow[T]], task_id: object, *, down: bool
) -> tuple[T, T] | None:
    """`task_id` and the sibling one step `down` (or up) from it on screen.

    None where there is no such sibling: a group header, a deeper or shallower
    line, a row from another project or section, or the end of the list.
    """
    found = _line_at(rendered, task_id)
    if found is None:
        return None
    index, line = found
    neighbour = _neighbour(rendered, index, line.level, down=down)
    if neighbour is None or not _siblings(line.row, neighbour.row):
        return None
    return line.row, neighbour.row


def _line_at[T: OrderedRow](
    rendered: Sequence[RenderRow[T]], task_id: object
) -> tuple[int, TaskLine[T]] | None:
    return next(
        (
            (i, row)
            for i, row in enumerate(rendered)
            if isinstance(row, TaskLine) and row.row.id == task_id
        ),
        None,
    )


def _neighbour[T: OrderedRow](
    rendered: Sequence[RenderRow[T]], index: int, level: int, *, down: bool
) -> TaskLine[T] | None:
    """The next line at `level`, stepping over a subtree but nothing else.

    The deeper lines beside `index` can only be its own or its neighbour's
    descendants, so skipping them keeps the move between siblings rather than
    letting it jump a group boundary.
    """
    step = 1 if down else -1
    position = index + step
    while 0 <= position < len(rendered):
        row = rendered[position]
        if isinstance(row, TaskLine) and row.level > level:
            position += step
            continue
        return row if isinstance(row, TaskLine) and row.level == level else None
    return None


def _siblings(one: OrderedRow, other: OrderedRow) -> bool:
    return (one.parent_id, one.project_id, one.section_id) == (
        other.parent_id,
        other.project_id,
        other.section_id,
    )
