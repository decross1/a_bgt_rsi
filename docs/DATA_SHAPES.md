# DATA_SHAPES — the contract between producers and the UI

Single reference for every data shape the **UI consumes**, plus a **changelog** of
shape changes. The primary session updates this whenever a producer's shape changes;
the **UI session reads it** (linked from `agent/prompts/ui_session.md`) instead of
reverse-engineering producers. This exists because a 2026-06-05 `ui/` reconcile was
made painful by undocumented Loop-v1 + experiment-summary shape drift.

**Rule (primary session):** any change to a shape below — a new `iteration_record`
field, a new endpoint payload, a new/changed experiment `summary.json` — gets a dated
**Changelog** entry here in the same commit that ships the producer change.

---

## 1. Loop schemas (canonical = the JSON Schema files; this doc only summarizes + dates)

| Shape | Canonical schema | Consumed by |
|---|---|---|
| `iteration_record` (one `memory/loop_memory.jsonl` row) | `schema/iteration_record.schema.json` | resolved-iterations list, iteration detail |
| `active_iteration` (`run_state/active_iteration.json`) | `schema/active_iteration.schema.json` | active-iteration panel (LOOP_V0-detail subset) |
| `active_run` (`run_state/active_run.json`) | `schema/active_run.schema.json` | single "what is running now" panel (any run kind) |
| worker activity (`logs/worker_activity.jsonl`) | none (this doc, §2) | per-call inference-internals panel |
| `loop_feedback` (one `memory/loop_feedback.jsonl` row) | `schema/loop_feedback.schema.json` | gate status / human-verdict surfacing |
| wrapper calls (`logs/calls.jsonl`) | `schema/calls.jsonl.schema.json` | call-chain inspector |
| events (`run_state/week1.run.jsonl`) | `schema/events.jsonl.schema.json` | activity / event stream |
| worker result contract | `schema/worker_contract.schema.json` | n/a (internal) |

**`iteration_record` — optional blocks the UI should render when present** (added Loop v1,
2026-06-05; all OPTIONAL, never in top-level `required`, so old rows stay valid):
- `meta_review`: `{ conditioning_bullets: string[] (3–5), rows_considered: int }`
- `redteam`: `{ verdict: "fatal_flaw"|"proceed", retries_used: int, critique?, confidence?, subagent_* }`
- `gate_status`: `"pending"|"valid"|"invalid"|"needs_revision"` (string)
- `experiment_outcome`: `{ experiment_id, metric, value: number|object, trials?, summary?, results_path? }`
- `cross_tier_comparison`: `{ claim, mechanism_a|rung_1, mechanism_b|rung_2, agreement: bool, diagnostic_note }`

`iteration_record.retrieval.neighbors[].source_layer` values: `"foundational"` (curated textbook/canon),
`"live_arxiv"` (`papers_recent`), `"live_ml_intern"` (the Slice-2 ML-Intern automated Semantic Scholar
backfill in `ml_intern_fetched`; appears only when retrieval escalation fired this iteration — D-038).

`loop_feedback` row: `{ iteration_id, verdict: "valid"|"invalid"|"needs_revision", note, gated_at, gated_by }`.

## 2. Experiment result shapes (NO JSON Schema — this doc is the only reference)

Experiments are **heterogeneous** by design; the UI's experiments feature detects artifacts
per `results/` dir. Document each here.

- **exp001_repeated_pd** → `results/summary.json`:
  `{ n_opponents, rounds_per_opponent, per_opponent: [{ opponent, llm_coop_rate, opp_coop_rate, llm_mean_payoff, ... }] }`
- **exp003_vickrey_rediscovery** → `results/summary.md` (markdown, no json): verdict line `**Verdict: YES|NO**`, `Truthful fraction at eps=5.0: N/M (P%)`.
- **exp004_combinatorial_auction** → `results/summary.json`:
  `{ n_trials, per_mechanism: [{ mechanism, truthful_fraction, mean_efficiency, mean_revenue, parse_failure_rate, verdict }] }`
- **exp005_mechanism_aware** → `results/summary.json`:
  `{ n_trials, per_mechanism: [{ mechanism, truthful_fraction, mean_signed_residual, parse_failure_rate, verdict }] }`
  — note **`mean_signed_residual`** (shading signal), and NO `mean_efficiency`/`mean_revenue` (differs from exp004).
- **exp006_mechanism_design** → `results/summary.json`:
  `{ n_trials, designer_mean_efficiency, feasibility_rate, matches_vcg_rate, verdict }` — flat (no `per_mechanism`).

