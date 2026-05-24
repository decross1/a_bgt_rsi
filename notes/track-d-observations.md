# Track D — observations for Track A

Things Track D (UI improvements) noticed while working that belong to
Track A's lanes. Track D does not edit `plan.yaml`, schemas, or the
apparatus; it files observations here instead.

## 2026-05-19 — experiment-result schema does not exist

The v2 UI results browser (sketched in `ui/ui_plan_v2.md`) needs
experiment *semantic* fields — experiment id, round index, agent
action, opponent identity, opponent action, payoff. Today only the
structural call-log fields are pinned (`request_id`,
`parent_request_id`, `task_id`, `caller_tag`, timestamps). No schema
pins experiment outcomes.

Not a v1 blocker — v1 deliberately never interprets results. But when
the apparatus reaches the day-7 experiment work, a decision is owed:
do experiment outcomes live as extra fields on the call-log lines, as
a separate per-experiment results file, or both? A committed
`schema/experiment.schema.json` (or an explicit extension of the
day-7 `exp###` contract) would unblock the v2 results browser without
any prompt-text parsing.

## 2026-05-19 — embedded tool-call key name unconfirmed

Track D resolved `ui_plan.md` §9's tool-call-shape question (r4) by
supporting both shapes. The embedded shape assumes the wrapper record
carries its tools under a `tool_calls` key. If the day-4 tool-call
work uses a different key, the UI side is a one-line change
(`EMBEDDED_TOOL_KEY` in `ui/backend/chain.py`) — no rework — but it
would be good to confirm the key name when day 4 lands.

## 2026-05-23 — 4 malformed lines in `run_state/week1.run.jsonl`

Surfaced by the new `/api/unlock_status` endpoint (`ui/backend/unlock.py`)
when it first ran against the real Day-7 state. Lines **99, 105, 106,
109** fail JSON parsing — all Day-6 entries with unescaped inner
double-quotes inside `observable_actual` strings. Examples:

- L99 (`day6_block1_reading`): `"observable_actual":"human attested complete ("these human blocks are done")"` — the inner `"these..."` needs `\"these...\"`.
- L106 (`day6_block3_reading`): same pattern with `"LLMs as Simulated Economic Agents"`.
- L105 (`day6_block2_inspect_run_cli`): inner `--task-id seq-1` quote nesting.
- L109 (`day6_end_of_day_artifacts`): the longest entry; multiple unescaped pairs.

These are Day-6 entries, so Day-7's experiment review is unaffected.
But per [`agent/autonomy.md`](../agent/autonomy.md) §4.3, the Week-2
unlock attestation requires zero malformed entries across the
run-log / attestations / escalations files. **The publication-review
gate's alignment-evidence check cannot legitimately clear with these
four lines as-is.** Track A is the rectifier per
[`agent/collision_protocol.md`](../agent/collision_protocol.md) §2.3
and §7 — Track D does not write to `run_state/*`.

**Related docs drift (Track A's call):** `autonomy.md` §4.3 references
`verify_log_integrity` against `run_state/*` files. The function in
`agent_wrapper/wrapper.py:315` validates against the *call-record*
schema (`schema/calls.jsonl.schema.json`) — it's the right validator
for `logs/day*.jsonl` and the wrong one for `run_state/week1.run.jsonl`.
Pointed at the run-log it reports 130 malformed, because none of the
entries are call records. Either `autonomy.md` should point at a
dedicated `verify_run_log_integrity` (apparatus-side), or the existing
function needs disambiguation. The UI-side
`ui/backend/unlock.py:verify_run_log_integrity` validates against the
run-log required-field set from CLAUDE.md inviolate rule 8 — it is the
function `/api/unlock_status` calls, and it correctly found the four
genuinely-broken lines above. The two-validator situation is fine if
documented; Week-2 polish item.

## 2026-05-23 — Day-7-EOD UX audit (orchestrator queue + decode tile)

Surfaced when the user ran the Day-7 PD experiment through v1's
dashboard. **All fixes landed in `worktree-day7-ui`** under
`ui/**` — no apparatus-side code touched. Filing here so Track A
knows what Day 38's Track-D scope now covers and what schema-stability
assumption v1 was making.

1. **`OrchestratorQueue.tsx` filtered on `status === "started"`** —
   stale pre-Day-6 status name. Day-6+ writes `dispatched` /
   `running` / `passed` / `error` across `orchestrator_dispatch` /
   `worker_invocation` / `orchestrator_receipt` / `orchestrator_reject`
   stages (the schema set during day 6's contract work; cf.
   `schema/worker_contract.schema.json`). The "Running" section was
   silently empty during real runs. Filter widened to the full
   in-flight set.

2. **`backend/chain.py:recent_tasks` sorted by `dispatch_ts`** — also
   pre-Day-6. Day-6+ orchestrator records carry `timestamp` + `stage`
   instead. Every record sorted as `""` → dict-insertion order, so
   fresh experimental tasks (`exp001-tft`, `exp001_7_3-mirror_llm`,
   ...) ended up *below* stale Day-6 summarize_paper rows in the
   tabular view. Sort key now uses `timestamp` primary, `dispatch_ts`
   fallback (back-compat with existing fixtures).

   **Forward-looking note for Track A:** when the orchestrator schema
   evolves further (additional stages, new statuses), the dashboard
   needs a re-validation pass. A small protocol — "when a new stage
   or status is added, file an issue on Track D" — keeps the dashboard
   from silently going stale.

3. **`Day4ChainList` and `RobustnessPanel` are Day-4-specific** by
   contract (they read `logs/day4_e2e.jsonl` / `logs/day4_robust.jsonl`).
   The empty-state copy didn't say so; the user reasonably read
   "empty" as "broken" while the PD experiment was running through a
   different code path. Panels now show "(logs/day4_*.jsonl —
   day-4-specific; quiet during other workloads)" in the heading and
   "this panel only lights up during the day-4 [thing]" in the empty
   state. Not a generalization — that's v2-class work.

