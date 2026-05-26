# Phase 1 Roadmap — Days 1–90

> The 90-day arc that closes with apparatus v1 + first findings +
> public preprint. Replaces the implicit 7-day planning horizon with
> an executable map of Days 31–60 (detailed), Days 61–90 (milestones),
> and a stub for Days 1–30 (pre-flight).
>
> Authoritative for *plan content*: `plan.yaml`. Authoritative for
> *agent posture*: [`agent/autonomy.md`](agent/autonomy.md). This
> file is the human-readable narrative tying them together.

---

## 1. The arc at a glance

| Window | Days | Goal | Status |
|---|---|---|---|
| Phase 0 — Pre-flight | 1–30 | Hardware, books, weights, credentials staged | Complete (see [`human/days_01_30_recap.md`](human/days_01_30_recap.md)) |
| **Week 1** — apparatus v0 | 31–37 | Self-hosted research loop; one synthetic-tier experiment | Days 31–36 complete; Day 37 (PD experiment + retrospective) imminent |
| **Week 2** — critic + meta-review + UI v1 | 38–44 | Add critic agent, active meta-review, auto-evaluator calibration; ship UI v1; unlock Week-2 tier shifts | Pending |
| **Week 3** — calibration + novelty | 45–51 | Rediscovery-with-holdout, novelty evaluator, degradation metrics | Pending |
| **Week 4** — first applied rung | 52–58 | Single-item auction rung; multi-candidate generation + bandit; CFTC compliance worksheet (design) | Pending |
| **Buffer + write-up** | 59–60 | Absorb slips; first preprint scope memo | Pending |
| **Phase 1 back half** | 61–90 | Phase-2 architecture; Qwen 3.6; full intelligence loop; preprint draft | Milestones only (see §6) |

---

## 2. Slip mechanism

Days are integers (31, 32, …). If a day can't complete, state tracks both:

- `current_day` — the integer day (the week marker)
- `current_subday` — appended decimal (`31.2` = second slip on day 31)

A slip is created when:

1. A `hard_gate` failure aborts the day (CLAUDE.md inviolate rule 6).
2. A `hard_gate` stays open past its 48h SLA.
3. A side-track merge requires same-day rework.
4. The human declares a slip ("today bled into tomorrow").

### 2.1 Slip task templating

For day N that slips into N.1, N.2, … the slip's task IDs are
`dayN_<S>_block2_…` where `<S>` is the subday index. Subday tasks
inherit the parent day's `autonomy_tier` unless explicitly overridden.

Example: Day 3 slipped into Day 3.5 on 2026-05-19 (the schema-amendment
day inserted between Day 3 and Day 4). Tasks were
`day3_5_block2_retrieval_context_field`,
`day3_5_block2_events_schema`,
`day3_5_block2_wrapper_retrieval_passthrough`.

### 2.2 Slip discipline

- The run log records the slip event as a first-class entry: `{kind:
  "slip_declared", parent_day, subday, reason, declared_by}`.
- The next-integer-day's preconditions still reference the parent
  integer day (so `day_4_*` depends on `day_3` cleanly, even though
  `day_3.5` ran in between).
- The state file's `current_day` advances past the slip when the slip
  succeeds; if the slip itself slips, append further subday indices
  (`3.5.1`, etc.), though in practice this rarely goes past one level.

### 2.3 When to declare a slip

- A hard-gate failure → slip is automatic (CLAUDE.md inviolate rule 6).
- A soft-gate `rejected` outcome that requires rework → declare a slip
  for the rework window.
- A bug discovered late in Block 2 that needs more than the day's
  remaining time → declare a slip; Block 3 still happens (journal,
  reading); end-of-day commits roll forward.
- Side-track merge work that bleeds into Track A's Block 2 → declare a
  slip if the merge consumes > 30 min of critical-path time.

Do **not** declare a slip just because Block 1 reading wasn't finished
— Block 1 doesn't gate Block 2 (decoupled per
[`agent/autonomy.md`](agent/autonomy.md) §7).

---

## 3. Days 1–30 — Phase 0 (stub)

Stub recap at [`human/days_01_30_recap.md`](human/days_01_30_recap.md).
Drafted from `PROJECT_CONTEXT.md`, `DECISIONS.md` (D-001…D-018),
`notes/research/`, and the user's memory. Not a day-by-day
reconstruction.

Key facts going into Day 31:
- Hardware ordered, delivered, racked.
- vLLM + Gemma 4 image pulled and verified.
- BGE-M3 weights staged at `/mnt/models/bge-m3`.
- Gemma 4 NVFP4 weights staged at `/mnt/models/gemma-4-26b-a4b-nvfp4`.
- Books pre-staged in `books/` (Osborne & Rubinstein, Cesa-Bianchi &
  Lugosi, Camerer, Bowles & Polanía-Reyes).
- API keys provisioned: `SEMANTIC_SCHOLAR_API_KEY`, `ANTHROPIC_API_KEY`
  (for the auto-evaluator escape hatch), GitHub PAT.
