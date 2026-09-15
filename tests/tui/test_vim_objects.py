import pytest

from todoist_tui.tui.vim.keys import Object, TextObject
from todoist_tui.tui.vim.motions import Cursor
from todoist_tui.tui.vim.objects import span


def word(
    lines: list[str], cursor: Cursor, *, inner: bool
) -> tuple[Cursor, Cursor] | None:
    return span(TextObject(Object.WORD, inner), lines, cursor)


@pytest.mark.parametrize(
    ("lines", "cursor", "expected"),
    [
        (["one   two"], (0, 1), ((0, 0), (0, 3))),  # the word around the cursor
        (["one   two"], (0, 3), ((0, 3), (0, 6))),  # a run of blanks is a word too
        (["a.b"], (0, 1), ((0, 1), (0, 2))),  # so is a run of punctuation
        (["one   two"], (0, 8), ((0, 6), (0, 9))),  # the last word ends the line
    ],
)
def test_iw_is_the_run_the_cursor_sits_in(
    lines: list[str], cursor: Cursor, expected: tuple[Cursor, Cursor]
) -> None:
    assert word(lines, cursor, inner=True) == expected


def test_aw_takes_the_blanks_that_follow_the_word() -> None:
    assert word(["one   two"], (0, 1), inner=False) == ((0, 0), (0, 6))


def test_aw_falls_back_to_the_blanks_before_a_word_ending_the_line() -> None:
    """Vim's rule: the padding is the trailing run, or the leading one when the
    word has nothing after it."""
    assert word(["abc def"], (0, 4), inner=False) == ((0, 3), (0, 7))


def test_aw_leaves_an_indent_alone() -> None:
    """Blanks opening the line are indentation, not the word's padding."""
    assert word(["  one"], (0, 2), inner=False) == ((0, 2), (0, 5))


def test_aw_on_blanks_takes_the_word_that_follows_them() -> None:
    assert word(["one   two"], (0, 3), inner=False) == ((0, 3), (0, 9))


def test_aw_on_blanks_with_no_word_after_them_is_the_blanks() -> None:
    assert word(["one  "], (0, 4), inner=False) == ((0, 3), (0, 5))


@pytest.mark.parametrize("inner", [True, False])
def test_a_word_object_never_crosses_the_line_end(inner: bool) -> None:
    assert word(["one", "two"], (0, 1), inner=inner) == ((0, 0), (0, 3))


@pytest.mark.parametrize("inner", [True, False])
def test_an_empty_line_holds_no_word(inner: bool) -> None:
    assert word(["", "two"], (0, 0), inner=inner) is None