UI guidance: do not assume a uniform experiment-summary shape. Probe keys; render
`per_mechanism` as a table when present, else the flat metrics; treat `verdict ∈ {YES,NO,INVALID}`.

### 2a. Per-call inference internals (`logs/worker_activity.jsonl`) — NO JSON Schema

Append-only JSONL; one row per finished inference call (NOT a per-decode-step stream).
Emitted by the wrapper after each `call_sync`/`call_async`/`call_with_tools`, by Nara
orchestrator turns, and by sub-agent turns (full coverage since 2026-06-10). Shape:
`{ timestamp, run_id, task_id (=caller_tag), tokens_generated, tokens_target,
tok_per_s, eta_s (null when tok_per_s==0), synthetic: false, backend?, model? }`.
`backend` (registry name, e.g. `vllm-qwen`) + `model` (served-model-name) are OPTIONAL —
absent on pre-2026-06-10 rows; always stamped since. `synthetic:false` because
this is real data — a future live stream is a separate upgrade. `tokens_target` falls back to
`tokens_generated` when the caller passed no `max_tokens` cap.

---

## Changelog

- **2026-06-10 (Session 3)** — β-arming + Polymarket paper-strategy shapes:
  - **`run_state/coordinator_budget.jsonl`** (NEW, append-only): one row per EXECUTED
    coordinator cycle `{date, timestamp, run_id, spent}`; the cycle refuses to execute
    when today's total + cycle budget would exceed `COORDINATOR_DAILY_CAP` (default 18).
    Dry-runs are never charged. `run_state/pause_coordinator` (presence = kill switch)
    and `run_state/d049_ratified` (presence = the human ratified D-049 scheduled cycles)
    are SENTINEL files — content ignored.
  - **`memory/promotion_near_misses.jsonl`** (NEW, append-only): one row per promotion
    near-miss `{timestamp, source_iteration_id, reason, stage}` — the per-candidate WHY
    that the cycle log dropped (first live read: 58 rows; recent candidates unanimously
    refuted 3/3 by the Qwen adversarial panel).
  - **Coordinator cycle rows**: plans may now name `run_experiment` (cost 5) and
    `forecast_markets` (cost 3); `state.topic_suggestions[].source` gains
    `finding_followup` (the `memory/finding_followups.jsonl` queue finally has a consumer).
  - **`experiments/exp007_polymarket/results/strategy_memo.{json,md}`** (NEW, per-run):
    schema `schema/strategy_memo.schema.json` — `{strategy_id, created_at,
    experiment_outcome, edge_analysis (with top_edges), paper_rule, limitations,
    disclaimer (const)}`. Design-only: the disclaimer is schema-enforced verbatim.

- **2026-06-10** — Provenance EMIT (screenshot-review legibility work; pairs with the
  rewritten `docs/ui_next_session_plan.md`):
  - **`logs/calls.jsonl`**: new OPTIONAL top-level `backend` (backend registry name,
    e.g. `vllm-gemma`/`vllm-qwen`/`ollama-coder`/`anthropic`) on every record from every
    producer (`wrapper._record`, `call_with_tools`, `nara._record_turn`,
    `subagent._emit_record`). Sub-agent records now also stamp `run_id` (they previously
    dropped it even inside a registered iteration) and `max_tokens`. Old rows validate
    unchanged (field optional in `schema/calls.jsonl.schema.json`).
  - **`logs/worker_activity.jsonl`**: rows gain OPTIONAL `backend` + `model`; emission
    coverage extended to `call_async`, Nara orchestrator turns
    (`task_id="nara.run_iteration"`), and sub-agent turns (`task_id="subagent.<name>"`).
  - **`run_state/active_iteration.json`**: new OPTIONAL `steps[]` board —
    `{name, status ∈ pending|running|passed|failed|skipped, started_at?, ended_at?}` for
    `meta_review` + the 5-step chain, with dynamic `redteam` / `ml_intern` entries
    inserted when those sub-loops fire. Absent on legacy iterations → UI falls back to
    its static strip. Schema updated (`schema/active_iteration.schema.json`).
  - **`run_state/week1.run.jsonl`**: new event types `loop_v0_active_step`
    (`{iteration_id, step, status}` per board transition), `subagent_start` /
    `subagent_finish` (`{subagent, run_id, status?, turns_used?, backend?}`).
  - **Run registration**: `experiments/lit_falsification_battery`, `exp001`, `exp007`,
    `exp008` (both evals), and the `novelty_skeptic` smoke now `set_run_id` +
    `write_active_run` (exp009 pattern) — backend load from these is no longer
    "BUSY (unregistered)".
  - **Multi-run registry (D-047)**: `run_state/active_runs/<safe(run_id)>.json` —
    one schema-validated file per LIVE run (the active_run.json shape; both files
    carry `heartbeat_at`, refreshed on every update; deleted on completion; absent
    dir == no live runs). `run_state/active_run.json` remains the foreground mirror
    (most recent writer) with only-owner-clears — concurrent runs no longer clobber
    it; nested in-process registration (coordinator → iteration) pops back to the
    parent. Caveat for `steps[]` consumers: a `journal_writer` chip marked `passed`
    may be orchestrator-filled after Nara skipped the step — the journal EXISTS
    either way; the degraded path is distinguishable by the paired
    `loop_v0_fallback` run-log event, not by the chip.
  - **Write-back ledgers (D-046)**: NEW `memory/coordinator_acks.jsonl`
    (`{bubble_run_id, ack_by, acked_at, note}`; written ONLY by
    `orchestrator/todo_cli.py ack`) and NEW `memory/dev_session_queue.jsonl`
    (`{ref_id, kind, note, status:"open", attested_by, deferred_at}` /
    closing rows `{ref_id, status:"closed", note, closed_by, closed_at}`;
    written ONLY by `todo_cli defer|close`; readers fold by ref_id, last status
    wins). One-shot finding dispositions append the existing
    `surfaced_findings.status.jsonl` row shape with `session_id: null`
    (`finding_session --set-status`). See `docs/human_writeback_contract.md`.
  - **Purge (D-048)**: `coordinator_cycles.jsonl` 140→117, `calls.jsonl`
    4,819→879, `worker_activity.jsonl` 1,251→1,163 — provably-synthetic test
    rows removed with `.pre_purge_2026-06-10` backups kept beside each file.
    Consumers must not pin the existence of the removed rows.

