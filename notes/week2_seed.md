# Week 2+ planning seed — insights from the adversarial review

> **What this is.** A *seed* for Week 2's planning task, capturing the
> validated insights from the adversarial review that belong in Weeks 2–4
> implementation. **This is not a Week 2 plan.** Per the handoff prompt's
> guardrails, writing the Week 2 plan is a separate task. This file
> exists so that when Week 2 planning happens, the architectural
> decisions from this review are already in front of the planner.
>
> Each insight gets: a name, a one-sentence success criterion, an
> estimated phase (Phase 1 still possible vs. Phase 2 only), and a
> rough sequencing hint. Anything that would touch Week 1 itself is
> NOT here — it's in `5_frozen_plan_change_proposals.md`.

---

## Items that should land in Weeks 2–4

### W2-01 — Critic agent (red-team prompt pattern)

**One-sentence success criterion.** A `workers/critic.py` worker reads a
hypothesis and emits a structured red-team critique; in a calibration
sweep, the critic produces a substantively different critique on ≥ 80 %
of 20 known-flawed test hypotheses (test set authored by the human).

**Sequencing.** Implementable on day-one of Week 2 (single-model
pattern, no new dependencies). Lands before any expansion of experiment
domains.

**Rationale.** Insight O1 — protect scarce experiment budget by
falsifying hypotheses before dispatch. Consistent with D-012 (no
second model required).

### W2-02 — Active meta-review synthesis worker

**One-sentence success criterion.** A `workers/meta_review.py` worker
reads the last N entries from Layer 3 of the knowledge base and emits
3–5 conditioning bullets that, when included in the generator's
prompt, cause the generator to avoid duplicating any of the last 3
hypotheses in a 20-trial test.

**Sequencing.** Week 2–3. Cannot land until Layer 3 has accumulated
≥ 10 entries (i.e., after Week 1's single Day 7 entry plus a few more
Week 2 cycles).

**Rationale.** Insight O2 — make Layer 3 an active read, not a passive
library. Closes the gap between "we have loop memory" and "the loop
uses it."

### W2-03 — Per-hypothesis compute budget in the orchestrator

**One-sentence success criterion.** The orchestrator deducts measured
GPU-time per worker call against a per-hypothesis budget (defaulting
to 30 min for a synthetic-tier experiment); a worker that would exceed
the budget gets a clean early-stop signal; the JSONL records
`budget_remaining_at_completion` per hypothesis.

**Sequencing.** Week 2. Requires the wrapper's `latency_ms` field
(Day 2) to already exist, which it does.

**Rationale.** Insight O3 — GPU-hours are the binding Phase 2
constraint and currently untracked at the hypothesis granularity.

### W2-04 — Cost-aware bandit reward

**One-sentence success criterion.** The keep/discard bandit's reward
function (from D-010) reads `compute_consumed` (per W2-03) and
normalizes the reward as skill-per-GPU-hour rather than raw skill; a
unit test confirms two hypotheses with equal skill but 10× compute
difference get 10× different rewards.

**Sequencing.** Week 3, after W2-03 lands. Phase 2 only — D-010
explicitly defers the bandit to Phase 2.

**Rationale.** Insight O3 — without cost-normalization, the bandit
preferentially selects compute-heavy hypotheses.

### W2-05 — Calibration of auto-evaluator against synthetic-tier ground truth

**One-sentence success criterion.** Run the same Gemma 4 endpoint that
will score semi-synthetic findings on a held-out set of 10
synthetic-tier outcomes (where ground truth is known, e.g.,
cooperation rate against TFT); measure agreement (κ or Spearman) and
document the threshold below which auto-scoring is not trusted for
semi-synthetic.

**Sequencing.** Week 3 — once the synthetic tier has produced enough
outcomes (the Day 7 experiment is one; Week 2 will add more). Must
land *before* any semi-synthetic claim is auto-scored.

**Rationale.** Lower-priority insight from the prior analysis. Avoids
the co-scientist's Elo-circularity in the semi-synthetic tier where
ground truth doesn't exist.

### W2-06 — Test-time-compute knob experiment at 26B

**One-sentence success criterion.** A single experiment compares
hypothesis quality with 0, 1, and 3 rounds of self-critique →
re-generation cycles on the same 20-hypothesis test set; quality is
scored by the calibrated auto-evaluator from W2-05 plus a human
sample; the experiment reports whether self-critique improves or
degrades quality at 26B.

**Sequencing.** Week 3–4, after W2-01 (critic) and W2-05
(calibrated auto-evaluator) are in place.

**Rationale.** Lower-priority insight from the prior analysis. The
co-scientist's headline improvement curves are at Gemini 2.0; at 26B
the critique loop *may* amplify errors. This experiment tells us.

### W2-07 — Six-role agent taxonomy as Week 2–4 worker menu

**Sequencing & criterion combined.** Map the co-scientist's six roles
onto the project's worker plan as follows; commit to *some* in
Weeks 2–4 with the success criterion being "worker exists with a
contract, gets called by the orchestrator in ≥ 5 cycles, and has at
least one JSONL log line."

