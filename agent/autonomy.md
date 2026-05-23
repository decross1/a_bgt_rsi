# Agent autonomy framework

> Authoritative reference for **agent autonomy posture** across Phase 1.
> Read by every Claude Code session after `CLAUDE.md`. Companion to
> [`agent/orchestration.md`](orchestration.md) (who launches sessions),
> [`agent/ownership.yaml`](ownership.yaml) (which paths each track owns),
> and [`agent/collision_protocol.md`](collision_protocol.md) (how
> concurrent agents claim files).
>
> Where this file disagrees with prose elsewhere, **this file wins**.
> Where this file disagrees with `plan.yaml`, plan.yaml wins on task
> content; this file wins on tier assignment.

---

## 1. The three tiers

Every task in `plan.yaml` carries an `autonomy_tier` field with exactly
one of these values.

| Tier | Default action | Halts when | Examples |
|---|---|---|---|
| **`autonomous`** | Proceed; log every step to the run log | Never within the tier's domain | Daily arXiv ingest cron; log rotation; deterministic file-integrity checks; retrospective ops |
| **`soft_gate`** | Proceed; record an *attestation request* in `run_state/attestations.jsonl`; allow rollback within the SLA window | Only if the human marks the attestation `rejected` | Determinism check; ChromaDB metadata verification; prompt grep; 4-of-5 robustness; credentials check |
| **`hard_gate`** | Halt at entry; record gate in `state.human_gates_pending`; wait for explicit attestation | On entry | Block 1 reading + problem set; Day 7 publication review; schema/contract authoring; MARLIN backend startup; novel-result evaluation (Phase 2); retrospective |

A task **never** silently changes tier. Tier transitions are governed
by phase-aware unlocks (§3) and recorded in the run log.

---

## 2. SLA discipline

Per-tier SLAs determine what happens when the human is unavailable.

| Tier | SLA | On expiry |
|---|---|---|
| `soft_gate` | **4 hours** | Auto-clear: append `{kind: "no_objection", task_id, original_request_ts, cleared_ts}` to `run_state/attestations.jsonl`; record the auto-clear in `run_state/week1.run.jsonl` |
| `hard_gate` | **48 hours** | Escalate: append to `run_state/escalations.jsonl`; optionally fire a notification hook; **gate stays halted** |
| Block 1 (pedagogy) | **none** | Human attestation required. Never auto-clears. |

The cron-driven sweeper is [`tools/gate_sla_check.py`](../tools/gate_sla_check.py).
Track A is the only writer for `state.human_gates_pending`. The
sweeper reads and appends; it never mutates state directly.

### 2.1 Soft-gate attestation lifecycle

```
agent appends "request"  →  human reviews via UI
        │                          │
        │                          ├── "approved"  → append "approved";  agent continues
        │                          └── "rejected" → append "rejected";  agent rolls back per task's rollback recipe
        │
        └── after SLA (4h, no human input)
                                   → append "no_objection"; treated as approved
```

The `request` entry SHOULD include enough context for the human to
decide without re-running anything (the actual observed value, the
expected band, the relevant artifact paths). The agent is **proceeding**
during the SLA window — soft-gates do not block forward progress.
Rollback happens after the fact, within the rollback window the task
declares (`rollback_window_hours`, default = SLA + 2h).

### 2.2 Hard-gate escalation lifecycle

```
agent enters task  →  appends entry to state.human_gates_pending  →  HALTS
                                                                       │
                                              human attestation ───────┘
                                                                       │
                            after 48h (no attestation) → sweeper appends to escalations.jsonl,
                                                          stays halted, optionally notifies
```

Hard-gates do **not** auto-clear. The escalation is informational — to
get someone's attention — but the gate itself remains until a human
explicitly clears it.

---

## 3. Phase-aware tier boundaries

Tiers don't move; the *classification of tasks into tiers* moves as
observability matures. Unlocks are gated on the **alignment evidence**
defined in §4, not on calendar dates.

| Phase boundary | Trigger (not calendar) | Tier shifts unlocked |
|---|---|---|
| **Week 1 baseline** | Current — apparatus v0 not yet validated end-to-end | All 13 today-hard-checkpoints stay `hard_gate`; all 35 today-human-only stay as-is |
| **Week 2 unlock** | UI v1 deployed; sampler running; dashboard live; 1 week of clean run-log integrity | Determinism check, ChromaDB metadata, prompt grep, robustness mini → `soft_gate`. Credentials check → `autonomous` (env-var verifier). Day-5 arxiv cross-check → `soft_gate` (agent samples + posts to UI for human scan). |
| **Weeks 3–4 unlock** | UI v2 (call-chain inspector) live; 2 weeks of consistent alignment; zero silent drift detections | + Hyperparameter tuning, retrieval relevance scoring → `soft_gate`. Daily ingest + log review → `autonomous`. |
| **Phase 2 entry (~Day 91)** | UI showing consistent alignment for 4+ consecutive weeks; meta-review + critic agents shipped; auto-evaluator calibrated (W2-05) | Hypothesis generation, experiment runs → `soft_gate` (was `hard_gate`). Critic verdict + meta-review synthesis → `autonomous`. `hard_gate` retained only for: Block 1, publication, novel-finding evaluation (Step 8 of the intelligence loop), resource budget violations. |

The `plan.yaml` field `autonomy_tier_after_unlock` carries the
post-Week-2-unlock tier value. The sweeper applies it automatically
when the phase boundary advances (§4.2).

---

## 4. Alignment — the load-bearing definition

