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

    async def inbox(self) -> list[Task]:
        projects = await self._client.projects()
        inbox = next((p for p in projects if p.get("inbox_project")), None)
        if inbox is None:
            raise LookupError("no inbox project found")
        records = await self._client.tasks_in_project(str(inbox["id"]))
        return [_to_task(record) for record in records]

    async def projects(self) -> list[Project]:
        return [
            Project(id=str(record["id"]), name=str(record["name"]))
            for record in await self._client.projects()
        ]

    async def complete(self, task_id: TaskId) -> None:
        await self._client.close_item(str(task_id))


def _to_task(record: dict[str, Any]) -> Task:
    due = record.get("due")
    return Task(
        id=TaskId(str(record["id"])),
        content=str(record["content"]),
        priority=Priority.from_api(int(record["priority"])),
        due=Due.from_api(due) if due else None,
        project_id=str(record["project_id"]),
    )
