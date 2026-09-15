"""What a vim command does to a document.

Pure: an effect describes the move or the text swap, and the caller is what
touches a widget. Planning against the lines it is given means every vim quirk
— `dw` stopping at the line end, `cw` not being `ce`, where the cursor lands
after `dd` — is decided here and tested without a terminal.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from todoist_tui.tui.vim.keys import (
    Edit,
    Insertion,
    Mode,
    Motion,
    MotionCommand,
    Operator,
    OperatorCommand,
    Over,
    TextObject,
    Where,
)
from todoist_tui.tui.vim.motions import (
    Cursor,
    Position,
    clamped,
    first_non_blank,
    offset,
    target,
)
from todoist_tui.tui.vim.objects import span


@dataclass(frozen=True, slots=True)
class Move:
    position: Position
    mode: Mode = Mode.NORMAL


@dataclass(frozen=True, slots=True)
class Change:
    """Swap the text between `start` and `end` for `text`, then land here."""

    start: Cursor
    end: Cursor
    text: str
    position: Position
    mode: Mode = Mode.NORMAL


type Effect = Move | Change

_LINEWISE = (Motion.LINE, Motion.DOWN, Motion.UP, Motion.TO_LINE, Motion.BOTTOM)
_INCLUSIVE = (Motion.WORD_END,)


def plan(command: Edit, lines: Sequence[str], position: Position) -> Effect | None:
    """What the command does here, or None when there is nothing to do."""
    match command:
        case MotionCommand(motion, count):
            landing = target(motion, count, lines, position)
            return Move(Position(clamped(lines, landing.cursor), landing.to_end))
        case Insertion(where):
            return _insertion(where, lines, position.cursor)
        case OperatorCommand(operator, over, count):
            return _operated(operator, over, count, lines, position)


def _operated(
    operator: Operator,
    over: Over,
    count: int,
    lines: Sequence[str],
    position: Position,
) -> Effect | None:
    if isinstance(over, TextObject):
        found = span(over, lines, position.cursor)
        return None if found is None else _spanned(operator, lines, found)
    if over in _LINEWISE:
        return _linewise(operator, over, count, lines, position)
    return _charwise(operator, over, count, lines, position)


def _insertion(where: Where, lines: Sequence[str], cursor: Cursor) -> Effect:
    row, col = cursor
    line = lines[row]
    match where:
        case "before":
            return Move(Position(cursor), Mode.INSERT)
        case "after":
            return Move(Position((row, min(col + 1, len(line)))), Mode.INSERT)
        case "line_start":
            return Move(Position((row, first_non_blank(line))), Mode.INSERT)
        case "line_end":
            return Move(Position((row, len(line))), Mode.INSERT)
        case "below":
            return _opened(lines, (row, len(line)), (row + 1, 0))
        case "above":
            return _opened(lines, (row, 0), (row, 0))


def _opened(lines: Sequence[str], at: Cursor, landing: Cursor) -> Change:
    return Change(at, at, "\n", Position(landing), Mode.INSERT)


def _linewise(
    operator: Operator,
    motion: Motion,
    count: int,
    lines: Sequence[str],
    position: Position,
) -> Effect:
    row = position.cursor[0]
    reach = (
        row + count - 1
        if motion is Motion.LINE
        else _reach(motion, count, lines, position)
    )
    first, last = min(row, reach), min(max(row, reach), len(lines) - 1)

    if operator is Operator.CHANGE:  # the lines stay, emptied
        span = ((first, 0), (last, len(lines[last])))
        return Change(*span, "", Position((first, 0)), Mode.INSERT)

    if first == 0 and last == len(lines) - 1:  # nothing left to hold a newline
        span = ((0, 0), (last, len(lines[last])))
    elif last == len(lines) - 1:  # the trailing lines take the newline before them
        span = ((first - 1, len(lines[first - 1])), (last, len(lines[last])))
    else:
        span = ((first, 0), (last + 1, 0))
    remaining = _without(lines, *span)
    landing = min(first, len(remaining) - 1)
    return Change(*span, "", Position((landing, first_non_blank(remaining[landing]))))


def _reach(motion: Motion, count: int, lines: Sequence[str], position: Position) -> int:
    return target(motion, count, lines, position).cursor[0]


def _charwise(
    operator: Operator,
    motion: Motion,
    count: int,
    lines: Sequence[str],
    position: Position,
) -> Effect | None:
    cursor = position.cursor
    if operator is Operator.CHANGE and motion is Motion.WORD:
        span = _change_word(count, lines, position)
    else:
        reach = target(motion, count, lines, position).cursor
        if motion in _INCLUSIVE:
            reach = (reach[0], reach[1] + 1)
        span = _ordered(cursor, reach)
        if motion is Motion.WORD:
            span = _held_to_the_line(lines, span)

    return _spanned(operator, lines, span)


def _spanned(
    operator: Operator, lines: Sequence[str], span: tuple[Cursor, Cursor]
) -> Effect | None:
    """What an operator does to the stretch it was aimed at, however that
    stretch was found."""
    start, end = span
    if start == end:
        # nothing to delete; a change still has a line to start typing on
        if operator is Operator.DELETE:
            return None
        return Move(Position(start), Mode.INSERT)
    if operator is Operator.CHANGE:
        return Change(start, end, "", Position(start), Mode.INSERT)
    remaining = _without(lines, start, end)
    return Change(start, end, "", Position(clamped(remaining, start)))


def _change_word(
    count: int, lines: Sequence[str], position: Position
) -> tuple[Cursor, Cursor]:
    """`cw` is not `ce`: on a word it changes only that word's rest, so on the
    last letter it changes one letter. Only on a blank does it act like `w`."""
    row, col = position.cursor
    line = lines[row]
    if col >= len(line) or line[col] in " \t":
        return _ordered(
            position.cursor, target(Motion.WORD, count, lines, position).cursor
        )
    walked = position
    for _ in range(count - 1):
        walked = target(Motion.WORD, 1, lines, walked)
    end = target(Motion.WORD_END, 1, lines, _before(walked, lines))
    return position.cursor, (end.cursor[0], end.cursor[1] + 1)


def _before(position: Position, lines: Sequence[str]) -> Position:
    """One column back, so a cursor already on a word end still ends there."""
    row, col = position.cursor
    if col:
        return Position((row, col - 1))
    return Position((row - 1, len(lines[row - 1]))) if row else position


def _held_to_the_line(
    lines: Sequence[str], span: tuple[Cursor, Cursor]
) -> tuple[Cursor, Cursor]:
    """Vim's one `dw` oddity: a word motion off the end of a line does not drag
    the next line up — unless the line was empty, which is the whole word."""
    start, end = span
    if end[0] == start[0] or not lines[start[0]]:
        return span
    return start, (start[0], len(lines[start[0]]))


def _ordered(one: Cursor, other: Cursor) -> tuple[Cursor, Cursor]:
    return (one, other) if one <= other else (other, one)


def _without(lines: Sequence[str], start: Cursor, end: Cursor) -> list[str]:
    text = "\n".join(lines)
    return (text[: offset(lines, start)] + text[offset(lines, end) :]).split("\n")
