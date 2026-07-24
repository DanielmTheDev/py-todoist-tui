# Saved Filters ladder

Living tracker. One rung per context, each a small TDD diff. **Delete this file
at F10.** Design: `~/.claude/plans/ok-next-i-want-transient-torvalds.md`.

Decision: **server-side eval** — selecting a filter fetches its tasks from
Todoist's `/tasks/filter` endpoint (perfect grammar fidelity, no local parser,
no domain expansion). Saved-filter *list* is synced + cached; *results* are live.

Each rung: failing test → minimal green → refactor → `ruff` + `pyright` +
`lint-imports` clean → reviewer subagent → UAT → user reviews → commit.

## Rungs

- [x] **F0 — tracker doc.** This file. No code.
- [x] **F1 — `Filter` entity.** `domain/filter.py`: frozen dataclass
  `id, name, query, order`. Test construction + stable order sort. Done:
  4 tests, ruff/pyright/lint-imports clean, reviewer clean (added empty-list test).
- [x] **F2 — Snapshot carries filters.** `filters` on `Snapshot` + `SyncDelta`
  (`filters` + `deleted_filter_ids`); `merge` mirrors projects/tasks via `_apply`.
  New fields defaulted (empty) so unrelated call sites untouched; real values
  wired in F3/F4. `default_factory=list[Filter]` for pyright-strict. Done:
  2 merge tests, all green, reviewer clean.
- [x] **F3 — SQLite caches filters.** `filters(id,name,query,item_order)` table
  (`order` is reserved → `item_order`); `_save` delete+insert, `_load` selects.
  `_load` try/except broadened over all reads → legacy file w/o filters table
  returns None → re-sync. Done: round-trip (via `_snapshot` helper) + legacy-
  schema test, all green, reviewer clean.
- [x] **F4 — /sync fetches filters.** `resource_types += "filters"`;
  `delta` maps `body.get("filters", [])` via `_split`/`_to_filter`
  (`item_order`→`order`, drops `is_deleted`). Tolerates missing key on
  incremental sync. Done: 3 respx tests, all green, reviewer clean.
- [x] **F5 — client + repo query.** `client.filter_tasks(query)` (today_tasks
  now delegates); port gains `filtered(query)` + `filters()`;
  `ApiTaskRepository.filtered` (live /tasks/filter), `.filters()` (via /sync,
  documented); `SnapshotTaskRepository.filtered` → inner (server-side, live),
  `.filters()` → snapshot (cached). All test fakes updated for port. Done:
  5 new tests, all green, reviewer addressed (design comment).
- [x] **F6 — filter View factory.** `filter_view(f)` → `View(f.name,
  lambda repo: repo.filtered(f.query))`, mirroring TODAY/INBOX. Done: 1 test
  (title + query forwarded + result), all green.
- [x] **F7 — Filters screen.** `tui/screens/filters.py` `FilterScreen(ModalScreen
  [Filter|None])` + `FilterList(OptionList)` (vim j/k); name + dim query, sorted
  by order, `Enter`→dismiss(filter), `Esc`→dismiss(None). Gotcha: don't store
  filters in `self._filters` (Textual App owns that name → render crash); used
  `self._choices`. **F8: TodoistApp must avoid `self._filters` too.** Done: 4
  Pilot tests (hammered 30×), reviewer clean (kept `str(option.id)` for pyright).
- [x] **F8 — wire into app.** `f` → async `action_view_filters`: `repo.filters()`
  → `push_screen(FilterScreen, _on_filter_chosen)` → `_switch_to(filter_view(f))`;
  cancel keeps view. Footer `f`. Empty → "No saved filters"; load-error → status;
  `_picking_filter` flag stops stacking pickers (reviewer race fix). Done: 6 pilot
  tests (hammered), all gates green, reviewer addressed. **UAT below.**
- [x] **F9 — live smoke parity (opt-in).** `tests/smoke/test_filters_parity_live.py`
  (`smoke`, read-only): saved filters sync+parse; each filter's query accepted by
  Todoist and our `filtered()` mapping == raw endpoint ids. Written; **run it:**
  `uv run pytest -m smoke`.
- [ ] **F10 — finalize.** README/help note; final UAT; delete this file.

## Notes / decisions log
- (append surprises, API field names, deviations here as rungs land)
