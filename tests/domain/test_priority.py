import pytest

from todoist_tui.domain.priority import Priority


@pytest.mark.parametrize(
    ("api_value", "expected"),
    [
        (4, Priority.P1),
        (3, Priority.P2),
        (2, Priority.P3),
        (1, Priority.P4),
    ],
)
def test_from_api_maps_todoist_int_to_priority(
    api_value: int, expected: Priority
) -> None:
    assert Priority.from_api(api_value) is expected


def test_from_api_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="priority"):
        Priority.from_api(5)


def test_label_is_human_readable() -> None:
    assert Priority.P1.label == "P1"


@pytest.mark.parametrize(
    ("priority", "api_value"),
    [
        (Priority.P1, 4),
        (Priority.P2, 3),
        (Priority.P3, 2),
        (Priority.P4, 1),
    ],
)
def test_to_api_maps_priority_to_todoist_int(
    priority: Priority, api_value: int
) -> None:
    assert priority.to_api == api_value
