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
- [ ] **R1 — Projects cache (in-memory).** ← NEXT
  Memoize `projects()` for the session behind a `store/` caching repository.
  Kills the redundant projects trip per view switch/complete + the inbox
  double-fetch.
- [ ] **R2 — Parallelize `load_view`.**
  `asyncio.gather` the task-fetch and `projects()` (serial→parallel). ~halves
  first-load latency. Isolated to `views.py`.
- [ ] **R3 — `/sync` snapshot (in-memory).**
  `TodoistClient.sync(token="*")` → POST `/sync` returns items + projects
  (+sections/labels) in one trip. `store/` snapshot repo serves
  `projects()`/`inbox()`/project tasks from it. `today()` still hits server
  `/tasks/filter` (hybrid). Complete must update/invalidate the snapshot.
- [ ] **R4 — Persist snapshot + `sync_token` (SQLite).**
  `store/` SQLite cache; load on startup → instant offline cold start, refresh
  in background.
- [ ] **R5 — Incremental sync.**
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
