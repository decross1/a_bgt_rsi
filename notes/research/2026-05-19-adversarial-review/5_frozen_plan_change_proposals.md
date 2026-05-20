# Frozen-plan change proposals

> **Read this carefully.** Per the handoff prompt's hard guardrails, the
> Week 1 plan is **frozen**. Nothing in this review's "applied" deliverables
> (the architecture document patches, the v5 diagrams, the Week 2+ planning
> seed) edits `plan.yaml`, `CLAUDE.md`'s inviolate rules, or any version
> pin. This file is a **proposals-only** document — it lists three small,
> additive schema changes that would touch Week 1 (specifically, the Day 2
> JSONL schema, which is a Week 1 artifact). Each is presented with
> rationale, cost, and explicit reversibility. **They are NOT applied.**
> Huchi reviews and explicitly approves (or declines) each.

For comparison: the existing JSONL schema is the Day 2 deliverable
authored by `day2_block2_jsonl_schema` in `plan.yaml`. The schema is
load-bearing — every downstream day (Day 3 ingest logs, Day 4 tool-call
logs, Day 5 pipeline logs, Day 6 orchestrator logs, Day 7 experiment
logs) writes to it. Adding fields *additively* is straightforward;
re-typing existing fields would be a much bigger change and is not
proposed here.

---

## Proposal P1 — Add `human_intervention` event type to the run-log

**Motivation.** Verdict C4 from the adversarial review: the preprint will
face the question "how much was you?" exactly as the co-scientist's
validation experiments do. Without typed counts of human edits inside
otherwise-agent-executable tasks, the preprint cannot honestly report
N generated / M survived / K edits, and the project's headline claim
becomes harder to defend.

**Change.** Add an event type to the JSONL schema:

```json
{
  "event_type": "human_intervention",
  "timestamp": "2026-05-XX...",
  "task_id": "<the agent_executable task id>",
  "subtype": "edit_prompt | edit_code | reject | redirect | manual_decision",
  "reason": "<free-text, human-supplied>",
  "context_hash": "<hash of the task state at intervention>"
}
```

This is distinct from existing `human_only` task entries (which are
*scheduled* human work) and from `gate_clear` events (which are
human-gate clearance). This event captures human action *inside* an
otherwise-agent task.

**Cost.** ~30 minutes of schema work, ~30 minutes of wrapper
instrumentation, ~30 minutes of CLAUDE.md prose update telling Claude
when to emit the event (or how to flag for the human to emit it). One
hour total, additive, no existing field changes.

**Touches Week 1?** Yes — the Day 2 schema is a Week 1 artifact. The
schema validation in `day2_block2_jsonl_schema` would need to accept
the new event_type. The wrapper instrumentation goes in `agent_wrapper/`.
None of the existing Day 1–7 tasks change.

**Reversibility.** Trivial. Remove the event type from the schema enum;
existing logs without the event type remain valid.

**Risk if NOT adopted.** The preprint defensibility argument weakens.
Week 1 produces Day 7 data without the typed events, so the entire week
is unaccounted-for human-intervention-wise. Phase 1's first preprint
materially benefits from having these events from Day 1, not from
Day 8 onward. This is the strongest case for approving the proposal.

**Risk if adopted.** Marginal Week 1 schedule risk if the schema work
slips. Mitigation: schema work is a known-quantity hour, not novel
engineering.

**Recommendation.** Approve. This is the single most important Stage-2
finding by impact-per-cost.

---

## Proposal P2 — Add `retrieval_context` field to wrapper call records

**Motivation.** Missed-gap M1 from the adversarial review: the
reproducibility commitment in `PROJECT_CONTEXT.md` §3 — "every model
call is a research observation" — is not actually true if retrieved
literature is part of the prompt but not pinned in the log. Retrieval
drifts as the corpus grows; without per-call provenance the exact
literature context a hypothesis was generated against cannot be
reconstructed.

**Change.** Add a field to the existing wrapper call schema (not a new
event type — an addition to an existing record):

```json
{
  ...existing fields...,
  "retrieval_context": [
    {"doc_id": "arxiv:2401.12345", "content_hash": "sha256:...",
     "chunk_offset": 1024, "chunk_length": 512}
  ]
}
```

`retrieval_context` is `null` when no retrieval was performed (most
calls). It is a list when one or more retrievals contributed to the
prompt — typically generator calls and novelty-evaluation calls.

**Cost.** ~1 hour: ~15 minutes schema, ~30 minutes wrapper change to
plumb the retrieval results into the call record, ~15 minutes test
update.

**Touches Week 1?** Yes — Day 2 schema and Day 3 ingest are both
affected. Day 3's `day3_block2_chunking_and_ingest_script` already
produces chunks with offsets; the schema change just *requires* them
to be persisted. Day 4 tool-call work (`day4_block2_e2e_test`) becomes
a slightly richer test (it should verify `retrieval_context` is
populated when a retrieval tool is called).

**Reversibility.** Easy. The field is nullable; older code that
doesn't populate it still produces valid logs.

