from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from todoist_tui.application.views import View
from todoist_tui.domain.view_slots import ViewSlots
from todoist_tui.tui.screens.scrolling import PickList

_HINT = "ctrl+b bind key · ctrl+s startup · enter open · esc close"

_SIGILS = {"project": "#", "filter": "⚑"}


@dataclass(frozen=True, slots=True)
class ViewsOutcome:
    """What the Views screen leaves behind: the edited slots, and the view to open.

    `jump` is None when the screen was merely closed — the slots may still have
    changed, so the caller persists them either way.
    """

    slots: ViewSlots
    jump: View | None


class ViewsScreen(ModalScreen[ViewsOutcome]):
    """Every view in one list: open one, or bind it to a key that jumps straight here.

    Transient like the arrange screen — it edits an immutable `ViewSlots` and hands
    it back, so it never touches the store itself. `taken` maps each key the app
    already binds to what that key does, so a clash can be refused by name.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    ViewsScreen {
        align: center middle;
    }
    ViewsScreen Input {
        width: 60%;
        max-width: 80;
        border: round $primary;
    }
    ViewsScreen OptionList {
        width: 60%;
        max-width: 80;
        border: round $primary;
    }
    ViewsScreen Static {
        width: 60%;
        max-width: 80;
        color: $text-muted;
    }
    """

    def __init__(
        self, views: list[View], slots: ViewSlots, taken: Mapping[str, str]
    ) -> None:
        super().__init__()
        self._views = views
        self._slots = slots
        self._taken = taken
        self._query = ""
        self._capturing: View | None = None  # the view awaiting a key, if any
        self._visible = self._matches()

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type to filter…")
        yield PickList(*(self._option(v) for v in self._visible))
        yield Static(_HINT, id="views-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_key(self, event: events.Key) -> None:
        """Keys are handled here rather than as bindings: while a key is being
        captured, escape must cancel the capture instead of closing the screen."""
        if self._capturing is not None:
            self._capture(event)
            event.stop()
            event.prevent_default()
            return
        if event.key == "escape":
            self.dismiss(ViewsOutcome(self._slots, None))
        elif event.key == "ctrl+b":
            self._start_capture()
        elif event.key == "ctrl+s":
            self._toggle_startup()
        else:
            return
        event.stop()
        event.prevent_default()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._query = event.value
        self._repaint()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._open()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._open()

    def action_cursor_down(self) -> None:
        self.query_one(OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(OptionList).action_cursor_up()

    def _open(self) -> None:
        view = self._highlighted()
        if view is None:  # nothing matches what was typed: stay open
            return
        self.dismiss(ViewsOutcome(self._slots, view))

    def _start_capture(self) -> None:
        view = self._highlighted()
        if view is None:
            return
        self._capturing = view
        # the Input would otherwise swallow the captured character
        self.set_focus(None)
        self._hint(f"press a key for {view.title} · backspace unbind · esc cancel")

    def _capture(self, event: events.Key) -> None:
        view = self._capturing
        if view is None:  # unreachable: only called while capturing
            return
        if event.key == "escape":
            self._end_capture(_HINT)
        elif event.key == "backspace":
            key = self._slots.key_for(view.key)
            self._slots = self._slots if key is None else self._slots.clear(key)
            self._end_capture(f"{view.title} unbound")
        elif event.key in self._taken:  # `taken` is keyed by Textual's own key names
            self._hint(
                f"{event.character or event.key} is already {self._taken[event.key]}"
            )
        elif event.character is not None and event.character.isprintable():
            # the character, not event.key: a `.` bound as "full_stop" would badge
            # the row with that name
            self._slots = self._slots.assign(event.character, view.key)
            self._end_capture(f"{view.title} → {event.character}")
        # anything else types nothing, so the capture keeps waiting

    def _end_capture(self, hint: str) -> None:
        self._capturing = None
        self._hint(hint)
        self.query_one(Input).focus()
        self._repaint()

    def _toggle_startup(self) -> None:
        view = self._highlighted()
        if view is None:
            return
        opens_here = self._slots.startup == view.key
        self._slots = self._slots.with_startup(None if opens_here else view.key)
        self._repaint()

    def _highlighted(self) -> View | None:
        index = self.query_one(OptionList).highlighted
        return None if index is None else self._visible[index]

    def _matches(self) -> list[View]:
        """The views the typed text matches, slotted ones first — a key's badge is
        easiest to find where the keys cluster."""
        query = self._query.casefold()
        found = [v for v in self._views if query in v.title.casefold()]
        by_key = {v.key: v for v in found}
        bound = [by_key[k] for k in self._slots.by_key.values() if k in by_key]
        return bound + [v for v in found if v not in bound]

    def _repaint(self) -> None:
        """Rebuild the list, keeping the highlight on the view it was on."""
        was = self._highlighted()
        self._visible = self._matches()
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([self._option(v) for v in self._visible])
        if not self._visible:
            return
        options.highlighted = next(
            (i for i, v in enumerate(self._visible) if v.key == (was and was.key)), 0
        )

    def _option(self, view: View) -> Option:
        # Text, not a plain string: a view name or a `[w]` badge would otherwise be
        # read as markup and painted as nothing
        return Option(self._label(view))

    def _label(self, view: View) -> Text:
        key = self._slots.key_for(view.key)
        label = Text()
        if self._slots.startup == view.key:
            label.append("★ ")
        if key is not None:
            label.append(f"[{key}] ")
        sigil = _sigil(view)
        if sigil:
            label.append(f"{sigil} ", style="dim")  # the kind recedes, the name leads
        label.append(view.title)
        return label

    def _hint(self, text: str) -> None:
        self.query_one("#views-hint", Static).update(Text(text))


def _sigil(view: View) -> str:
    """The kind marker a title carries — two views can share a name. `#` is
    Todoist's own project sigil, so it reads without being learnt. Today and Inbox
    are one of a kind, so they carry nothing."""
    prefix, _, _ = view.key.partition(":")
    return _SIGILS.get(prefix, "")