- **2026-06-08** — Coordinator-brain (Slice-Alpha) `coordinator_report` shape +
  `active_run` adoption. **OPT-IN host tooling, NOT the always-on Nara.** Produced by
  `orchestrator/coordinator.py` (`coordinator_cycle` / `python -m orchestrator.coordinator
  --once`), built ALONGSIDE the scripted `orchestrator/nara.py:run_iteration`, which
  stays the unmodified DEFAULT. A single `--once` cycle (NOT continuous); **DRY-RUN by
  default** (plans only, executes nothing) — execution requires the explicit `--execute`
  flag. The constrained action space in `orchestrator/coordinator_actions.py` is the
  guardrail: an off-menu / malformed / over-budget plan is REJECTED and re-planned
  (bounded), never executed.
  - **`coordinator_report`** (NEW, in-memory / CLI-printed return value, NO JSON Schema —
    this doc is the only reference; not persisted to the spine): the value returned by
    `coordinator_cycle(...)`. Fields:
    `run_id` (`"coordinator_<hex8>"`), `status`
    (`planned` = dry-run validated plan | `executed` = `--execute` ran handlers |
    `no_valid_plan` = every attempt rejected by the guardrail, nothing executed),
    `dry_run` (bool; absent on `no_valid_plan`), `plan` (the validated/normalized actions,
    each `{name, args, cost, handler_ref}`; `[]` on `no_valid_plan`), `attempts`
    (per plan attempt `{attempt, raw_plan, ok, errors}` — initial + up to `_MAX_REPLANS`=2
    replans), `state` (the `assess_state` snapshot the plan was made from), `executed`
    (per dispatched action `{action, status (passed|error|skipped), result?|reason?}`;
    `[]` in dry-run), `bubble_up` (human-facing summary of every `bubble_up` action:
    `[{finding_ids, note}]`), `errors` (rejection errors; populated on `no_valid_plan`).
  - **`active_run` adoption**: the cycle announces itself via `run_state/active_run.json`
    with **`kind="ad_hoc"`** (label `coordinator_cycle`) and stamps `wrapper.set_run_id`
    so its `logs/calls.jsonl` rows carry the run context; the record is cleared in a
    `finally` so an idle apparatus shows no stale coordinator run. NOTE: `kind="coordinator"`
    is NOT (yet) a registered `active_run` kind (`schema/active_run.schema.json` /
    `orchestrator/active_run.py:_KINDS` allow only `experiment|autoresearch|loop_v0|ad_hoc`);
    the alpha reuses `ad_hoc` rather than amend the spine schema. Promote to a dedicated
    `coordinator` kind if/when the coordinator graduates from opt-in alpha to a standing surface.
  - This is **opt-in alpha host tooling**, not a loop artifact or a registered surface —
    nothing here is wired into the spine, no continuous loop is added, and the default
    remains dry-run.

