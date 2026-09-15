import pytest

from todoist_tui.tui.vim.keys import Motion
from todoist_tui.tui.vim.motions import (
    Cursor,
    Position,
    clamped,
    first_non_blank,
    target,
)

LINES = ["alpha beta", "", "  gamma(delta)", "eps"]


def at(row: int, col: int, *, to_end: bool = False) -> Position:
    return Position((row, col), to_end)


def moved(motion: Motion, lines: list[str], cursor: Cursor, count: int = 1) -> Cursor:
    return target(motion, count, lines, Position(cursor)).cursor


@pytest.mark.parametrize(
    ("motion", "cursor", "count", "expected"),
    [
        (Motion.LEFT, (0, 4), 1, (0, 3)),
        (Motion.LEFT, (0, 2), 5, (0, 0)),  # clamps, never wraps to the line above
        (Motion.RIGHT, (0, 4), 1, (0, 5)),
        (Motion.RIGHT, (0, 8), 9, (0, 10)),  # one past the last char, for `x`/`d`
        (Motion.RIGHT, (1, 0), 3, (1, 0)),  # an empty line has nowhere to go
    ],
)
def test_h_and_l_stay_on_their_line(
    motion: Motion, cursor: Cursor, count: int, expected: Cursor
) -> None:
    assert moved(motion, LINES, cursor, count) == expected


@pytest.mark.parametrize(
    ("motion", "cursor", "count", "expected"),
    [
        (Motion.DOWN, (0, 3), 1, (1, 0)),  # the empty line has no column 3
        (Motion.DOWN, (0, 3), 2, (2, 3)),
        (Motion.DOWN, (0, 0), 9, (3, 0)),  # clamps rather than refusing
        (Motion.UP, (3, 2), 1, (2, 2)),
        (Motion.UP, (3, 2), 9, (0, 2)),
    ],
)
def test_j_and_k_keep_the_column_where_the_line_allows(
    motion: Motion, cursor: Cursor, count: int, expected: Cursor
) -> None:
    assert moved(motion, LINES, cursor, count) == expected


def test_dollar_then_j_keeps_hugging_the_line_end() -> None:
    end = target(Motion.LINE_END, 1, LINES, at(0, 0))
    assert end == at(0, 10, to_end=True)  # one past the last char; `$` clamps on move
    down = target(Motion.DOWN, 2, LINES, end)
    assert down == at(2, 14, to_end=True)


@pytest.mark.parametrize(
    "motion", [Motion.LEFT, Motion.RIGHT, Motion.WORD, Motion.LINE_START, Motion.FIRST]
)
def test_any_horizontal_motion_forgets_the_line_end(motion: Motion) -> None:
    assert not target(motion, 1, LINES, at(2, 13, to_end=True)).to_end


@pytest.mark.parametrize(
    ("motion", "cursor", "expected"),
    [
        (Motion.LINE_START, (2, 9), (2, 0)),
        (Motion.FIRST, (2, 9), (2, 2)),
        (Motion.FIRST, (1, 0), (1, 0)),
        (Motion.LINE_END, (2, 0), (2, 14)),
        (Motion.LINE_END, (1, 0), (1, 0)),
    ],
)
def test_the_line_ends(motion: Motion, cursor: Cursor, expected: Cursor) -> None:
    assert moved(motion, LINES, cursor) == expected


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, (0, 0)), (3, (2, 2)), (4, (3, 0)), (9, (3, 0))],
)
def test_gg_lands_on_the_first_non_blank_of_the_line_it_names(
    count: int, expected: Cursor
) -> None:
    assert moved(Motion.TO_LINE, LINES, (0, 5), count) == expected


def test_G_lands_on_the_last_line() -> None:
    assert moved(Motion.BOTTOM, LINES, (0, 5)) == (3, 0)


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [
        ((0, 0), (0, 6)),  # alpha -> beta
        ((0, 6), (1, 0)),  # beta -> the empty line, which counts as a word
        ((1, 0), (2, 2)),  # the empty line -> gamma
        ((2, 2), (2, 7)),  # gamma -> the ( , a word of punctuation
        ((2, 7), (2, 8)),  # ( -> delta
        ((2, 13), (3, 0)),  # ) -> eps, across the line end
        ((3, 0), (3, 2)),  # nothing left: clamp to the last character
    ],
)
def test_w_walks_to_the_next_word(cursor: Cursor, expected: Cursor) -> None:
    assert moved(Motion.WORD, LINES, cursor) == expected


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [
        ((0, 6), (0, 0)),
        ((1, 0), (0, 6)),
        ((2, 2), (1, 0)),
        ((2, 8), (2, 7)),
        ((3, 0), (2, 13)),
        ((0, 0), (0, 0)),  # nothing before: clamp to the start
    ],
)
def test_b_walks_back_to_a_word_start(cursor: Cursor, expected: Cursor) -> None:
    assert moved(Motion.BACK, LINES, cursor) == expected


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [
        ((0, 0), (0, 4)),  # to the end of alpha
        ((0, 4), (0, 9)),  # already at an end: on to beta's
        ((0, 9), (2, 6)),  # empty lines are not stops for `e`
        ((2, 6), (2, 7)),
        ((2, 8), (2, 12)),
        ((3, 2), (3, 2)),  # nothing left
    ],
)
def test_e_walks_to_a_word_end(cursor: Cursor, expected: Cursor) -> None:
    assert moved(Motion.WORD_END, LINES, cursor) == expected


@pytest.mark.parametrize(
    ("count", "expected"), [(2, (2, 2)), (3, (2, 7)), (99, (3, 2))]
)
def test_a_count_repeats_a_word_motion_and_clamps(count: int, expected: Cursor) -> None:
    assert moved(Motion.WORD, LINES, (0, 6), count) == expected


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [((0, 10), (0, 9)), ((0, 3), (0, 3)), ((1, 0), (1, 0)), ((1, 4), (1, 0))],
)
def test_the_normal_mode_column_never_sits_past_the_last_character(
    cursor: Cursor, expected: Cursor
) -> None:
    assert clamped(LINES, cursor) == expected


@pytest.mark.parametrize(
    ("line", "expected"), [("  gamma", 2), ("eps", 0), ("", 0), ("   ", 0)]
)
def test_first_non_blank(line: str, expected: int) -> None:
    assert first_non_blank(line) == expected


def test_the_linewise_pseudo_motion_stays_put() -> None:
    """`dd` names no target of its own: the operator works it out from the row."""
    assert target(Motion.LINE, 2, LINES, at(2, 5)) == at(2, 5)
