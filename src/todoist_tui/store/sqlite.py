import asyncio
import datetime
import sqlite3
from contextlib import closing
from pathlib import Path

from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.repository import Snapshot
from todoist_tui.domain.task import Task, TaskId

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (sync_token TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (id TEXT, name TEXT, is_inbox INTEGER);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT, content TEXT, priority INTEGER,
    due_date TEXT, due_time TEXT, due_recurring INTEGER, project_id TEXT
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
            except sqlite3.OperationalError:  # file exists but no schema yet
                return None
            if token_row is None:  # schema present but never fully written
                return None
            projects = [
                Project(id=pid, name=name, is_inbox=bool(is_inbox))
                for pid, name, is_inbox in conn.execute(
                    "SELECT id, name, is_inbox FROM projects"
                )
            ]
            tasks = [_row_to_task(row) for row in conn.execute("SELECT * FROM tasks")]
        return Snapshot(projects=projects, tasks=tasks, sync_token=token_row[0])

    def _save(self, snapshot: Snapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as conn:
            conn.executescript(_SCHEMA)
            conn.execute("DELETE FROM meta")
            conn.execute("DELETE FROM projects")
            conn.execute("DELETE FROM tasks")
            conn.execute(
                "INSERT INTO meta (sync_token) VALUES (?)", (snapshot.sync_token,)
            )
            conn.executemany(
                "INSERT INTO projects (id, name, is_inbox) VALUES (?, ?, ?)",
                [(p.id, p.name, int(p.is_inbox)) for p in snapshot.projects],
            )
            conn.executemany(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
                [_task_to_row(task) for task in snapshot.tasks],
            )
            conn.commit()


def _task_to_row(
    task: Task,
) -> tuple[str, str, int, str | None, str | None, int | None, str]:
    due = task.due
    return (
        task.id,
        task.content,
        task.priority.value,
        due.date.isoformat() if due else None,
        due.time.isoformat() if due and due.time else None,
        int(due.is_recurring) if due else None,
        task.project_id,
    )


def _row_to_task(
    row: tuple[str, str, int, str | None, str | None, int | None, str],
) -> Task:
    tid, content, priority, due_date, due_time, due_recurring, project_id = row
    due = None
    if due_date is not None:
        due = Due(
            date=datetime.date.fromisoformat(due_date),
            time=datetime.time.fromisoformat(due_time) if due_time else None,
            is_recurring=bool(due_recurring),
        )
    return Task(
        id=TaskId(tid),
        content=content,
        priority=Priority(priority),
        due=due,
        project_id=project_id,
    )
