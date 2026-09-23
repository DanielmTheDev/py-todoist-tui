from todoist_tui.domain.section import (
    Section,
    section_insert_plan,
    sections_by_project,
    sorted_sections,
)


def test_section_holds_fields() -> None:
    s = Section(id="5", project_id="9", name="Planning", order=3)
    assert (s.id, s.project_id, s.name, s.order) == ("5", "9", "Planning", 3)


def test_section_order_defaults_to_zero() -> None:
    assert Section(id="5", project_id="9", name="Planning").order == 0


def test_sorted_sections_empty() -> None:
    assert sorted_sections([]) == []


def test_sorted_sections_orders_by_order() -> None:
    a = Section(id="a", project_id="9", name="A", order=2)
    b = Section(id="b", project_id="9", name="B", order=1)
    assert sorted_sections([a, b]) == [b, a]


def test_sorted_sections_is_stable_for_equal_order() -> None:
    a = Section(id="a", project_id="9", name="A", order=1)
    b = Section(id="b", project_id="9", name="B", order=1)
    assert sorted_sections([a, b]) == [a, b]


def test_sections_by_project_groups_in_display_order() -> None:
    grouped = sections_by_project(
        [
            Section(id="s2", project_id="9", name="Backlog", order=2),
            Section(id="s3", project_id="7", name="Errands", order=1),
            Section(id="s1", project_id="9", name="Planning", order=1),
        ]
    )

    assert {pid: [s.name for s in ss] for pid, ss in grouped.items()} == {
        "9": ["Planning", "Backlog"],
        "7": ["Errands"],
    }


def test_insert_plan_into_empty_project_starts_at_one() -> None:
    assert section_insert_plan([], after_id=None) == (1, [])


def test_insert_plan_appends_after_a_clean_run() -> None:
    a = Section(id="a", project_id="9", name="A", order=1)
    b = Section(id="b", project_id="9", name="B", order=2)
    assert section_insert_plan([a, b], after_id=None) == (3, [])


def test_insert_plan_opens_a_slot_after_the_named_section() -> None:
    a = Section(id="a", project_id="9", name="A", order=1)
    b = Section(id="b", project_id="9", name="B", order=2)
    c = Section(id="c", project_id="9", name="C", order=3)

    assert section_insert_plan([a, b, c], after_id="a") == (2, [("b", 3), ("c", 4)])


def test_insert_plan_renumbers_a_gapped_run() -> None:
    a = Section(id="a", project_id="9", name="A", order=2)
    b = Section(id="b", project_id="9", name="B", order=7)

    assert section_insert_plan([a, b], after_id=None) == (3, [("a", 1), ("b", 2)])


def test_insert_plan_separates_sections_sharing_an_order() -> None:
    a = Section(id="a", project_id="9", name="A", order=1)
    b = Section(id="b", project_id="9", name="B", order=1)

    assert section_insert_plan([a, b], after_id="a") == (2, [("b", 3)])


def test_insert_plan_appends_when_the_section_is_gone() -> None:
    a = Section(id="a", project_id="9", name="A", order=1)
    assert section_insert_plan([a], after_id="vanished") == (2, [])
