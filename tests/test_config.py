import json
from pathlib import Path

import pytest

from todoist_tui.config import (
    ConfigError,
    default_cache_path,
    default_config_path,
    load_token,
)


def _write_config(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload))
    return path


def test_load_token_returns_token_from_config(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "config.json", {"token": "abc123"})

    assert load_token(config) == "abc123"


def test_load_token_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_token(tmp_path / "config.json")


def test_load_token_missing_key_raises(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "config.json", {"other": "x"})

    with pytest.raises(ConfigError, match="token"):
        load_token(config)


def test_load_token_blank_token_raises(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "config.json", {"token": "  "})

    with pytest.raises(ConfigError, match="token"):
        load_token(config)


def test_load_token_invalid_json_raises(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text("not json")

    with pytest.raises(ConfigError):
        load_token(config)


def test_default_config_path_is_xdg_todoist_config() -> None:
    assert default_config_path() == Path.home() / ".config" / "todoist" / "config.json"


def test_default_cache_path_is_xdg_cache_todoist() -> None:
    assert default_cache_path() == Path.home() / ".cache" / "todoist" / "tui.sqlite3"
