"""Picking a listed row by its number, shared by the pickers that filter by typing."""

from collections.abc import Iterable

from textual import events
from textual.widgets import Input

_KEYS = "123456789"


class PickFilter(Input):
    """A filter that lets digits through: they pick a numbered row instead of typing.

    `prevent_default` ends Textual's walk up the MRO, so `Input` never sees the key
    and it goes on bubbling to the screen.
    """

    async def _on_key(self, event: events.Key) -> None:
        if event.character is not None and event.character in _KEYS:
            event.prevent_default()


def numbered(labels: Iterable[str]) -> list[str]:
    """Each label behind the digit that picks it; the rows past nine keep the
    indent but get no digit — narrow the filter to reach them."""
    return [
        f"{_KEYS[i]} {label}" if i < len(_KEYS) else f"  {label}"
        for i, label in enumerate(labels)
    ]


def row_for_key(key: str) -> int | None:
    """The row index a key picks, or None when it picks none."""
    return _KEYS.index(key) if len(key) == 1 and key in _KEYS else None
