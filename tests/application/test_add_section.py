import pytest

from tests.application.test_duplicate import FakeRepository
from todoist_tui.application.add_section import add_section
from todoist_tui.domain.section import Section


def _repo(sections: list[Section]) -> FakeRepository:
    return FakeRepository([], sections, {})


@pytest.mark.anyio
async def test_add_section_creates_it_at_the_end_without_reordering() -> None:
    sections = [Section(id="a", project_id="9", name="A", order=1)]
    repo = _repo(sections)

    await add_section(repo, "9", "Backlog", sections, None, temp_id="t0")

    (plan,) = repo.applied
    assert (plan.projects, plan.tasks) == ((), ())
    (created,) = plan.sections
    assert (created.temp_id, created.name, created.project_ref, created.order) == (
        "t0",
        "Backlog",
        "9",
        2,
    )
    assert repo.reordered_sections == []


@pytest.mark.anyio
async def test_add_section_renumbers_the_sections_it_pushes_down() -> None:
    sections = [
        Section(id="a", project_id="9", name="A", order=1),
        Section(id="b", project_id="9", name="B", order=2),
    ]
    repo = _repo(sections)

    await add_section(repo, "9", "Backlog", sections, "a", temp_id="t0")

    assert repo.reordered_sections == [[("b", 3)]]
    assert repo.applied[0].sections[0].order == 2


@pytest.mark.anyio
async def test_add_section_ignores_other_projects_sections() -> None:
    sections = [
        Section(id="a", project_id="9", name="A", order=1),
        Section(id="z", project_id="7", name="Z", order=1),
    ]
    repo = _repo(sections)

    await add_section(repo, "9", "Backlog", sections, None, temp_id="t0")

    assert repo.applied[0].sections[0].order == 2
    assert repo.reordered_sections == []


@pytest.mark.anyio
async def test_add_section_names_its_own_temp_id_when_none_is_given() -> None:
    repo = _repo([])

    await add_section(repo, "9", "Backlog", [], None)

    assert repo.applied[0].sections[0].temp_id