- **2026-06-08** — exp008 QAT-eval scratch artifacts (eval-only benchmark; **NOT** loop
  artifacts, **NOT** the production call log). Written by the
  `experiments/exp008_qat_eval/` harness (`eval_*.py` producers + `analyze.py`
  aggregator), served against a scratch container on port `:8002`; never touches
  the serial spine, schema, or production `logs/calls.jsonl`.
  - **`experiments/exp008_qat_eval/runs/*.jsonl`** (NEW, eval-scratch, NO JSON Schema):
    append-only per-arm eval **call records**, one row per (arm, fixture) eval call.
    File-per-(surface, arm): `runs/{toolcall,robustness,novelty}_<arm>.jsonl`, where
    `arm ∈ {pin, B, C}` (`pin` = the NVFP4 production pin baseline; B/C = QAT GGUF /
    QAT unquantized). Each row carries at least `arm` (the aggregation key) plus the
    surface-specific eval payload. **Separate from production `logs/calls.jsonl`** —
    eval calls are isolated to the experiment's `runs/` dir and are never loop data.
  - **`experiments/exp008_qat_eval/results/summary.json`** (NEW, eval-scratch, the
    comparison table; written by `analyze.py`): `{ verdict (H0|H1|...), reasons[],
    per_metric, arms: { <arm>: <aggregated-metrics> }, config: { source, used_default,
    materiality, tool_call_adherence_floor, min_sample, robustness_modal_share_min },
    tertiary_disclaimer }`. `verdict` reads QAT relative to the `pin` arm. tok/s and
    memory are context-only, NOT decision inputs.
  - These are **eval-scratch, not loop artifacts** — do not treat them as a
    sandbox-tier experiment summary; exp008 is intentionally NOT registered in
    `orchestrator/tier_registry.py`.

- **2026-06-06** — Finding-promotion + rubberbanding-session surfaces. New producers and a
  session API the UI consumes. Written by `orchestrator/finding_promotion.py` and
  `orchestrator/finding_session.py`; both now announce themselves via
  `run_state/active_run.json` (`kind="ad_hoc"`, labels `promote_findings` /
  `finding-session <finding_id>`) so they appear in the "what is running now" panel,
  and stamp `wrapper.set_run_id` so their `logs/calls.jsonl` rows carry the run context.
  - **`memory/surfaced_findings.jsonl`** (NEW, `schema/surfaced_finding.schema.json`): one
    promoted finding per row. Idempotent on `finding_id` (= `"sf-" + source_iteration_id`).
    Key fields the UI renders: `title`, `claim`, `tier` (NULLABLE string), `novelty_class`
    (`novel|rediscovery|nonsense|unclear`), `critic_verdict`
    (`survives|falsified|restated|malformed`), `why_it_matters`, `what_would_change_it`,
    `status` (file value; the LIVE status is the audit override below), and `adversarial`
    `{model, backend, n_skeptics, n_voting, n_refuted, adversarial_margin, survived,
    qwen_failures, refutation_summaries[]}`. `evidence.experiment_outcome` and
    `evidence.results_path` are BOTH NULLABLE — a finding can be promoted on a
    surprising-vs-theory verdict with no attached experiment. UI must treat them as nullable.
  - **`memory/surfaced_findings.status.jsonl`** (NEW, append-only status audit): rows
    `{finding_id, status, changed_at, changed_by, session_id, reason}`. `status ∈
    {valid, invalid, spawn_topic, in_review}`. EFFECTIVE status of a finding = the LAST
    row for its `finding_id` (none yet == still `surfaced`). The UI's status pill reflects
    this override, NOT the static `status` on the surfaced row.
  - **`memory/finding_sessions/<finding_id>/<session_id>.jsonl`** (NEW, append-only
    transcript, one file per interrogation session). Event rows by `type`:
    `system_seed` (the defender seed; carries `refutation_count`, `backend`, `iteration_id`),
    `user` / `assistant` (`{turn_index, content, request_id?, backend?, at}`), and
    terminal `feedback` (`{outcome, note, gated_by, new_topic?, refined_claim?}`).
  - **`memory/finding_followups.jsonl`** (NEW, append-only queue): rows
    `{finding_id, session_id, new_topic, queued_at, queued_by, reason}`. A `spawn_topic`
    outcome enqueues here; the session engine does NOT run the loop on it.
  - **Session API** (Python; backs the chat view — SAME functions back the REPL):
    `start_session(finding_id) -> {session_id, finding}` (loads finding, joins source
    iteration, reads journal + prior refutations, writes the `system_seed` row, NO LLM
    call); `session_turn(finding_id, session_id, user_msg) -> {reply, request_id,
    turn_index}` (replay → append user → `call_sync` → append assistant; bounded by
    `MAX_TURNS=24`, at which it returns an explicit cap reply and does NOT call the model);
    `end_session(finding_id, session_id, outcome, note, ...) -> {loop_feedback_row,
    status_audit_row, followup_row}` with `outcome ∈ {validated, rejected, spawn_topic,
    refine, abandoned}`.

  **UI SPEC — Top Findings board + session/chat view** (NOT `ui/` code; this is the spec the
  UI session implements):
  - **Top Findings board panel** — one card per `surfaced_findings.jsonl` row, sorted newest
    `promoted_at` first. Card shows: `title`; `claim`; an ADVERSARIAL BADGE reading
    `survived N-K` where `N = adversarial.n_voting`, `K = adversarial.n_refuted`, colored by
    `adversarial.adversarial_margin` (higher margin = stronger/greener, margin near 0 =
    amber); a MODEL BADGE (`adversarial.model` / `adversarial.backend`); a TIER CHIP
    (`tier`, rendered "—" or hidden when null); `why_it_matters`; a STATUS PILL reflecting the
    EFFECTIVE status from `surfaced_findings.status.jsonl` (fall back to the row's `status`);
    and a QWEN_FAILURES WARNING icon when `adversarial.qwen_failures > 0` (the vote ran short
    of skeptics — caveat the margin). Treat `evidence.experiment_outcome`/`results_path` as
    nullable — render an "experiment evidence" affordance only when present.
  - **Session / chat view** — opened from a card; drives the session API
    (`start_session` → `session_turn` loop → `end_session`). Renders the transcript from the
    per-session JSONL (user/assistant rows by `turn_index`), a COLLAPSIBLE "what skeptics
    already argued" block seeded from `adversarial.refutation_summaries` (the attacks the
    finding already survived), and verdict controls mapping to the `end_session` outcomes.
    Honor the `MAX_TURNS` cap reply (disable further turns, prompt for a verdict).

