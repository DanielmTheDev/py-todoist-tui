from todoist_tui.domain.filter import Filter, sorted_filters


def test_filter_holds_fields() -> None:
    f = Filter(id="1", name="Work", query="@work & p1", order=3)
    assert (f.id, f.name, f.query, f.order) == ("1", "Work", "@work & p1", 3)


def test_sorted_filters_empty() -> None:
    assert sorted_filters([]) == []


def test_sorted_filters_orders_by_order() -> None:
    a = Filter(id="a", name="A", query="today", order=2)
    b = Filter(id="b", name="B", query="overdue", order=1)
    assert sorted_filters([a, b]) == [b, a]


def test_sorted_filters_is_stable_for_equal_order() -> None:
    a = Filter(id="a", name="A", query="today", order=1)
    b = Filter(id="b", name="B", query="overdue", order=1)
    assert sorted_filters([a, b]) == [a, b]
