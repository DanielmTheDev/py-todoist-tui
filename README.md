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
| `i` | Inbox view |
| `p` | Views: keys you bound, then saved filters, projects, Today and Inbox (type to filter, `Enter` opens) |
| *your own keys* | Jump straight to a view you bound in the Views screen (Today included — it has no reserved key) |
| `/` | Search every task by title or description; matches preview as you type, `Enter` opens them as a view |
| `e` | Complete the highlighted task |
| `z` | Undo the last complete |
| `r` | Force a resync |
| `j`/`↓` `k`/`↑` | Move the cursor down / up |
| `l`/`→` `h`/`←` | Expand / collapse the task or group under the cursor |
| `?` | Every shortcut, including the keys you bound |

Inside the Views screen (`p`): `ctrl+b` binds the highlighted view to a key you
then press — any key no shortcut already owns, `Backspace` unbinds it, `Esc`
cancels. `ctrl+s` marks the view the app opens into (`★`); pressing it again
clears the mark and startup falls back to Today.

Saved filters sync from your Todoist account; opening one runs its query on
Todoist (full fidelity) and caches the result, refreshing in the background.

Pasting a URL into a task's title makes the whole title the link
(`[title](url)`), so the row shows the title and not the URL. Paste before there
is a title and the link waits for the one you type. A title that already carries
a link takes the URL bare instead of nesting, and the description takes every
paste verbatim.

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
