from dataclasses import dataclass

from todoist_tui.domain.arrange import (
    Arrangement,
    Field,
    RenderRow,
    SortKey,
    arrange,
)
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.reorder import swap_with_neighbour


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
