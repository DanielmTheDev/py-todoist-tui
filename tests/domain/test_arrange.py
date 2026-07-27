import datetime
from dataclasses import dataclass

import pytest

from todoist_tui.domain.arrange import (
    Arrangement,
    Field,
    GroupHeader,
    RenderRow,
    SortKey,
    TaskLine,
    arrange,
)
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority


@dataclass(frozen=True)
class Row:
    id: str
    content: str
    priority: Priority = Priority.P4
    due: Due | None = None
    project_name: str | None = "Work"
    labels: tuple[str, ...] = ()


def _date(y: int, m: int, d: int) -> Due:
    return Due(date=datetime.date(y, m, d))


def _shape(rows: list[RenderRow[Row]]) -> list[tuple[str, int, str]]:
    """Flatten arrange() output to (kind, level, label) for easy assertions."""
    out: list[tuple[str, int, str]] = []
    for r in rows:
        if isinstance(r, GroupHeader):
            out.append(("H", r.level, r.label))
        else:
            out.append(("T", r.level, r.row.content))
    return out


# --- no grouping / default order ---


def test_empty_arrangement_returns_tasks_in_stable_order() -> None:
    rows = [Row("2", "beta"), Row("1", "alpha"), Row("3", "alpha")]

    result = arrange(rows, Arrangement())

    # ties on content broken deterministically by id → alpha#1, alpha#3, beta#2
    assert _shape(result) == [("T", 0, "alpha"), ("T", 0, "alpha"), ("T", 0, "beta")]
    assert isinstance(result[0], TaskLine) and result[0].row.id == "1"


# --- sorting ---


def test_sort_by_content_descending() -> None:
    rows = [Row("1", "alpha"), Row("2", "gamma"), Row("3", "beta")]

    result = arrange(
        rows, Arrangement(sort_by=(SortKey(Field.CONTENT, ascending=False),))
    )

    assert [c for _, _, c in _shape(result)] == ["gamma", "beta", "alpha"]


def test_sort_by_due_date_puts_no_due_last() -> None:
    rows = [
        Row("1", "later", due=_date(2026, 8, 1)),
        Row("2", "none"),
        Row("3", "soon", due=_date(2026, 7, 26)),
    ]

    result = arrange(rows, Arrangement(sort_by=(SortKey(Field.DUE_DATE),)))

    assert [c for _, _, c in _shape(result)] == ["soon", "later", "none"]


def test_sort_by_due_date_descending_still_puts_no_due_last() -> None:
    rows = [
        Row("1", "later", due=_date(2026, 8, 1)),
        Row("2", "none"),
        Row("3", "soon", due=_date(2026, 7, 26)),
    ]

    result = arrange(
        rows, Arrangement(sort_by=(SortKey(Field.DUE_DATE, ascending=False),))
    )

    # latest present date first, but a missing due date stays last in both directions
    assert [c for _, _, c in _shape(result)] == ["later", "soon", "none"]


def test_sort_by_project_descending_still_puts_no_project_last() -> None:
    rows = [
        Row("1", "orphan", project_name=None),
        Row("2", "at-work", project_name="Work"),
        Row("3", "at-home", project_name="Home"),
    ]

    result = arrange(
        rows, Arrangement(sort_by=(SortKey(Field.PROJECT, ascending=False),))
    )

    assert [c for _, _, c in _shape(result)] == ["at-work", "at-home", "orphan"]


def test_sort_by_priority_ascending_is_most_important_first() -> None:
    rows = [Row("1", "low", Priority.P4), Row("2", "top", Priority.P1)]

    result = arrange(rows, Arrangement(sort_by=(SortKey(Field.PRIORITY),)))

    assert [c for _, _, c in _shape(result)] == ["top", "low"]


def test_multi_level_sort_priority_then_content() -> None:
    rows = [
        Row("1", "b", Priority.P1),
        Row("2", "a", Priority.P1),
        Row("3", "z", Priority.P4),
    ]

    result = arrange(
        rows,
        Arrangement(sort_by=(SortKey(Field.PRIORITY), SortKey(Field.CONTENT))),
    )

    assert [c for _, _, c in _shape(result)] == ["a", "b", "z"]


# --- grouping ---


def test_group_by_project() -> None:
    rows = [
        Row("1", "w1", project_name="Work"),
        Row("2", "h1", project_name="Home"),
        Row("3", "w2", project_name="Work"),
    ]

    result = arrange(rows, Arrangement(group_by=(Field.PROJECT,)))

    assert _shape(result) == [
        ("H", 0, "Home"),
        ("T", 1, "h1"),
        ("H", 0, "Work"),
        ("T", 1, "w1"),
        ("T", 1, "w2"),
    ]


def test_group_header_carries_subtree_task_count() -> None:
    rows = [
        Row("1", "w1", project_name="Work"),
        Row("2", "w2", project_name="Work"),
        Row("3", "h1", project_name="Home"),
    ]

    result = arrange(rows, Arrangement(group_by=(Field.PROJECT,)))

    counts = {r.label: r.count for r in result if isinstance(r, GroupHeader)}
    assert counts == {"Home": 1, "Work": 2}