| co-scientist role | this project's worker | week target |
|---|---|---|
| Generation | existing generator | already live (Day 6) |
| Reflection | critic / red-team | W2-01, Week 2 |
| Ranking | bandit keep/discard | W2-04, Week 3 |
| Evolution | not in scope Phase 1; possible Phase 2 if "evolve a single hypothesis variant" becomes useful | deferred |
| Proximity | clustering hypotheses by similarity — Phase 2 once Layer 3 is dense | deferred |
| Meta-review | meta-review synthesis | W2-02, Week 2–3 |

**Rationale.** Lower-priority insight from the prior analysis.
Taxonomy as menu, not as mandate.

### W2-08 — Rediscovery-with-holdout evaluation protocol

**One-sentence success criterion.** Pick one known result in
game-theory (e.g., McKelvey & Palfrey 1995 QRE behavior in matching
pennies); remove from the foundational corpus and any literature
references; run the loop end-to-end on a hypothesis-shaped question
that should rediscover that result; score the gap between the loop's
output and the actual known finding.

**Sequencing.** Week 4 at the earliest — requires a stable loop end-
to-end and a non-trivial corpus. This is *the* clean test of "does
the loop add signal." Worth doing on a dedicated test corpus rather
than perturbing the production knowledge base.

**Rationale.** Lower-priority insight from the prior analysis.
Methodologically the most defensible single test the project can do.

### W2-09 — Concurrency design

**One-sentence success criterion.** Two worker processes run in
parallel (e.g., literature-summarize + experiment-execute) without
race conditions on the JSONL log; integrity tests pass on a 100-call
sweep.

**Sequencing.** Week 2 — explicit "no concurrency in Week 1" rule
expires here.

**Rationale.** Carries over from Appendix A "What this plan
deliberately does NOT do in Week 1." Not from the adversarial review
proper; included here because Week 2 planning needs to assume it.

### W2-10 — Structured-claim search alongside semantic retrieval

**One-sentence success criterion.** The novelty checker extracts a
structured claim of form `(X, Y, Z)` from a candidate finding and runs
a structured-query search against ChromaDB metadata + Semantic
Scholar; in a 20-finding test set including 10 known restatements of
classical results, the structured search surfaces the prior in ≥ 8 of
10, including ≥ 3 cases where BGE-M3 semantic search alone misses
them.

**Sequencing.** Week 3–4. Cannot land before W2-05 (the auto-evaluator
calibration is a prerequisite for trusting the novelty checker's
auto-call).

**Rationale.** Missed-gap M3 — the novelty checker's pre-arXiv blind
spot.

### W2-11 — Model-degradation canary task

**One-sentence success criterion.** A fixed-prompt fixed-seed call
runs every 4 hours against the live orchestrator; its output is
scored against a stored baseline (BLEU or string overlap, whichever
is stable for the canary prompt); a > 10 % drift triggers a
notification to the human.

**Sequencing.** Week 2 — small, independent, useful day-one.

**Rationale.** Missed-gap M4 — silent model drift.

### W2-12 — Multi-candidate generation + bandit selection (tournament-style exploration)

**One-sentence success criterion.** The orchestrator can request K (=3
to start) hypotheses per generation cycle; the keep/discard bandit
selects 1 for experiment dispatch; the remaining K-1 are logged but
not run; on a 30-cycle sweep, the bandit-selected hypothesis beats a
random pick from the K on the calibrated auto-evaluator score.

**Sequencing.** Week 4 — requires W2-04 (cost-aware bandit). Phase 2.

**Rationale.** Missed-gap M5 — the project's robustness battery is
falsification, not exploration. Multi-candidate generation is the
exploration layer the architecture currently lacks.

---

## What this seed deliberately does NOT decide

- Whether Polymarket goes live in Phase 2. That's the program's call,
  not this review's. (Phase 2+ per program; design-only in Phase 1.)
- Whether Qwen 3.6 lands in Week 2 or Week 3. That's a separate
  decision (D-006 has it as "Week 2-3"). Several items above (W2-05's
  generator-scorer separation, W2-12's multi-candidate bandit) become
  meaningfully better when Qwen 3.6 is live; the Week 2 planner can
  decide whether to wait.
- Whether the preprint timing in Phase 1 stays at "by Day 90." Some
  items above (W2-08 in particular) take long enough that they would
  push the preprint out. The Week 2 planner should consider this.

---

## Cross-cutting note for the Week 2 planner

The validated insights from this review do not change the *shape* of
Phase 1. They change two things:

1. **What goes into the run-log schema** — three new event types
   (`human_intervention`, `retrieval_context`, `calibration_entry`)
   that touch Week 1 and are proposed in
   `5_frozen_plan_change_proposals.md`. If those proposals are
   approved, the Week 2 plan can assume the schema is in place. If not,
   the Week 2 plan should add the schema work as an early-Week-2 task.

2. **What the orchestrator dispatches** — three new worker types
   (`critic`, `meta_review`, `degradation_canary`) and three new
   orchestrator-level concerns (compute budget, cost-aware bandit
   reward, structured-claim novelty search). These all fit on the
   existing worker contract (D-013, Pi-shaped) and require no harness
   changes.

The list above is the work that survives Stage 2. It is not exhaustive —
Week 2 will surface its own work — but it is the floor on what the
adversarial review's validated insights demand.
