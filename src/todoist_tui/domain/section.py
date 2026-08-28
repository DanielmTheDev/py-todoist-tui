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


def sections_by_project(sections: list[Section]) -> dict[str, list[Section]]:
    """Each project's sections in display order, keyed by project id."""
    grouped: dict[str, list[Section]] = {}
    for section in sorted_sections(sections):
        grouped.setdefault(section.project_id, []).append(section)
    return grouped
