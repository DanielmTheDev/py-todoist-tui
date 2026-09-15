import pytest

from todoist_tui.tui.vim.keys import (
    History,
    Insertion,
    Motion,
    MotionCommand,
    Object,
    Operator,
    OperatorCommand,
    Resolution,
    TextObject,
    Unresolved,
    Where,
    resolve,
)


@pytest.mark.parametrize(
    ("keys", "motion"),
    [
        ("h", Motion.LEFT),
        ("j", Motion.DOWN),
        ("k", Motion.UP),
        ("l", Motion.RIGHT),
        ("w", Motion.WORD),
        ("b", Motion.BACK),
        ("e", Motion.WORD_END),
        ("0", Motion.LINE_START),
        ("^", Motion.FIRST),
        ("$", Motion.LINE_END),
    ],
)
def test_a_bare_motion_key_resolves_to_that_motion(keys: str, motion: Motion) -> None:
    assert resolve(keys) == MotionCommand(motion)


def test_g_waits_for_its_second_press() -> None:
    assert resolve("g") is Unresolved.PENDING


def test_gg_is_the_first_line() -> None:
    assert resolve("gg") == MotionCommand(Motion.TO_LINE, 1)


def test_a_counted_gg_names_the_line() -> None:
    assert resolve("3gg") == MotionCommand(Motion.TO_LINE, 3)


def test_a_bare_G_is_the_last_line_but_a_counted_one_names_a_line() -> None:
    """Vim's one count-sensitive motion: `G` ends the document, `3G` is line 3."""
    assert resolve("G") == MotionCommand(Motion.BOTTOM)
    assert resolve("3G") == MotionCommand(Motion.TO_LINE, 3)


@pytest.mark.parametrize(("keys", "count"), [("3j", 3), ("12j", 12), ("1j", 1)])
def test_a_count_prefixes_a_motion(keys: str, count: int) -> None:
    assert resolve(keys) == MotionCommand(Motion.DOWN, count)


def test_a_count_alone_waits_for_what_it_counts() -> None:
    assert resolve("3") is Unresolved.PENDING
    assert resolve("12") is Unresolved.PENDING


def test_zero_is_a_motion_first_and_a_digit_only_after_one() -> None:
    assert resolve("0") == MotionCommand(Motion.LINE_START)
    assert resolve("10j") == MotionCommand(Motion.DOWN, 10)


def test_an_empty_buffer_is_pending() -> None:
    assert resolve("") is Unresolved.PENDING


@pytest.mark.parametrize(
    ("keys", "where"),
    [
        ("i", "before"),
        ("a", "after"),
        ("I", "line_start"),
        ("A", "line_end"),
        ("o", "below"),
        ("O", "above"),
    ],
)
def test_insert_entry_keys_resolve_to_an_insertion(keys: str, where: Where) -> None:
    assert resolve(keys) == Insertion(where)


def test_undo_is_the_only_history_key_with_a_character() -> None:
    """Redo is ctrl+r, which carries none: the widget maps it, not the parser."""
    assert resolve("u") is History.UNDO


@pytest.mark.parametrize(
    ("keys", "command"),
    [
        ("x", OperatorCommand(Operator.DELETE, Motion.RIGHT)),
        ("3x", OperatorCommand(Operator.DELETE, Motion.RIGHT, 3)),
        ("D", OperatorCommand(Operator.DELETE, Motion.LINE_END)),
        ("C", OperatorCommand(Operator.CHANGE, Motion.LINE_END)),
    ],
)
def test_the_shorthand_edits_are_the_operator_they_stand_for(
    keys: str, command: Resolution
) -> None:
    """`x` is `dl`, `D` is `d$`, `C` is `c$` — so the operator code sees one shape."""
    assert resolve(keys) == command


def test_an_operator_waits_for_its_motion() -> None:
    assert resolve("d") is Unresolved.PENDING
    assert resolve("c") is Unresolved.PENDING
    assert resolve("d2") is Unresolved.PENDING
    assert resolve("dg") is Unresolved.PENDING


@pytest.mark.parametrize(
    ("keys", "command"),
    [
        ("dw", OperatorCommand(Operator.DELETE, Motion.WORD)),
        ("de", OperatorCommand(Operator.DELETE, Motion.WORD_END)),
        ("cw", OperatorCommand(Operator.CHANGE, Motion.WORD)),
        ("d0", OperatorCommand(Operator.DELETE, Motion.LINE_START)),
        ("d$", OperatorCommand(Operator.DELETE, Motion.LINE_END)),
        ("dgg", OperatorCommand(Operator.DELETE, Motion.TO_LINE, 1)),
        ("dG", OperatorCommand(Operator.DELETE, Motion.BOTTOM)),
    ],
)
def test_an_operator_takes_a_motion(keys: str, command: Resolution) -> None:
    assert resolve(keys) == command


def test_a_doubled_operator_is_linewise() -> None:
    assert resolve("dd") == OperatorCommand(Operator.DELETE, Motion.LINE)
    assert resolve("cc") == OperatorCommand(Operator.CHANGE, Motion.LINE)


@pytest.mark.parametrize(
    ("keys", "count"), [("d2w", 2), ("2dw", 2), ("2d3w", 6), ("3dd", 3)]
)
def test_counts_on_both_sides_of_an_operator_multiply(keys: str, count: int) -> None:
    motion = Motion.LINE if keys.endswith("dd") else Motion.WORD
    assert resolve(keys) == OperatorCommand(Operator.DELETE, motion, count)


def test_an_operator_waits_for_the_object_the_i_or_a_opens() -> None:
    """`i` and `a` insert on their own, but after an operator they name an
    object and the key that follows says which."""
    assert resolve("di") is Unresolved.PENDING
    assert resolve("ca") is Unresolved.PENDING


@pytest.mark.parametrize(
    ("keys", "command"),
    [
        ("diw", OperatorCommand(Operator.DELETE, TextObject(Object.WORD, inner=True))),
        ("daw", OperatorCommand(Operator.DELETE, TextObject(Object.WORD, inner=False))),
        ("ciw", OperatorCommand(Operator.CHANGE, TextObject(Object.WORD, inner=True))),
        ("caw", OperatorCommand(Operator.CHANGE, TextObject(Object.WORD, inner=False))),
    ],
)
def test_an_operator_takes_a_text_object(keys: str, command: Resolution) -> None:
    assert resolve(keys) == command


@pytest.mark.parametrize(
    "keys",
    ["z", "dz", "gz", "cx", "!", "jj", "0j", "dgz", "dww", "dcw", "diz", "diww", "dax"],
)
def test_a_buffer_that_can_never_grow_into_a_command_is_rejected(keys: str) -> None:
    assert resolve(keys) is Unresolved.REJECTED


@pytest.mark.parametrize("keys", ["3i", "2u", "3D", "2C", "d2iw", "2diw"])
def test_a_count_on_a_command_that_takes_none_is_rejected(keys: str) -> None:
    """Rather than silently ignored: a swallowed count hides the typo."""
    assert resolve(keys) is Unresolved.REJECTED
