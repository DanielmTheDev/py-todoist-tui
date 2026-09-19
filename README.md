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
— the command tracks this checkout, so `git pull` is enough to update it, unless
the pull brought a new dependency: re-run `./install.sh` then — and
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
| `p` | Views: keys you bound, then saved filters, projects and their sections, Today and Inbox (type to filter, `Enter` opens) |
| *your own keys* | Jump straight to a view you bound in the Views screen (Today included — it has no reserved key) |
| `/` | Search every task by title or description; matches preview as you type, `Enter` opens them as a view |
| `e` | Complete the highlighted task |
| `z` | Undo the last complete |
| `r` | Force a resync |
| `C` | Read the comments on the task under the cursor (`❞` in a row marks a commented task); inside the thread, `j`/`k` move, the image under the cursor previews inline, `o` opens the file, `a` writes a comment, `u` attaches a file by path, `p` attaches the clipboard image, `d` deletes |
| `j`/`↓` `k`/`↑` | Move the cursor down / up |
| `l`/`→` `h`/`←` | Expand / collapse the task or group under the cursor; `h` keeps climbing out — to the parent task, then to the group holding it |
| `J`/`K` | Move the task under the cursor down / up among its siblings; on a section header, move the section itself (project views only) |
| `?` | Every shortcut, including the keys you bound |

Inside the Views screen (`p`): `ctrl+b` binds the highlighted view to a key you
then press — any key no shortcut already owns, `Backspace` unbinds it, `Esc`
cancels. `ctrl+s` marks the view the app opens into (`★`); pressing it again
clears the mark and startup falls back to Today. Picking a `§` section opens
its project with the cursor on that section's header — a section takes no jump
key and no startup mark of its own.

Writing a comment (`a`) opens the same vim-keyed field the description uses;
`ctrl+s` posts it. `u` takes a path (a file dragged into the terminal pastes
one) and `p` takes whatever image is on the clipboard — both post the file as a
comment of its own, which is the screenshot flow: copy, `C`, `p`. `p` needs
`xclip`, and says so when it is missing.

A comment's image previews inline when the terminal can draw one (ghostty,
kitty, or anything with Sixel). Set `TODOIST_TUI_IMAGE` to `tgp`, `sixel`,
`halfcell` or `unicode` to name the renderer yourself — `halfcell` draws with
Unicode blocks and needs no graphics protocol. Without one, a comment names its
file and `o` still opens it.

Saved filters sync from your Todoist account; opening one runs its query on
Todoist (full fidelity) and caches the result, refreshing in the background.

Pasting a URL into a task's title makes the whole title the link
(`[title](url)`), so the row shows the title and not the URL. Paste before there
is a title and the link waits for the one you type. A title that already carries
a link takes the URL bare instead of nesting, and the description takes every
paste verbatim.

The editor's description field takes vim keys. It opens in insert mode, so
tabbing in and typing works as it always did; `Esc` leaves insert (the border
says which mode you are in), and `Esc` again closes the editor without saving.

| Key | Action |
|-----|--------|
| `i` `a` `I` `A` `o` `O` | Start typing — here, after, at the line start/end, on a new line below/above |
| `h` `j` `k` `l` | Move a character or a line (the arrows do the same) |
| `w` `b` `e` | Next word, previous word, end of word |
| `0` `^` `$` | Line start, first word, line end |
| `gg` `G` | First line, last line (`3gg` and `3G` name a line) |
| `x` `dd` `D` | Delete a character, a line, to the line end |
| `cw` `cc` `C` | Change a word, a line, to the line end |
| `d`/`c` + motion | Delete or change what the motion covers (`d2w`, `dG`) |
| `diw` `daw` `ciw` `caw` | The whole word under the cursor, alone or with its space |
| `u` `ctrl+r` | Undo, redo |

A count prefixes any of them (`3j`, `d2w`). There is no yank or paste: `u` is
what brings a deletion back.

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
