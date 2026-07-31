from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    project_id: str
    name: str
    order: int = 0


def sorted_sections(sections: list[Section]) -> list[Section]:
    """Sections in their project's display order (Todoist `section_order`)."""
    return sorted(sections, key=lambda s: s.order)
