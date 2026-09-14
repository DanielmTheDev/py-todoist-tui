from dataclasses import dataclass

from todoist_tui.domain.arrange import (
    Arrangement,
    Field,
    ManualOrder,
    RenderRow,
    SortKey,
    arrange,
)
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reorder import (
    day_order_plan,
    swap_section_with_neighbour,
    swap_with_neighbour,
)
from todoist_tui.domain.section import Section


@dataclass(frozen=True)
class Row:
    id: str
    content: str
    child_order: int = 0
    parent_id: str | None = None
    project_id: str | None = "9"
    section_id: str | None = None
    section_name: str | None = None
    section_order: int = 0
    day_order: int = -1
    priority: Priority = Priority.P4
    due: Due | None = None
    deadline: Deadline | None = None
    project_name: str | None = "Work"
    labels: tuple[str, ...] = ()


def _run(*contents: str) -> list[Row]:
    return [Row(c, c, child_order=i) for i, c in enumerate(contents)]


_UNSORTED = Arrangement()


def _rendered(
    rows: list[Row],
    arrangement: Arrangement = _UNSORTED,
    expanded: frozenset[str] = frozenset(),
) -> list[RenderRow[Row]]:
    return arrange(
        rows,
        arrangement,
        expanded=expanded,
        open_groups=frozenset(
            {(name,) for name in {r.section_name for r in rows} if name}
        ),
    )


def _rendered_day(
    rows: list[Row], expanded: frozenset[str] = frozenset()
) -> list[RenderRow[Row]]:
    return arrange(rows, _UNSORTED, expanded=expanded, manual=ManualOrder.DAY)


def _pair(result: tuple[Row, Row] | None) -> tuple[str, str] | None:
    return None if result is None else (result[0].content, result[1].content)


def test_moves_down_onto_the_next_sibling() -> None:
    rows = _run("a", "b", "c")

    assert _pair(swap_with_neighbour(_rendered(rows), "b", down=True)) == ("b", "c")


def test_moves_up_onto_the_previous_sibling() -> None:
    rows = _run("a", "b", "c")

    assert _pair(swap_with_neighbour(_rendered(rows), "b", down=False)) == ("b", "a")


def test_refuses_at_the_end_of_the_list() -> None:
    rows = _run("a", "b")

    assert swap_with_neighbour(_rendered(rows), "b", down=True) is None


def test_refuses_at_the_start_of_the_list() -> None:
    rows = _run("a", "b")

    assert swap_with_neighbour(_rendered(rows), "a", down=False) is None


def test_refuses_to_cross_a_group_header() -> None:
    """The last task of a section stays in it — order is per sibling set."""
    rows = [
        Row("a", "a", section_id="s1", section_name="One", section_order=1),
        Row("b", "b", section_id="s2", section_name="Two", section_order=2),
    ]

    rendered = _rendered(rows, Arrangement(group_by=(Field.SECTION,)))

    assert swap_with_neighbour(rendered, "a", down=True) is None


def test_refuses_a_neighbour_from_another_section() -> None:
    """Ungrouped, the rows are adjacent but not siblings."""
    rows = [
        Row("a", "a", section_id="s1", child_order=1),
        Row("b", "b", section_id="s2", child_order=1),
    ]

    assert swap_with_neighbour(_rendered(rows), "a", down=True) is None


def test_refuses_a_neighbour_from_another_project() -> None:
    rows = [
        Row("a", "a", project_id="9", child_order=1),
        Row("b", "b", project_id="10", child_order=1),
    ]

    assert swap_with_neighbour(_rendered(rows), "a", down=True) is None


def test_swaps_subtasks_under_the_same_parent() -> None:
    rows = [
        Row("p", "parent"),
        Row("1", "kid-a", parent_id="p", child_order=1),
        Row("2", "kid-b", parent_id="p", child_order=2),
    ]

    rendered = _rendered(rows, expanded=frozenset({"p"}))

    assert _pair(swap_with_neighbour(rendered, "1", down=True)) == ("kid-a", "kid-b")


def test_refuses_to_move_a_subtask_out_of_its_parent() -> None:
    rows = [
        Row("p", "parent", child_order=1),
        Row("1", "kid", parent_id="p", child_order=1),
        Row("q", "next root", child_order=2),
    ]

    rendered = _rendered(rows, expanded=frozenset({"p"}))

    assert swap_with_neighbour(rendered, "1", down=True) is None


def test_a_parent_moves_past_its_own_expanded_subtree() -> None:
    """The rows between two roots are the first one's children, not a boundary."""
    rows = [
        Row("p", "parent", child_order=1),
        Row("1", "kid", parent_id="p", child_order=1),
        Row("q", "next root", child_order=2),
    ]

    rendered = _rendered(rows, expanded=frozenset({"p"}))

    assert _pair(swap_with_neighbour(rendered, "p", down=True)) == (
        "parent",
        "next root",
    )


