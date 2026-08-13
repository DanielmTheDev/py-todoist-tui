import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.view_slots import ViewSlots
from todoist_tui.store.sqlite import SqliteSnapshotCache, SqliteViewSlotStore


@pytest.mark.anyio
async def test_get_returns_empty_slots_when_absent(tmp_path: Path) -> None:
    store = SqliteViewSlotStore(tmp_path / "cache.sqlite3")

    assert await store.get() == ViewSlots()


@pytest.mark.anyio
async def test_save_then_get_round_trips(tmp_path: Path) -> None:
    store = SqliteViewSlotStore(tmp_path / "cache.sqlite3")
    slots = ViewSlots().assign("w", "filter:f1").assign("b", "project:9")

    await store.save(slots)

    assert await store.get() == slots


@pytest.mark.anyio
async def test_saved_keys_keep_their_order(tmp_path: Path) -> None:
    store = SqliteViewSlotStore(tmp_path / "cache.sqlite3")

    await store.save(ViewSlots().assign("w", "filter:f1").assign("b", "project:9"))

    assert list((await store.get()).by_key) == ["w", "b"]


@pytest.mark.anyio
async def test_save_replaces_the_previous_slots(tmp_path: Path) -> None:
    store = SqliteViewSlotStore(tmp_path / "cache.sqlite3")

    await store.save(ViewSlots().assign("w", "filter:f1"))
    await store.save(ViewSlots().assign("b", "project:9"))

    assert await store.get() == ViewSlots().assign("b", "project:9")


@pytest.mark.anyio
async def test_startup_round_trips_without_any_key(tmp_path: Path) -> None:
    store = SqliteViewSlotStore(tmp_path / "cache.sqlite3")

    await store.save(ViewSlots().with_startup("project:9"))

    assert await store.get() == ViewSlots().with_startup("project:9")


@pytest.mark.anyio
async def test_dropping_startup_clears_the_stored_one(tmp_path: Path) -> None:
    store = SqliteViewSlotStore(tmp_path / "cache.sqlite3")

    await store.save(ViewSlots().with_startup("project:9"))
    await store.save(ViewSlots().with_startup(None))

    assert (await store.get()).startup is None


@pytest.mark.anyio
async def test_slots_survive_a_snapshot_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    await SqliteViewSlotStore(path).save(ViewSlots().assign("i", "inbox"))
    await SqliteSnapshotCache(path).save(
        Snapshot(projects=[Project(id="9", name="Work")], tasks=[], sync_token="tok")
    )

    assert await SqliteViewSlotStore(path).get() == ViewSlots().assign("i", "inbox")


@pytest.mark.anyio
async def test_save_creates_parent_directory(tmp_path: Path) -> None:
    store = SqliteViewSlotStore(tmp_path / "nested" / "dir" / "cache.sqlite3")

    await store.save(ViewSlots().with_startup("today"))

    assert await store.get() == ViewSlots().with_startup("today")


@pytest.mark.anyio
async def test_the_retired_home_table_is_dropped(tmp_path: Path) -> None:
    """The old single home key is not migrated — its table goes away with it."""
    path = tmp_path / "cache.sqlite3"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            "CREATE TABLE home (id INTEGER PRIMARY KEY CHECK (id = 1),"
            " view_key TEXT NOT NULL);"
            " INSERT INTO home (id, view_key) VALUES (1, 'filter:old');"
        )
        conn.commit()

    await SqliteViewSlotStore(path).save(ViewSlots().assign("w", "filter:f1"))

    with closing(sqlite3.connect(path)) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "home" not in tables
