# py-todoist-tui — Project Rules

Rich, fully keyboard-driven Todoist TUI. Personal, single-user. Built
iteratively in small, reviewed steps.

## Stack & commands
- Python ≥3.12, `uv`-managed. TUI: **Textual**. HTTP: **httpx** (Todoist API v1).
- Install: `uv sync`
- Test: `uv run pytest` (live-API `smoke` tests excluded by default)
- Live smoke (opt-in): `uv run pytest -m smoke`
- Lint/format: `uv run ruff check` · `uv run ruff format`
- Types: `uv run pyright`
- Dep-graph: `uv run lint-imports` (enforces the layer rule below)
- Run app: `uv run todoist-tui`

## Architecture (layered, pragmatic tactical DDD)
```
src/todoist_tui/
  domain/       entities (Task, Project, Section, Label),
                value objects (Due, Priority, TaskId, FilterQuery). No I/O.
  store/        repository interfaces + SQLite cache, sync-token state.
  api/          httpx v1 client: incremental /sync + batched commands.
  application/  workflows as services (schedule, postpone-redistribute, bulk ops).
  tui/          Textual app, screens, widgets, keymap. No direct I/O.
  config.py     token/config loading.
tests/          mirrors src/. tests/smoke/ = opt-in live-API.
```
**Dependency rule (hard):** `tui → application → domain`. `application` reaches
`store`/`api` only through interfaces. `domain` imports nothing outward. TUI
never calls httpx or the DB directly. Enforced by `import-linter`
(`uv run lint-imports`) — config in `pyproject.toml`.

## Coding guideline
- **TDD, no exceptions.** Failing test first → minimal code to pass → refactor.
  No production code without a test that drove it.
- **No flaky tests.** A test must pass deterministically. If one is flaky, fix
  the root cause (usually a real race in the code, not just the test) — never
  retry-loop, sleep-tune, or `xfail` around it. New/suspect async or timing
  tests: hammer them (e.g. run ~30×) before calling done.
- **Testable by design.** All I/O (http, db, clock, filesystem) behind an
  injected interface. Pure domain logic has zero I/O.
- **Concise & self-documenting.** Names carry intent. Comments explain *why* /
  non-obvious tradeoffs only — never restate *what*. No dead code, no
  speculative generality (YAGNI).
- **No duplication (DRY).** One source of truth for each rule, constant, or
  behavior. Extract a shared function/value object before copy-pasting logic;
  don't restate the same knowledge in two layers. But prefer a little
  duplication over the wrong abstraction — couple only what changes together.
- **DDD, pragmatic.** Ubiquitous language matching Todoist terms. Value objects
  (frozen dataclasses) for concepts with rules; entities for identity;
  repository interfaces abstract the store; workflows are application services.
  No domain events / CQRS until a real need appears.
- **Types.** Full hints; `pyright` strict clean. Prefer immutable value objects.
- **Small & modular.** Short functions (one job, early returns, shallow
  nesting); small focused classes (single responsibility, few public methods).
  Split modules before they sprawl; group by domain concept, not by kind. If a
  function/class is hard to name or test, it's doing too much — split it.
- **Style.** `ruff` check + format clean before commit.
- **Commits.** Conventional, small, one logical change; message says *why*.

## Data safety
- Token read from `~/.config/todoist/config.json` key `"token"` (shared with
  todoist-cli + the i3 quick-add scripts). Never invent a new env var.
- **No live-API writes in automated tests.** Unit tests mock httpx (`respx`).
  Live calls only in `tests/smoke/`, marked `smoke`, excluded from default runs.
- Destructive ops honor a `--dry-run` where applicable. Never mutate the real
  account from an automated/CI run.
- **Free to probe the live API to confirm behavior before implementing.** A
  throwaway test account token lives in the repo-root `.env` as
  `TODOIST_SMOKE_TOKEN` (same one the `smoke` tests use). When the API's real
  response shape or a payload's effect is uncertain, write a scratch script
  against that account and verify first — don't guess and don't build on an
  assumption. Clean up any tasks you create.

## Development loop
Each increment is one small, single-purpose diff:
0. **Clarify intent first.** Before a feature or behavior change, ask targeted
   questions with concrete options (which surface, UX/keys, edge cases,
   multi-item handling) — don't assume intent. Skip only for trivial/mechanical
   diffs (docs, pure refactors, typos).
1. Write the failing test.
2. Minimal implementation to green.
3. Refactor (tests stay green).
4. `ruff` + `pyright` clean.
5. **Reviewer subagent** checks it against the checklist below.
6. **User acceptance test.** Every feature ends with a concrete UAT: the exact
   end-to-end steps the user runs to see the behavior for real (usually
   `uv run todoist-tui` with the precise keys/actions and expected on-screen
   result; include setup/teardown, e.g. delete the cache to force a cold start).
   Automated tests passing is *not* sufficient — spell out the manual check and
   present it before handing over. Skip only for non-behavioral diffs (docs,
   pure refactors with no observable change).
7. **User reviews** (runs the UAT), then commit.
Keep diffs small so review is fast. No big-bang PRs.

**Commit straight to `main`.** Single-user repo — no feature branches, no PRs.
Commit the reviewed increment directly on `main` and push.

## Reviewer checklist (subagent uses this)
1. Test-first honored; test exercises real behavior, not trivial.
2. New logic covered incl. edge cases; no untested public method.
3. Dependency rule respected (no outward domain import; TUI no direct I/O).
4. DDD: logic in the right layer (domain vs application vs infra); language matches.
5. Concise: no what-comments, no dead/speculative code, clear names.
6. Types complete; `pyright` strict + `ruff` clean.
7. No live-API or account-mutating test.
8. Diff small and single-purpose.

Reviewer output: one line per finding — `path:line: severity: problem. fix.`
No praise, no scope creep.

## Subagent briefs
Give agents: the task, the relevant rules subset, acceptance criteria, output
format. **No persona role-play** — rules and checklists shape quality, not
characters.

## Reference (do not copy code, same-user prior art)
- `~/git/todoist-tui` — old F#/.NET client; has the workflow logic (load
  balancing, postpone-redistribute) worth mirroring behaviorally.
- `~/git/i3-dotfiles/scripts/i3/gui-todoist-quickadd.py` — capture + token
  convention.
