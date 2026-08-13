from todoist_tui.domain.view_slots import ViewSlots


def test_empty_slots_hold_nothing() -> None:
    slots = ViewSlots()
    assert slots.view_key_for("w") is None
    assert slots.key_for("filter:1") is None
    assert slots.startup is None


def test_assigned_key_resolves_both_ways() -> None:
    slots = ViewSlots().assign("w", "filter:1")
    assert slots.view_key_for("w") == "filter:1"
    assert slots.key_for("filter:1") == "w"


def test_reassigning_a_key_replaces_what_it_held() -> None:
    slots = ViewSlots().assign("w", "filter:1").assign("w", "project:2")
    assert slots.view_key_for("w") == "project:2"
    assert slots.key_for("filter:1") is None


def test_a_view_keeps_only_its_newest_key() -> None:
    """Two keys onto one view would leave the modal unable to show one badge."""
    slots = ViewSlots().assign("w", "filter:1").assign("n", "filter:1")
    assert slots.view_key_for("w") is None
    assert slots.view_key_for("n") == "filter:1"


def test_clearing_a_key_leaves_the_others() -> None:
    slots = ViewSlots().assign("w", "filter:1").assign("b", "project:2").clear("w")
    assert slots.view_key_for("w") is None
    assert slots.view_key_for("b") == "project:2"


def test_clearing_an_unassigned_key_changes_nothing() -> None:
    slots = ViewSlots().assign("w", "filter:1")
    assert slots.clear("b") == slots


def test_startup_is_independent_of_any_key() -> None:
    slots = ViewSlots().with_startup("project:2")
    assert slots.startup == "project:2"
    assert slots.key_for("project:2") is None


def test_clearing_a_key_keeps_it_as_the_startup_view() -> None:
    slots = ViewSlots().assign("w", "filter:1").with_startup("filter:1").clear("w")
    assert slots.startup == "filter:1"


def test_startup_can_be_dropped() -> None:
    slots = ViewSlots().with_startup("filter:1").with_startup(None)
    assert slots.startup is None


def test_assignments_keep_their_order() -> None:
    """The modal lists assigned views first; a stable order keeps it from jumping."""
    slots = ViewSlots().assign("w", "filter:1").assign("b", "project:2")
    assert list(slots.by_key.items()) == [("w", "filter:1"), ("b", "project:2")]
