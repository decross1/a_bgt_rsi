> ARCHIVED 2026-06-14 — executed/ superseded work order, kept for the record. Current UI handoffs live in the session note (human/sessions/), current state in LOOP_V0.md.

# UI plan — autonomy observability (the coordinator loop must stop running "dark")

> **Authored by the primary session (2026-06-09) as a SPEC for the UI session.**
> The primary session does not write `ui/`. This doc splits the work into
> **EMIT (primary session — spine instrumentation)** and **RENDER (UI session —
> `ui/`)**, per the boundary note. The UI session folds the RENDER half into
> `ui_plan.md` and implements it; the primary session lands the EMIT half first.

## Context — what went dark, and why it matters now

On the first live `coordinator --execute --once` (2026-06-09), the autonomous loop
ran, picked a topic, planned, dispatched an iteration, promoted findings, and
produced a bubble — and **a human watching the dashboard saw essentially nothing**:
an unlabeled `ad_hoc` blip on the activity panel and Qwen internals ticking. As the
apparatus moves toward autonomy (β / D-040), the human's role shifts from *operator*
to *auditor* — and you cannot audit what the UI doesn't show. Six data streams flow
through stages with no view:

1. **The coordinator cycle** writes `active_run.json` as `kind="ad_hoc"` with no
   per-phase narration → the panel can't say what stage it's in or why.
2. **The plan** (proposed actions, auto-chosen topic, executed/skipped/errored) lives
   only in the cycle's return dict + stdout → nothing in the UI reads it.