def test_a_parent_moves_up_past_the_previous_subtree() -> None:
    rows = [
        Row("p", "parent", child_order=1),
        Row("1", "kid", parent_id="p", child_order=1),
        Row("q", "next root", child_order=2),
    ]

    rendered = _rendered(rows, expanded=frozenset({"p"}))

    assert _pair(swap_with_neighbour(rendered, "q", down=False)) == (
        "next root",
        "parent",
    )


def test_returns_none_for_an_unknown_task() -> None:
    assert swap_with_neighbour(_rendered(_run("a")), "nope", down=True) is None


def test_a_collapsed_group_header_is_not_a_sibling() -> None:
    """Folded away, a section's tasks are not on screen to swap with."""
    rows = [
        Row("a", "a", section_id="s1", section_name="One", section_order=1),
        Row("b", "b", section_id="s1", section_name="One", section_order=1),
    ]

    rendered = arrange(
        rows, Arrangement(group_by=(Field.SECTION,)), open_groups=frozenset()
    )

    assert swap_with_neighbour(rendered, "a", down=True) is None


def test_finds_the_task_under_an_active_sort() -> None:
    """The caller refuses sorted views; the rule itself still reads the render."""
    rows = _run("a", "b")

    rendered = _rendered(rows, Arrangement(sort_by=(SortKey(Field.CONTENT),)))

    assert _pair(swap_with_neighbour(rendered, "a", down=True)) == ("a", "b")


# --- day ordering: a run that spans projects ---


def _plan(result: list[tuple[Row, int]] | None) -> list[tuple[str, int]] | None:
    return None if result is None else [(row.content, order) for row, order in result]


def test_an_unplaced_list_is_numbered_from_the_top() -> None:
    """Every task starts at -1, so the first move has to place the whole run."""
    rows = [
        Row("1", "a", day_order=-1),
        Row("2", "b", day_order=-1),
        Row("3", "c", day_order=-1),
    ]

    plan = day_order_plan(_rendered_day(rows), "1", down=True)

    assert _plan(plan) == [("b", 1), ("a", 2), ("c", 3)]


def test_an_already_placed_list_only_trades_the_two() -> None:
    rows = [
        Row("1", "a", day_order=1),
        Row("2", "b", day_order=2),
        Row("3", "c", day_order=3),
    ]

    plan = day_order_plan(_rendered_day(rows), "1", down=True)

    assert _plan(plan) == [("a", 2), ("b", 1)]


def test_a_part_placed_list_is_renumbered_whole() -> None:
    """Unplaced rows trail the placed ones, so the run reads a, c, b."""
    rows = [
        Row("1", "a", day_order=1),
        Row("2", "b", day_order=-1),
        Row("3", "c", day_order=3),
    ]

    plan = day_order_plan(_rendered_day(rows), "1", down=True)

    assert _plan(plan) == [("c", 1), ("a", 2), ("b", 3)]


def test_duplicate_day_orders_are_renumbered_whole() -> None:
    """Trading equal values would move nothing, so the run is rewritten."""
    rows = [
        Row("1", "a", day_order=4),
        Row("2", "b", day_order=4),
    ]

    plan = day_order_plan(_rendered_day(rows), "1", down=True)

    assert _plan(plan) == [("b", 1), ("a", 2)]


def test_the_day_run_crosses_projects_and_sibling_sets() -> None:
    """The whole point: neighbours here are not siblings."""
    rows = [
        Row("1", "a", project_id="9", parent_id="p1", day_order=1),
        Row("2", "b", project_id="10", parent_id="p2", day_order=2),
    ]

    plan = day_order_plan(_rendered_day(rows), "1", down=True)

    assert _plan(plan) == [("a", 2), ("b", 1)]


def test_day_move_refuses_at_the_end_of_the_run() -> None:
    rows = [Row("1", "a", day_order=1), Row("2", "b", day_order=2)]

    assert day_order_plan(_rendered_day(rows), "b", down=True) is None


def test_day_move_refuses_at_the_start_of_the_run() -> None:
    rows = [Row("1", "a", day_order=1), Row("2", "b", day_order=2)]

    assert day_order_plan(_rendered_day(rows), "a", down=False) is None


def test_a_group_header_bounds_the_day_run() -> None:
    """Grouped, each group is its own run — a move never crosses the header."""
    rows = [
        Row("a", "a", section_id="s1", section_name="One", section_order=1),
        Row("b", "b", section_id="s2", section_name="Two", section_order=2),
    ]

    rendered = _rendered(rows, Arrangement(group_by=(Field.SECTION,)))

    assert day_order_plan(rendered, "a", down=True) is None


def test_a_nested_subtask_has_no_day_plan() -> None:
    """Under a visible parent the order is the sibling one, not the day's."""
    rows = [
        Row("p", "parent", day_order=1),
        Row("1", "kid-a", parent_id="p", day_order=2),
        Row("2", "kid-b", parent_id="p", day_order=3),
    ]

    rendered = _rendered(rows, expanded=frozenset({"p"}))

    assert day_order_plan(rendered, "1", down=True) is None


