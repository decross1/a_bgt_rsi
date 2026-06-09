# EMIT test plan — close the autonomy-observability validation loop

> **Authored by the UI session (2026-06-09) to hand to the primary / EMIT session.**
> The UI RENDER half is now **live-validated** against real data for every path that
> real data exists for (19 coordinator cycles incl. 3 errored, 52 loop_memory rows,
> 2 live `nemoclaw_agent` rows → violet badge). **Five render paths cannot be
> exercised live yet** because the EMIT side hasn't produced the data condition. This
> plan lists, for each: the EMIT work to produce it, the EMIT-side test to add, and the
> one-line UI re-validation that closes it.
>
> Producing these also **hardens EMIT**: several producers have no test asserting the
> *full row reaches the artifact the UI reads* — a field rename there silently blanks the
> corresponding UI panel (the UI reconciled to these exact field names on commit
> `0fdb671`; treat them as the join contract).
>
> **Boundary:** the EMIT producers, `schema/`, and the actual runs are the primary
> session's. The render side is built + proven; if a real row breaks a UI surface, file
> it back to the UI session — do not edit `ui/` from the primary session.

## The 5 EMIT→UI gaps

### 1. Low-evidence flag has no live trigger
> **Disposition (WF-B, 2026-06-09 late evening): DEFERRED-no-live-data-yet.**
> Still 0/4 live relevance rows with `low_confidence==true`. The render side
> grew the category/rule tooltip detail and stays pinned; the genuine
> off-domain re-run appears to have landed ON-domain — primary to either
> append the real flagged row or confirm the intended iteration_id. The
> live-census tests in `test_revalidate_live_rows.tsx` auto-validate it the
> moment it lands.
- **Live now:** `retrieval.relevance` on 4 `loop_memory` rows, **0** with `low_confidence===true` → the UI's low-evidence badge never fires on real data (only fixtures). Correct behavior (doesn't cry wolf), but the *firing* path is live-unexercised.
- **EMIT work:** confirm `workers/retrieval_relevance.py` actually emits `low_confidence=true` + a `reason` on a genuine thin/off-domain verdict (the 2026-06-09 false `novel/survives` class — an off-domain topic retrieved against the game-theory corpus), and that `nara.run_iteration` writes it through to `loop_memory.jsonl` → `retrieval.relevance.{relevance,low_confidence,reason}`.
- **EMIT test:** `tests/test_retrieval_relevance.py` case — a known off-domain hypothesis → `low_confidence=true`; plus an end-to-end assert that the iteration record persisted to `loop_memory.jsonl` carries `retrieval.relevance.low_confidence=true`.
- **UI re-validation:** re-run `ui/frontend/tests/test_validate_lowevidence.tsx` semantics against the real row → the amber **low-evidence** badge fires on that iteration in `ResolvedIterationsList`. (No UI change expected.)

### 2. Surfaced-findings / bubbles / health-signals panels are fixture-only
> **Disposition (WF-B): DEFERRED-no-live-data-yet.** All three files still
> ABSENT (re-checked 2026-06-09 ~21:08 UTC). The findings/bubbles tests now
> branch on the REAL file state (`test_revalidate_live_rows.tsx`): honest
> empty today, real rows rendered automatically when the files appear.
- **Live now:** `memory/surfaced_findings.jsonl`, `memory/coordinator_bubbles.jsonl`, `run_state/health_signals.jsonl` are **ABSENT** → UI validated only the clean empty state.
- **EMIT work:** drive one cycle that (a) promotes a finding (`finding_promotion._promote_findings` → `surfaced_findings.jsonl`), (b) raises a bubble (`coordinator._persist_bubble_up` → `coordinator_bubbles.jsonl`), (c) trips a degraded signal (`coordinator_cycle_log.emit_health_signals` → `health_signals.jsonl`: `ml_intern_zero_papers` and/or `qwen_degraded_empty_content`).
- **EMIT test — assert the exact UI-read fields** (a regression here silently blanks the panel):
  - finding: `{finding_id, title, source_iteration_id, novelty_class, critic_verdict, promoted_at, status}`
  - bubble: `{timestamp, run_id, finding_ids, note}`
  - health: `{timestamp, run_id, signal, severity:"degraded", iteration_id, detail}`
