"""Which task a manual move swaps with. Pure domain logic, no I/O.

Todoist keeps two hand-set orders, and a view uses whichever its shape allows.
`child_order` is a task's place among its siblings — the tasks sharing a parent,
or sharing a project and section at the top level — so it can only order a list
that *is* one sibling set, such as a project's section. `day_order` is a task's
place in a day-scoped list, which is what a view spanning projects has to use.

This module names what a move lands on under each: the sibling one step away, or
the assignments that place a whole day run.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from todoist_tui.domain.arrange import ArrangeRow, RenderRow, TaskLine
from todoist_tui.domain.task import UNSET_DAY_ORDER


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


def day_order_plan[T: OrderedRow](
    rendered: Sequence[RenderRow[T]], task_id: object, *, down: bool
) -> list[tuple[T, int]] | None:
    """The day orders to write so `task_id` moves one step within its run.

    The run is the stretch of lines beside it at its own level, bounded by a
    group header — so a grouped view orders inside each group, and an ungrouped
    one orders the whole list, siblings or not.

    Every task starts unplaced, and Todoist will happily report two tasks at the
    same day order, so a run that is not already a clean sequence is renumbered
    from 1 rather than having two values traded across it.

    None where the move is impossible, or where the row is a subtask under a
    parent that is itself on screen — there the sibling order is the real one.
    """
    found = _line_at(rendered, task_id)
    if found is None:
        return None
    index, line = found
    if _is_nested(rendered, line.row):
        return None
    run = _run(rendered, index, line)
    at = next(i for i, row in enumerate(run) if row.id == task_id)
    to = at + (1 if down else -1)
    if not 0 <= to < len(run):
        return None
    run[at], run[to] = run[to], run[at]
    if _is_a_clean_sequence(run):
        return [(run[to], run[at].day_order), (run[at], run[to].day_order)]
    return [(row, position) for position, row in enumerate(run, start=1)]


def _is_a_clean_sequence(run: Sequence[OrderedRow]) -> bool:
    """Every row placed, and no two sharing a position — so a trade is enough."""
    orders = [row.day_order for row in run]
    return all(order > UNSET_DAY_ORDER for order in orders) and len(set(orders)) == len(
        orders
    )


def _is_nested[T: OrderedRow](rendered: Sequence[RenderRow[T]], row: T) -> bool:
    """Is this row a subtask of another row on screen?

    A row indented under a group header is not: only a parent makes it a subtask,
    and only then is its sibling order the one the user sees.
    """
    if row.parent_id is None:
        return False
    return any(
        isinstance(entry, TaskLine) and str(entry.row.id) == row.parent_id
        for entry in rendered
    )


def _run[T: OrderedRow](
    rendered: Sequence[RenderRow[T]], index: int, line: TaskLine[T]
) -> list[T]:
    """The lines at `line`'s level reachable from it without crossing a header.

    Deeper lines in the way are subtrees and are stepped over; a header or a
    shallower line ends the run, which is what keeps a grouped view's groups
    ordered separately.
    """
    before: list[T] = []
    after: list[T] = []
    for step, reached in ((-1, before), (1, after)):
        position = index + step
        while 0 <= position < len(rendered):
            entry = rendered[position]
            if not isinstance(entry, TaskLine) or entry.level < line.level:
                break
            if entry.level == line.level:
                reached.append(entry.row)
            position += step
    return [*reversed(before), line.row, *after]


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
