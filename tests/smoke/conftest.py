import pytest

from tests.smoke.env import SMOKE_TOKEN_KEY, smoke_token


@pytest.fixture(scope="session")
def token() -> str:
    resolved = smoke_token()
    if resolved is None:
        pytest.skip(f"no {SMOKE_TOKEN_KEY} (set env var or .env in repo root)")
    return resolved
