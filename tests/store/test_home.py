from pathlib import Path

import pytest

from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.store.sqlite import SqliteHomeViewStore, SqliteSnapshotCache


@pytest.mark.anyio
async def test_get_returns_none_when_absent(tmp_path: Path) -> None:
    store = SqliteHomeViewStore(tmp_path / "cache.sqlite3")

    assert await store.get() is None


@pytest.mark.anyio
async def test_save_then_get_round_trips(tmp_path: Path) -> None:
    store = SqliteHomeViewStore(tmp_path / "cache.sqlite3")

    await store.save("project:9")

    assert await store.get() == "project:9"


@pytest.mark.anyio
async def test_save_overwrites_previous_home(tmp_path: Path) -> None:
    store = SqliteHomeViewStore(tmp_path / "cache.sqlite3")

    await store.save("project:9")
    await store.save("filter:f1")

    assert await store.get() == "filter:f1"


@pytest.mark.anyio
async def test_home_survives_a_snapshot_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    await SqliteHomeViewStore(path).save("inbox")
    await SqliteSnapshotCache(path).save(
        Snapshot(projects=[Project(id="9", name="Work")], tasks=[], sync_token="tok")
    )

    assert await SqliteHomeViewStore(path).get() == "inbox"


@pytest.mark.anyio
async def test_save_creates_parent_directory(tmp_path: Path) -> None:
    store = SqliteHomeViewStore(tmp_path / "nested" / "dir" / "cache.sqlite3")

    await store.save("today")

    assert await store.get() == "today"
