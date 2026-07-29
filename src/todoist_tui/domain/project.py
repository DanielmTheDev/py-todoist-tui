from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    is_inbox: bool = False
    order: int = 0


def sorted_projects(projects: list[Project]) -> list[Project]:
    """Projects in the account's sidebar order (Todoist `child_order`)."""
    return sorted(projects, key=lambda p: p.order)
