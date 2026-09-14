from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto
from types import MappingProxyType

from todoist_tui.application.views import TaskRow, prune
from todoist_tui.domain.section import Section

_NO_PATCH: Mapping[str, object] = MappingProxyType({})
_NO_ORDERS: Mapping[str, int] = MappingProxyType({})


class Kind(Enum):
    """What a mutation does to the view: change fields, take rows out, put back,
    or move the section headers the rows sit under."""

    EDIT = auto()
    HIDE = auto()
    RESTORE = auto()
    SECTION_ORDER = auto()


@dataclass(frozen=True, slots=True)
class Mutation:
    """One local change to the view, not yet confirmed by the server.

    A log of these is the single source of the app's optimistic state: replayed
    over each freshly loaded snapshot by `apply`, so a lagging sync can never
    revert a change the user just made, and a mutation is retired on the server's
    acknowledgement rather than by guessing from the snapshot's contents.
    """

    kind: Kind
    task_ids: tuple[str, ...] = ()
    patch: Mapping[str, object] = _NO_PATCH  # EDIT: the `TaskRow` fields to set
    rows: tuple[TaskRow, ...] = ()  # RESTORE: what to put back
    # SECTION_ORDER: each moved section's new place in its project
    section_orders: Mapping[str, int] = _NO_ORDERS


def edit(task_ids: Iterable[str], **patch: object) -> Mutation:
    return Mutation(Kind.EDIT, tuple(task_ids), patch=patch)


def hide(task_ids: Iterable[str]) -> Mutation:
    """Take rows out of the view — a complete or a delete. `task_ids` carries the
    whole subtree a close takes down (see `with_subtrees`)."""
    return Mutation(Kind.HIDE, tuple(task_ids))


def restore(rows: Iterable[TaskRow]) -> Mutation:
    """Put rows back — the undo of a `hide`. The rows travel with the mutation
    because the server snapshot no longer holds them."""
    return Mutation(Kind.RESTORE, rows=tuple(rows))


def reorder_sections(orders: Mapping[str, int]) -> Mutation:
    """Move section headers. Sections are not rows, so this rides the same log
    only to retire on the same acknowledgement — `apply_sections` replays it."""
    return Mutation(Kind.SECTION_ORDER, section_orders=orders)


def touched(log: Sequence[Mutation]) -> frozenset[str]:
    """The tasks `log` changes — the ones still waiting on the server."""
    return frozenset(
        task_id
        for mutation in log
        for task_id in (*mutation.task_ids, *(str(r.id) for r in mutation.rows))
    )


def apply(rows: Sequence[TaskRow], log: Sequence[Mutation]) -> list[TaskRow]:
    """`rows` as the user sees them: the server's, with `log` replayed in order.

    Later mutations win over earlier ones, field by field. A restored row is
    appended — the arrangement decides where it lands.
    """
    result = list(rows)
    hidden: set[str] = set()
    for mutation in log:
        if mutation.kind is Kind.SECTION_ORDER:
            continue  # sections are not rows; `apply_sections` replays these
        if mutation.kind is Kind.EDIT:
            targets = set(mutation.task_ids)
            result = [
                replace(row, **mutation.patch) if str(row.id) in targets else row
                for row in result
            ]
        elif mutation.kind is Kind.HIDE:
            hidden |= set(mutation.task_ids)
        else:
            hidden -= {str(row.id) for row in mutation.rows}
            present = {str(row.id) for row in result}
            result += [row for row in mutation.rows if str(row.id) not in present]
    return prune(result, lambda row: str(row.id) in hidden)


def apply_sections(
    sections: Sequence[Section], log: Sequence[Mutation]
) -> list[Section]:
    """`sections` as the user sees them: the server's, with `log` replayed in
    order, so a header a move has not been acknowledged yet still sits where the
    user just put it."""
    orders = {
        section_id: order
        for mutation in log
        if mutation.kind is Kind.SECTION_ORDER
        for section_id, order in mutation.section_orders.items()
    }
    return [
        replace(section, order=orders[section.id]) if section.id in orders else section
        for section in sections
    ]
