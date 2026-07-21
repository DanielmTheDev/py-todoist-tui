from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

from todoist_tui.application.today import TodayRow, load_today
from todoist_tui.domain.repository import TaskRepository

_COLUMNS = ("Priority", "Time", "Task", "Project")


class TodoistApp(App[None]):
    """Shows the tasks due today in a table on startup."""

    def __init__(self, repo: TaskRepository) -> None:
        super().__init__()
        self._repo = repo

    def compose(self) -> ComposeResult:
        yield Static("Loading…", id="status")
        yield DataTable[str]()

    async def on_mount(self) -> None:
        self.query_one(DataTable[str]).add_columns(*_COLUMNS)
        try:
            rows = await load_today(self._repo)
        except Exception as error:  # surface any load failure to the user
            self._set_status(f"Failed to load tasks: {error}")
            return
        self._render(rows)

    def _render(self, rows: list[TodayRow]) -> None:
        if not rows:
            self._set_status("No tasks due today")
            return
        table = self.query_one(DataTable[str])
        for row in rows:
            table.add_row(
                row.priority.label,
                _format_time(row),
                row.content,
                row.project_name or "",
            )
        self._set_status(f"{len(rows)} task(s) due today")

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)


def _format_time(row: TodayRow) -> str:
    if row.due is None or row.due.time is None:
        return ""
    return row.due.time.strftime("%H:%M")
