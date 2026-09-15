"""Vim keystrokes resolved into commands.

Pure text: nothing here knows about Textual, a widget, or a document. `resolve`
reads the whole buffer every time rather than holding parser state, so the
caller owns the one copy of the keys pressed so far.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal


class Mode(Enum):
    NORMAL = auto()
    INSERT = auto()


class Operator(Enum):
    DELETE = auto()
    CHANGE = auto()


class Motion(Enum):
    LEFT = auto()
    DOWN = auto()
    UP = auto()
    RIGHT = auto()
    WORD = auto()
    BACK = auto()
    WORD_END = auto()
    LINE_START = auto()
    FIRST = auto()
    LINE_END = auto()
    TO_LINE = auto()  # the line the count names; `gg` is line 1
    BOTTOM = auto()  # `G` with no count
    LINE = auto()  # linewise: what a doubled operator (`dd`) works over


class Object(Enum):
    WORD = auto()


@dataclass(frozen=True, slots=True)
class TextObject:
    """What `iw`/`aw` name: a stretch the operator finds around the cursor
    rather than walks to. `inner` is the `i` of `diw`, leaving the padding."""

    kind: Object
    inner: bool


type Over = Motion | TextObject


class History(Enum):
    UNDO = auto()
    REDO = auto()


class Unresolved(Enum):
    """A buffer that is not a command: PENDING may still grow into one,
    REJECTED never can and should be dropped."""

    PENDING = auto()
    REJECTED = auto()


type Where = Literal["before", "after", "line_start", "line_end", "below", "above"]


@dataclass(frozen=True, slots=True)
class MotionCommand:
    motion: Motion
    count: int = 1


@dataclass(frozen=True, slots=True)
class OperatorCommand:
    operator: Operator
    over: Over
    count: int = 1


@dataclass(frozen=True, slots=True)
class Insertion:
    where: Where


type Edit = MotionCommand | OperatorCommand | Insertion
type Command = Edit | History
type Resolution = Command | Unresolved

_MOTIONS = {
    "h": Motion.LEFT,
    "j": Motion.DOWN,
    "k": Motion.UP,
    "l": Motion.RIGHT,
    "w": Motion.WORD,
    "b": Motion.BACK,
    "e": Motion.WORD_END,
    "0": Motion.LINE_START,
    "^": Motion.FIRST,
    "$": Motion.LINE_END,
}
_OPERATORS = {"d": Operator.DELETE, "c": Operator.CHANGE}
_INSERTIONS: dict[str, Where] = {
    "i": "before",
    "a": "after",
    "I": "line_start",
    "A": "line_end",
    "o": "below",
    "O": "above",
}
# `x` is `dl`, `D` is `d$`, `C` is `c$`: one operator shape for the edit code
_SHORTHAND = {
    "x": (Operator.DELETE, Motion.RIGHT, True),
    "D": (Operator.DELETE, Motion.LINE_END, False),
    "C": (Operator.CHANGE, Motion.LINE_END, False),
}


_INNER = {"i": True, "a": False}
_OBJECTS = {"w": Object.WORD}


def resolve(keys: str) -> Resolution:
    """What the keys pressed so far mean."""
    count, rest = _count(keys)
    if not rest:
        return Unresolved.PENDING
    head, tail = rest[0], rest[1:]

    if head == "g":
        if not tail:
            return Unresolved.PENDING
        if tail != "g":
            return Unresolved.REJECTED
        return MotionCommand(Motion.TO_LINE, count or 1)
    if head == "G":
        motion = Motion.TO_LINE if count else Motion.BOTTOM
        return MotionCommand(motion, count or 1) if not tail else Unresolved.REJECTED
    if tail and head not in _OPERATORS:
        return Unresolved.REJECTED
    if head in _MOTIONS:
        return MotionCommand(_MOTIONS[head], count or 1)
    if head in _SHORTHAND:
        operator, motion, counted = _SHORTHAND[head]
        if count and not counted:
            return Unresolved.REJECTED
        return OperatorCommand(operator, motion, count or 1)
    if head in _INSERTIONS:
        return Insertion(_INSERTIONS[head]) if not count else Unresolved.REJECTED
    if head == "u":
        return History.UNDO if not count else Unresolved.REJECTED
    if head in _OPERATORS:
        return _operated(_OPERATORS[head], tail, count)
    return Unresolved.REJECTED


def _operated(operator: Operator, keys: str, outer: int) -> Resolution:
    """An operator's own count and what it acts over. The two counts
    multiply, as in vim: `2d3w` deletes six words."""
    own, rest = _count(keys)
    if not rest:
        return Unresolved.PENDING
    count = (outer or 1) * (own or 1)
    head, tail = rest[0], rest[1:]

    if head == "g":
        if not tail:
            return Unresolved.PENDING
        if tail != "g":
            return Unresolved.REJECTED
        return OperatorCommand(operator, Motion.TO_LINE, count)
    if head in _INNER:  # `i`/`a` open a text object, two keys like `gg`
        if not tail:
            return Unresolved.PENDING
        if outer or own or tail not in _OBJECTS:  # an object takes no count
            return Unresolved.REJECTED
        return OperatorCommand(operator, TextObject(_OBJECTS[tail], _INNER[head]))
    if tail:
        return Unresolved.REJECTED
    if head == "G":
        motion = Motion.TO_LINE if outer or own else Motion.BOTTOM
        return OperatorCommand(operator, motion, count)
    if head in _OPERATORS and _OPERATORS[head] is operator:  # `dd`, `cc`
        return OperatorCommand(operator, Motion.LINE, count)
    if head in _MOTIONS:
        return OperatorCommand(operator, _MOTIONS[head], count)
    return Unresolved.REJECTED


def _count(keys: str) -> tuple[int, str]:
    """The count the keys open with and what follows it. 0 is a motion of its
    own, so it only counts once a digit has already been typed. A missing count
    is 0, which reads as "none given" — `G` alone means the last line, `1G` the
    first."""
    digits = ""
    for index, key in enumerate(keys):
        if not key.isdigit() or (not digits and key == "0"):
            return int(digits or 0), keys[index:]
        digits += key
    return int(digits or 0), ""
