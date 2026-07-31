from todoist_tui.domain.section import Section, sorted_sections


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