A phase boundary advances **only** when the human attests, in a weekly
retrospective, that the following hold over a rolling 7-day window:

1. **Decision parity.** For every task the system *would have* halted
   at (had the gate been `hard_gate`), the human, looking at the UI
   retrospectively, agrees the halt was warranted — OR — the human
   agrees the auto-proceed was correct. Disagreement rate **≤ 1 case
   per week**.
2. **No silent metric drift.** Retrospective audits of `metric_log`
   entries show drift ≤ **5%** between consecutive runs of the same
   task.
3. **Run-log integrity.** `verify_log_integrity` reports **0**
   malformed entries across `run_state/week1.run.jsonl`,
   `run_state/attestations.jsonl`, and `run_state/escalations.jsonl`.
4. **Claim-protocol cleanliness.** [`tools/claims_check.py`](../tools/claims_check.py)
   reports zero overlapping claims and zero expired-claim writes
   across the window. See [`agent/collision_protocol.md`](collision_protocol.md).

The retrospective writes the attestation to
`human/retrospectives/weekN.md`. **Two consecutive weekly attestations**
are required to advance a phase boundary — this prevents a single
optimistic week from unlocking too much.

### 4.1 Trust trajectory

The user's stated trajectory: start at the **tiered + phase-aware**
posture; expand toward **trust-by-default** as the UI proves it shows
the human what the system is doing. Concretely, "trust-by-default"
means: `hard_gate` retained only for Block 1, publication, novel-finding
evaluation, and resource budget violations. Everything else becomes
`soft_gate` or `autonomous`.

The trajectory is **not calendar-driven**. If alignment evidence
plateaus, the posture does too. If alignment degrades, the posture
walks back: `autonomous` → `soft_gate` → `hard_gate` (the same shifts
in reverse).

### 4.2 Applying a tier shift

When two consecutive retrospectives clear the bar, Track A:

1. Reads `agent/autonomy.md` §3 to identify which tasks advance.
2. For each affected task, swaps the `autonomy_tier` value to its
   `autonomy_tier_after_unlock` value in `plan.yaml`.
3. Appends a single `tier_shift` entry to `run_state/week1.run.jsonl`
   recording the affected task IDs, the prior tier, the new tier, and
   the retrospective references that authorized the shift.
4. Commits with message `tier shift: week N → unlock; tasks: <list>`.

Tier walk-backs follow the same procedure with the directionality
reversed.

---

## 5. Parallel axis: who can dispatch (§7.5 of the restructure plan)

This file governs **what** is autonomous. A *separate* axis governs
**who can launch agents**: today the human launches each Claude Code
session manually; the trajectory is toward orchestrator-dispatched
coding agents. That axis is defined in
[`agent/collision_protocol.md`](collision_protocol.md) §3 and uses the
same alignment evidence (§4 above) as its unlock criterion. The two
axes can advance independently.

---

## 6. The Week-1 inviolate core (does NOT relax)

Regardless of phase boundary or alignment evidence:

1. **No Block 1.** Every Block 1 task stays `hard_gate` with no SLA.
   The agent prints the reading and problem set, sets a timer, and
   HALTS. Cleared only by human attestation.
2. **Day 7 publication review** (`day7_publication_review_gate`)
   stays `hard_gate`. The agent never auto-publishes results.
3. **Version pins are verbatim.** See [`ARCHITECTURE.md`](../ARCHITECTURE.md)
   §2 for the canonical pin table. Wrong pins do not negotiate.
4. **MARLIN backend startup check** stays `hard_gate`. Wrong backend
   (CUTLASS_FP4 instead of MARLIN) corrupts every downstream
   experiment; this is not a soft-gate candidate.
5. **Schema and worker-contract authoring** stay `hard_gate`. The
   human authors the contract; the agent validates. The agent does
   not author load-bearing contracts.
6. **Validation rigor.** Each bullet under a `validation:` block is
   an independent pass/fail check. Mismatches are reported, never
   coerced. "Below band but close" is a failure unless the source
   explicitly bands it as informational.
7. **State-file authoring.** Only Track A writes to
   `run_state/week1.state.json` and `run_state/week1.run.jsonl`.
   Other tracks append to their own JSONL (`attestations.jsonl`,
   `escalations.jsonl`, `claims.jsonl`).

These items are repeated in [`CLAUDE.md`](../CLAUDE.md) because they
are inviolate. If a future revision of this file removes them, that
revision is wrong.

---

## 7. Decoupling from the human's learning track

`plan.yaml` no longer makes Block 1 a `precondition:` of any Block 2
task. Block 1 progress is a *parallel rail*, tracked in
[`human/learning_track.md`](../human/learning_track.md) and attested
weekly in retrospectives. The agent proceeds on Block 2 work whether
or not the human has finished today's reading.

The exception list — tasks where human understanding **is** the
content, not background — is in `plan.yaml` itself via the
`requires_human_understanding: <topic>` field. Those tasks stay
`hard_gate` regardless of phase boundary:

- JSONL schema authoring (`day2_block2_jsonl_schema`)
- Worker contract authoring (`day6_block2_worker_contract`)
- Expected-range pre-specification (`day7_block2_precompute_expected_range`)
- Publication review (`day7_publication_review_gate`)
- Architectural decision points (every new `D-NNN` entry)
- System-failure escalations (agent posts state to UI; human decides direction)
- Phase 2 hypothesis-generation onboarding (first cycle per topic only)

Everything else: agent proceeds. The human reads in parallel and
catches up via the UI.
