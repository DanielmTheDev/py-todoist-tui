import datetime

from todoist_tui.application.mutation import (
    apply,
    apply_sections,
    edit,
    hide,
    reorder_sections,
    restore,
    touched,
)
from todoist_tui.application.views import TaskRow
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import TaskId


def _row(
    task_id: str,
    parent_id: str | None = None,
    matched: bool = True,
    priority: Priority = Priority.P4,
) -> TaskRow:
    return TaskRow(
        id=TaskId(task_id),
        content=task_id,
        priority=priority,
        due=None,
        project_name="Inbox",
        parent_id=parent_id,
        matched=matched,
    )


def _ids(rows: list[TaskRow]) -> list[str]:
    return [str(row.id) for row in rows]


def test_an_empty_log_leaves_the_rows_alone() -> None:
    rows = [_row("a"), _row("b")]

    assert apply(rows, []) == rows


def test_an_edit_overlays_its_fields_on_the_named_rows_only() -> None:
    rows = [_row("a"), _row("b")]

    result = apply(rows, [edit(["a"], priority=Priority.P1)])

    assert result[0].priority is Priority.P1
    assert result[1].priority is Priority.P4


def test_the_last_edit_of_a_field_wins() -> None:
    log = [edit(["a"], priority=Priority.P1), edit(["a"], priority=Priority.P2)]

    assert apply([_row("a")], log)[0].priority is Priority.P2


def test_edits_of_different_fields_accumulate() -> None:
    due = Due(date=datetime.date(2026, 8, 11))
    log = [edit(["a"], priority=Priority.P1), edit(["a"], due=due)]

    result = apply([_row("a")], log)[0]

    assert (result.priority, result.due) == (Priority.P1, due)


def test_a_hidden_row_is_dropped() -> None:
    result = apply([_row("a"), _row("b")], [hide(["a"])])

    assert _ids(result) == ["b"]


def test_a_hidden_parent_takes_its_pulled_in_subtask_with_it() -> None:
    rows = [_row("p"), _row("c", parent_id="p", matched=False)]

    assert apply(rows, [hide(["p"])]) == []


def test_a_restore_puts_a_hidden_row_back() -> None:
    rows = [_row("a"), _row("b")]

    result = apply(rows, [hide(["a"]), restore([_row("a")])])

    assert _ids(result) == ["a", "b"]


def test_a_restore_re_inserts_a_row_the_server_no_longer_returns() -> None:
    result = apply([_row("b")], [restore([_row("a")])])

    assert _ids(result) == ["b", "a"]


def test_a_restore_does_not_duplicate_a_row_already_present() -> None:
    result = apply([_row("a")], [restore([_row("a")])])

    assert _ids(result) == ["a"]


def test_an_edit_after_a_restore_reaches_the_restored_row() -> None:
    log = [restore([_row("a")]), edit(["a"], priority=Priority.P1)]

    assert apply([], log)[0].priority is Priority.P1


def test_a_hide_after_a_restore_hides_again() -> None:
    log = [hide(["a"]), restore([_row("a")]), hide(["a"])]

    assert apply([_row("a")], log) == []


def test_touched_names_every_task_the_log_is_waiting_on() -> None:
    log = [edit(["a", "b"], priority=Priority.P1), hide(["c"]), restore([_row("d")])]

    assert touched(log) == frozenset({"a", "b", "c", "d"})


def test_touched_is_empty_for_an_empty_log() -> None:
    assert touched([]) == frozenset()


def test_the_input_rows_are_left_untouched() -> None:
    rows = [_row("a"), _row("b")]

    apply(rows, [hide(["a"]), edit(["b"], priority=Priority.P1)])

    assert _ids(rows) == ["a", "b"]
    assert rows[1].priority is Priority.P4


# --- section order ---


_PLANNING = Section("s1", "9", "Planning", 1)
_WAITING = Section("s2", "9", "Waiting", 2)


def test_a_section_order_mutation_replays_the_new_orders() -> None:
    log = [reorder_sections({"s1": 2, "s2": 1})]

    assert apply_sections([_PLANNING, _WAITING], log) == [
        Section("s1", "9", "Planning", 2),
        Section("s2", "9", "Waiting", 1),
    ]


def test_a_later_section_order_wins_over_an_earlier_one() -> None:
    log = [reorder_sections({"s1": 2}), reorder_sections({"s1": 3})]

    assert apply_sections([_PLANNING], log)[0].order == 3


def test_a_section_the_log_never_names_is_left_alone() -> None:
    assert apply_sections([_PLANNING], [reorder_sections({"s2": 1})]) == [_PLANNING]


def test_apply_sections_leaves_the_input_untouched() -> None:
    sections = [_PLANNING]

    apply_sections(sections, [reorder_sections({"s1": 9})])

    assert sections[0].order == 1


def test_the_row_log_ignores_a_section_order_mutation() -> None:
    rows = [_row("a")]

    assert apply(rows, [reorder_sections({"s1": 2})]) == rows


def test_a_section_order_mutation_touches_no_task() -> None:
    assert touched([reorder_sections({"s1": 2})]) == frozenset()
