import pytest

from todoist_tui.tui.vim.edits import Effect, Move, plan
from todoist_tui.tui.vim.keys import (
    Insertion,
    Mode,
    Motion,
    MotionCommand,
    Object,
    Operator,
    OperatorCommand,
    Over,
    TextObject,
    Where,
)
from todoist_tui.tui.vim.motions import Cursor, Position


def applied(lines: list[str], effect: Effect | None) -> tuple[str, Cursor, Mode]:
    """The document, cursor and mode an effect leaves behind."""
    text = "\n".join(lines)
    if effect is None:
        return text, (0, 0), Mode.NORMAL
    if isinstance(effect, Move):
        return text, effect.position.cursor, effect.mode
    offsets = [
        sum(len(line) + 1 for line in lines[:row]) + col
        for row, col in (effect.start, effect.end)
    ]
    edited = text[: offsets[0]] + effect.text + text[offsets[1] :]
    return edited, effect.position.cursor, effect.mode


def delete(
    lines: list[str], over: Over, cursor: Cursor, count: int = 1
) -> Effect | None:
    command = OperatorCommand(Operator.DELETE, over, count)
    return plan(command, lines, Position(cursor))


def change(
    lines: list[str], over: Over, cursor: Cursor, count: int = 1
) -> Effect | None:
    command = OperatorCommand(Operator.CHANGE, over, count)
    return plan(command, lines, Position(cursor))


def a_word(*, inner: bool) -> TextObject:
    return TextObject(Object.WORD, inner)


def test_a_motion_only_moves_and_rests_on_a_character() -> None:
    lines = ["alpha", "hi"]
    effect = plan(MotionCommand(Motion.LINE_END), lines, Position((0, 0)))
    assert applied(lines, effect) == ("alpha\nhi", (0, 4), Mode.NORMAL)


@pytest.mark.parametrize(
    ("where", "cursor", "expected"),
    [
        ("before", (0, 2), (0, 2)),
        ("after", (0, 2), (0, 3)),
        ("after", (0, 4), (0, 5)),  # `a` on the last character reaches past it
        ("line_start", (0, 4), (0, 2)),
        ("line_end", (0, 0), (0, 5)),
    ],
)
def test_insert_entry_moves_the_cursor_without_touching_the_text(
    where: Where, cursor: Cursor, expected: Cursor
) -> None:
    lines = ["  abc"]
    effect = plan(Insertion(where), lines, Position(cursor))
    assert applied(lines, effect) == ("  abc", expected, Mode.INSERT)


def test_o_and_O_open_a_line() -> None:
    lines = ["one", "two"]
    assert applied(lines, plan(Insertion("below"), lines, Position((0, 1)))) == (
        "one\n\ntwo",
        (1, 0),
        Mode.INSERT,
    )
    assert applied(lines, plan(Insertion("above"), lines, Position((1, 1)))) == (
        "one\n\ntwo",
        (1, 0),
        Mode.INSERT,
    )


def test_o_on_the_last_line_appends_one() -> None:
    lines = ["one", "two"]
    assert applied(lines, plan(Insertion("below"), lines, Position((1, 1)))) == (
        "one\ntwo\n",
        (2, 0),
        Mode.INSERT,
    )


def test_A_on_an_empty_document_starts_at_the_beginning() -> None:
    assert applied([""], plan(Insertion("line_end"), [""], Position((0, 0)))) == (
        "",
        (0, 0),
        Mode.INSERT,
    )


@pytest.mark.parametrize(
    ("cursor", "count", "expected", "landing"),
    [
        ((0, 0), 1, "lpha", (0, 0)),
        ((0, 4), 1, "alph", (0, 3)),  # the cursor follows the text back
        ((0, 1), 3, "aa", (0, 1)),
        ((0, 3), 9, "alp", (0, 2)),  # clamps at the line end, never joins
    ],
)
def test_x_deletes_forward_within_the_line(
    cursor: Cursor, count: int, expected: str, landing: Cursor
) -> None:
    lines = ["alpha"]
    effect = delete(lines, Motion.RIGHT, cursor, count)
    assert applied(lines, effect) == (expected, landing, Mode.NORMAL)


def test_x_on_an_empty_line_does_nothing() -> None:
    assert delete(["", "b"], Motion.RIGHT, (0, 0)) is None


def test_dh_at_the_start_of_a_line_does_nothing() -> None:
    assert delete(["ab"], Motion.LEFT, (0, 0)) is None


@pytest.mark.parametrize(
    ("cursor", "expected", "landing"),
    [((0, 0), "", (0, 0)), ((0, 2), "al", (0, 1))],
)
def test_D_clears_to_the_end_of_the_line(
    cursor: Cursor, expected: str, landing: Cursor
) -> None:
    lines = ["alpha"]
    assert applied(lines, delete(lines, Motion.LINE_END, cursor)) == (
        expected,
        landing,
        Mode.NORMAL,
    )


def test_D_on_an_empty_line_does_nothing_but_C_still_opens_insert() -> None:
    assert delete([""], Motion.LINE_END, (0, 0)) is None
    assert applied([""], change([""], Motion.LINE_END, (0, 0))) == (
        "",
        (0, 0),
        Mode.INSERT,
    )


def test_dw_stops_at_the_line_end_rather_than_joining() -> None:
    lines = ["one two", "three"]
    assert applied(lines, delete(lines, Motion.WORD, (0, 4))) == (
        "one \nthree",
        (0, 3),
        Mode.NORMAL,
    )


