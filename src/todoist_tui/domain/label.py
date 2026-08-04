from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Label:
    id: str
    name: str
    order: int = 0
