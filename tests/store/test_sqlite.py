import datetime
import sqlite3
from pathlib import Path

import pytest

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId
from todoist_tui.store.sqlite import SqliteSnapshotCache


def _snapshot(sync_token: str = "tok-1") -> Snapshot:
    return Snapshot(
        filters=[
            Filter(id="f1", name="Priority 1", query="p1 & overdue", order=1),
            Filter(id="f2", name="Work today", query="#Work & today", order=2),
        ],
        projects=[
            Project(id="220", name="Eingang", is_inbox=True, order=0),
            Project(id="9", name="Work", order=5),
        ],
        sections=[
            Section(id="s1", project_id="9", name="Planning", order=1),
            Section(id="s2", project_id="9", name="In progress", order=2),
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
                    string="every day at 9:30",
                    lang="en",
                ),
                project_id="9",
                section_id="s1",
                labels=("home", "urgent"),
                description="water them all",
                deadline=Deadline(date=datetime.date(2026, 8, 15)),
            ),
            Task(
                id=TaskId("b"),
                content="no due",
                priority=Priority.P4,
                due=None,
                project_id="9",
                parent_id="a",
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
    assert loaded is not None
    assert loaded.tasks[0].labels == ("home", "urgent")
    assert loaded.tasks[0].description == "water them all"
    assert loaded.tasks[0].section_id == "s1"
    assert loaded.tasks[0].deadline == Deadline(date=datetime.date(2026, 8, 15))
    assert loaded.tasks[0].parent_id is None
    assert loaded.tasks[1].section_id is None
    assert loaded.tasks[1].deadline is None
    assert loaded.tasks[1].parent_id == "a"
    assert [(s.id, s.name, s.order) for s in loaded.sections] == [
        ("s1", "Planning", 1),
        ("s2", "In progress", 2),
    ]


@pytest.mark.anyio
async def test_save_migrates_a_legacy_tasks_schema(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"  # pre-labels cache: tasks has only 7 columns
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "CREATE TABLE meta (sync_token TEXT NOT NULL);"
            "CREATE TABLE projects (id TEXT, name TEXT, is_inbox INTEGER);"
            "CREATE TABLE tasks (id TEXT, content TEXT, priority INTEGER,"
            " due_date TEXT, due_time TEXT, due_recurring INTEGER, project_id TEXT);"
            "CREATE TABLE filters (id TEXT, name TEXT, query TEXT, item_order INTEGER);"
            "INSERT INTO meta (sync_token) VALUES ('old');"
        )
        conn.commit()
    finally:
        conn.close()

    await SqliteSnapshotCache(path).save(_snapshot())  # must not raise on 8 values

    assert await SqliteSnapshotCache(path).load() == _snapshot()


@pytest.mark.anyio
async def test_load_returns_none_when_tasks_lack_labels_column(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"  # legacy cache written before labels existed
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "CREATE TABLE meta (sync_token TEXT NOT NULL);"
            "CREATE TABLE projects (id TEXT, name TEXT, is_inbox INTEGER);"
            "CREATE TABLE tasks (id TEXT, content TEXT, priority INTEGER,"
            " due_date TEXT, due_time TEXT, due_recurring INTEGER, project_id TEXT);"
            "CREATE TABLE filters (id TEXT, name TEXT, query TEXT, item_order INTEGER);"
            "INSERT INTO meta (sync_token) VALUES ('tok');"
        )
        conn.commit()
    finally:
        conn.close()

    assert await SqliteSnapshotCache(path).load() is None


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
