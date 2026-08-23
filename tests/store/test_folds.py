import sqlite3
from pathlib import Path

import pytest

from todoist_tui.store.sqlite import SqliteFoldStore


@pytest.mark.anyio
async def test_get_returns_nothing_open_when_absent(tmp_path: Path) -> None:
    store = SqliteFoldStore(tmp_path / "cache.sqlite3")

    assert await store.get("today") == frozenset()


@pytest.mark.anyio
async def test_save_then_get_round_trips(tmp_path: Path) -> None:
    store = SqliteFoldStore(tmp_path / "cache.sqlite3")
    open_groups = frozenset({("Work",), ("Work", "P1")})

    await store.save("today", open_groups)

    assert await store.get("today") == open_groups


@pytest.mark.anyio
async def test_open_groups_are_isolated_per_view(tmp_path: Path) -> None:
    store = SqliteFoldStore(tmp_path / "cache.sqlite3")

    await store.save("today", frozenset({("Work",)}))
    await store.save("inbox", frozenset({("Home",)}))

    assert await store.get("today") == frozenset({("Work",)})
    assert await store.get("inbox") == frozenset({("Home",)})


@pytest.mark.anyio
async def test_save_overwrites_the_previous_set(tmp_path: Path) -> None:
    store = SqliteFoldStore(tmp_path / "cache.sqlite3")

    await store.save("today", frozenset({("Work",)}))
    await store.save("today", frozenset())  # the user folded it back up

    assert await store.get("today") == frozenset()


@pytest.mark.anyio
@pytest.mark.parametrize("paths", ["not json", '{"Work": true}', "[[1, 2]]"])
async def test_get_tolerates_unreadable_paths(tmp_path: Path, paths: str) -> None:
    path = tmp_path / "cache.sqlite3"
    store = SqliteFoldStore(path)
    await store.save("today", frozenset({("Work",)}))  # create the table
    conn = sqlite3.connect(path)  # corrupt / legacy row the parser cannot read
    try:
        conn.execute(
            "UPDATE open_groups SET paths = ? WHERE view_key = 'today'", (paths,)
        )
        conn.commit()
    finally:
        conn.close()

    assert await store.get("today") == frozenset()


@pytest.mark.anyio
async def test_save_creates_parent_directory(tmp_path: Path) -> None:
    store = SqliteFoldStore(tmp_path / "nested" / "dir" / "cache.sqlite3")

    await store.save("today", frozenset({("Work",)}))

    assert await store.get("today") == frozenset({("Work",)})
