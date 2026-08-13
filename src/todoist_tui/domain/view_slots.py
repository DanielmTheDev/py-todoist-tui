from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ViewSlots:
    """The keys that jump straight to a view, and which view opens on startup.

    Both sides hold a `View.key`, so a target that no longer exists resolves to
    nothing rather than to the wrong view. `startup` is independent of `by_key`: a
    view can open on launch without owning a key, and owning one says nothing about
    launching. Insertion order is kept — it is the order the slots are listed in.
    """

    by_key: Mapping[str, str] = field(default_factory=dict[str, str])
    startup: str | None = None

    def view_key_for(self, key: str) -> str | None:
        return self.by_key.get(key)

    def key_for(self, view_key: str) -> str | None:
        return next((k for k, v in self.by_key.items() if v == view_key), None)

    def assign(self, key: str, view_key: str) -> "ViewSlots":
        """Bind `key` to a view, dropping whatever either side held before — a view
        shows one badge, so it owns at most one key."""
        kept = {k: v for k, v in self.by_key.items() if k != key and v != view_key}
        return ViewSlots({**kept, key: view_key}, self.startup)

    def clear(self, key: str) -> "ViewSlots":
        if key not in self.by_key:
            return self
        return ViewSlots(
            {k: v for k, v in self.by_key.items() if k != key}, self.startup
        )

    def with_startup(self, view_key: str | None) -> "ViewSlots":
        return ViewSlots(self.by_key, view_key)
