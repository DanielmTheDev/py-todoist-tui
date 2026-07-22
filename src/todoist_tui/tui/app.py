from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.widgets import DataTable, Static

from todoist_tui.application.complete import complete_task
from todoist_tui.application.today import TodayRow, load_today
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId

_COLUMNS = ("", "Time", "Task", "Project")  # priority dot needs no header
_PRIORITY_DOTS = {Priority.P1: "🔴", Priority.P2: "🟠", Priority.P3: "🔵"}


class TodoistApp(App[None]):
    """Shows the tasks due today as a row-highlighted table on startup."""

    BINDINGS: ClassVar[list[BindingType]] = [("e", "complete", "Complete")]

    def __init__(self, repo: TaskRepository) -> None:
        super().__init__()
        self._repo = repo

    def compose(self) -> ComposeResult:
        yield Static("Loading…", id="status")
        yield DataTable[object]()

    async def on_mount(self) -> None:
        table = self.query_one(DataTable[object])
        table.cursor_type = "row"
        table.add_columns(*_COLUMNS)
        await self._reload()

    def action_complete(self) -> None:
        table = self.query_one(DataTable[object])
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        task_id = TaskId(str(row_key.value))
        table.remove_row(row_key)  # optimistic: drop it now, sync in the background
        self._set_status(_count_status(table.row_count))
        self._complete(task_id)

    @work
    async def _complete(self, task_id: TaskId) -> None:
        try:
            await complete_task(self._repo, task_id)
        except Exception as error:  # command rejected: resync, then report
            await self._reload()
            self._set_status(f"Failed to complete task: {error}")

    async def _reload(self) -> None:
        try:
            rows = await load_today(self._repo)
        except Exception as error:  # surface any load failure to the user
            self._set_status(f"Failed to load tasks: {error}")
            return
        self._render(rows)

    def _render(self, rows: list[TodayRow]) -> None:
        table = self.query_one(DataTable[object])
        table.clear()
        for row in rows:
            table.add_row(
                _priority_dot(row.priority),
                _format_time(row),
                row.content,
                Text(row.project_name, style="dim") if row.project_name else "",
                key=str(row.id),
            )
        self._set_status(_count_status(len(rows)))

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)


def _count_status(count: int) -> str:
    return "No tasks due today" if count == 0 else f"{count} task(s) due today"


def _priority_dot(priority: Priority) -> str:
    return _PRIORITY_DOTS.get(priority, "")  # P4 (default) stays blank


def _format_time(row: TodayRow) -> str:
    if row.due is None or row.due.time is None:
        return ""
    return row.due.time.strftime("%H:%M")
