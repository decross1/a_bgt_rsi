# Week 1 retrospective — Days 31–37

> First weekly attestation. Records what shipped, what surprised, and
> the **alignment evidence** that gates Week-2 tier-shift unlocks.
>
> Authoritative for: which tasks the human attests are
> reproducible / understood / trusted; whether the Week-2 unlock
> conditions in [`../../agent/autonomy.md`](../../agent/autonomy.md) §3
> are met.
>
> Format follows the six retrospective questions from Day 7. Human
> writes prose; agent appends `{kind: "retrospective_recorded",
> week, attested_by, ts}` to the run log when the file is committed.

---

## 0. Status as of writing

_Current state when this retrospective is being drafted. Update at end
of Day 7._

- `state.current_day`: `day_7` (Day 37) — last task completed:
  `day6_end_of_day_artifacts` (committed 66d7318).
- Tracks merged this week:
  - Track B day-3 schemas → merged Day 5 morning.
  - Track C day-3 arxiv pipeline → merged Day 5 morning.
  - Track C day-4 PD strategies → merged Day 7 morning (pending).
  - Track C day-5 inspect_run → merged Day 6 morning (commit `7741795`).
  - Track C day-6 quicklook → merged Day 7 morning (commit `98898ff`).
  - Track D day-4 UI sync → merged Day 5 (commit `e154814`).
- Pending gates: Day-7 publication review gate (`day7_publication_review_gate`)
  will land in `state.human_gates_pending` after Day-7 experiment
  completes.

---

## 1. What I shipped (chronologically)

_Every artifact, every day. Be honest about what landed and what
slipped. Day-by-day summary is also in [`../../current_day.md`](../../current_day.md);
this section is your narrative._

- **Day 1 (Day 31)**: …
- **Day 2 (Day 32)**: …
- **Day 3 (Day 33)**: …
- **Day 3.5**: schema amendments (retrieval_context, events)
- **Day 4 (Day 34)**: …
- **Day 5 (Day 35)**: arXiv pipeline (138 papers ingested into
  `papers_recent`, BGE-M3, 7-day window). Source switched
  S2 → arXiv API (D-027).
- **Day 6 (Day 36)**: OpenClaw orchestrator on multiprocessing
  fallback (NemoClaw skipped per D-021); 5/5 sequential workers + 1
  malformed rejection passed; `inspect_run.py` integrated. Cron
  enabled (03:00 nightly).
- **Day 7 (Day 37)**: …

## 2. What broke

_Every error, every workaround that survived as code, every "I'll fix
this later" that didn't get fixed. The painful list, written for your
future self._

- …

## 3. What surprised me

_3× as long, 0.3× as long, "this turned out to matter more than I
thought," "this turned out to matter less.""_

- …

## 4. What I changed in the plan vs the original Day 1 design

_Decisions made mid-week that weren't in the original plan.yaml or
PROJECT_CONTEXT.md. Cross-reference DECISIONS.md D-019 through
D-027 — these are the locked changes._

- D-019 → D-022: MTP enabled on vLLM v0.21.0 (32 → 69 tok/s).
- D-023: needle-haystack score band updated from "≥0.85" to "≥0.7"
  (informational; rationale recorded).
- D-024 / D-025: from the adversarial review notes; recorded outcomes.
- D-026: Day-4 jsonl-integrity check amended (≥30 total entries →
  per-artifact counts).
- D-027: pipeline source switched Semantic Scholar → arXiv API
  (S2 lag).
- …

## 5. Where Week 1 deviates from the research program document

_Comparisons to PROJECT_CONTEXT.md / ARCHITECTURE.md. What did we
build that wasn't planned? What didn't we build that was planned?_

- …

## 6. What Week 2 needs to do — top 5 priorities

_Each with a one-sentence success criterion. This is the seed for
the Week-2 detailed plan in PHASE_1_ROADMAP.md §5._

1. **UI v1 deployment** — success: dashboard shows every Week-1
   artifact correctly; alignment evidence visible to the human.
2. **W2-01 Critic agent** — success: ≥80% substantively different
   critique on 20 known-flawed hypotheses.
3. **W2-02 Active meta-review synthesis** — success: no duplication
   of last 3 hypotheses in a 20-trial test.
4. **W2-05 Auto-evaluator calibration** — success: κ + Spearman on
   10 synthetic-tier ground-truth outcomes; threshold documented.
5. **Dispatcher plumbing** — success:
   `agent_wrapper/dispatch_coding_agent.py` lands; first
   orchestrator-dispatched task merges via soft-gate.

---

## 7. Alignment evidence (load-bearing — gates the Week-2 unlock)

Per [`../../agent/autonomy.md`](../../agent/autonomy.md) §4. To pass,
ALL four must hold over the rolling 7-day window (Days 31–37):

- [ ] **Decision parity.** For each task this week, if I look at the
      UI retrospectively, would I have made the same halt-or-proceed
      call as the system did? Disagreement count: __ /
      eligible-task-count. Target: ≤ 1.
- [ ] **No silent metric drift.** Did any metric_log entry move > 5%
      between consecutive runs of the same task? Drift > 5%: __ /
      task-count. Target: 0.
- [ ] **Run-log integrity.** `verify_log_integrity` on
      `run_state/week1.run.jsonl` returns ___. Target: 0
      malformed.
- [ ] **Claim-protocol cleanliness.** `tools/claims_check.py
      --weekly-summary` reports __ overlapping claims, __
      expired-claim writes. Target: 0 each. (Note: claims.jsonl
      may be empty for Week 1; that's fine — protocol begins Week 2.)

If all four boxes are checked, this is the **first** of two
consecutive weekly attestations needed to authorize Week-2 unlock
tier shifts. Without the second (week2.md), no shifts apply.

---

## 8. Phase boundary inventory

What was hard-gate this week and would shift on Week-2 unlock:

- `preflight_credentials_staged` → autonomous (env-var verifier)
- `day2_block2_50call_sweep` → soft_gate (4h SLA)
- `day3_block2_chroma_install` → soft_gate
- `day6_block2_robustness_mini` → soft_gate (≥4/5)
- `day7_block2_strategies_and_llm_agent` (prompt grep) → soft_gate
- Day-5 arxiv cross-check `[GATE]` → soft_gate

If alignment evidence passes here AND in week2.md, Track A applies
the shifts and logs a `tier_shift` event in the run log.

---

## 9. Block-1 progress (informational; not gating)

From [`../learning_track.md`](../learning_track.md):

- Chapters completed this week: ___ / 7 planned.
- Keystone problems completed: ___ / 2 in Week 1.
- Chapters slipped to Week 2: ___ .
- Surprises in reading: ___

This section is informational. Block 1 progress does NOT gate the
Week-2 unlock. The human's understanding for *specific* hard-gate
tasks (schema authoring, contract authoring, expected-range pre-spec,
publication review) is gated per-task via
`requires_human_understanding: true` in `plan.yaml`.

---

## 10. Attestation

_Date this retrospective was written and committed:_ ____.

_Attested by:_ Derrick Cross.

_Hash of this commit:_ ____. (Track A's commit message: `retrospective:
week1 attestation`.)