- **UI re-validation:** re-run the panels' validation with the populated files → findings/bubbles render the rows; health renders **AMBER** (degraded ≠ down). (UI: add a populated-render assertion alongside the existing empty-state one.)

### 3. `active_run.json` mid-flight is unvalidated
> **Disposition (WF-B): DEFERRED-no-live-data-yet.** File still absent;
> `/api/coordinator/active` → 204 live. Stepper + the WF-A staleness hint are
> unit-pinned; needs one mid-flight snapshot from the EMIT side.
- **Live now:** `/api/coordinator/active` returns **204** (no cycle in flight) → UI validated only the idle state.
- **EMIT work:** during a cycle, `active_run.write_active_run` / `update_active_run` writes `kind="coordinator"` + `current_step ∈ {assess,plan,validate,dispatch}` + `narration` (chosen topic + why). Capture an `active_run.json` snapshot while a cycle runs (or a fixture-run that writes the in-flight doc without clearing it).
- **EMIT test:** assert `update_active_run` yields a schema-valid doc carrying `current_step` + `narration` at each phase.
- **UI re-validation:** point `CoordinatorPhases` / `Activity` at the captured doc → the stepper highlights `current_step`, the narration shows.

### 4. No `dispatched_iteration_id` on any cycle (0/19)
> **Disposition (WF-B): DEFERRED-no-live-data-yet.** Now 0/**133** cycles
> (22 errored) — pure accretion, still no successful dispatch. Footer-link
> render remains fixture-pinned.
- **Live now:** all 19 cycles either errored or didn't dispatch → the Coordinator card's "dispatched `<iter>`" footer link is live-unexercised.
- **EMIT work:** a **successful** `run_loop_iteration` in a cycle → `coordinator_cycle_log.cycle_row_from_report` writes `dispatched_iteration_id` (it populates this only on a passed dispatch).
- **EMIT test:** `cycle_row_from_report` with a passed `run_loop_iteration` → `dispatched_iteration_id` present and equal to the iteration's id.
- **UI re-validation:** the card renders the dispatched-iteration footer for that cycle.

### 5. `nemoclaw_agent` end-to-end (the β headline) — UI done, EMIT/track-B last mile
> **Disposition (WF-B): CLOSED (UI side).** The two live rows
> (`iter-2026-06-09-003`/`-004`) are now pasted VERBATIM as permanent render
> pins in `test_revalidate_live_rows.tsx` (violet badge, novel/survives chips,
> red redteam chip, NO low-evidence flag). EMIT-side schema-enum test stays
> the primary's last mile.
- **Live now:** 2 `nemoclaw_agent` rows in `loop_memory.jsonl` → UI renders the **violet** source badge (validated end-to-end). **UI side is complete.**
- **EMIT/primary (L1/L2/L4):** the in-sandbox OpenClaw agent forming + running a thesis via the tool plane (`run_loop_iteration(topic, source="nemoclaw_agent")`) is the primary's Track-B last mile. **EMIT test:** the tool-plane `run_loop_iteration` writes `seed.source="nemoclaw_agent"` and the `schema/iteration_record.schema.json` `seed.source` enum includes it.

## Re-validate the UI after EMIT lands (no UI change expected)
```
cd ui/frontend && npx vitest run            # test_validate_* + the populated-path assertions
cd ui && env -u MOCK_LLM PYTHONPATH="$PWD" .venv-ui/bin/python -m pytest backend/tests -q
# live smoke: TestClient(create_app()) over the real run_state/ + memory/ (it reads
# _PRIMARY_REPO), confirming each /api/coordinator/* serves the newly-produced rows.
```
The render paths are built and proven against fixtures + the live data that exists; this
step confirms the **live wire** once EMIT produces the missing conditions.

## One stale comment to refresh (non-blocking, in EMIT's tree)
`backend/tests/test_validate_live_real_data.py` is a UI-session file, but the original
brief's "13 cycles / 2 errored" wording also appears in the broader plan docs; the live
counts are now 19 / 3 / 52 (pure data accretion — all UI assertions are count-agnostic
cohort invariants and stayed green).