def test_dw_on_an_empty_line_does_join_it_to_the_next() -> None:
    lines = ["", "three"]
    assert applied(lines, delete(lines, Motion.WORD, (0, 0))) == (
        "three",
        (0, 0),
        Mode.NORMAL,
    )


def test_dw_inside_a_line_leaves_the_following_word() -> None:
    lines = ["one two three"]
    assert applied(lines, delete(lines, Motion.WORD, (0, 4))) == (
        "one three",
        (0, 4),
        Mode.NORMAL,
    )


def test_de_is_inclusive_where_dw_is_exclusive() -> None:
    lines = ["one two"]
    assert applied(lines, delete(lines, Motion.WORD_END, (0, 4)))[0] == "one "
    assert applied(lines, delete(lines, Motion.WORD, (0, 0)))[0] == "two"


def test_d0_deletes_back_to_the_line_start() -> None:
    lines = ["alpha"]
    assert applied(lines, delete(lines, Motion.LINE_START, (0, 3))) == (
        "ha",
        (0, 0),
        Mode.NORMAL,
    )


def test_cw_changes_only_the_rest_of_the_word_under_the_cursor() -> None:
    """The classic: `cw` on the last letter of a word is not `ce` from there."""
    lines = ["one two three"]
    assert applied(lines, change(lines, Motion.WORD, (0, 4))) == (
        "one  three",
        (0, 4),
        Mode.INSERT,
    )
    assert applied(lines, change(lines, Motion.WORD, (0, 6))) == (
        "one tw three",
        (0, 6),
        Mode.INSERT,
    )


def test_cw_on_a_blank_falls_back_to_the_plain_word_motion() -> None:
    lines = ["one   two"]
    assert applied(lines, change(lines, Motion.WORD, (0, 3))) == (
        "onetwo",
        (0, 3),
        Mode.INSERT,
    )


@pytest.mark.parametrize(
    ("cursor", "count", "expected", "landing"),
    [
        ((0, 1), 1, "  two\nthree", (0, 2)),
        ((1, 0), 1, "one\nthree", (1, 0)),
        ((2, 1), 1, "one\n  two", (1, 2)),  # the last line takes the newline before it
        ((0, 0), 2, "three", (0, 0)),
        ((1, 0), 9, "one", (0, 0)),  # clamps at the document end
    ],
)
def test_dd_works_over_whole_lines(
    cursor: Cursor, count: int, expected: str, landing: Cursor
) -> None:
    lines = ["one", "  two", "three"]
    assert applied(lines, delete(lines, Motion.LINE, cursor, count)) == (
        expected,
        landing,
        Mode.NORMAL,
    )


def test_dd_on_the_only_line_leaves_an_empty_one() -> None:
    lines = ["only"]
    assert applied(lines, delete(lines, Motion.LINE, (0, 2))) == (
        "",
        (0, 0),
        Mode.NORMAL,
    )


def test_cc_empties_the_line_and_opens_insert() -> None:
    lines = ["one", "  two"]
    assert applied(lines, change(lines, Motion.LINE, (1, 3))) == (
        "one\n",
        (1, 0),
        Mode.INSERT,
    )


@pytest.mark.parametrize(
    ("motion", "count", "expected"),
    [
        (Motion.DOWN, 1, "one"),
        (Motion.UP, 1, "three"),
        (Motion.BOTTOM, 1, "one"),
        (Motion.TO_LINE, 1, "three"),
    ],
)
def test_an_operator_over_a_vertical_motion_is_linewise(
    motion: Motion, count: int, expected: str
) -> None:
    lines = ["one", "two", "three"]
    cursor = (1, 0) if motion in (Motion.DOWN, Motion.BOTTOM) else (1, 1)
    assert applied(lines, delete(lines, motion, cursor, count))[0] == expected


def test_a_counted_cw_reaches_the_end_of_the_last_word_it_covers() -> None:
    lines = ["one two three four"]
    assert applied(lines, change(lines, Motion.WORD, (0, 4), 2)) == (
        "one  four",
        (0, 4),
        Mode.INSERT,
    )


def test_cw_at_the_start_of_a_line_below_the_first() -> None:
    lines = ["one", "two three"]
    assert applied(lines, change(lines, Motion.WORD, (1, 0))) == (
        "one\n three",
        (1, 0),
        Mode.INSERT,
    )


def test_diw_takes_the_word_the_cursor_sits_in_and_nothing_around_it() -> None:
    lines = ["one two three"]
    assert applied(lines, delete(lines, a_word(inner=True), (0, 5))) == (
        "one  three",
        (0, 4),
        Mode.NORMAL,
    )


def test_daw_takes_the_space_after_the_word_too() -> None:
    lines = ["one two three"]
    assert applied(lines, delete(lines, a_word(inner=False), (0, 5))) == (
        "one three",
        (0, 4),
        Mode.NORMAL,
    )


def test_caw_opens_insert_where_the_word_stood() -> None:
    lines = ["one two three"]
    assert applied(lines, change(lines, a_word(inner=False), (0, 5))) == (
        "one three",
        (0, 4),
        Mode.INSERT,
    )


def test_a_word_object_on_an_empty_line_does_nothing_at_all() -> None:
    """Not even a change opens insert: there is no word to stand in for."""
    lines = ["one", "", "two"]
    assert change(lines, a_word(inner=True), (1, 0)) is None
    assert delete(lines, a_word(inner=True), (1, 0)) is None
