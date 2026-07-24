from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Filter:
    """A saved Todoist filter: a named query evaluated server-side."""

    id: str
    name: str
    query: str
    order: int


def sorted_filters(filters: list[Filter]) -> list[Filter]:
    """Filters in the account's display order (Todoist `item_order`)."""
    return sorted(filters, key=lambda f: f.order)