def test_nested_group_header_counts_whole_subtree() -> None:
    rows = [
        Row("1", "w-a", Priority.P1, project_name="Work"),
        Row("2", "w-b", Priority.P4, project_name="Work"),
    ]

    result = arrange(rows, Arrangement(group_by=(Field.PROJECT, Field.PRIORITY)))

    headers = [r for r in result if isinstance(r, GroupHeader)]
    work = next(h for h in headers if h.label == "Work")
    assert work.count == 2  # both leaves under the two priority subgroups


def test_group_by_project_none_bucket_last() -> None:
    rows = [Row("1", "orphan", project_name=None), Row("2", "w", project_name="Work")]

    result = arrange(rows, Arrangement(group_by=(Field.PROJECT,)))

    labels = [lbl for kind, _, lbl in _shape(result) if kind == "H"]
    assert labels == ["Work", "No project"]


def test_group_by_project_descending_reverses_order_but_keeps_missing_last() -> None:
    rows = [
        Row("1", "w", project_name="Work"),
        Row("2", "h", project_name="Home"),
        Row("3", "orphan", project_name=None),
    ]

    result = arrange(
        rows,
        Arrangement(group_by=(Field.PROJECT,), group_desc=frozenset({Field.PROJECT})),
    )

    headers = [lbl for kind, _, lbl in _shape(result) if kind == "H"]
    assert headers == ["Work", "Home", "No project"]  # Z→A, missing still last


def test_group_by_priority_orders_p1_first() -> None:
    rows = [Row("1", "low", Priority.P4), Row("2", "top", Priority.P1)]

    result = arrange(rows, Arrangement(group_by=(Field.PRIORITY,)))

    headers = [lbl for kind, _, lbl in _shape(result) if kind == "H"]
    assert headers == [Priority.P1.label, Priority.P4.label]


def test_group_by_labels_multi_membership() -> None:
    rows = [
        Row("1", "rent", labels=("home", "urgent")),
        Row("2", "plants", labels=("home",)),
        Row("3", "dentist", labels=("urgent",)),
    ]

    result = arrange(rows, Arrangement(group_by=(Field.LABELS,)))

    # leaves fall back to deterministic content order within each bucket
    assert _shape(result) == [
        ("H", 0, "home"),
        ("T", 1, "plants"),
        ("T", 1, "rent"),
        ("H", 0, "urgent"),
        ("T", 1, "dentist"),
        ("T", 1, "rent"),
    ]


def test_group_by_labels_no_labels_bucket() -> None:
    rows = [Row("1", "tagged", labels=("home",)), Row("2", "bare", labels=())]

    result = arrange(rows, Arrangement(group_by=(Field.LABELS,)))

    labels = [lbl for kind, _, lbl in _shape(result) if kind == "H"]
    assert labels == ["home", "(no labels)"]


def test_nested_group_project_then_priority_with_sorted_leaves() -> None:
    rows = [
        Row("1", "w-low", Priority.P4, project_name="Work"),
        Row("2", "w-top", Priority.P1, project_name="Work"),
        Row("3", "h-mid", Priority.P2, project_name="Home"),
    ]

    result = arrange(
        rows,
        Arrangement(
            group_by=(Field.PROJECT, Field.PRIORITY),
            sort_by=(SortKey(Field.CONTENT),),
        ),
    )

    assert _shape(result) == [
        ("H", 0, "Home"),
        ("H", 1, Priority.P2.label),
        ("T", 2, "h-mid"),
        ("H", 0, "Work"),
        ("H", 1, Priority.P1.label),
        ("T", 2, "w-top"),
        ("H", 1, Priority.P4.label),
        ("T", 2, "w-low"),
    ]


# --- Arrangement invariants + serde ---


def test_group_by_rejects_more_than_three_levels() -> None:
    with pytest.raises(ValueError, match="group"):
        Arrangement(
            group_by=(Field.PROJECT, Field.PRIORITY, Field.LABELS, Field.CONTENT)
        )


def test_sort_by_rejects_more_than_three_levels() -> None:
    with pytest.raises(ValueError, match="sort"):
        Arrangement(
            sort_by=(
                SortKey(Field.CONTENT),
                SortKey(Field.PRIORITY),
                SortKey(Field.DUE_DATE),
                SortKey(Field.DUE_TIME),
            )
        )


def test_arrangement_dict_round_trip() -> None:
    arrangement = Arrangement(
        group_by=(Field.PROJECT, Field.LABELS),
        group_desc=frozenset({Field.LABELS}),
        sort_by=(SortKey(Field.DUE_DATE), SortKey(Field.PRIORITY, ascending=False)),
    )

    assert Arrangement.from_dict(arrangement.to_dict()) == arrangement


def test_empty_arrangement_round_trips() -> None:
    assert Arrangement.from_dict(Arrangement().to_dict()) == Arrangement()
