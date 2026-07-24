import datetime
import sqlite3
from pathlib import Path

import pytest

from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.store.sqlite import SqliteSnapshotCache


def _snapshot(sync_token: str = "tok-1") -> Snapshot:
    return Snapshot(
        filters=[
            Filter(id="f1", name="Priority 1", query="p1 & overdue", order=1),
            Filter(id="f2", name="Work today", query="#Work & today", order=2),
        ],
        projects=[
            Project(id="220", name="Eingang", is_inbox=True),
            Project(id="9", name="Work"),
        ],
        tasks=[
            Task(
                id=TaskId("a"),
                content="dated",
                priority=Priority.P1,
                due=Due(
                    date=datetime.date(2026, 7, 22),
                    time=datetime.time(9, 30),
                    is_recurring=True,
                ),
                project_id="220",
            ),
            Task(
                id=TaskId("b"),
                content="no due",
                priority=Priority.P4,
                due=None,
                project_id="9",
            ),
        ],
        sync_token=sync_token,
    )


@pytest.mark.anyio
async def test_load_returns_none_when_file_absent(tmp_path: Path) -> None:
    cache = SqliteSnapshotCache(tmp_path / "cache.sqlite3")

    assert await cache.load() is None


@pytest.mark.anyio
async def test_load_returns_none_when_file_has_no_schema(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    path.touch()
    cache = SqliteSnapshotCache(path)

    assert await cache.load() is None


@pytest.mark.anyio
async def test_load_returns_none_when_meta_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    await SqliteSnapshotCache(path).save(_snapshot())
    conn = sqlite3.connect(path)  # simulate a crash mid-write: rows lost
    try:
        conn.execute("DELETE FROM meta")
        conn.commit()
    finally:
        conn.close()

    assert await SqliteSnapshotCache(path).load() is None


@pytest.mark.anyio
async def test_load_returns_none_when_filters_table_missing(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"  # legacy cache written before F3
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "CREATE TABLE meta (sync_token TEXT NOT NULL);"
            "CREATE TABLE projects (id TEXT, name TEXT, is_inbox INTEGER);"
            "CREATE TABLE tasks (id TEXT, content TEXT, priority INTEGER,"
            " due_date TEXT, due_time TEXT, due_recurring INTEGER, project_id TEXT);"
            "INSERT INTO meta (sync_token) VALUES ('tok');"
        )
        conn.commit()
    finally:
        conn.close()

    assert await SqliteSnapshotCache(path).load() is None


@pytest.mark.anyio
async def test_save_then_load_roundtrips_the_snapshot(tmp_path: Path) -> None:
    cache = SqliteSnapshotCache(tmp_path / "cache.sqlite3")
    original = _snapshot()

    await cache.save(original)
    loaded = await cache.load()

    assert loaded == original


@pytest.mark.anyio
async def test_save_creates_parent_directory(tmp_path: Path) -> None:
    cache = SqliteSnapshotCache(tmp_path / "nested" / "dir" / "cache.sqlite3")

    await cache.save(_snapshot())

    assert (await cache.load()) is not None


@pytest.mark.anyio
async def test_second_save_replaces_previous_rows(tmp_path: Path) -> None:
    cache = SqliteSnapshotCache(tmp_path / "cache.sqlite3")

    await cache.save(_snapshot(sync_token="old"))
    smaller = Snapshot(
        projects=[Project(id="9", name="Work")],
        tasks=[],
        sync_token="new",
    )
    await cache.save(smaller)

    assert (await cache.load()) == smaller
