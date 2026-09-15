"""The task editor's description field, driven by vim keys.

Insert mode is what the field opens in, so tabbing in and typing works as it
always did. Escape leaves it; escape again, with nothing half-typed, reaches the
editor's own binding and cancels.
"""

from typing import ClassVar

from rich.style import Style
from textual import events
from textual.binding import Binding, BindingType
from textual.widgets import TextArea
from textual.widgets.text_area import TextAreaTheme

from todoist_tui.tui.vim.edits import Change, Move, plan
from todoist_tui.tui.vim.keys import Command, History, Mode, Unresolved, resolve
from todoist_tui.tui.vim.motions import Position, clamped

# Declared, not bound: these are characters the field reads itself, so the help
# screen has to be told about them.
VIM_KEYS: list[BindingType] = [
    Binding("escape", "", "Description: leave insert mode"),
    Binding("i,a,I,A,o,O", "", "Description: start typing"),
    Binding("h,j,k,l", "", "Description: move"),
    Binding("w,b,e", "", "Description: word forward / back / end"),
    Binding("0,^,$", "", "Description: line start / first word / end"),
    Binding("gg,G", "", "Description: first / last line"),
    Binding("x,dd,dw,D", "", "Description: delete"),
    Binding("cw,cc,C", "", "Description: change"),
    Binding("diw,daw,ciw,caw", "", "Description: delete / change a word whole"),
    Binding("u,ctrl+r", "", "Description: undo / redo"),
]

# would edit the text if TextArea saw them, and mean nothing in normal mode
_INERT = frozenset({"enter", "backspace", "delete"})
# left to TextArea they would park the cursor past the last character
_ARROWS = {"left": "h", "right": "l", "up": "k", "down": "j"}

# Textual paints its own cursor over a whole cell, so insert mode cannot have a
# bar between two characters: it underlines the cell the bar would stand before.
_CURSORS = {
    Mode.NORMAL: TextAreaTheme(name="vim-normal"),  # the filled block from the CSS
    Mode.INSERT: TextAreaTheme(name="vim-insert", cursor_style=Style(underline=True)),
}


class DescriptionArea(TextArea):
    """A description edited with vim keys, in normal or insert mode."""

    BINDINGS: ClassVar[list[BindingType]] = [
        # select-all on the same key as the title field, not only TextArea's f7
        Binding("ctrl+shift+a", "select_all", show=False),
    ]

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        for theme in _CURSORS.values():
            self.register_theme(theme)
        self._mode = Mode.INSERT
        self._keys = ""  # a command being typed, e.g. "d" or "2"
        self._to_end = False  # `$` was pressed: j/k keep hugging the line end

    def on_mount(self) -> None:
        self._show(self._mode)

    def on_focus(self) -> None:
        """Coming back to the field is coming back to typing."""
        self._keys = ""
        self._switch(Mode.INSERT)

    def on_key(self, event: events.Key) -> None:
        if self._mode is Mode.INSERT:
            if event.key == "escape":
                self._end_insert()
                event.stop()  # or it would reach the editor and cancel
            return
        if event.key == "escape":
            if self._keys:  # drop the half-typed command, not the whole edit
                self._keys = ""
                event.stop()
            return  # nothing pending: the editor's own binding cancels
        if event.key == "ctrl+r":
            self._rewind(History.REDO)
            event.stop()
            return
        if event.key in _ARROWS:
            event.stop()
            event.prevent_default()
            self._press(_ARROWS[event.key])
            return
        if not event.is_printable and event.key not in _INERT:
            return  # ctrl+s, f1, tab and the alt chords still reach the editor
        # stop() keeps the app's bare-letter bindings out of the way;
        # prevent_default() keeps TextArea from typing the key as a character
        event.stop()
        event.prevent_default()
        if event.key in _INERT or event.character is None:
            return
        self._press(event.character)

    def _press(self, character: str) -> None:
        self._keys += character
        resolution = resolve(self._keys)
        if resolution is Unresolved.PENDING:
            return
        self._keys = ""
        if resolution is not Unresolved.REJECTED:
            self._run(resolution)

    def _run(self, command: Command) -> None:
        if isinstance(command, History):
            self._rewind(command)
            return
        effect = plan(
            command, self._lines(), Position(self.cursor_location, self._to_end)
        )
        match effect:
            case None:
                return
            case Move():
                self._land(effect.position, effect.mode)
            case Change():
                self.replace(
                    effect.text,
                    effect.start,
                    effect.end,
                    maintain_selection_offset=False,
                )
                self._land(effect.position, effect.mode)

    def _rewind(self, history: History) -> None:
        self.undo() if history is History.UNDO else self.redo()
        self._settle()

    def _land(self, position: Position, mode: Mode) -> None:
        self.move_cursor(position.cursor)
        self._to_end = position.to_end
        self._switch(mode)

    def _end_insert(self) -> None:
        self._switch(Mode.NORMAL)
        self._settle()

    def _settle(self) -> None:
        """Back onto a character, and no longer hugging a line end the cursor
        was moved away from."""
        self.move_cursor(clamped(self._lines(), self.cursor_location))
        self._to_end = False

    def _switch(self, mode: Mode) -> None:
        if mode is self._mode:
            return
        self._mode = mode
        self._show(mode)
        # so an insert session undoes as one edit, not character by character
        self.history.checkpoint()

    def _show(self, mode: Mode) -> None:
        self.border_title = mode.name
        self.theme = _CURSORS[mode].name

    def _lines(self) -> list[str]:
        document = self.document
        return [document.get_line(row) for row in range(document.line_count)]