- **2026-06-06** — UI observability wiring (asks #1–#3). Four producers added/extended:
  - **`run_state/active_run.json`** (NEW, `schema/active_run.schema.json`): a single live-state
    file written atomically by any run-mode driver — `kind ∈ {experiment, autoresearch, loop_v0, ad_hoc}` —
    with `{run_id, kind, label, started_at, current_step?, step_started_at?, progress?{done,total,unit},
    narration?, model?, n_err?}`. Absent file == idle. Replaces per-mode bespoke state for the
    "what is running now" panel; `active_iteration.json` stays the LOOP_V0-detail subset.
  - **wrapper calls (`logs/calls.jsonl`)** gain two OPTIONAL fields: `run_id` (string — the run-mode
    context, set by `wrapper.set_run_id`) and `max_tokens` (integer — the requested generation cap).
    Both OMITTED when unset; NOT in `required`, so the existing ~13MB of rows stay valid.
  - **`logs/worker_activity.jsonl`** (NEW, per-call, append-only): one row per finished inference call —
    `{timestamp, run_id, task_id, tokens_generated, tokens_target, tok_per_s, eta_s|null, synthetic:false}`.
    Real per-call data (`synthetic:false`); the wrapper emits it after each `call_sync`/`call_with_tools`.
  - **experiment orchestrator rows (`logs/orchestrator.jsonl`)**: the exp00{3,4,5,6} drivers now emit the
    OrchestratorClient `orchestrator_dispatch → worker_invocation → orchestrator_receipt` triple per trial
    (`task_type="experiment_trial"`, receipt carries `duration_ms`), so the UI worker table + causal graph
    light up during an experiment with zero UI change.
- **2026-06-05** — Slice-2 ML-Intern: new `source_layer` value `"live_ml_intern"` in
  `iteration_record.retrieval.neighbors[].source_layer` (schema enum widened to
  `["foundational","live_arxiv","live_ml_intern"]`). Surfaces only when retrieval escalation
  fired and the `ml_intern_fetched` collection contributed neighbors to the re-run. See D-038.
- **2026-06-05** — Loop v1 added optional `iteration_record` blocks `meta_review`, `redteam`,
  `gate_status` (+ `cross_tier_comparison`); new `loop_feedback.jsonl` + `schema/loop_feedback.schema.json`.
- **2026-06-05** — New experiment summaries: `exp004` (`per_mechanism` with `mean_efficiency`/`mean_revenue`),
  `exp005` (`per_mechanism` with `mean_signed_residual`), `exp006` (flat `designer_mean_efficiency`/`feasibility_rate`).
- **2026-06-05** — This doc created. Autoresearch/tier work appends here as shapes change.
