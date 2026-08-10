# todoist-tui

Rich, fully keyboard-driven terminal UI for [Todoist](https://todoist.com),
built for a personal filter/view + bulk-edit workflow. Task capture is handled
elsewhere (i3 quick-add); this tool is for browsing, filtering, and bulk editing.

> Status: early. Scaffolding + ground rules in place; features built iteratively.

## Requirements
- Python ≥ 3.12
- [`uv`](https://docs.astral.sh/uv/)
- A Todoist API token in `~/.config/todoist/config.json`:
  ```json
  { "token": "<your-todoist-api-token>" }
  ```
  (Same file used by `todoist-cli`. Get the token from Todoist → Settings →
  Integrations → Developer.)

## Install
```sh
./install.sh
```
Installs `todoist-tui` as an editable [`uv` tool](https://docs.astral.sh/uv/guides/tools/)
— the command tracks this checkout, so `git pull` is enough to update it — and
adds uv's bin directory to `PATH` in your shell config (zsh, bash, fish, or
`~/.profile`) if it isn't there already. Re-running it is safe.

| Flag | Effect |
|------|--------|
| `--dry-run` | Print every action, change nothing |
| `--uninstall` | Remove the tool and the `PATH` block (config and cache are kept) |
| `--shell zsh\|bash\|fish\|posix\|none` | Override the detected shell; `none` only prints the `export` line |

## Setup (development)
```sh
uv sync
```

## Run
```sh
todoist-tui        # installed
uv run todoist-tui # from a checkout
```

## Keys
| Key | Action |
|-----|--------|
| `t` / `i` | Today / Inbox view |
| `f` | Pick a saved filter (server-side, cached; ↑/↓ move, `Enter` select, `Esc` cancel) |
| `/` | Search every task by title or description; matches preview as you type, `Enter` opens them as a view |
| `e` | Complete the highlighted task |
| `z` | Undo the last complete |
| `r` | Force a resync |
| `j`/`↓` `k`/`↑` | Move the cursor down / up |
| `l`/`→` `h`/`←` | Expand / collapse the task or group under the cursor |

Saved filters sync from your Todoist account; selecting one runs its query on
Todoist (full fidelity) and caches the result, refreshing in the background.

## Development
```sh
uv run pytest          # unit tests (live-API tests excluded)
uv run pytest -m smoke # opt-in live-API smoke tests
uv run ruff check      # lint
uv run ruff format     # format
uv run pyright         # type check
```

Contributor rules, architecture, and the review process live in
[`CLAUDE.md`](./CLAUDE.md). Core principles: TDD always, pragmatic tactical DDD,
concise self-documenting code, small reviewed increments.
