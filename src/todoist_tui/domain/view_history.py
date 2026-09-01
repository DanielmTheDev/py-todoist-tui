from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Visit:
    """One place the user has been.

    Held as plain keys rather than a `View`: a view is rebuilt from its key, two
    builds of the same one are never equal (they carry a fetch closure), and a
    section shares its project's key — so where it landed is remembered beside it.
    `cursor_id` is the task the cursor sat on when the visit was left.
    """

    view_key: str
    land_section: str | None = None
    cursor_id: str | None = None

    def same_place(self, other: "Visit") -> bool:
        return (self.view_key, self.land_section) == (
            other.view_key,
            other.land_section,
        )


@dataclass(frozen=True, slots=True)
class ViewHistory:
    """The trail of views walked, and where along it the user stands.

    Browser semantics: visiting drops whatever was ahead, and `index` addresses
    the visit on screen. Empty until the first view opens.
    """

    visits: tuple[Visit, ...] = ()
    index: int = 0

    @property
    def current(self) -> Visit | None:
        return self.visits[self.index] if self.visits else None

    def visit(self, visit: Visit) -> "ViewHistory":
        """Walk to `visit`, forgetting what lay ahead — re-opening the view already
        on screen stays put, so leaving it again costs one press, not two."""
        here = self.current
        if here is not None and here.same_place(visit):
            return self
        kept = self.visits[: self.index + 1] if self.visits else ()
        return ViewHistory((*kept, visit), len(kept))

    def with_cursor(self, cursor_id: str | None) -> "ViewHistory":
        """Note where the cursor rests, so returning here puts it back."""
        here = self.current
        if here is None:
            return self
        stamped = replace(here, cursor_id=cursor_id)
        return ViewHistory(
            (*self.visits[: self.index], stamped, *self.visits[self.index + 1 :]),
            self.index,
        )

    def back(self) -> "ViewHistory | None":
        return None if self.index <= 0 else replace(self, index=self.index - 1)

    def forward(self) -> "ViewHistory | None":
        if self.index + 1 >= len(self.visits):
            return None
        return replace(self, index=self.index + 1)

    def without(self, view_key: str) -> "ViewHistory":
        """Forget every visit to a view that is gone, staying where we stand — the
        next step then skips it whichever way it goes. The current visit is on
        screen, so it is never the one being dropped."""
        kept = [v for v in self.visits if v.view_key != view_key]
        dropped_before = sum(
            1 for v in self.visits[: self.index] if v.view_key == view_key
        )
        return ViewHistory(tuple(kept), self.index - dropped_before)