- Failure-mode walkthroughs rehearsed (4 of them: NemoClaw fallback,
  CUDA 13.2 trap, filesystem cache, CUTLASS gibberish).

---

## 4. Days 31–37 — Week 1 (apparatus v0)

Authoritative source: `plan.yaml` `day_1` … `day_7`. Summary:

- **Day 31 (Day 1)** — Hardware bring-up + vLLM serving + NemoClaw
  router probe (→ plain-Docker fallback per D-021).
- **Day 32 (Day 2)** — JSONL wrapper + 50-call sweep + determinism check.
- **Day 33 (Day 3)** — ChromaDB install + textbook ingest + needle
  benchmark.
- **Day 33.5** — Schema amendments (retrieval_context, events).
- **Day 34 (Day 4)** — First tool call / function calling.
- **Day 35 (Day 5)** — arXiv pipeline → 138 papers in `papers_recent`
  (D-027: switched S2 → arXiv API).
- **Day 36 (Day 6)** — OpenClaw orchestrator + first worker
  (`summarize_paper`); inspect_run CLI; cron enabled.
- **Day 37 (Day 7)** — Repeated PD experiment (100 rounds × 4
  opponents) + publication review gate + retrospective.

**Day-37 publication review gate** is `hard_gate` and stays `hard_gate`
throughout Phase 1 (never auto-clears). The agent never auto-publishes
results.

---

## 5. Days 38–60 — Weeks 2–4 detailed

Drives on the 12 items in `notes/week2_seed.md` plus the Phase-2
architectural deltas in `ARCHITECTURE.md`. Each day inherits the
Week-1 Block 1 / Block 2 / Block 3 cadence.

### Week 2 — Days 38–44 (critic + meta-review + UI v1)

| Day | Block 2 (Track A) | Side-tracks (parallel) | Gates |
|---|---|---|---|
| **38** | UI v1 deployment + Week-2 unlock attestation. Block 2 = ship the UI; it must show every Week-1 artifact correctly before any tier shift applies. Also: land `agent/ownership.yaml`, `agent/collision_protocol.md`, `run_state/claims.jsonl` empties. | Track D: UI v1 sampler + dashboard. Track B: schema amendments for human_intervention + retrieval_context + calibration_entry. | `hard_gate`: Week-2 unlock attestation (human reads alignment evidence in the UI; attests in `human/retrospectives/week2.md`). |
| **39** | W2-01 Critic agent (red-team). `workers/critic.py`; eval on 20 known-flawed hypotheses; target ≥80% substantively different critique. Also: `agent_wrapper/dispatch_coding_agent.py` lands. | Track B: critic test scaffolds. Track C: hypothesis fixture set. | Soft-gate: critic eval result. Hard-gate: dispatcher integration test. |
| **40** | W2-02 Active meta-review synthesis. `workers/meta_review.py`; 20-trial test for no duplication of last-3 hypotheses. **First orchestrator-dispatched coding agent task** lands (draft of Day-41 test scaffolds, soft-gate). | Track D: UI surfaces meta-review output. | Soft-gate: dispatched task review. |
| **41** | W2-05 Auto-evaluator calibration. 10 synthetic-tier outcomes with ground truth; κ + Spearman; threshold documented. | Track C: novel-finding fixtures. | Hard-gate: calibration threshold decision (D-NNN). |
| **42** | W2-06 Schema amendments lock; `plan.yaml` `autonomy_tier` + `dispatchable` + `target_zone` fields populated for every task. | Track B: regression tests against new schema. | Hard-gate: schema version bump. |
| **43** | W2-04 PD experiment re-run with critic in loop. First end-to-end Phase 2-architecture exercise. Soft-gate the experiment run; hard-gate the publication. | Track D: experiment-results surface. | Hard-gate: publication review. |
| **44** | Week-2 retrospective + alignment scoring + concurrency attestation (was the claim log clean? any collisions?). | All side-tracks idle. | Hard-gate: weekly retrospective. **First** of two needed for Weeks-3-4 tier-shift unlock. |

### Week 3 — Days 45–51 (calibration + novelty)

| Day | Block 2 (Track A) | Gates |
|---|---|---|
| **45** | W2-08 Rediscovery-with-holdout protocol — pick McKelvey & Palfrey 1995 QRE; remove from corpus; run loop end-to-end; score gap. Second dispatched task lands (cron script). | Hard-gate: holdout corpus integrity. |
| **46** | W2-03 Novelty evaluator — Step 8 of intelligence loop; stays `hard_gate` (load-bearing for publication integrity). | Hard-gate: novelty threshold decision. |
| **47** | W2-07 Degradation metrics — model drift, rediscovery loops, researcher calibration. Logged but no thresholds yet (Phase 2). | Soft-gate: metric definitions. |
| **48** | First orchestrator-only dispatched task — orchestrator decides what to dispatch (not the human). | Hard-gate: dispatch queue review (until alignment evidence accumulates). |
| **49** | Buffer + integration testing for Phase-2 worker chain. | Soft-gate: end-to-end test. |
| **50** | UI v2 (call-chain inspector) ship. | Hard-gate: UI v2 demo to user. |
| **51** | Week-3 retrospective + alignment scoring. **Second consecutive** weekly attestation; if clean, Weeks-3-4 tier shifts unlock. | Hard-gate: weekly retrospective + tier-shift application (if eligible). |

