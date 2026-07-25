import sqlite3
from pathlib import Path

import pytest

from todoist_tui.domain.arrange import Arrangement, Field, SortKey
from todoist_tui.store.sqlite import SqliteArrangementStore


@pytest.mark.anyio
async def test_get_returns_empty_arrangement_when_absent(tmp_path: Path) -> None:
    store = SqliteArrangementStore(tmp_path / "cache.sqlite3")

    assert await store.get("today") == Arrangement()


@pytest.mark.anyio
async def test_save_then_get_round_trips(tmp_path: Path) -> None:
    store = SqliteArrangementStore(tmp_path / "cache.sqlite3")
    arrangement = Arrangement(
        group_by=(Field.PROJECT, Field.LABELS),
        sort_by=(SortKey(Field.DUE_DATE), SortKey(Field.PRIORITY, ascending=False)),
    )

    await store.save("today", arrangement)

    assert await store.get("today") == arrangement


@pytest.mark.anyio
async def test_arrangements_are_isolated_per_view(tmp_path: Path) -> None:
    store = SqliteArrangementStore(tmp_path / "cache.sqlite3")
    today = Arrangement(group_by=(Field.PRIORITY,))
    inbox = Arrangement(sort_by=(SortKey(Field.CONTENT),))

    await store.save("today", today)
    await store.save("inbox", inbox)

    assert await store.get("today") == today
    assert await store.get("inbox") == inbox


@pytest.mark.anyio
async def test_save_overwrites_previous_arrangement(tmp_path: Path) -> None:
    store = SqliteArrangementStore(tmp_path / "cache.sqlite3")

    await store.save("today", Arrangement(group_by=(Field.PROJECT,)))
    await store.save("today", Arrangement(group_by=(Field.LABELS,)))

    assert await store.get("today") == Arrangement(group_by=(Field.LABELS,))


@pytest.mark.anyio
@pytest.mark.parametrize("spec", ["not json", '{"group_by": ["gone_field"]}'])
async def test_get_tolerates_unreadable_spec(tmp_path: Path, spec: str) -> None:
    path = tmp_path / "cache.sqlite3"
    store = SqliteArrangementStore(path)
    await store.save("today", Arrangement(group_by=(Field.PROJECT,)))  # create table
    conn = sqlite3.connect(path)  # corrupt / legacy row the parser cannot read
    try:
        conn.execute(
            "UPDATE arrangement SET spec = ? WHERE view_key = 'today'", (spec,)
        )
        conn.commit()
    finally:
        conn.close()

    assert await store.get("today") == Arrangement()


@pytest.mark.anyio
async def test_save_creates_parent_directory(tmp_path: Path) -> None:
    store = SqliteArrangementStore(tmp_path / "nested" / "dir" / "cache.sqlite3")

    await store.save("today", Arrangement(group_by=(Field.PROJECT,)))

    assert await store.get("today") == Arrangement(group_by=(Field.PROJECT,))
