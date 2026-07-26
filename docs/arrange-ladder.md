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
- [x] **A4a — labels through data path.** `TaskRow.labels` (populated in
      `load_view`) + `labels` column in the snapshot-cache `tasks` table
      (JSON); explicit-column read so a pre-labels cache is treated as cold.
- [x] **A4b — render nested groups.** `arrange()` wired into `_reload`/`_render`;
      group-header rows (`▾ label`, indented) + task lines with typed row keys
      (`h:i` / `t:i:id`); completion & cursor resolve the task id from the key,
      headers inert; status line shows `Group: … Sort: …`. Arrangement injected
      via `ArrangementStore` (in-memory default; `__main__` wires the SQLite
      store). Multi-label tasks render under each label.
- [x] **A5 — leader transients.** `ArrangeScreen` (mirrors `FilterScreen`):
      `g` builds the group chain, `s` the sort chain; field keys
      p/r/d/t/u/c/l, `⌫` pops, `G`/`S` clears, enter applies, esc cancels;
      sort re-tap toggles ↑/↓; capped at 3. Apply persists via
      `ArrangementStore.save(view.key)` then reloads. Per-view restore on
      switch; SQLite store makes it survive restart.

## Out of scope (future)
- Group fold/collapse.
- Group/sort by **section** (needs `Task.section_id` + parser + name resolve).
- Typed-DSL power-user entry.