### Week 4 — Days 52–58 (first applied rung)

| Day | Block 2 (Track A) | Gates |
|---|---|---|
| **52** | ARCHITECTURE.md §3.2 Rung 1 — single-item auction in known-equilibrium mechanism design. | Hard-gate: mechanism choice (D-NNN). |
| **53** | W2-12 Multi-candidate generation + bandit selection — K=3 hypotheses per cycle; bandit selects 1; on 30-cycle sweep, selected beats random pick. | Soft-gate: bandit comparison. |
| **54** | W2-09/10 CFTC compliance worksheet (design-only) — Polymarket gating; not live trading. | Hard-gate: compliance design review. |
| **55** | Up to 3 concurrent dispatched coding agents (Weeks-3-4 unlock concurrency cap). Validation pass on Rung-1 mechanism + critic + meta-review. | Soft-gate: integration test. |
| **56** | Mechanism-design rung-2 sketch (combinatorial auctions; Phase 2 candidate). Day-90 preprint scope draft. | Soft-gate: preprint outline. |
| **57** | Buffer for slips from Weeks 2–4 (high probability — Week 1 already had a Day-3.5 slip). | — |
| **58** | Week-4 retrospective + Phase-1-midpoint attestation (Day 60 boundary). | Hard-gate: midpoint review. |

### Days 59–60 — buffer + write-up start

- **Day 59**: Slip absorption + first preprint scope memo
  (`notes/preprint_scope_v0.md`). What's claim-worthy? What's not?
- **Day 60**: Phase-1-midpoint attestation: alignment evidence
  cumulative; concurrency cap status; tier-shift inventory.

---

## 6. Days 61–90 — milestones only

| Day (approx) | Milestone | Gate |
|---|---|---|
| **65** | Rung 2 launch — combinatorial auctions | Hard-gate: rung-2 mechanism choice |
| **72** | Qwen 3.6 second model online (D-006) | Hard-gate: A/B comparison report |
| **80** | Full intelligence loop with all Phase-2 additions (critic, meta-review, experiment-outcome feedback) running for 1 consecutive week | Hard-gate: end-to-end week check |
| **85** | Preprint draft sent to colleague reviewers | Hard-gate: scope review (D-NNN) |
| **90** | Phase 1 exit attestation + Phase 2 entry decision | Hard-gate, no SLA |

---

## 7. Open dependencies the user must answer

Captured here so the roadmap doesn't pretend to resolve them. Each
gets `[OPEN]` in the affected day's task list when it lands.

- **[OPEN]** Exact ordering inside Week 2 if W2-01 (critic), W2-02
  (meta-review), and W2-05 (calibration) collide on the same human
  attention window.
- **[OPEN]** Whether CFTC compliance work lands in Phase 2 or only
  gates Phase 3 entry.
- **[OPEN]** Preprint scope at Day 90 — whether W2-08 (rediscovery)
  lands in time to be in scope.
- **[OPEN]** Which mechanism-design rungs (1–4) land in Phase 1 vs
  Phase 2 (Rung 1 is in Week 4; Rung 2 is Day-65-ish; Rungs 3–4
  unconfirmed).
- **[OPEN]** 80% orchestrator-dispatched target by Day 90 —
  aspirational; the actual number depends on alignment-evidence
  accumulation. Tracked but not committed.

---

## 8. How the roadmap interacts with the run log

Every day's `block_2` is bracketed in the run log by two entries:

- `day_start`: `{kind, day_id, subday, planned_tasks, autonomy_tier_inventory}`.
- `day_end`: `{kind, day_id, subday, completed_tasks, slipped_to,
  retrospective_link}`.

Slip declarations land between these as their own first-class events.
Tier shifts land as their own first-class events
(`autonomy.md` §4.2).

This means a future Track A session resuming a roadmap can read the
last `day_end` to know where the integer day pointer is, and the last
`tier_shift` to know which tier mapping applies right now.

---

## 9. Where to look next

- For agent posture (tiers, SLAs, alignment evidence):
  [`agent/autonomy.md`](agent/autonomy.md)
- For concurrent-agent coordination (claim protocol, dispatch):
  [`agent/collision_protocol.md`](agent/collision_protocol.md)
- For the human's daily cadence: [`human/daily_plan.md`](human/daily_plan.md)
- For the reading list (independent of the daily plan):
  [`human/learning_track.md`](human/learning_track.md)
- For task-level detail: `plan.yaml` (canonical) +
  [`current_day.md`](current_day.md) (live tracker).
