"""Hermetic tests for `install.sh`.

Every run gets a throwaway ``$HOME`` and a stub ``uv`` on ``$PATH`` that logs its
argv instead of touching the real uv tool directory.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
MARKER = "# >>> todoist-tui installer >>>"
SYSTEM_PATH = "/usr/bin:/bin"

UV_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$UV_LOG"
if [ "$1" = tool ] && [ "$2" = dir ]; then
    printf '%s\\n' "$UV_BIN_DIR"
fi
"""


@dataclass(frozen=True)
class Env:
    home: Path
    bin_dir: Path
    uv_log: Path
    stub_dir: Path

    @property
    def zshrc(self) -> Path:
        return self.home / ".zshrc"

    @property
    def config(self) -> Path:
        return self.home / ".config" / "todoist" / "config.json"

    def uv_calls(self) -> list[str]:
        if not self.uv_log.exists():
            return []
        return self.uv_log.read_text().splitlines()


@pytest.fixture
def env(tmp_path: Path) -> Env:
    home = tmp_path / "home"
    home.mkdir()
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    uv = stub_dir / "uv"
    uv.write_text(UV_STUB)
    uv.chmod(0o755)
    return Env(
        home=home,
        bin_dir=tmp_path / "uvbin",
        uv_log=tmp_path / "uv.log",
        stub_dir=stub_dir,
    )


def install(
    env: Env, *args: str, with_uv: bool = True, path_extra: str = ""
) -> subprocess.CompletedProcess[str]:
    search_path = f"{env.stub_dir}:{SYSTEM_PATH}" if with_uv else SYSTEM_PATH
    if path_extra:
        search_path = f"{path_extra}:{search_path}"
    return subprocess.run(
        [str(INSTALL_SH), *args],
        capture_output=True,
        text=True,
        env={
            "HOME": str(env.home),
            "PATH": search_path,
            "SHELL": "/bin/zsh",
            "UV_LOG": str(env.uv_log),
            "UV_BIN_DIR": str(env.bin_dir),
        },
    )


def test_dry_run_changes_nothing(env: Env) -> None:
    result = install(env, "--dry-run", "--shell", "zsh")

    assert result.returncode == 0, result.stderr
    assert not env.zshrc.exists()
    assert not any(call.startswith("tool install") for call in env.uv_calls())


def test_install_adds_tool_and_path_block(env: Env) -> None:
    result = install(env, "--shell", "zsh")

    assert result.returncode == 0, result.stderr
    assert f"tool install --editable --force {REPO_ROOT}" in env.uv_calls()
    assert env.zshrc.read_text().count(MARKER) == 1


def test_install_is_idempotent(env: Env) -> None:
    install(env, "--shell", "zsh")
    result = install(env, "--shell", "zsh")

    assert result.returncode == 0, result.stderr
    assert env.zshrc.read_text().count(MARKER) == 1


def test_skips_path_block_when_bin_dir_already_on_path(env: Env) -> None:
    result = install(env, "--shell", "zsh", path_extra=str(env.bin_dir))

    assert result.returncode == 0, result.stderr
    assert not env.zshrc.exists()
    assert "already on PATH" in result.stdout


def test_fish_gets_a_conf_drop_in(env: Env) -> None:
    result = install(env, "--shell", "fish")

    assert result.returncode == 0, result.stderr
    drop_in = env.home / ".config" / "fish" / "conf.d" / "todoist-tui.fish"
    assert "fish_add_path" in drop_in.read_text()


def test_shell_none_only_prints_the_export_line(env: Env) -> None:
    result = install(env, "--shell", "none")

    assert result.returncode == 0, result.stderr
    assert not env.zshrc.exists()
    assert str(env.bin_dir) in result.stdout


def test_keeps_the_last_rc_line_intact_without_a_trailing_newline(env: Env) -> None:
    env.zshrc.write_text("alias ll='ls -l'")

    install(env, "--shell", "zsh")

    lines = env.zshrc.read_text().splitlines()
    assert lines[0] == "alias ll='ls -l'"
    assert MARKER in lines


def test_uninstall_removes_tool_and_block_but_keeps_config(env: Env) -> None:
    env.config.parent.mkdir(parents=True)
    env.config.write_text('{"token": "abc"}')
    install(env, "--shell", "zsh")

    result = install(env, "--uninstall", "--shell", "zsh")

    assert result.returncode == 0, result.stderr
    assert "tool uninstall todoist-tui" in env.uv_calls()
    assert MARKER not in env.zshrc.read_text()
    assert env.config.read_text() == '{"token": "abc"}'


def test_uninstall_keeps_unrelated_rc_lines(env: Env) -> None:
    env.zshrc.write_text("alias ll='ls -l'\n")
    install(env, "--shell", "zsh")

    install(env, "--uninstall", "--shell", "zsh")

    assert env.zshrc.read_text() == "alias ll='ls -l'\n"


def test_warns_when_token_config_is_missing(env: Env) -> None:
    result = install(env, "--shell", "zsh")

    assert result.returncode == 0, result.stderr
    assert "config.json" in result.stdout


def test_no_warning_when_token_config_exists(env: Env) -> None:
    env.config.parent.mkdir(parents=True)
    env.config.write_text('{"token": "abc"}')

    result = install(env, "--shell", "zsh")

    assert "config.json" not in result.stdout


def test_fails_clearly_without_uv(env: Env) -> None:
    result = install(env, "--shell", "zsh", with_uv=False)

    assert result.returncode != 0
    assert "uv" in result.stderr


def test_rejects_unknown_flags(env: Env) -> None:
    result = install(env, "--nope")

    assert result.returncode == 2
    assert "usage" in result.stderr.lower()
