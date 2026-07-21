import pytest
from pytest import CaptureFixture

from todoist_tui import __main__
from todoist_tui.config import ConfigError


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
