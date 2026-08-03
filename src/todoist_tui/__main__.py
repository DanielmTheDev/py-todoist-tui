import asyncio
import sys
from collections.abc import Sequence

from todoist_tui.api.client import TodoistClient
from todoist_tui.api.repository import ApiSnapshotSource, ApiTaskRepository
from todoist_tui.config import (
    ConfigError,
    default_cache_path,
    default_config_path,
    load_token,
)
from todoist_tui.domain.clock import SystemClock
from todoist_tui.store.repository import SnapshotTaskRepository
from todoist_tui.store.sqlite import (
    SqliteArrangementStore,
    SqliteHomeViewStore,
    SqliteSnapshotCache,
)
from todoist_tui.tui.app import TodoistApp


def main(argv: Sequence[str] | None = None) -> int:
    try:
        token = load_token(default_config_path())
    except ConfigError as error:
        print(f"todoist-tui: {error}", file=sys.stderr)
        return 1

    asyncio.run(_run(token))
    return 0


async def _run(token: str) -> None:
    cache_path = default_cache_path()
    clock = SystemClock()
    async with TodoistClient.create(token) as client:
        repo = SnapshotTaskRepository(
            ApiTaskRepository(client),
            ApiSnapshotSource(client),
            SqliteSnapshotCache(cache_path),
            clock,
        )
        app = TodoistApp(
            repo,
            SqliteArrangementStore(cache_path),
            clock,
            home=SqliteHomeViewStore(cache_path),
        )
        await app.run_async()


if __name__ == "__main__":
    raise SystemExit(main())
