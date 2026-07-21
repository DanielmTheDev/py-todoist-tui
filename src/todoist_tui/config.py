import json
from pathlib import Path
from typing import cast


class ConfigError(Exception):
    """Raised when the Todoist configuration is missing or malformed."""


def default_config_path() -> Path:
    return Path.home() / ".config" / "todoist" / "config.json"


def load_token(path: Path) -> str:
    if not path.is_file():
        raise ConfigError(f"config not found: {path}")

    try:
        parsed: object = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config is not valid JSON: {path}") from exc

    data: dict[str, object] = {}
    if isinstance(parsed, dict):
        data = cast("dict[str, object]", parsed)
    token = data.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ConfigError(f'config missing non-empty "token": {path}')

    return token.strip()
