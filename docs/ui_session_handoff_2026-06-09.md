# UI session handoff — autonomy observability (2026-06-09)

> **To the UI session.** Your task this cycle is the **RENDER half** of the
> autonomy-observability work. The **EMIT half** (the data contracts below) is being
> landed by the primary session in a parallel Dynamic Workflow; build against these
> contracts and I'll confirm field names when the emit half merges. Full design +
> rationale: [`docs/ui_autonomy_observability_plan.md`](ui_autonomy_observability_plan.md).
>
> **Boundary (CLAUDE.md):** you write only `ui/` + `ui_plan.md`. You do NOT touch
> `orchestrator/`, `run_state/`, `schema/`, `workers/`. Fold this into `ui_plan.md`,
> implement in `ui/`, print `UI READY TO MERGE` when done.

## Why — the loop runs "dark"

The autonomous `coordinator --execute --once` cycle (live 2026-06-09) did real work —
auto-picked a topic, planned, dispatched a real iteration, promoted findings — and a
human watching saw an unlabeled `ad_hoc` blip + Qwen internals. As the apparatus goes
autonomous, the human is an **auditor**: the UI must answer *"what did the loop decide,
on what basis, and can I trust it?"* — not just "is it up?"

## Design principles (apply these, not generic dashboards)

1. **Make absence legible** — every dispatched action renders an explicit state
   (`queued/running/succeeded/failed+error/skipped/degraded`). A failed dispatch is a
   **row**, never a silent gap. Idle ≠ failed ≠ running.
2. **Provenance everywhere** — badge every row/panel with the `agent` field
   (`coordinator` / `nara` / `workflow:<id>/<role>` / `human`).
3. **Show the epistemic basis** — a `novel/survives` verdict carries its evidence:
   retrieval relevance, external-search status, skeptic health. **Flag low-evidence
   verdicts** (verdict on thin/off-domain retrieval). This is the headline 2026-06-09
   bug: a false `novel/survives` on off-domain retrieval.
4. **Degraded ≠ broken** — Qwen "generating but empty-content" and ml-intern
   "ran but 0 papers" are **degraded** (amber), not down (red). Gemma healthy = green.
5. **One cycle = one narrative** — a Coordinator-cycle card ties topic→plan→outcomes→
   iteration→findings→bubbles together.

## Data contracts the EMIT half produces (build against these)

> Field names finalized when the emit PR merges; treat as the contract. All are
> append-only JSONL under `run_state/`/`memory/` (gitignored; the UI backend reads the
> live files, as it already does for `loop_memory.jsonl`).

- **`run_state/coordinator_cycles.jsonl`** (NEW) — one row per coordinator cycle:
  `{timestamp, run_id, agent, topic, topic_source, plan:[{action,args}],
  outcomes:[{action, status: passed|skipped|errored, error?}], dispatched_iteration_id?,
  promoted_finding_ids:[], bubble_run_ids:[]}`. The join key for the Coordinator view.
- **`run_state/active_run.json`** — now `kind:"coordinator"` (not `ad_hoc`) with
  per-phase narration: `current_step ∈ {assess,plan,validate,dispatch}` + `narration`
  (incl. the chosen topic + why).
- **Failed dispatches** — surfaced via the cycle row's `outcomes` (status `errored` +
  `error`). Render these explicitly in Recent Iterations / the Coordinator card.
- **`memory/loop_memory.jsonl`** — iteration rows now carry `seed.source` (badge
  `coordinator`-triggered vs `human`) and a **`retrieval.relevance`** signal (a
  low/thin flag when top-neighbor similarity is weak → drive the **low-evidence** badge).
- **`memory/surfaced_findings.jsonl`** — promoted findings (NEW panel).
- **`memory/coordinator_bubbles.jsonl`** — the loop's "raise to the human" output (NEW panel).
- **Health signals** — `agent` field (D-043) on run-log rows; a qwen-degraded +
  ml-intern-0-papers status the sampler exposes (confirm with the emit PR).

## What to build — 3 pages + a new view

- **NEW: Coordinator / Orchestration view** — card per `coordinator_cycles.jsonl` row:
  topic (+ source badge) → plan with per-action status chips (executed/skipped/**errored+error**)
  → linked iteration → promoted findings → bubbles. Agent badge on the header.
- **Activity page** — live + recent stream: coordinator phases (from `active_run`
  narration), agent badges, **explicit failed-dispatch rows**, qwen-degraded distinct.
- **Dashboard page** — overview: health row (gemma green / qwen amber / ml-intern status);
  Recent Iterations **with failed/aborted rows + a coordinator-triggered badge + a
  low-evidence-verdict badge**; **Surfaced Findings** panel; **Bubbles** panel; a
  standing-red-flags trend strip (novel-rate, suspected-false-novel rate, off-domain rate).
- **Experiment page** — experiments + **coordinator cycles as auditable units** (plan→
  outcome→evidence), with the epistemic basis (retrieval relevance, external-search
  status, skeptic health) visible so a verdict can be trusted or doubted.

## Priority order

1. **Make absence legible + the Coordinator view** (the #1 gap — failed/coordinator
   iterations stop being invisible).
2. **Surfaced-Findings + Bubbles panels** + agent badges.
3. **Low-evidence-verdict flag + degraded-vs-broken health.**
4. Standing-red-flags trend strip.

## Acceptance

Re-run `coordinator --execute --once`: the Coordinator view shows the full arc; a
**forced failed dispatch** appears as an explicit row (never silent absence); Surfaced
Findings + Bubbles populate; every row has an agent badge; a verdict on thin retrieval
shows a **low-evidence** flag; qwen-degraded renders amber. Print `UI READY TO MERGE`.
