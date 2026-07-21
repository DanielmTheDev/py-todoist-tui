from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.widgets import DataTable, Static

from todoist_tui.application.complete import complete_task
from todoist_tui.application.today import TodayRow, load_today
from todoist_tui.domain.repository import TaskRepository
from todoist_tui.domain.task import TaskId

_COLUMNS = ("Priority", "Time", "Task", "Project")


class TodoistApp(App[None]):
    """Shows the tasks due today in a table on startup."""

    BINDINGS: ClassVar[list[BindingType]] = [("e", "complete", "Complete")]

    def __init__(self, repo: TaskRepository) -> None:
        super().__init__()
        self._repo = repo

    def compose(self) -> ComposeResult:
        yield Static("Loading…", id="status")
        yield DataTable[str]()

    async def on_mount(self) -> None:
        self.query_one(DataTable[str]).add_columns(*_COLUMNS)
        await self._reload()

    def action_complete(self) -> None:
        table = self.query_one(DataTable[str])
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
        table = self.query_one(DataTable[str])
        table.clear()
        for row in rows:
            table.add_row(
                row.priority.label,
                _format_time(row),
                row.content,
                row.project_name or "",
                key=str(row.id),
            )
        self._set_status(_count_status(len(rows)))

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)


def _count_status(count: int) -> str:
    return "No tasks due today" if count == 0 else f"{count} task(s) due today"


def _format_time(row: TodayRow) -> str:
    if row.due is None or row.due.time is None:
        return ""
    return row.due.time.strftime("%H:%M")
