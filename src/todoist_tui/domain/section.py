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


def section_insert_plan(
    sections: list[Section], after_id: str | None
) -> tuple[int, list[tuple[str, int]]]:
    """Where a new section goes in `sections` and how the rest renumber.

    Returns its `section_order` and the `(id, order)` writes the existing
    sections need, omitting the ones already sitting right. The whole run is
    renumbered from 1 rather than the tail nudged along: Todoist will happily
    report two sections at the same `section_order`, so a run that is not
    already a clean sequence has no single free slot to insert into.

    `after_id` names the section the new one follows; None, or an id the sync
    has already taken away, appends it to the end.
    """
    run = sorted_sections(sections)
    at = next((i for i, section in enumerate(run) if section.id == after_id), None)
    slot = len(run) if at is None else at + 1
    moved = [
        (section.id, order)
        for index, section in enumerate(run)
        if (order := index + 1 if index < slot else index + 2) != section.order
    ]
    return slot + 1, moved
