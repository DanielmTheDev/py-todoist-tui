from todoist_tui.domain.project import Project, sorted_projects


def test_project_holds_fields() -> None:
    p = Project(id="9", name="Work", is_inbox=False, order=3)
    assert (p.id, p.name, p.is_inbox, p.order) == ("9", "Work", False, 3)


def test_project_order_defaults_to_zero() -> None:
    assert Project(id="9", name="Work").order == 0


def test_sorted_projects_empty() -> None:
    assert sorted_projects([]) == []


def test_sorted_projects_orders_by_order() -> None:
    a = Project(id="a", name="A", order=2)
    b = Project(id="b", name="B", order=1)
    assert sorted_projects([a, b]) == [b, a]


def test_sorted_projects_is_stable_for_equal_order() -> None:
    a = Project(id="a", name="A", order=1)
    b = Project(id="b", name="B", order=1)
    assert sorted_projects([a, b]) == [a, b]