3. **A dispatched iteration reaches Recent Iterations only if it completes.** When a
   dispatch **fails** (this cycle's `run_loop_iteration` errored on a schema-enum gap),
   it leaves **no row at all** → the human sees "nothing happened" when the truth is
   "it tried and failed." **Absence is indistinguishable from idle.**
4. **`promote_findings` → `memory/surfaced_findings.jsonl`** has no UI surface.
5. **`bubble_up` → `memory/coordinator_bubbles.jsonl`** (new this cycle) — the loop's
   "here's what I'd raise to you" output is invisible.
6. **Per-agent attribution** (the new `agent` run-log field, D-043 — coordinator vs
   nara vs `workflow:<id>/<role>`) is shown nowhere → you can't tell who did what.

## Design principles (research-apparatus UX, not generic monitoring)

The UI is a **trust-calibration + audit surface**, not an uptime dashboard. Apply:

1. **Overview-first, details-on-demand** (Shneiderman): Dashboard = at-a-glance system
   state + recent cycles → drill into a cycle → drill into an iteration's evidence chain.
2. **Make absence legible** (the #1 fix): every dispatched action renders with an
   explicit state — `queued / running / succeeded / failed (+error) / skipped /
   degraded`. Never let "nothing rendered" mean "nothing happened." Idle ≠ failed ≠ running.
3. **Provenance everywhere**: every row/panel badges its actor from the `agent` field
   (coordinator / nara / `workflow:<id>/<role>` / human). This is the auditability the
   governance harness exists for — surface it.
4. **Show the epistemic basis, not just the verdict.** A `novel/survives` result must
   carry its evidence: retrieval relevance (neighbor count, source layers, **topical
   match to the hypothesis**), external-search status (ml-intern `papers_stored`, with
   **0-papers flagged**), and skeptic independence/health. **Flag low-evidence verdicts**
   — e.g. when a verdict rests on thin or off-domain retrieval (the 2026-06-09 false
   `novel/survives` on an off-domain code-quality topic retrieved against game-theory books).
5. **Tie a cycle into one narrative.** A Coordinator Cycle card: auto-chosen topic
   (+ `source` + why) → plan (proposed actions) → per-action outcome (incl. errors) →
   linked iteration → promoted findings → bubbles. One scroll = the whole decision.
6. **Distinguish degraded from broken.** Qwen "generating but empty-content" is
   **degraded** (amber), not down (red). ml-intern "ran but 0 papers" is
   **degraded-silent** — surface it. Gemma healthy = green.
7. **Standing red-flags** (the research program's own self-checks): a trend panel —
   novel-rate, **suspected-false-novel rate** (verdict on off-domain/thin retrieval),
   off-domain-topic rate, ml-intern-empty rate — so "is the loop surfacing things
   genuinely new?" is answerable at a glance.
8. **Don't over-alarm.** Bubbles are the "raise to the human" channel — prominent but
   not noisy; flag only what needs a human.

## EMIT — primary-session spine prerequisites (land these FIRST)

These are spine edits the UI then renders. None touch `ui/`.

- **Dedicated coordinator identity.** Give the coordinator run a real `active_run`
  `kind="coordinator"` (not `ad_hoc`) — add it to `schema/active_run.schema.json`'s
  enum (mirrors the `seed.source="coordinator"` fix already landed). `orchestrator/
  coordinator.py:_coordinator_cycle` currently writes `kind="ad_hoc"` (L461).
- **Per-phase narration.** Call `active_run.update_active_run(current_step=..., narration=...)`
  at each stage (assess → plan → validate → dispatch), including the auto-chosen topic +
  its `source` + the proposed plan, so the active panel can say *what stage and why*.
- **Persist the cycle as a first-class artifact.** Write `run_state/coordinator_cycles.jsonl`
  (append-only; gitignored like the run log) — one row per cycle:
  `{timestamp, run_id, agent, topic, topic_source, plan:[{action,args}],
  outcomes:[{action,status,error?}], dispatched_iteration_id?, promoted_finding_ids:[],
  bubble_run_ids:[]}`. This is the join key for the Coordinator Cycle view. Source is the
  cycle's return dict (already assembled in `_coordinator_cycle`).
- **Failed dispatches are never silent.** When `run_loop_iteration` (or any dispatched
  action) errors, the UI must still get a row. Either (a) write a minimal **failed
  iteration stub** to `loop_memory.jsonl` (`status:"failed"`, the error, `seed.source`),
  or (b) rely on the `coordinator_cycles.jsonl` outcome row — decide one and make it the
  contract. (Recommendation: the cycle row is the source of truth for dispatch outcome;
  Recent Iterations reads failed stubs only if we also want them inline.)
- **Health signals.** Emit ml-intern `papers_stored` (already in the run log) and a
  **qwen-degraded** signal (detect empty-content / `finish_reason=length`) to the
  health/status artifact the sampler reads, so the UI can render degraded-distinct.
- **Evidence for the confidence badge.** Ensure each iteration record carries enough to
  compute "low-evidence verdict": neighbor count, source-layer mix, and ml-intern
  papers_stored (mostly present; confirm `retrieval` + `novelty`/`critique` rationales
  are in `loop_memory.jsonl`). A **topical-relevance signal** (hypothesis-vs-neighbor
  similarity) is the one genuinely new emit — even a cheap cosine of the hypothesis
  embedding vs neighbor embeddings, surfaced as `retrieval.relevance`.

## RENDER — UI session work (`ui/`), the three pages + a new view

**New: Coordinator / Orchestration view** (the missing cycle narrative). Card per cycle
from `coordinator_cycles.jsonl`: topic (+source badge: `coordinator`/`human`/`arxiv_pick`)
→ plan with per-action status chips (executed/skipped/**errored+error**) → linked
iteration → promoted findings → bubbles. Agent badge on the header.

**Activity page** — live + recent stream. Render the coordinator cycle's phases
(assess/plan/validate/dispatch) with narration from `active_run`; agent badges; **failed
dispatch rows shown explicitly**; qwen "empty-content/degraded" distinct from healthy.

**Dashboard page** — overview. Health row (gemma green / qwen amber-degraded / ml-intern
status); Recent Iterations **including failed/aborted rows and a coordinator-triggered
badge** (`seed.source="coordinator"`) + a **low-evidence-verdict** badge; a **Surfaced
Findings** panel (`surfaced_findings.jsonl`); a **Bubbles** panel (`coordinator_bubbles.jsonl`);
a **standing red-flags** trend strip (novel-rate, suspected-false-novel rate, off-domain rate).

**Experiment page** — experiments + **coordinator cycles as auditable units**: the plan →
outcome → evidence chain, with the epistemic basis (retrieval relevance, external-search
status, skeptic health) visible so a verdict can be trusted or doubted.

## Acceptance

- Re-run `coordinator --execute --once`: the Activity page shows the cycle's phases with
  the chosen topic + why; the Coordinator view shows the full arc; a **failed** dispatch
  appears as an explicit row (verify by forcing an error); Surfaced Findings + Bubbles
  panels populate; every row carries an agent badge; a verdict on off-domain/thin
  retrieval shows a **low-evidence** flag; qwen-degraded renders amber, not red.
