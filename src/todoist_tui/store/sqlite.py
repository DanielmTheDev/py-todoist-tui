import asyncio
import datetime
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from todoist_tui.domain.arrange import Arrangement
from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.filter import Filter
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.section import Section
from todoist_tui.domain.task import Task, TaskId

# Dropped and recreated on every save: the snapshot is disposable and fully
# rewritten each time, so this also migrates any older column layout in place.
_SCHEMA = """
DROP TABLE IF EXISTS meta;
DROP TABLE IF EXISTS projects;
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS filters;
DROP TABLE IF EXISTS sections;
CREATE TABLE meta (sync_token TEXT NOT NULL);
CREATE TABLE projects (id TEXT, name TEXT, is_inbox INTEGER, child_order INTEGER);
CREATE TABLE tasks (
    id TEXT, content TEXT, priority INTEGER,
    due_date TEXT, due_time TEXT, due_recurring INTEGER,
    due_string TEXT, due_lang TEXT, project_id TEXT,
    section_id TEXT, labels TEXT, description TEXT, deadline_date TEXT
);
CREATE TABLE filters (
    id TEXT, name TEXT, query TEXT, item_order INTEGER
);
CREATE TABLE sections (
    id TEXT, project_id TEXT, name TEXT, section_order INTEGER
);
"""


class SqliteSnapshotCache:
    """Persists the latest /sync snapshot to SQLite for offline cold starts.

    `sqlite3` is blocking, so every DB touch runs in a worker thread.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    async def load(self) -> Snapshot | None:
        return await asyncio.to_thread(self._load)

    async def save(self, snapshot: Snapshot) -> None:
        await asyncio.to_thread(self._save, snapshot)

    def _load(self) -> Snapshot | None:
        if not self._path.is_file():
            return None
        with closing(sqlite3.connect(self._path)) as conn:
            try:
                token_row = conn.execute("SELECT sync_token FROM meta").fetchone()
                if token_row is None:  # schema present but never fully written
                    return None
                projects = [
                    Project(id=pid, name=name, is_inbox=bool(is_inbox), order=order)
                    for pid, name, is_inbox, order in conn.execute(
                        "SELECT id, name, is_inbox, child_order FROM projects"
                    )
                ]
                tasks = [
                    _row_to_task(row)
                    for row in conn.execute(
                        "SELECT id, content, priority, due_date, due_time,"
                        " due_recurring, due_string, due_lang, project_id, section_id,"
                        " labels, description, deadline_date FROM tasks"
                    )
                ]
                filters = [
                    Filter(id=fid, name=name, query=query, order=order)
                    for fid, name, query, order in conn.execute(
                        "SELECT id, name, query, item_order FROM filters"
                    )
                ]
                sections = [
                    Section(id=sid, project_id=pid, name=name, order=order)
                    for sid, pid, name, order in conn.execute(
                        "SELECT id, project_id, name, section_order FROM sections"
                    )
                ]
            except sqlite3.OperationalError:  # missing/legacy schema: treat as cold
                return None
        return Snapshot(
            projects=projects,
            tasks=tasks,
            sync_token=token_row[0],
            filters=filters,
            sections=sections,
        )

    def _save(self, snapshot: Snapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as conn:
            conn.executescript(_SCHEMA)  # drops + recreates the four tables
            conn.execute(
                "INSERT INTO meta (sync_token) VALUES (?)", (snapshot.sync_token,)
            )
            conn.executemany(
                "INSERT INTO projects (id, name, is_inbox, child_order)"
                " VALUES (?, ?, ?, ?)",
                [(p.id, p.name, int(p.is_inbox), p.order) for p in snapshot.projects],
            )
            conn.executemany(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [_task_to_row(task) for task in snapshot.tasks],
            )
            conn.executemany(
                "INSERT INTO filters (id, name, query, item_order) VALUES (?, ?, ?, ?)",
                [(f.id, f.name, f.query, f.order) for f in snapshot.filters],
            )
            conn.executemany(
                "INSERT INTO sections (id, project_id, name, section_order)"
                " VALUES (?, ?, ?, ?)",
                [(s.id, s.project_id, s.name, s.order) for s in snapshot.sections],
            )
            conn.commit()


_ARRANGEMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS arrangement (
    view_key TEXT PRIMARY KEY, spec TEXT NOT NULL
);
"""


class SqliteArrangementStore:
    """Persists each view's group/sort arrangement in SQLite (its own table)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def get(self, view_key: str) -> Arrangement:
        return await asyncio.to_thread(self._get, view_key)

    async def save(self, view_key: str, arrangement: Arrangement) -> None:
        await asyncio.to_thread(self._save, view_key, arrangement)

    def _get(self, view_key: str) -> Arrangement:
        if not self._path.is_file():
            return Arrangement()
        with closing(sqlite3.connect(self._path)) as conn:
            try:
                row = conn.execute(
                    "SELECT spec FROM arrangement WHERE view_key = ?", (view_key,)
                ).fetchone()
            except sqlite3.OperationalError:  # table not created yet
                return Arrangement()
        if row is None:
            return Arrangement()
        try:  # a corrupt or legacy spec falls back to the empty default
            return Arrangement.from_dict(json.loads(row[0]))
        except (ValueError, KeyError, TypeError):
            return Arrangement()

    def _save(self, view_key: str, arrangement: Arrangement) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as conn:
            conn.executescript(_ARRANGEMENT_SCHEMA)
            conn.execute(
                "INSERT INTO arrangement (view_key, spec) VALUES (?, ?)"
                " ON CONFLICT(view_key) DO UPDATE SET spec = excluded.spec",
                (view_key, json.dumps(arrangement.to_dict())),
            )
            conn.commit()


def _task_to_row(
    task: Task,
) -> tuple[
    str,
    str,
    int,
    str | None,
    str | None,
    int | None,
    str | None,
    str | None,
    str,
    str | None,
    str,
    str,
    str | None,
]:
    due = task.due
    deadline = task.deadline
    return (
        task.id,
        task.content,
        task.priority.value,
        due.date.isoformat() if due else None,
        due.time.isoformat() if due and due.time else None,
        int(due.is_recurring) if due else None,
        due.string if due else None,
        due.lang if due else None,
        task.project_id,
        task.section_id,
        json.dumps(list(task.labels)),
        task.description,
        deadline.date.isoformat() if deadline else None,
    )


def _row_to_task(
    row: tuple[
        str,
        str,
        int,
        str | None,
        str | None,
        int | None,
        str | None,
        str | None,
        str,
        str | None,
        str | None,
        str | None,
        str | None,
    ],
) -> Task:
    (
        tid,
        content,
        priority,
        due_date,
        due_time,
        due_recurring,
        due_string,
        due_lang,
        project_id,
        section_id,
        labels,
        description,
        deadline_date,
    ) = row
    due = None
    if due_date is not None:
        due = Due(
            date=datetime.date.fromisoformat(due_date),
            time=datetime.time.fromisoformat(due_time) if due_time else None,
            is_recurring=bool(due_recurring),
            string=due_string,
            lang=due_lang,
        )
    return Task(
        id=TaskId(tid),
        content=content,
        priority=Priority(priority),
        due=due,
        project_id=project_id,
        section_id=section_id,
        labels=tuple(json.loads(labels)) if labels else (),
        description=description or "",
        deadline=Deadline(date=datetime.date.fromisoformat(deadline_date))
        if deadline_date
        else None,
    )
