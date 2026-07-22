"""Minimal `.env` reader for smoke-test credentials. Zero-dependency."""

import os
from collections.abc import Mapping
from pathlib import Path

SMOKE_TOKEN_KEY = "TODOIST_SMOKE_TOKEN"

_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def parse_env(text: str) -> dict[str, str]:
    """Parse `KEY=VALUE` lines. Ignores blanks and `#` comments; strips quotes."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if not sep:
            continue
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def smoke_token(
    environ: Mapping[str, str] | None = None, env_file: Path | None = None
) -> str | None:
    """Resolve the smoke token: process env wins, else a repo-root `.env`."""
    environ = os.environ if environ is None else environ
    env_file = _DEFAULT_ENV_FILE if env_file is None else env_file

    token = environ.get(SMOKE_TOKEN_KEY)
    if token and token.strip():
        return token.strip()

    if env_file.is_file():
        token = parse_env(env_file.read_text()).get(SMOKE_TOKEN_KEY)
        if token and token.strip():
            return token.strip()
    return None
