#!/usr/bin/env sh
# Install todoist-tui as an editable uv tool and put uv's bin dir on PATH.
set -eu

APP=todoist-tui
MARKER_START="# >>> todoist-tui installer >>>"
MARKER_END="# <<< todoist-tui installer <<<"
BACKUP_SUFFIX=".todoist-tui.bak"

usage() {
    cat <<EOF
usage: install.sh [--uninstall] [--dry-run] [--shell zsh|bash|fish|posix|none]

  --uninstall  remove the tool and the PATH block (keeps config and cache)
  --dry-run    print what would happen, change nothing
  --shell      target shell config; defaults to \$SHELL, "none" skips the edit
EOF
}

die() {
    printf '%s: %s\n' "$APP" "$1" >&2
    exit 1
}

bad_usage() {
    printf '%s: %s\n' "$APP" "$1" >&2
    usage >&2
    exit 2
}

# Gate for every mutating command so --dry-run has zero side effects.
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'DRY-RUN: %s\n' "$*"
    else
        "$@"
    fi
}

detect_shell() {
    case "$(basename -- "${SHELL:-}")" in
        zsh) printf 'zsh\n' ;;
        bash) printf 'bash\n' ;;
        fish) printf 'fish\n' ;;
        *) printf 'posix\n' ;;
    esac
}

rc_file() {
    case "$1" in
        zsh) printf '%s\n' "$HOME/.zshrc" ;;
        # macOS terminals start login shells, which skip .bashrc.
        bash)
            if [ "$(uname -s)" = Darwin ]; then
                printf '%s\n' "$HOME/.bash_profile"
            else
                printf '%s\n' "$HOME/.bashrc"
            fi
            ;;
        fish) printf '%s\n' "$HOME/.config/fish/conf.d/$APP.fish" ;;
        posix) printf '%s\n' "$HOME/.profile" ;;
    esac
}

# Keep $HOME symbolic so the rc block survives a home-dir move.
display_dir() {
    case "$1" in
        "$HOME"/*) printf '$HOME/%s\n' "${1#"$HOME"/}" ;;
        *) printf '%s\n' "$1" ;;
    esac
}

path_block() {
    if [ "$1" = fish ]; then
        cat <<EOF
$MARKER_START
fish_add_path -g "$2"
$MARKER_END
EOF
    else
        cat <<EOF
$MARKER_START
case ":\$PATH:" in *":$2:"*) ;; *) PATH="$2:\$PATH" ;; esac
export PATH
$MARKER_END
EOF
    fi
}

backup() {
    if [ -f "$1" ]; then
        cp -p "$1" "$1$BACKUP_SUFFIX"
    fi
}

add_path_block() {
    rc=$1

    case ":$PATH:" in
        *":$BIN_DIR:"*)
            printf '%s is already on PATH.\n' "$BIN_DIR"
            return 0
            ;;
    esac
    if [ -f "$rc" ] && grep -qF "$MARKER_START" "$rc"; then
        printf 'PATH block already present in %s.\n' "$rc"
        return 0
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'DRY-RUN: append PATH block for %s to %s\n' "$BIN_DIR" "$rc"
        return 0
    fi

    mkdir -p "$(dirname -- "$rc")"
    backup "$rc"
    # A file without a trailing newline would swallow the first block line.
    if [ -s "$rc" ] && [ -n "$(tail -c 1 "$rc")" ]; then
        printf '\n' >>"$rc"
    fi
    path_block "$SHELL_KIND" "$(display_dir "$BIN_DIR")" >>"$rc"
    printf 'Added %s to PATH in %s.\n' "$BIN_DIR" "$rc"
    PATH_CHANGED=1
}

remove_path_block() {
    rc=$1

    if [ ! -f "$rc" ]; then
        return 0
    fi
    if [ "$SHELL_KIND" = fish ]; then
        run rm -f "$rc"
        printf 'Removed %s.\n' "$rc"
        return 0
    fi
    if ! grep -qF "$MARKER_START" "$rc"; then
        return 0
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'DRY-RUN: remove PATH block from %s\n' "$rc"
        return 0
    fi

    stripped=$(mktemp "${TMPDIR:-/tmp}/$APP.XXXXXX") # bare mktemp is GNU-only
    awk -v start="$MARKER_START" -v end="$MARKER_END" '
        $0 == start { skipping = 1 }
        skipping == 0 { print }
        $0 == end { skipping = 0 }
    ' "$rc" >"$stripped"
    backup "$rc"
    cat "$stripped" >"$rc" # rewrite in place to keep the rc file's mode
    rm -f "$stripped"
    printf 'Removed the PATH block from %s.\n' "$rc"
}

warn_missing_token() {
    config="$HOME/.config/todoist/config.json"
    if [ -f "$config" ] && grep -q '"token"' "$config"; then
        return 0
    fi
    cat <<EOF

No Todoist API token found. Create it with:
  mkdir -p "$(dirname -- "$config")"
  printf '{"token": "<your-todoist-api-token>"}\n' > "$config"
  chmod 600 "$config"
Get the token from Todoist -> Settings -> Integrations -> Developer.
EOF
}

DRY_RUN=0
PATH_CHANGED=0
MODE=install
SHELL_KIND=""

while [ $# -gt 0 ]; do
    case "$1" in
        --uninstall) MODE=uninstall ;;
        --dry-run) DRY_RUN=1 ;;
        --shell)
            shift
            [ $# -gt 0 ] || bad_usage "--shell needs a value"
            SHELL_KIND=$1
            ;;
        --shell=*) SHELL_KIND=${1#--shell=} ;;
        -h | --help)
            usage
            exit 0
            ;;
        *) bad_usage "unknown option: $1" ;;
    esac
    shift
done

[ -n "$SHELL_KIND" ] || SHELL_KIND=$(detect_shell)
case "$SHELL_KIND" in
    zsh | bash | fish | posix | none) ;;
    *) bad_usage "unknown shell: $SHELL_KIND" ;;
esac

command -v uv >/dev/null 2>&1 ||
    die "uv not found on PATH. Install it: https://docs.astral.sh/uv/getting-started/installation/"

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
[ -f "$REPO_DIR/pyproject.toml" ] || die "no pyproject.toml next to install.sh ($REPO_DIR)"
BIN_DIR=$(uv tool dir --bin)

if [ "$MODE" = uninstall ]; then
    run uv tool uninstall "$APP"
    if [ "$SHELL_KIND" != none ]; then
        remove_path_block "$(rc_file "$SHELL_KIND")"
    fi
    printf 'Uninstalled %s. Config and cache in ~/.config/todoist and ~/.cache/todoist were kept.\n' "$APP"
    exit 0
fi

# --force: the version is static, so uv would otherwise see nothing to upgrade.
run uv tool install --editable --force "$REPO_DIR"

if [ "$SHELL_KIND" = none ]; then
    printf 'Add this to your shell config:\n  export PATH="%s:$PATH"\n' "$BIN_DIR"
else
    add_path_block "$(rc_file "$SHELL_KIND")"
fi

warn_missing_token

if [ "$PATH_CHANGED" -eq 1 ]; then
    printf '\nRestart your shell (or run: exec %s -l) and then: %s\n' "${SHELL:-sh}" "$APP"
else
    printf '\nRun it with: %s\n' "$APP"
fi
