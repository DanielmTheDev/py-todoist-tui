# Arrange ladder — multi-level group-by / sort-by

Powerful **Arrange** for the task table: group-by then-by (≤3) and sort-by
then-by (≤3), leader-key transient UI, nested render, per-view persistence.
One rung per context; check off as landed. Full design:
`~/.claude/plans/alright-now-i-want-lively-river.md`.

## Locked decisions
- **UI:** leader-key transient — `g` group chain, `s` sort chain; compact
  persistent indicator on the status line. (Not a modal rule-list, not a DSL.)
- **Fields:** project, priority, due-date, due-time, recurring, content, labels.
- **Multi-label:** task with N labels appears once **under each** label
  (multi-membership) → same task renders in multiple groups.
- **Depth:** ≤3 group levels, ≤3 sort levels.
- **Persistence:** per-view (Today / Inbox / each filter), SQLite, restored on
  restart + view switch.
- **MVP render:** always expanded (fold/collapse deferred).

## Rungs
- [x] **A1 — labels in domain.** `Task.labels: tuple[str, ...]` (+parser).
      Tests: domain default-empty + holds-labels; api maps labels + empty when
      absent. Non-behavioral (no UAT).
- [x] **A2 — `arrange()` core.** `domain/arrange.py`: `Field`, `SortKey`,
      `Arrangement` (3-cap + dict serde), pure `arrange(rows, arrangement) ->
      list[GroupHeader | TaskLine]` with multi-label expansion, sort chain,
      stable ties, nested headers. Operates on the `ArrangeRow` Protocol
      (application `TaskRow` satisfies it structurally). 15 unit tests.
- [x] **A3 — persistence.** `store.SqliteArrangementStore` (own `arrangement`
      table in the cache DB, upsert, JSON serde) behind new domain port
      `ArrangementStore`. `View.key` is the stable per-view identity
      (`today` / `inbox` / `filter:<id>`). Tests: round-trip, default-when-absent,
      per-view isolation, overwrite, parent-dir creation, view keys.
- [ ] **A4 — render nested groups.** Wire `arrange()` into the render path
      (`app.py:_render`, `views.py`); header rows, composite keys `path|id`,
      indent, completion by extracted id, status indicator. Seed a fixed
      arrangement to demo. **Also:** add `labels` to `TaskRow` (`load_view`) and
      persist `Task.labels` in the snapshot-cache `tasks` table (`sqlite.py`
      `_task_to_row`/`_row_to_task`) so grouping-by-labels survives a cold start.
      UAT: grouped+sorted view, complete inside a group, cursor sane across rebuild.
- [ ] **A5 — leader transients.** `g`/`s` transient screens (mirror
      `FilterScreen`), apply + persist, live indicator. UAT: `g p r enter` →
      group Project › Priority; `s d` → sort Due; view switch restores per-view;
      restart persists.

## Out of scope (future)
- Group fold/collapse.
- Group/sort by **section** (needs `Task.section_id` + parser + name resolve).
- Typed-DSL power-user entry.
