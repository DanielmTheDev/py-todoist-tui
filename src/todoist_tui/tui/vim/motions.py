"""Where vim's motions land, over plain lines of text.

A target may sit one past the last character of its line: that is the column an
operator needs (`d$` has to reach the end), and `clamped` is what pulls a plain
move back to where normal mode lets the cursor rest.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto

from todoist_tui.tui.vim.keys import Motion

type Cursor = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Position:
    """Where the cursor is, and whether it is hugging the end of its line. `$`
    sets that and j/k keep it, so walking down ragged lines stays at the end."""

    cursor: Cursor
    to_end: bool = False


def target(
    motion: Motion, count: int, lines: Sequence[str], position: Position
) -> Position:
    """Where `count` of `motion` lands, before any normal-mode clamping."""
    row, col = position.cursor
    match motion:
        case Motion.LEFT:
            return Position((row, max(col - count, 0)))
        case Motion.RIGHT:
            return Position((row, min(col + count, len(lines[row]))))
        case Motion.DOWN:
            return _vertical(lines, position, row + count)
        case Motion.UP:
            return _vertical(lines, position, row - count)
        case Motion.LINE_START:
            return Position((row, 0))
        case Motion.FIRST:
            return Position((row, first_non_blank(lines[row])))
        case Motion.LINE_END:
            return Position((row, len(lines[row])), to_end=True)
        case Motion.TO_LINE:
            return _landing(lines, count - 1)
        case Motion.BOTTOM:
            return _landing(lines, len(lines) - 1)
        case Motion.WORD | Motion.BACK | Motion.WORD_END:
            return _word(motion, count, lines, position.cursor)
        case Motion.LINE:
            return position  # linewise: the operator works it out from the row


def clamped(lines: Sequence[str], cursor: Cursor) -> Cursor:
    """The cursor pulled back to where normal mode lets it rest — on a
    character, not past the last one."""
    row, col = cursor
    return row, min(col, max(len(lines[row]) - 1, 0))


def offset(lines: Sequence[str], cursor: Cursor) -> int:
    """The cursor as an index into the lines joined by newlines."""
    row, col = cursor
    return sum(len(line) + 1 for line in lines[:row]) + col


def first_non_blank(line: str) -> int:
    stripped = line.lstrip(" \t")
    return len(line) - len(stripped) if stripped else 0


def _vertical(lines: Sequence[str], position: Position, row: int) -> Position:
    row = min(max(row, 0), len(lines) - 1)
    width = len(lines[row])
    col = width if position.to_end else min(position.cursor[1], width)
    return Position((row, col), position.to_end)


def _landing(lines: Sequence[str], row: int) -> Position:
    row = min(max(row, 0), len(lines) - 1)
    return Position((row, first_non_blank(lines[row])))


class Kind(Enum):
    BLANK = auto()
    NEWLINE = auto()
    KEYWORD = auto()
    PUNCTUATION = auto()


def kind(character: str) -> Kind:
    if character == "\n":
        return Kind.NEWLINE
    if character in " \t":
        return Kind.BLANK
    if character.isalnum() or character == "_":
        return Kind.KEYWORD
    return Kind.PUNCTUATION


def _starts_word(text: str, index: int) -> bool:
    here = kind(text[index])
    if here is Kind.NEWLINE:  # an empty line is a word of its own
        return index == 0 or text[index - 1] == "\n"
    if here is Kind.BLANK:
        return False
    return index == 0 or kind(text[index - 1]) is not here


def _ends_word(text: str, index: int) -> bool:
    here = kind(text[index])
    if here in (Kind.BLANK, Kind.NEWLINE):  # `e`, unlike `w`, skips blank lines
        return False
    return index == len(text) - 1 or kind(text[index + 1]) is not here


def _word(motion: Motion, count: int, lines: Sequence[str], cursor: Cursor) -> Position:
    """Word motions read the lines as one string, so crossing a line end needs
    no case of its own."""
    text = "\n".join(lines)
    index = offset(lines, cursor)
    for _ in range(count):
        index = _stepped(motion, text, lines, index)
    return Position(located(lines, index))


def _stepped(motion: Motion, text: str, lines: Sequence[str], index: int) -> int:
    backwards = motion is Motion.BACK
    stops = _ends_word if motion is Motion.WORD_END else _starts_word
    indices = range(index - 1, -1, -1) if backwards else range(index + 1, len(text))
    for candidate in indices:
        if stops(text, candidate):
            return candidate
    # nothing left to reach: rest against the end we were walking towards
    last = len(lines) - 1
    return 0 if backwards else offset(lines, (last, max(len(lines[last]) - 1, 0)))


def located(lines: Sequence[str], index: int) -> Cursor:
    for row, line in enumerate(lines[:-1]):
        if index <= len(line):
            return row, index
        index -= len(line) + 1
    return len(lines) - 1, index
