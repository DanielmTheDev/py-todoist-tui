from todoist_tui.domain.label import Label


def test_label_holds_fields() -> None:
    label = Label(id="5", name="work", order=3)
    assert (label.id, label.name, label.order) == ("5", "work", 3)


def test_label_order_defaults_to_zero() -> None:
    assert Label(id="5", name="work").order == 0