**Risk if NOT adopted.** A reproducibility claim that doesn't survive
scrutiny. The Day 7 experiment's strategies file is not the issue —
that's deterministic. The issue is the hypothesis generator's context
in Week 2+ once the literature pipeline is feeding it. A reviewer
asking "what literature was the loop conditioned on when it produced
finding X?" gets "we have the timestamp, you'll have to trust that
ChromaDB hasn't changed since" — which is exactly the answer the
project wants to avoid.

**Risk if adopted.** Wrapper change is non-trivial because it requires
plumbing the retrieval tool's output into the call record. The Day 4
tool-call work is where this naturally fits, so the adoption window is
narrow (after Day 2 schema lands and before Day 4 tool work hardens).

**Recommendation.** Approve, with adoption sequenced *after* Day 2
schema is committed and *before* Day 4 tool-call work concludes. This
makes the change a Day 3-evening or Day 4-morning insertion, not a
back-edit.

---

## Proposal P3 — Add `calibration_entry` event type

**Motivation.** Missed-gap M2 from the adversarial review: the human's
pre-experiment expected range is already an artifact of Day 7 (per
`plan.yaml` `day7_block2_run_experiment`'s `on_failure` clause). Over
Phase 1, repeated calibration of the researcher's expected ranges
against measured outcomes is research data — if the researcher's
calibration improves, the apparatus is teaching the human; if it
doesn't, the human is the bottleneck on what the loop can surface.
Per-person calibration metrics over time are publishable on their own.

**Change.** Add an event type to the JSONL schema:

```json
{
  "event_type": "calibration_entry",
  "timestamp": "2026-05-XX...",
  "experiment_id": "exp001_repeated_pd",
  "metric_name": "coop_rate_vs_tft",
  "pre_experiment_expected_range": [low, high],
  "post_experiment_observed": value,
  "within_range": true|false,
  "human_attestation": "<free-text>"
}
```

The Day 7 hard checkpoint *already* compares observed to expected; this
proposal asks the agent to write the comparison to the run log as a
typed event instead of (or in addition to) the implicit
`day7_coop_rate_vs_tft` `metric_log_key`.

**Cost.** ~30 minutes: ~15 minutes schema, ~15 minutes wrapper
instrumentation. The simplest of the three proposals.

**Touches Week 1?** Yes — the Day 7 quicklook script
(`day7_block2_quicklook`) would need to emit the event. The expected
range is currently elicited at experiment-design time (Day 4–5); the
human's value gets attested into the log at run time.

**Reversibility.** Trivial.

**Risk if NOT adopted.** The Day 7 experiment is the *first* data point
in what could be a 90-day calibration series; missing it means the
series starts at Day 8 of Week 2 at the earliest. Week 1 has one shot
at this and it's already designed.

**Risk if adopted.** Negligible.

**Recommendation.** Approve. Cheapest of the three; loses nothing if
the calibration data turns out to be uninteresting; gains a publishable
metric if it turns out interesting.

---

## Summary table

| # | Proposal | Cost | Risk if rejected | Recommendation |
|---|---|---|---|---|
| P1 | `human_intervention` event type | ~1 hr | Preprint defensibility weakens | **Approve** |
| P2 | `retrieval_context` field | ~1 hr | Reproducibility claim becomes weak | **Approve**, sequence carefully |
| P3 | `calibration_entry` event type | ~30 min | Lose Day 7 as first calibration point | **Approve** |

All three are additive, reversible, and complete within a combined ~2.5
hours of focused work. None touches version pins, human-only blocks,
human gates, or hard checkpoints. None creates new dependencies. None
moves the autonomy boundary.

## What is NOT proposed

To be explicit about what this review does NOT propose for Week 1:

- No change to the Day 1–7 task ladder.
- No change to version pins (`vllm/vllm-openai:v0.21.0`, CUDA 13.0,
  BGE-M3, `--moe-backend marlin`, NVFP4 weights path).
- No change to the Day 7 publication review gate.
- No change to Block 1's human-only rule.
- No change to hard checkpoints or their abort semantics.
- No new task added to `plan.yaml`'s day sections.
- No new dependency (no critic worker in Week 1; no meta-review worker
  in Week 1; no second model in Week 1).
- No change to CLAUDE.md's inviolate rules. (The new
  `human_intervention` event type does add to CLAUDE.md prose, but as
  *additional* logging guidance, not as a relaxation of any rule.)

If any of P1–P3 are approved, the corresponding edit to `plan.yaml`'s
Day 2 schema task and to CLAUDE.md is a *follow-up*, executed by Huchi
or under explicit Huchi approval — not by the agent in the course of
this review.

---

## Decision form (to be filled by Huchi)

```
P1 — human_intervention event type
  [ ] Approve  [ ] Defer to Week 2  [ ] Decline

P2 — retrieval_context field
  [ ] Approve  [ ] Defer to Week 2  [ ] Decline

P3 — calibration_entry event type
  [ ] Approve  [ ] Defer to Week 2  [ ] Decline

Date:
Signed:
```
