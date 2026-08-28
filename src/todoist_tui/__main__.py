import argparse
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
    SqliteFoldStore,
    SqliteSnapshotCache,
    SqliteViewSlotStore,
)
from todoist_tui.tui.app import TodoistApp


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="todoist-tui")
    parser.add_argument(
        "--reset-cache",
        action="store_true",
        help="discard the cached snapshot and resync from scratch"
        " (view bindings, arrangements and folds are kept)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        token = load_token(default_config_path())
    except ConfigError as error:
        print(f"todoist-tui: {error}", file=sys.stderr)
        return 1

    asyncio.run(_run(token, reset_cache=args.reset_cache))
    return 0


async def _run(token: str, reset_cache: bool = False) -> None:
    cache_path = default_cache_path()
    clock = SystemClock()
    cache = SqliteSnapshotCache(cache_path)
    if reset_cache:
        await cache.clear()
    async with TodoistClient.create(token) as client:
        repo = SnapshotTaskRepository(
            ApiTaskRepository(client),
            ApiSnapshotSource(client),
            cache,
            clock,
        )
        app = TodoistApp(
            repo,
            SqliteArrangementStore(cache_path),
            clock,
            slots=SqliteViewSlotStore(cache_path),
            folds=SqliteFoldStore(cache_path),
        )
        await app.run_async()


if __name__ == "__main__":
    raise SystemExit(main())
