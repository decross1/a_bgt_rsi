# UI session handoff — validate the autonomy render + add agent-provenance (2026-06-10)

> **To the UI session.** Two tasks: (1) **validate** the already-merged
> autonomy-observability render against LIVE data, and (2) a small **additive**
> change — distinguish a research cycle/iteration that was driven by the *in-sandbox
> NemoClaw Nara agent* from a host-coordinator one. Full design context:
> [`docs/ui_autonomy_observability_plan.md`](ui_autonomy_observability_plan.md) and the
> validation plan [`docs/validation_session_plan.md`](validation_session_plan.md).
>
> **Boundary (CLAUDE.md):** write only `ui/` + `ui_plan.md`. Do NOT touch
> `orchestrator/`, `run_state/`, `schema/`, `workers/`. Print `UI READY TO MERGE` when done.

## Why now
The render half (commit `07b6729`) is merged and unit-green (200 frontend / 152 backend), but it
has **never been seen against live data** — the running backend predated the merge and 404'd on
`/api/coordinator/*`. The primary session restarts the backend in the validation session; your job
is to confirm the live dashboard actually renders the real artifacts, fix anything broken, and add
one provenance signal.

## Task 1 — Validate the render against live data (after the backend restart)
Drive a real run (the primary session will have produced `run_state/coordinator_cycles.jsonl` — ~13
rows — and a `nemoclaw_agent`-sourced iteration). Confirm each surface PASSES against the live data,
not just fixtures:
- **Coordinator view** (`/coordinator`): the cycle cards list the real cycles; a `promote_findings`
  cycle and any `run_loop_iteration` cycle render; **a failed dispatch (if present) shows as an
  explicit red row with its error** (force one if needed by pointing at a cycle whose `outcomes` has
  `status:"errored"`).
- **Low-evidence flag**: the 2026-06-09 FASE iteration (`iter-2026-06-09-001`) and any off-domain
  thesis render the **low-evidence/low-confidence badge** (from `retrieval.relevance.low_confidence`
  / the thin-retrieval signal). An *on-domain* iteration (e.g. `iter-2026-06-09-002`) must NOT show it.
- **Panels**: Surfaced Findings (`surfaced_findings.jsonl`) and Bubbles (`coordinator_bubbles.jsonl`)
  populate or show a clean empty state; the **health-signals** panel renders `ml_intern_zero_papers` /
  `qwen_degraded` as **amber (degraded), not red**.
- **Agent badges** appear on every cycle/row (`coordinator` / `nara` / `workflow:…` / `nemoclaw_agent`).
- **Activity + Dashboard + Experiment** pages render without console errors against live data.
Report PASS/FAIL per surface; **fix any render bug you find** (that's the point of validation).

## Task 2 — Provenance: surface "driven by the in-sandbox NemoClaw agent" (additive)
The validation session adds a new iteration provenance value **`seed.source = "nemoclaw_agent"`**
(an autonomous research thesis formed + run by Nara *inside* nara-sandbox, via the host tool plane) —
alongside the existing `human_cli` / `human_ui` / `arxiv_pick` / `loop_memory_probe` / `coordinator`.
Make this legible:
- Add a **`nemoclaw_agent` source badge** (distinct tone — e.g. violet) on the iteration row /
  CoordinatorCycleCard `topic_source`, so a human auditor can tell *"the sandboxed Nara agent chose
  and ran this thesis"* apart from a host-coordinator cycle. This is the headline β signal — the
  apparatus running an idea it picked itself, from inside the sandbox.
- Keep it consistent with the existing `sourceTone()` / `AgentBadge` patterns; small, additive, tested.

## Data contracts (what the EMIT side produces — build against these)
- `memory/loop_memory.jsonl` iteration rows: `seed.source` now also takes `"nemoclaw_agent"`;
  `retrieval.relevance = {relevance, low_confidence, reason}`; `novelty.low_confidence` /
  `critique.low_confidence` (booleans, may be absent on pre-2026-06-09 rows — handle gracefully).
- `run_state/coordinator_cycles.jsonl`, `run_state/health_signals.jsonl`,
  `memory/surfaced_findings.jsonl`, `memory/coordinator_bubbles.jsonl`, `run_state/active_run.json`
  (`kind:"coordinator"`) — as already wired in the merged backend (`ui/backend/coordinator.py`).

## Acceptance
The live dashboard (restarted backend) renders the real coordinator cycles + panels + agent badges;
a failed dispatch shows as an explicit red row; an off-domain thesis shows the low-evidence flag and
an on-domain one does not; a `nemoclaw_agent`-sourced iteration shows the new provenance badge.
Unit tests green (+ a test for the new badge). Print `UI READY TO MERGE`.

## 2026-06-09 evening additions (EMIT-side schema changes — additive, no UI crash path)
- Critic verdict enum gains `undecidable` (fails closed; every consumer gates on `== "survives"`)
  — render it as a plain string chip like the other verdicts.
- Novelty result gains optional `novelty_axes` ({phenomenon, substrate, predicted_direction}, may
  be null) plus optional `verdict_overridden_from`/`override_reason`/`skeptic_verdict` strings on
  the novelty and critique blocks — all render as strings; absent on legacy rows.
- `retrieval.relevance` gains additive keys {anchor_cosine, curated_overlap, neighbor_spread,
  category, rule_fired}. Existing keys {relevance, low_confidence, reason} and the legacy novelty
  `class` are UNCHANGED (UI join contract, commit 0fdb671).

## 2026-06-09 evening — EMIT live-data status per gap (for UI re-validation)
1. **Low-evidence badge (gap 1): LIVE ROW EXISTS** — `iter-2026-06-09-007`
   (off-domain static-analysis topic): `retrieval.relevance.low_confidence=true`,
   `reason` mentions the LLM topicality check, new additive keys
   `topicality:"off"` / `rule_fired:"R0"` / `category:"off_domain"`. The on-domain
   contrast row is `iter-2026-06-09-006` (p-beauty re-run, rediscovery/restated,
   low_confidence=false, novelty_axes present).
2. **Findings/bubbles/health (gap 2):** a real coordinator cycle ran post-T1
   (run_id `coordinator_6d8a2c4e`); whether findings/bubbles/health rows were
   legitimately produced is recorded in `run_state/coordinator_cycles.jsonl` —
   panels keep their proven empty state if no real row passed the gate
   (fabricating rows was rejected). EMIT-side field-shape regression tests are in
   `tests/test_emit_join_contract.py`.
3. **active_run mid-flight (gap 3):** two distinct in-flight snapshots captured
   during the live cycle (both lack `current_step`/`narration` — the cycle's
   update_active_run granularity is coarser than the stepper; render what exists):
   `{"run_id": "coordinator_6d8a2c4e", "kind": "coordinator", "label": "coordinator_cycle", "started_at": "2026-06-09T21:28:18.362557Z"}`
   `{"run_id": "promote_findings_4c9ac22e", "kind": "ad_hoc", "label": "promote_findings", "started_at": "2026-06-09T21:28:23.423345Z"}`
4. **dispatched_iteration_id (gap 4):** check the latest row of
   `run_state/coordinator_cycles.jsonl` for the `coordinator_6d8a2c4e` cycle.
5. **nemoclaw_agent (gap 5):** unchanged (2 live rows); the in-sandbox agent
   re-drive is blocked on a broken sandbox→gemma gRPC channel (h2 broken pipe),
   NOT on the MCP wiring — `tools/list` over `/mcp` works from inside the sandbox.
