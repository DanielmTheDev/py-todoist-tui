from pathlib import Path

from tests.smoke.env import SMOKE_TOKEN_KEY, smoke_token


def test_none_when_unset_and_no_file(tmp_path: Path) -> None:
    assert smoke_token(environ={}, env_file=tmp_path / "absent") is None


def test_reads_from_env(tmp_path: Path) -> None:
    token = smoke_token(environ={SMOKE_TOKEN_KEY: " abc "}, env_file=tmp_path / "x")
    assert token == "abc"


def test_falls_back_to_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{SMOKE_TOKEN_KEY}=from-file\n")
    assert smoke_token(environ={}, env_file=env_file) == "from-file"


def test_env_var_wins_over_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{SMOKE_TOKEN_KEY}=from-file\n")
    token = smoke_token(environ={SMOKE_TOKEN_KEY: "from-env"}, env_file=env_file)
    assert token == "from-env"


def test_blank_env_var_falls_back_to_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{SMOKE_TOKEN_KEY}=from-file\n")
    token = smoke_token(environ={SMOKE_TOKEN_KEY: "   "}, env_file=env_file)
    assert token == "from-file"
