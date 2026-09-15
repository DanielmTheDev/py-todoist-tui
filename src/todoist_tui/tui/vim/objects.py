"""The stretch of text a text object names.

Pure, like the rest of the package: a span is a half-open pair of cursors, the
same `[start, end)` the effects speak in. `None` is no such object here, which
is not the same as an empty one — `ci(` on empty brackets has somewhere to type,
`ci(` with no brackets at all has nothing to do.
"""

from collections.abc import Sequence

from todoist_tui.tui.vim.keys import TextObject
from todoist_tui.tui.vim.motions import Cursor, Kind, kind


def span(
    over: TextObject, lines: Sequence[str], cursor: Cursor
) -> tuple[Cursor, Cursor] | None:
    """What the object covers here, or None when there is none to cover."""
    row, col = cursor
    line = lines[row]
    if col >= len(line):  # an empty line, or a cursor resting past its end
        return None
    start, end = _run(line, col)
    if not over.inner:
        start, end = _padded(line, start, end)
    return (row, start), (row, end)


def _run(line: str, col: int) -> tuple[int, int]:
    """The stretch of one kind of character around `col` — a word, a run of
    blanks, or a run of punctuation, as `w` already reads them."""
    here = kind(line[col])
    start = col
    while start and kind(line[start - 1]) is here:
        start -= 1
    end = col + 1
    while end < len(line) and kind(line[end]) is here:
        end += 1
    return start, end


def _padded(line: str, start: int, end: int) -> tuple[int, int]:
    """What `a` adds to `i`: the run after this one — its blanks, or the word
    the blanks under the cursor lead to. A run ending the line reaches back over
    the blanks before it instead, indentation excepted."""
    if end < len(line):
        return start, _run(line, end)[1]
    if start and kind(line[start - 1]) is Kind.BLANK:
        leading = _run(line, start - 1)[0]
        if leading:  # blanks opening the line are indentation, not padding
            return leading, end
    return start, end
