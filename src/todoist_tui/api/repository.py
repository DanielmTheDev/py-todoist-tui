from typing import Any

from todoist_tui.api.client import TodoistClient
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.domain.project import Project
from todoist_tui.domain.task import Task, TaskId


class ApiTaskRepository:
    """Adapter binding the Todoist client to the domain `TaskRepository` port."""

    def __init__(self, client: TodoistClient) -> None:
        self._client = client

    async def today(self) -> list[Task]:
        return [_to_task(record) for record in await self._client.today_tasks()]

    async def projects(self) -> list[Project]:
        return [
            Project(id=str(record["id"]), name=str(record["name"]))
            for record in await self._client.projects()
        ]


def _to_task(record: dict[str, Any]) -> Task:
    due = record.get("due")
    return Task(
        id=TaskId(str(record["id"])),
        content=str(record["content"]),
        priority=Priority.from_api(int(record["priority"])),
        due=Due.from_api(due) if due else None,
        project_id=str(record["project_id"]),
    )