def test_a_parent_moves_over_its_own_subtree_in_the_day_run() -> None:
    rows = [
        Row("p", "parent", day_order=1),
        Row("1", "kid", parent_id="p", day_order=9),
        Row("q", "next", day_order=2),
    ]

    rendered = _rendered_day(rows, expanded=frozenset({"p"}))

    assert _plan(day_order_plan(rendered, "p", down=True)) == [
        ("parent", 2),
        ("next", 1),
    ]


def test_day_plan_returns_none_for_an_unknown_task() -> None:
    assert day_order_plan(_rendered_day(_run("a")), "nope", down=True) is None


# --- moving a section ---


_BY_SECTION = Arrangement(group_by=(Field.SECTION,))


def _sectioned(*sections: Section) -> list[RenderRow[Row]]:
    """A project view of `sections`, each holding one task, all unfolded."""
    rows = [
        Row(s.id, s.id, section_id=s.id, section_name=s.name, section_order=s.order)
        for s in sections
    ]
    return arrange(
        rows,
        _BY_SECTION,
        open_groups=frozenset({(s.name,) for s in sections}),
        sections=list(sections),
    )


_PLANNING = Section("s1", "9", "Planning", 1)
_WAITING = Section("s2", "9", "Waiting", 2)
_BACKLOG = Section("s3", "9", "Backlog", 3)


def test_a_section_trades_with_the_one_below() -> None:
    rendered = _sectioned(_PLANNING, _WAITING, _BACKLOG)

    assert swap_section_with_neighbour(rendered, ("Waiting",), down=True) == (
        "Waiting",
        "Backlog",
    )


def test_a_section_trades_with_the_one_above() -> None:
    rendered = _sectioned(_PLANNING, _WAITING, _BACKLOG)

    assert swap_section_with_neighbour(rendered, ("Waiting",), down=False) == (
        "Waiting",
        "Planning",
    )


def test_the_last_section_has_nothing_below_it() -> None:
    rendered = _sectioned(_PLANNING, _WAITING)

    assert swap_section_with_neighbour(rendered, ("Waiting",), down=True) is None


def test_the_first_section_has_nothing_above_it() -> None:
    rendered = _sectioned(_PLANNING, _WAITING)

    assert swap_section_with_neighbour(rendered, ("Planning",), down=False) is None


def test_a_section_holding_no_task_moves_like_any_other() -> None:
    rows = [
        Row("t", "t", section_id="s1", section_name="Planning", section_order=1),
    ]
    rendered = arrange(
        rows,
        _BY_SECTION,
        open_groups=frozenset({("Planning",), ("Waiting",)}),
        sections=[_PLANNING, _WAITING],
    )

    assert swap_section_with_neighbour(rendered, ("Planning",), down=True) == (
        "Planning",
        "Waiting",
    )


def test_a_folded_section_still_moves() -> None:
    rows = [
        Row(s.id, s.id, section_id=s.id, section_name=s.name, section_order=s.order)
        for s in (_PLANNING, _WAITING)
    ]
    rendered = arrange(rows, _BY_SECTION, sections=[_PLANNING, _WAITING])

    # a folded header hides its tasks but is still the row the cursor sits on
    assert swap_section_with_neighbour(rendered, ("Planning",), down=True) == (
        "Planning",
        "Waiting",
    )


def test_an_unknown_path_moves_nothing() -> None:
    rendered = _sectioned(_PLANNING, _WAITING)

    assert swap_section_with_neighbour(rendered, ("Nowhere",), down=True) is None


def test_a_group_that_is_not_a_section_does_not_move() -> None:
    rows = [
        Row("a", "a", priority=Priority.P1),
        Row("b", "b", priority=Priority.P2),
    ]
    rendered = arrange(rows, Arrangement(group_by=(Field.PRIORITY,)))

    assert (
        swap_section_with_neighbour(rendered, (Priority.P1.label,), down=True) is None
    )


def test_a_section_nested_under_another_group_does_not_move() -> None:
    rows = [
        Row("a", "a", section_id="s1", section_name="Planning", section_order=1),
        Row("b", "b", section_id="s2", section_name="Waiting", section_order=2),
    ]
    paths = frozenset(
        {
            (Priority.P4.label,),
            (Priority.P4.label, "Planning"),
            (Priority.P4.label, "Waiting"),
        }
    )
    rendered = arrange(
        rows, Arrangement(group_by=(Field.PRIORITY, Field.SECTION)), open_groups=paths
    )

    # section_order is one order per project; a move here would reorder the
    # section under every other parent header too
    result = swap_section_with_neighbour(
        rendered, (Priority.P4.label, "Planning"), down=True
    )
    assert result is None