4. **Decode-tok/s tile reads ~11 during the PD experiment** vs the
   day-1 band `[80, 130]`. Not a regression — server-wide
   `vllm:generation_tokens_total` rate scales with output_tokens × QPS.
   Day-1 bench used 256 output tokens / call (decode-bound); PD uses
   ~2 (prefill / TTFT-bound). New `GET /api/workload_hint` summarizes
   the recent workload shape (calls/s, median output tokens, regime
   classification) and the frontend renders a small workload pill
   under the decode tile so the user sees "expected ~10 tok/s —
   short-completion workload" rather than reading `11 / [80,130]` as
   a failure. The Sparkline reference line (the day-1 hard floor of
   40) now only shows in the `decode_bound` regime.

   **Forward-looking note for Track A:** the workload-hint endpoint
   leans on `usage.output_tokens` (Day-7 shape) and
   `usage.completion_tokens` (Day-2 shape); both are recognized. If
   future workloads write the count under a different key, both
   `backend/workload.py:_output_tokens` and any apparatus-side
   downstream of the same field need to move together. Filed.

5. **Live orchestrator + workers graph view requested** (the
   visualization the user wanted, ranked separately from the four
   above because it is a v2 build, not a v1 fix). Sketch landed in
   `ui/ui_plan_v2.md` §5: `react-flow`, route `/graph`, macro-vs-
   micro zoom, `GET /api/graph` endpoint. Data contracts already
   exist; no Track-A blockers. Track-D plans to ship this *ahead* of
   the v2 results browser, because the results browser's
   experiment-outcome schema (see §1 of this file, 2026-05-19) is
   still un-pinned. Sequencing reasoning is in `ui_plan_v2.md` §5.5.

## 2026-05-24 — Day-8 audit of Day-7 artifacts (UI v1 ship)

Pre-flight audit before the Week-2 unlock attestation, paired with the
r11 `UnlockPanel.tsx` ship. UI v1's `/api/unlock_status` was driven
against the real on-disk Week-1 artifacts via the FastAPI TestClient.
**No integrity issues found.** Recorded here so a future session does
not re-audit blindly.

- `run_state/week1.run.jsonl`: 137 entries, 0 malformed (every line
  parses and carries the full plan.yaml Appendix-C required field set).
  Rolling 7-day window: 135 entries.
- `run_state/week1.state.json`: `current_day=day_8`, `completed_tasks`
  includes the 16 Day-7 backfilled IDs noted in
  `state.notes.day_7_completed_tasks_backfill`, `human_gates_pending=[]`
  (D-028 cleared the Day-7 publication-review gate), `fallbacks_taken`
  carries 4 entries (`day1_block2_vllm_serve`, `day1_nemoclaw`,
  `day5_ml_intern`, `day6_orchestrator_isolation`), `metric_log` has 11
  keys including the Day-7 slip-ladder triplet
  `day7_1/7_2/7_3_coop_rate_vs_tft` and the diagnostic
  `day7_3_coop_rate_vs_all_d`.
- `run_state/attestations.jsonl`: only the schema-comment line — no
  pending soft-gates.
- `run_state/escalations.jsonl`: only the schema-comment line — no
  hard-gate escalations.
- `run_state/claims.jsonl`: 5 entries beyond the schema comment — last
  release was Track B closing `tests-shared` on 2026-05-23T09:25:13Z;
  no stale active claims.
- `logs/orchestrator.jsonl` (88 lines): Day-7 PD experiment events
  surface in `/api/recent_tasks` (the r10 sort-key + filter fix works
  on real data — `exp001_7_3-*` rows render with
  `stage=orchestrator_receipt` and `status=passed`).
- `logs/exp001.jsonl` (600 lines), `exp001_7_{1,2,3}.jsonl`,
  `day7_dryrun.jsonl`: all readable; `/api/workload_hint` correctly
  classifies the current call shape as `short_completion`
  (5.81 call/s × 2 tokens/call), so the decode-tok/s tile carries the
  workload-aware annotation instead of misreading as a regression.
- `experiments/exp001_repeated_pd/`: 5 strategies' `results/*.csv`,
  `_aggregate/`, `per_round.jsonl`, `summary.json`,
  `analysis/quicklook.md`, 5 cumulative-payoff PNGs, `experiment.lock`
  — all present. The UI does not render experiment-level outputs in
  v1; the v2 results browser is `ui_plan_v2.md` §2–4 and is still
  blocked on the experiment-outcome schema (see §1 of this file,
  2026-05-19).

**Forward-looking process note for Track A (not blocking):** the r10
follow-up flagged ("when a new orchestrator stage or status is added,
validate the dashboard renders it") still stands. Recommend wiring it
into the orchestrator-schema change checklist rather than relying on a
side-track session catching it. The Day-8 audit caught no new gaps on
top of r10's, but the discipline scales better than spot checks.
