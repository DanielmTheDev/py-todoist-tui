# Sync + Cache Ladder

Making Today/Inbox fast. Moving to Todoist Sync API + a persistent cache,
ending with a domain filter engine. **One small, reviewed, TDD'd increment
(rung) per session** — each rung planned in a fresh context, committed, then
context cleared before the next.

## Why
`application/views.py:load_view` does sequential round-trips and re-fetches
`/projects` on every call. Inbox fetches projects twice per load (once to find
the inbox id, once for names) + the task fetch = 3 serial trips. No cache
(`store/` empty). Every view switch and complete-resync repeats the full fetch.

## Locked decisions
- R1 = projects cache **only** (parallelize is its own rung, R2).
- Manual-refresh key **deferred** to a later rung.
- End state = **SQLite + incremental sync** (persist across restarts).
- Today filter: keep **server `/tasks/filter`** until a client-side filter engine
  proves parity (both available → parity-testable), then replace.

## Checklist
- [x] **R1 — Projects cache (in-memory).**
  `store/CachingTaskRepository` memoizes `projects()` for the session (wraps the
  port). Kills the redundant projects trip per view switch/complete + the
  `load_view` half of the inbox render. Note: `inbox()`'s *internal*
  `client.projects()` (api layer) is out of reach of a store wrapper — that
  residual trip dies at R3.
- [x] **R2 — Parallelize `load_view`.**
  `asyncio.gather` the task-fetch and `projects()` (serial→parallel). ~halves
  first-load latency. Isolated to `views.py`.
- [x] **R3 — `/sync` snapshot (in-memory).**
  `TodoistClient.sync()` → POST `/sync` (`sync_token="*"`,
  `resource_types=["items","projects"]`) in one trip. `store/`
  `SnapshotTaskRepository` (via new `SnapshotSource` port) serves
  `projects()`/`inbox()` from a memoized snapshot — kills the double-`/projects`
  trip R1 couldn't reach. `today()` still hits server `/tasks/filter` (hybrid).
  Complete invalidates the snapshot. Inbox modeled as a normal project
  (`Project.is_inbox`). Sections/labels + `sync_token` persistence deferred.
  `CachingTaskRepository` (R1) removed — superseded.
- [x] **R4 — Persist snapshot + `sync_token` (SQLite).**
  `store/SqliteSnapshotCache` (new `SnapshotCache` port) persists the snapshot +
  `sync_token` at `~/.cache/todoist/tui.sqlite3`. `SnapshotTaskRepository` reads
  cache-first (instant offline cold start), writes through on a miss, and gains
  `refresh()`. TUI `on_mount` renders the cached view, then a background worker
  re-syncs from the network and re-renders (offline → keeps the cache). `Snapshot`
  now carries `sync_token` (captured by `ApiSnapshotSource`, seeds R5). blocking
  `sqlite3` wrapped in `asyncio.to_thread`; no new dep.
- [ ] **R5 — Incremental sync.** ← NEXT
  Startup uses stored `sync_token`; POST `/sync` with it; apply deltas (updated
  items, `deleted` ids) to SQLite. Fast steady-state refresh.
- [ ] **R6 — Domain filter engine (today first).**
  `FilterQuery` evaluator in `domain/` over cached items. Parity-test vs server
  `/tasks/filter` in smoke tests; once "today" matches, cut over, then extend
  filters (p1, overdue, project, label, boolean combos). Server filter calls
  finally replaced here.

## How we run it
- **This doc = tracker** (ladder + decisions + checklist). Detailed per-rung
  plans live in `~/.claude/plans/`, not here.
- Clear context **after each rung is committed — never mid-rung.**
- Kickoff a rung: *"Continue the sync+cache ladder. Read
  `docs/sync-cache-ladder.md`. Plan rung Rn only."*
