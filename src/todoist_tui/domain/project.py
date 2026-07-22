from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    is_inbox: bool = False
