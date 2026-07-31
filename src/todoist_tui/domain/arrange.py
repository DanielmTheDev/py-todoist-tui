"""Multi-level grouping and sorting for the task list.

Pure domain logic: `arrange` turns a flat list of rows into an ordered list of
group headers interleaved with task lines, given an `Arrangement` (a group-by
chain and a sort-by chain, each capped at three levels). No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority

MAX_LEVELS = 3

_NO_PROJECT = "No project"
_NO_LABELS = "(no labels)"
_NO_DUE_DATE = "No due date"
_NO_DUE_TIME = "No time"


class ArrangeRow(Protocol):
    """The fields `arrange` needs; the application's task view row supplies them.

    Read-only members so a frozen dataclass (e.g. `TaskRow`) satisfies it.
    """

    @property
    def id(self) -> Any: ...
    @property
    def content(self) -> str: ...
    @property
    def priority(self) -> Priority: ...
    @property
    def due(self) -> Due | None: ...
    @property
    def project_name(self) -> str | None: ...
    @property
    def labels(self) -> tuple[str, ...]: ...
    @property
    def parent_id(self) -> str | None: ...


# A group bucket's sort position. `present` (0) always orders before "missing"
# (1), so no-value buckets land last under ascending order.
_OrderKey = tuple[int, Any]


class Field(Enum):
    """A task attribute that can be grouped or sorted by."""

    PROJECT = "project"
    PRIORITY = "priority"
    DUE_DATE = "due_date"
    DUE_TIME = "due_time"
    RECURRING = "recurring"
    CONTENT = "content"
    LABELS = "labels"

    @property
    def label(self) -> str:
        return _FIELD_LABELS[self]


_FIELD_LABELS = {
    Field.PROJECT: "Project",
    Field.PRIORITY: "Priority",
    Field.DUE_DATE: "Due date",
    Field.DUE_TIME: "Due time",
    Field.RECURRING: "Recurring",
    Field.CONTENT: "Content",
    Field.LABELS: "Labels",
}


@dataclass(frozen=True, slots=True)
class _Bucket:
    order: _OrderKey
    label: str


def _buckets(field: Field, row: ArrangeRow) -> list[_Bucket]:
    """Group buckets a row belongs to under `field` (usually one; many for labels)."""
    match field:
        case Field.PROJECT:
            name = row.project_name
            if name is None:
                return [_Bucket((1, ""), _NO_PROJECT)]
            return [_Bucket((0, name.lower()), name)]
        case Field.PRIORITY:
            return [_Bucket((0, -row.priority.value), row.priority.label)]
        case Field.RECURRING:
            recurring = row.due.is_recurring if row.due else False
            return [
                _Bucket(
                    (0 if recurring else 1, ""),
                    "Recurring" if recurring else "Not recurring",
                )
            ]
        case Field.DUE_DATE:
            if row.due is None:
                return [_Bucket((1, 0), _NO_DUE_DATE)]
            return [_Bucket((0, row.due.date.toordinal()), row.due.date.isoformat())]
        case Field.DUE_TIME:
            if row.due is None or row.due.time is None:
                return [_Bucket((1, 0), _NO_DUE_TIME)]
            t = row.due.time
            return [_Bucket((0, t.hour * 60 + t.minute), t.strftime("%H:%M"))]
        case Field.CONTENT:
            return [_Bucket((0, row.content.lower()), row.content)]
        case Field.LABELS:
            if not row.labels:
                return [_Bucket((1, ""), _NO_LABELS)]
            return [_Bucket((0, name.lower()), name) for name in row.labels]


def _sort_order(field: Field, row: ArrangeRow) -> _OrderKey:
    """Leaf sort key for `field` (the first bucket's order; first label for labels)."""
    return _buckets(field, row)[0].order


class _Rev:
    """Inverts a value's order so a single ascending sort yields descending.

    Wrapping only the *value* (not the presence flag) keeps missing-value rows
    last in both directions.
    """

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __lt__(self, other: _Rev) -> bool:
        return other.value < self.value


def _bucket_order(
    order: _OrderKey, label: str, ascending: bool
) -> tuple[int, Any, str]:
    # Presence flag stays ascending (missing buckets last in both directions);
    # only the value flips for descending. Label is a stable final tie-break.
    present, value = order
    return (present, value if ascending else _Rev(value), label)


@dataclass(frozen=True)
class SortKey:
    field: Field
    ascending: bool = True


@dataclass(frozen=True)
class Arrangement:
    """A group-by chain and a sort-by chain, each capped at `MAX_LEVELS`."""

    group_by: tuple[Field, ...] = ()
    sort_by: tuple[SortKey, ...] = ()
    group_desc: frozenset[Field] = frozenset()  # group fields ordered descending

    def __post_init__(self) -> None:
        if len(self.group_by) > MAX_LEVELS:
            raise ValueError(f"group-by chain exceeds {MAX_LEVELS} levels")
        if len(self.sort_by) > MAX_LEVELS:
            raise ValueError(f"sort-by chain exceeds {MAX_LEVELS} levels")

    def group_ascending(self, field: Field) -> bool:
        return field not in self.group_desc

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_by": [f.value for f in self.group_by],
            "group_desc": [f.value for f in self.group_by if f in self.group_desc],
            "sort_by": [
                {"field": s.field.value, "ascending": s.ascending} for s in self.sort_by
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Arrangement:
        return cls(
            group_by=tuple(Field(v) for v in data.get("group_by", ())),
            group_desc=frozenset(Field(v) for v in data.get("group_desc", ())),
            sort_by=tuple(
                SortKey(Field(s["field"]), bool(s["ascending"]))
                for s in data.get("sort_by", ())
            ),
        )


@dataclass(frozen=True)
class GroupHeader:
    level: int
    label: str
    field: Field
    count: int  # task lines in this group's subtree (duplicates counted per membership)


@dataclass(frozen=True)
class TaskLine[T: ArrangeRow]:
    level: int
    row: T
    has_children: bool = False  # has subtasks present in the same row set
    expanded: bool = False  # its subtasks are currently shown


type RenderRow[T: ArrangeRow] = GroupHeader | TaskLine[T]


def arrange[T: ArrangeRow](
    rows: list[T], arrangement: Arrangement, expanded: frozenset[Any] = frozenset()
) -> list[RenderRow[T]]:
    """Group/sort the *root* tasks; nest each task's subtasks directly beneath it.

    A task is a root unless its `parent_id` names another row in `rows` (so an
    orphan whose parent is absent renders flat). Only roots are grouped/sorted;
    a task's children always follow it, indented one level deeper, and appear
    only when the task's id is in `expanded`.
    """
    present = {row.id for row in rows}
    children: dict[Any, list[T]] = {}
    roots: list[T] = []
    for row in rows:
        parent = row.parent_id
        if parent is not None and parent in present:
            children.setdefault(parent, []).append(row)
        else:
            roots.append(row)
    out: list[RenderRow[T]] = []
    _emit(roots, arrangement, 0, out, children, expanded)
    return out


def _emit[T: ArrangeRow](
    rows: list[T],
    arrangement: Arrangement,
    level: int,
    out: list[RenderRow[T]],
    children: dict[Any, list[T]],
    expanded: frozenset[Any],
) -> int:
    """Append this level's rows to `out`; return the task-line count emitted."""
    group_by = arrangement.group_by[level:]
    if not group_by:
        total = 0
        for row in _sorted(rows, arrangement.sort_by):
            total += _emit_subtree(row, arrangement, level, out, children, expanded)
        return total
    field = group_by[0]
    ascending = arrangement.group_ascending(field)
    members: dict[str, list[T]] = {}
    order: dict[str, _OrderKey] = {}
    for row in rows:
        for bucket in _buckets(field, row):
            members.setdefault(bucket.label, []).append(row)
            order[bucket.label] = bucket.order
    total = 0
    for label in sorted(
        members, key=lambda lbl: _bucket_order(order[lbl], lbl, ascending)
    ):
        subtree: list[RenderRow[T]] = []  # emit children first to know the count
        count = _emit(
            members[label], arrangement, level + 1, subtree, children, expanded
        )
        out.append(GroupHeader(level, label, field, count))
        out.extend(subtree)
        total += count
    return total


def _emit_subtree[T: ArrangeRow](
    row: T,
    arrangement: Arrangement,
    level: int,
    out: list[RenderRow[T]],
    children: dict[Any, list[T]],
    expanded: frozenset[Any],
) -> int:
    """Emit `row` then, if expanded, its subtask subtree; return lines emitted."""
    kids = children.get(row.id, [])
    is_expanded = bool(kids) and row.id in expanded
    out.append(TaskLine(level, row, has_children=bool(kids), expanded=is_expanded))
    count = 1
    if is_expanded:
        for child in _sorted(kids, arrangement.sort_by):
            count += _emit_subtree(
                child, arrangement, level + 1, out, children, expanded
            )
    return count


def _sorted[T: ArrangeRow](rows: list[T], sort_by: tuple[SortKey, ...]) -> list[T]:
    def key(row: T) -> tuple[tuple[int, Any], ...]:
        parts: list[tuple[int, Any]] = []
        for sort_key in sort_by:
            present, value = _sort_order(sort_key.field, row)
            parts.append((present, value if sort_key.ascending else _Rev(value)))
        # Deterministic tie-break so equal keys never order flakily.
        parts.append((0, row.content.lower()))
        parts.append((0, str(row.id)))
        return tuple(parts)

    return sorted(rows, key=key)
