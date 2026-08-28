import pytest
from pytest import CaptureFixture

from todoist_tui import __main__
from todoist_tui.config import ConfigError


def _token(_path: object) -> str:
    return "tok"


def test_main_reports_config_error_and_returns_1(
    monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    def boom(_path: object) -> str:
        raise ConfigError("config not found")

    monkeypatch.setattr(__main__, "load_token", boom)

    assert __main__.main([]) == 1
    assert "config not found" in capsys.readouterr().err


def test_main_launches_app_and_returns_0(monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[__main__.TodoistApp] = []

    def token(_path: object) -> str:
        return "tok"

    async def run_async(self: __main__.TodoistApp) -> None:
        launched.append(self)

    monkeypatch.setattr(__main__, "load_token", token)
    monkeypatch.setattr(__main__.TodoistApp, "run_async", run_async)

    assert __main__.main([]) == 0
    assert len(launched) == 1


def test_reset_cache_discards_the_snapshot_before_the_app_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    async def clear(_self: object) -> None:
        order.append("cleared")

    async def run_async(_self: __main__.TodoistApp) -> None:
        order.append("started")

    monkeypatch.setattr(__main__, "load_token", _token)
    monkeypatch.setattr(__main__.SqliteSnapshotCache, "clear", clear)
    monkeypatch.setattr(__main__.TodoistApp, "run_async", run_async)

    assert __main__.main(["--reset-cache"]) == 0
    assert order == ["cleared", "started"]


def test_the_cache_survives_a_plain_start(monkeypatch: pytest.MonkeyPatch) -> None:
    cleared: list[None] = []

    async def clear(_self: object) -> None:
        cleared.append(None)

    async def run_async(_self: __main__.TodoistApp) -> None:
        return None

    monkeypatch.setattr(__main__, "load_token", _token)
    monkeypatch.setattr(__main__.SqliteSnapshotCache, "clear", clear)
    monkeypatch.setattr(__main__.TodoistApp, "run_async", run_async)

    assert __main__.main([]) == 0
    assert cleared == []


def test_an_unknown_flag_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(__main__, "load_token", _token)

    with pytest.raises(SystemExit):
        __main__.main(["--nope"])
