from enum import Enum


class Priority(Enum):
    """Task urgency. Todoist's API uses 4 (highest) .. 1 (none); we expose P1..P4."""

    P1 = 4
    P2 = 3
    P3 = 2
    P4 = 1

    @classmethod
    def from_api(cls, value: int) -> "Priority":
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"unknown Todoist priority: {value}") from None

    @property
    def label(self) -> str:
        return self.name
