from todoist_tui.domain.view_history import ViewHistory, Visit


def _walked(*keys: str) -> ViewHistory:
    history = ViewHistory()
    for key in keys:
        history = history.visit(Visit(key))
    return history


def _back(history: ViewHistory) -> ViewHistory:
    stepped = history.back()
    assert stepped is not None
    return stepped


def _forward(history: ViewHistory) -> ViewHistory:
    stepped = history.forward()
    assert stepped is not None
    return stepped


def test_an_empty_history_is_nowhere() -> None:
    history = ViewHistory()
    assert history.current is None
    assert history.back() is None
    assert history.forward() is None


def test_visiting_moves_the_pointer_onto_the_new_view() -> None:
    assert _walked("today", "project:2").current == Visit("project:2")


def test_a_repeat_of_the_current_view_collapses() -> None:
    """Re-opening the view already on screen must not cost two presses to leave."""
    history = _walked("today", "project:2").visit(Visit("project:2"))
    assert _back(history).current == Visit("today")


def test_the_same_project_at_a_different_section_is_its_own_visit() -> None:
    history = _walked("project:2").visit(Visit("project:2", land_section="Planning"))
    assert history.current == Visit("project:2", land_section="Planning")
    assert _back(history).current == Visit("project:2")


def test_back_and_forward_walk_the_same_trail() -> None:
    history = _back(_back(_walked("today", "project:2", "inbox")))
    assert history.current == Visit("today")
    assert _forward(history).current == Visit("project:2")


def test_the_oldest_visit_has_nothing_behind_it() -> None:
    assert _walked("today").back() is None


def test_the_newest_visit_has_nothing_ahead_of_it() -> None:
    assert _walked("today", "inbox").forward() is None


def test_a_visit_after_going_back_drops_what_was_ahead() -> None:
    history = _back(_walked("today", "project:2")).visit(Visit("inbox"))
    assert history.forward() is None
    assert _back(history).current == Visit("today")


def test_the_cursor_is_stamped_on_the_visit_being_left() -> None:
    history = _walked("today", "inbox").with_cursor("7")
    assert history.current == Visit("inbox", cursor_id="7")
    assert _back(history).current == Visit("today")


def test_stamping_an_empty_history_changes_nothing() -> None:
    assert ViewHistory().with_cursor("7") == ViewHistory()


def test_a_gone_view_leaves_the_trail_on_the_visit_it_was_on() -> None:
    """A deleted project must not be walked into again, from either direction."""
    walked = _walked("project:2", "today", "project:2", "inbox")
    pruned = _back(_back(walked)).without("project:2")
    assert pruned.current == Visit("today")
    assert pruned.back() is None
    assert _forward(pruned).current == Visit("inbox")
