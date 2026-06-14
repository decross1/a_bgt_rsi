> Imported from ~/.claude/plans/snoopy-hopping-milner.md on 2026-06-14; scratch original; reference-only.

# Documentation restructure + autonomy framework + 30-day roadmap

## Context

The project is at the end of Week 1 of Phase 1 (Day 5 complete, Day 6 about to start). Today's documentation set was designed for a 7-day critical path with belt-and-suspenders gating: default-halt, fail-closed, indefinite blocks on every checkpoint. That posture was correct for hardware bring-up and the first apparatus build, but it now under-serves the next 30+ days for three reasons the user surfaced:

1. **Human and agent work are interleaved across files.** `plan.yaml`, `HUMAN_PLAN.md`, `CLAUDE.md`, and `AGENT_PLAN.md` each mix instructions for both audiences. As the system becomes more agentic, that mix produces friction (humans wading through agent contracts; agents reading prose meant for humans) and makes it hard to evolve either side independently.

2. **Every checkpoint is gated equally.** All 13 `hard_checkpoint: true` tasks halt the day on failure; all 35 `human_only: true` tasks block indefinitely. In practice ~7 are truly load-bearing (Block 1 pedagogy, publication review, schema/contract authoring, MARLIN backend correctness, retrospective). The rest are technical checks (determinism, ChromaDB metadata, prompt grep, robustness mini, credentials) that could flag-and-continue without breaking the apparatus. Treating both classes the same prevents the system from running more autonomously even when it safely could.

3. **Planning horizon is 7 days.** The 90-day Phase 1 arc is described in `PROJECT_CONTEXT.md` and `notes/week2_seed.md`, but there is no executable roadmap past Day 37. Days 1–30 (pre-flight) are referenced but not committed. Without a longer horizon, every week's planning happens under time pressure inside the prior week.

The restructure addresses all three. It is **bold** per the user: new files, audience-segregated directories, a formal autonomy framework with phase-aware tiers and SLAs, and a 30-day detailed roadmap with explicit slip semantics. The trajectory points toward greater agent autonomy as the UI/observability layer proves it can show the human what the system is doing — autonomy expansion is gated on demonstrated alignment, not on calendar dates.

Critical files to be modified or created appear in §4 below. The Week-1 inviolate core (Block 1 ban, publication review, version pins, validation rigor, MARLIN backend) is preserved exactly. Only the gates outside that core get reclassified.

---

## 1. The autonomy framework (new — drives everything else)

Created at `agent/autonomy.md`. Three tiers, phase-aware boundaries, SLA discipline.

### 1.1 Three tiers

| Tier | Default action | Halts when | Examples |
|---|---|---|---|
| **Autonomous** | Proceed; log every step to the run log | Never within the tier's domain | Daily arXiv ingest cron; log rotation; deterministic file integrity checks; retrospective ops |
| **Soft-gate** | Proceed; record an *attestation request* in `run_state/attestations.jsonl`; allow rollback within the SLA window | Only if the human marks the attestation `rejected` | Determinism check; ChromaDB metadata verification; prompt grep; 4-of-5 robustness; credentials check |
| **Hard-gate** | Halt at entry; record gate in `human_gates_pending`; wait for explicit attestation | On entry | Block 1 reading + problem set; Day 7 publication review; schema/contract authoring; MARLIN backend startup; novel-result evaluation (Phase 2); retrospective |

### 1.2 SLA discipline (per user's selection: soft auto-clear / hard escalate)

| Gate type | SLA | On expiry |
|---|---|---|
| Soft-gate | 4 hours | Auto-clear with a `no_objection` entry appended to `run_state/attestations.jsonl`; run log records the auto-clear with timestamp |
| Hard-gate | 48 hours | Escalate: write to `run_state/escalations.jsonl`, optionally fire a notification hook (configured per user); gate stays halted |
| Block 1 | None | No SLA. Human attestation required. Never auto-clears. |

Implementation: a small `tools/gate_sla_check.py` runs on a cron to sweep `human_gates_pending` against SLA timestamps and apply the action. Track A writes; cron only reads + appends.

### 1.3 Phase-aware boundaries

Tiers don't move; the *classification of tasks into tiers* moves as observability matures.

| Phase boundary | Trigger (not calendar) | Tier shifts unlocked |
|---|---|---|
| **Week 1 baseline** | Current — apparatus v0 not yet validated end-to-end | All 13 hard_checkpoints are hard-gate; all 35 human_only stay as-is |
| **Week 2 unlock** | UI v1 deployed; sampler running; dashboard live; 1 week of clean run-log integrity | Determinism check, ChromaDB metadata, prompt grep, robustness mini → soft-gate. Credentials check → autonomous (env-var verifier). Day-5 arxiv cross-check → soft-gate (agent samples + posts to UI for human scan). |
| **Weeks 3–4 unlock** | UI v2 (call-chain inspector) live; 2 weeks of consistent alignment (defined below); zero silent drift detections | + Hyperparameter tuning, retrieval relevance scoring → soft-gate. Daily ingest + log review → autonomous. |
| **Phase 2 entry (~Day 91)** | UI showing consistent alignment for 4+ consecutive weeks; meta-review + critic agents shipped; auto-evaluator calibrated (W2-05) | Hypothesis generation, experiment runs → soft-gate (was hard-gate). Critic verdict + meta-review synthesis → autonomous. Hard-gate retained only for: Block 1, publication, novel-finding evaluation (Step 8 of the intelligence loop), resource budget violations. |

**Consistent alignment** is the load-bearing definition. It means, over a rolling 7-day window:
- For every task the system *would have* halted at (had the gate been hard), the human, looking at the UI retrospectively, agrees the halt was warranted — OR — the human agrees the auto-proceed was correct.
- Disagreement rate ≤ 1 case per week.
- No silent metric drift > 5% in retrospective audits of metric_log entries.
- Run-log integrity 100% (no malformed JSONL).

A weekly attestation in `human/retrospectives/weekN.md` records the alignment score. The phase boundary only advances when two consecutive weekly attestations clear the bar — this prevents a single optimistic week from unlocking too much.

A *parallel* unlock axis governs **who can dispatch agents** (the human, or the orchestrator). That axis is in §7.5 and uses the same alignment gating; the two axes can advance independently.

### 1.4 Migration of existing gates (concrete reclassification)

Applied at the **Week 2 unlock** boundary, not now:

| Task | Today | After Week 2 unlock |
|---|---|---|
| `preflight_credentials_staged` | hard_checkpoint | Autonomous (env-var verifier; warns) |
| `day2_block2_50call_sweep` | hard_checkpoint | Soft-gate (4h SLA; logs all pairs to UI) |
| `day3_block2_chroma_install` | hard_checkpoint | Soft-gate (metadata + immediate needle test) |
| `day6_block2_robustness_mini` | hard_checkpoint | Soft-gate (≥4/5 passes; flag the 1) |
| `day7_block2_strategies_and_llm_agent` (prompt grep) | hard_checkpoint | Soft-gate (auto-pass on 0 hits; halt on any) |
| Day-5 arxiv cross-check `[GATE]` | hard human attestation | Soft-gate (agent posts 2 sampled papers to UI; auto-clear at 4h) |
| Day-1 firmware `[GATE]` | hard human attestation | Hard-gate (unchanged — physical UI work) |
| `day7_publication_review_gate` | hard_checkpoint + human_only | Hard-gate (unchanged — load-bearing for research integrity) |
| All Block 1 tasks | human_only | Hard-gate / Block 1 SLA-less (unchanged — pedagogy) |
| `day1_block2_vllm_serve` MARLIN check | hard_checkpoint | Hard-gate (unchanged — corruption risk) |
| `day2_block2_jsonl_schema` + `day6_block2_worker_contract` | hard_checkpoint | Hard-gate (unchanged — load-bearing for downstream) |

`plan.yaml` gets a new top-level field `autonomy_tier: hard_gate | soft_gate | autonomous` on each task, with the current values being the "today" column. The "after Week 2 unlock" column is reflected in a parallel `autonomy_tier_after_unlock` field, applied automatically by the orchestrator when the phase boundary advances.

---

## 2. The 30-day roadmap (new)

Created at `PHASE_1_ROADMAP.md` (root). Days 31–60 detailed; Days 61–90 milestone-only; Days 1–30 stub. Slip semantics explicit.

### 2.1 Slip mechanism

Days are integers (31, 32, …). If a day can't complete, the state file tracks both:
- `current_day` — the integer day (the week marker)
- `current_subday` — appended decimal (e.g., `31.2` = second slip on day 31)

A slip is created when:
- A hard-gate failure aborts the day (already CLAUDE.md inviolate rule 6).
- A hard-gate stays open past its 48h SLA.
- A side-track merge requires same-day rework.
- The human declares a slip ("today bled into tomorrow").

`plan.yaml` gets corresponding task IDs `dayN_X_block2_…` for slips. Subday tasks inherit the parent day's `autonomy_tier`. The run log records the slip event as a first-class entry.

### 2.2 Days 1–30 stub

Created at `human/days_01_30_recap.md`. Drafted from:
- `PROJECT_CONTEXT.md` (researcher identity, program arc, the bet of Phase 1)
- `notes/research/` (adversarial review notes — these are the substantive pre-Week-1 artifact)
- `DECISIONS.md` D-001 through D-018 (decisions locked before Day 31)
- The user's memory (e.g., the failure-mode rehearsal, pre-flight credentials, hardware ordering)

Structure: one-paragraph framing + a single "Decisions locked pre-Week-1" table + a "Known unknowns going into Week 1" list. Not a day-by-day reconstruction — that information isn't recoverable. The user is the source of truth for any gaps and fills them in prose.

### 2.3 Days 38–44 (Week 2 — critic + meta-review)

Drives on the 12 items in `notes/week2_seed.md`, sequenced into a daily plan analogous to Week 1:

- **Day 38**: UI v1 deployment + Week-2 unlock attestation (Block 2 = ship the UI; UI must show every Week-1 artifact correctly before any tier shift is applied). Also: `agent/ownership.yaml` + `agent/collision_protocol.md` + `run_state/claims.jsonl` land (the dispatch plumbing — see §7).
- **Day 39**: W2-01 Critic agent (red-team) — workers/critic.py; eval on 20 known-flawed hypotheses; target ≥80% substantively different critique. Also: `agent_wrapper/dispatch_coding_agent.py` lands (§7.3).
- **Day 40**: W2-02 Active meta-review synthesis — workers/meta_review.py; 20-trial test for no duplication of last-3 hypotheses. **First orchestrator-dispatched coding agent task lands** — draft of Day-41 test scaffolds, soft-gate, human reviews via UI.
- **Day 41**: W2-05 Auto-evaluator calibration — 10 synthetic-tier outcomes with ground truth; κ + Spearman; threshold documented.
- **Day 42**: W2-06 Schema amendments (human_intervention, retrieval_context, calibration_entry); plan.yaml `autonomy_tier` + `dispatchable` fields land.
- **Day 43**: W2-04 PD experiment re-run with critic in loop — first end-to-end Phase 2 architecture exercise; soft-gate the experiment, hard-gate the publication.
- **Day 44**: Week-2 retrospective + alignment scoring (first weekly attestation). Includes a *concurrency* attestation: was the claim log clean? Any collisions?

Each day inherits the Week-1 Block 1/2/3 cadence. Block 1 readings continue (Phase 1 reading list moves to `human/reading_list.md`).

### 2.4 Days 45–51 (Week 3 — calibration + novelty detection)

- W2-08 Rediscovery-with-holdout protocol (McKelvey & Palfrey 1995 QRE).
- W2-03 Novelty evaluator (Step 8 of intelligence loop) — kept hard-gate.
- W2-07 Degradation metrics — model drift, rediscovery loops, researcher calibration.
- Week-3 retrospective + alignment scoring (second consecutive — unlocks Weeks 3–4 tier shifts if clean).

### 2.5 Days 52–58 (Week 4 — first applied-tier rung)

- ARCHITECTURE.md §3.2 Rung 1 (single-item auctions in known-equilibrium mechanism design).
- W2-12 Multi-candidate generation + bandit selection.
- W2-09/10 (Polymarket *design-only*) — drafting CFTC compliance worksheet; not live trading.
- Week-4 retrospective + Phase-1-checkpoint attestation (90-day arc midpoint).

### 2.6 Days 59–60 (buffer + write-up start)

- Buffer for slips from Weeks 2–4 (highly likely; current Week 1 already had a Day-3.5 slip).
- First draft of the Day-90 preprint scope memo: what's claim-worthy, what's not.

### 2.7 Days 61–90 (milestones only)

- **Day ~65**: Rung 2 launch (combinatorial auctions).
- **Day ~72**: Qwen 3.6 second model online (per D-006).
- **Day ~80**: Full intelligence loop with all Phase-2 additions running for 1 consecutive week.
- **Day 90**: Preprint draft complete; Phase 1 exit attestation; Phase 2 entry decision (hard-gate, human-only, no SLA).

### 2.8 Open dependencies the user must answer

The roadmap notes these as `[OPEN]` markers (not invented):

- Exact ordering inside Week 2 if W2-01/02/05 collide on time (today they're parallel-track candidates but compete for the same human attention).
- Whether CFTC compliance work lands in Phase 2 or only gates Phase 3 entry.
- Preprint scope at Day 90 — whether W2-08 (rediscovery) lands in time to be in scope.
- Which mechanism-design rungs (1–4) land in Phase 1 vs Phase 2.

These are flagged in the roadmap, not resolved. The user fills them in as they reach them.

---

## 3. The file restructure (split by audience)

Two new directories created; six files moved; five new files added; one file deleted (after content migration). The existing `notes/`, `run_state/`, and source code directories are untouched.

### 3.1 Final layout

```
/                                       ← Root: shared / ambient
├── START_HERE.md                       (kept; rewritten as a thin orientation page that points to the doc map and explicitly names the three audiences)
├── CLAUDE.md                           (kept at root — auto-loaded by Claude Code; trimmed to: inviolate rules + pointer to agent/)
├── PROJECT_CONTEXT.md                  (kept; deduplicated of version-pins and inviolate-rules content that now lives in ARCHITECTURE/GLOSSARY)
├── ARCHITECTURE.md                     (kept; absorbs the "what the apparatus does NOT do" + version-pin sections from START_HERE)
├── DECISIONS.md                        (kept; gains a category index — Hardware / Models / Stack / Scope / Process / Operational — and a "superseded by" arrow per entry)
├── GLOSSARY.md                         (NEW: stable terminology — Track A/B/C/D, Block 1/2/3, autonomy tiers, gate types, apparatus v0, synthetic/semi-synthetic/applied tier, Phase 0–5)
├── PHASE_1_ROADMAP.md                  (NEW: §2 above)
├── current_day.md                      (kept; rewritten daily; gains a slip-banner if current_subday is set)
├── ui_plan.md                          (kept; gains a §10 "Observability gates autonomy" tying UI milestones to autonomy-tier shifts)
├── plan.yaml                           (kept; gains autonomy_tier + autonomy_tier_after_unlock fields per task; gains slip-task templating; Appendix C trimmed — moved to CLAUDE.md proper)
│
├── human/                              ← Read by the researcher
│   ├── README.md                       (NEW: one paragraph, points back to START_HERE.md)
│   ├── daily_plan.md                   (moved from HUMAN_PLAN.md; trimmed of agent-facing prose)
│   ├── reading_list.md                 (NEW: Phase 1 reading sequence extracted from HUMAN_PLAN.md Block 1 sections)
│   ├── days_01_30_recap.md             (NEW: §2.2 above)
│   └── retrospectives/
│       ├── week1.md                    (NEW: first weekly attestation, drafted from current_day.md + run_log)
│       └── (added each week)
│
├── agent/                              ← Read by Claude Code sessions
│   ├── README.md                       (NEW: one paragraph, points to CLAUDE.md)
│   ├── orchestration.md                (moved from AGENT_PLAN.md; the parallel-execution + worktree content)
│   ├── autonomy.md                     (NEW: §1 above)
│   └── prompts/
│       ├── track_a.md                  (extracted from AGENT_PLAN §"Per-track prompts")
│       ├── track_b.md                  (extracted)
│       ├── track_c.md                  (extracted)
│       └── track_d.md                  (NEW: per ui_plan.md Track D conventions)
│
├── notes/                              (unchanged)
├── run_state/                          (unchanged; gains attestations.jsonl + escalations.jsonl per §1.2)
└── ... source code, infra, etc.        (unchanged)
```

### 3.2 What moves where (concrete diff)

| Action | File | Destination | Notes |
|---|---|---|---|
| Move | `HUMAN_PLAN.md` | `human/daily_plan.md` | Plus prune; agent-facing prose absorbed into agent/orchestration.md |
| Move | `AGENT_PLAN.md` | `agent/orchestration.md` | Per-track prompts move to `agent/prompts/` |
| Create | `agent/autonomy.md` | new | §1 of this plan |
| Create | `agent/prompts/track_{a,b,c,d}.md` | new | One file per track; lifted from AGENT_PLAN §"Per-track prompts" + ui_plan.md for Track D |
| Create | `human/reading_list.md` | new | Extracts every Block 1 reading + problem set from HUMAN_PLAN.md + PROJECT_CONTEXT.md |
| Create | `human/days_01_30_recap.md` | new | §2.2 of this plan |
| Create | `human/retrospectives/week1.md` | new | First weekly attestation; drafted from current_day.md + run_log |
| Create | `GLOSSARY.md` | new | §3.1 above |
| Create | `PHASE_1_ROADMAP.md` | new | §2 of this plan |
| Trim | `START_HERE.md` | in place | Becomes thin orientation; doc map updated to point to new layout; inviolate-rules section reduced to a "see CLAUDE.md and agent/autonomy.md" pointer |
| Trim | `CLAUDE.md` | in place | Keeps inviolate rules in full (canonical for agents); absorbs `plan.yaml` Appendix C; references agent/autonomy.md for tier rules |
| Trim | `PROJECT_CONTEXT.md` | in place | Version pins removed (canonical in ARCHITECTURE.md §2); inviolate rules summary removed (pointer to CLAUDE.md) |
| Edit | `ARCHITECTURE.md` | in place | Absorbs version-pin table from PROJECT_CONTEXT.md + START_HERE.md; adds a "Phase 2 architecture deltas" section consolidating the scattered Phase 2 markers |
| Edit | `DECISIONS.md` | in place | Gains a category index and "supersedes / superseded by" arrows; no entries removed |
| Edit | `plan.yaml` | in place | `autonomy_tier` + `autonomy_tier_after_unlock` fields per task; slip-task templating note in preamble |
| Edit | `current_day.md` | in place | Format update only (slip banner); content rewritten daily per cadence |
| Edit | `ui_plan.md` | in place | New §10 ties UI milestones to autonomy unlocks |
| Add | `run_state/attestations.jsonl` | new | Soft-gate attestation log (empty file with schema comment) |
| Add | `run_state/escalations.jsonl` | new | Hard-gate escalation log (empty file with schema comment) |
| (None) | `notes/`, `run_state/week1.state.json`, `run_state/week1.run.jsonl` | unchanged | Existing state preserved |

### 3.3 Cross-link consistency pass

After file moves, sweep every `.md` for stale references:
- `HUMAN_PLAN.md` → `human/daily_plan.md`
- `AGENT_PLAN.md` → `agent/orchestration.md`
- Any inline restatement of inviolate rules → pointer to `CLAUDE.md`
- Any inline version-pin restatement → pointer to `ARCHITECTURE.md` §2
- Any inline glossary-worthy term first mention → wrap with link to `GLOSSARY.md`

A single `grep -RIn 'HUMAN_PLAN.md\|AGENT_PLAN.md'` confirms all references are updated post-move.

---

## 4. Critical files to modify

In execution order (and these are the only files touched):

1. `agent/autonomy.md` — new (§1)
2. `PHASE_1_ROADMAP.md` — new (§2)
3. `GLOSSARY.md` — new (§3.1)
4. `agent/orchestration.md` — moved from AGENT_PLAN.md
5. `agent/prompts/track_{a,b,c,d}.md` — extracted
6. `human/daily_plan.md` — moved from HUMAN_PLAN.md
7. `human/reading_list.md` — new (extracted from HUMAN_PLAN.md + PROJECT_CONTEXT.md)
8. `human/days_01_30_recap.md` — new (§2.2)
9. `human/retrospectives/week1.md` — new (drafted from current_day.md + run log)
10. `human/README.md`, `agent/README.md` — new (one-paragraph entry points)
11. `CLAUDE.md` — trim + add autonomy-tier pointer
12. `START_HERE.md` — rewrite doc map
13. `PROJECT_CONTEXT.md` — deduplicate
14. `ARCHITECTURE.md` — absorb pin table + add Phase-2 deltas section
15. `DECISIONS.md` — add category index + supersession arrows
16. `ui_plan.md` — add §10
17. `plan.yaml` — add `autonomy_tier` + `autonomy_tier_after_unlock` + slip-task templating
18. `current_day.md` — slip-banner format update (content stays Day-5 until Day-6 lands)
19. `run_state/attestations.jsonl`, `run_state/escalations.jsonl` — empty with schema-comment header
20. `tools/gate_sla_check.py` — new (~80 lines, sweeps SLAs, appends to logs)
21. Old `HUMAN_PLAN.md`, `AGENT_PLAN.md` — deleted **after** all cross-references are updated and the merge of Day 6 work has landed.
22. `human/learning_track.md` — new (§6.1; reading + problem-set syllabus extracted from HUMAN_PLAN.md + PROJECT_CONTEXT.md)
23. `agent/ownership.yaml` — new (§7.1)
24. `agent/collision_protocol.md` — new (§7.2)
25. `agent/prompts/dispatched_task.md` — new (§7.3 template)
26. `run_state/claims.jsonl` — new (empty + schema header)
27. `tools/claims_check.py` — new (~80 lines)
28. `agent_wrapper/dispatch_coding_agent.py` — new (Day-39 deliverable, not part of this restructure commit; called out here so the restructure's plan.yaml fields anticipate it)

Total: 2 small tools added (gate SLA + claims check), 1 Week-2 deliverable scoped (dispatch_coding_agent), 17 new docs, 9 docs edited in place, 2 docs deleted (post-migration).

### 4.1 Existing functions / utilities to reuse

- `run_state/week1.state.json` schema — extend, don't replace.
- `run_state/week1.run.jsonl` append discipline — reused for `attestations.jsonl` + `escalations.jsonl`.
- `tools/inspect_run.py` — extended to render attestation + escalation entries inline with the causal chain (no rewrite).
- `notes/week2_seed.md` — the 12 W2 items are the source-of-truth for §2.3; not rewritten, just sequenced.
- `cron/snapshot-chroma.sh` pattern — reused for the `gate_sla_check.py` cron entry.
- The existing `[GATE]` notation in HUMAN_PLAN.md — reused as the human-readable form of hard-gate task IDs.

---

## 6. Decoupling the human-learning track from system development

The current `plan.yaml` makes Block 1 a **precondition** of Block 2 (e.g., `day6_block2_worker_contract.preconditions: [day6_block1_reading]`). That is the actual mechanism by which the human's literature progression gates apparatus development — not the `human_only: true` flag, but the precondition edge. Decoupling these is more important than the tier reclassification.

The user expects the system to come online before they're ramped up on literature. The plan honors that by treating the reading track as a **parallel rail** rather than a daily gate, with explicit exceptions only where the human's understanding is the *content* of a task (not just background).

### 6.1 New file: `human/learning_track.md`

A standalone reading + problem-set syllabus, sequenced across Phase 1, distinct from `human/daily_plan.md`. Structure:

- **Reading sequence** — chapters from Cesa-Bianchi & Lugosi, Osborne & Rubinstein, Horton 2023, Camerer's behavioral game theory, etc., grouped by week with target completion dates but no hard deadlines.
- **Problem sets** — keystone problems (Multiplicative Weights derivation, SPNE characterization, QRE estimation, etc.) with status: not started / in progress / done. Attested in weekly retros.
- **Progress reporting** — a single `human/learning_progress.md` line per week, appended to the weekly retrospective. No daily attestation; the system does not query this file.

### 6.2 Changes to `plan.yaml`

Remove the precondition edges that make Block 1 block Block 2:

| Task | Today's `preconditions` | After |
|---|---|---|
| `day2_block2_jsonl_schema` | `[day2_block1_reading]` | `[]` |
| `day3_block2_chroma_install` | `[day3_block1_reading]` | `[]` |
| `day3_block2_chunking_and_ingest_script` | `[day3_block1_reading]` | `[]` |
| `day4_block2_mock_tool` | `[day4_block1_reading]` | `[]` |
| `day5_block2_ml_intern_router` | `[day5_block1_reading]` | `[]` |
| `day6_block2_worker_contract` | `[day6_block1_reading]` | `[]` |
| `day7_block2_openspiel_up` | `[day7_block1_reading]` | `[]` |
| (sweep all Block 2 tasks across Days 1–7 + future days) | | |

Replace with a new informational field `recommended_reading: [<reading_id>, ...]` that is rendered to the human but **not checked** by the orchestrator. The reading IDs point to entries in `human/learning_track.md`.

### 6.3 Exceptions — tasks that DO still require human understanding

A handful of tasks have human understanding as their content, not as background. These keep a hard-gate, but on a *task-specific* attestation (not on Block 1 globally):

| Task | Required understanding | Gate form |
|---|---|---|
| `day2_block2_jsonl_schema` (authoring) | What fields the schema must contain | Hard-gate: human authors the schema on paper, commits, agent validates |
| `day6_block2_worker_contract` (authoring) | Worker I/O contract | Hard-gate: same pattern |
| `day7_block2_precompute_expected_range` | Expected cooperation rate band | Hard-gate: human pre-specifies 60–95% before experiment runs |
| `day7_publication_review_gate` | What is publishable vs preliminary | Hard-gate: explicit human attestation |
| Phase 2 hypothesis-generation onboarding | Theoretical grounding for a generated hypothesis | Hard-gate, but only for the *first* generation cycle per topic |
| Architectural decision points (any new D-NNN entry) | Trade-off analysis | Hard-gate: human writes the decision; agent records |
| System-failure escalations | Triage + recovery direction | Hard-gate: agent posts state to UI; human decides direction |

Everything else: agent proceeds. The human reads in parallel and catches up via the UI when they're ready. If they spot something they would have decided differently, they roll back via the soft-gate rollback window (§1.2) or amend in retrospective.

### 6.4 Implication for Week 1

Day 6 today: `day6_block2_worker_contract.preconditions: [day6_block1_reading]` halts the agent until the human reads Ch. 1 §1.5–end + §2.1–2.3. Under this plan, the precondition is removed. The agent can author/validate the worker contract schema right after the **human authors the schema content** (which is the genuine hard-gate — it's authoring, not reading). The Multiplicative Weights derivation is still on the human's track; it does not block Day 6.

This change applies prospectively (Day 6+). Past completed days are not re-classified.

### 6.5 Implication for Phase 2 entry

Phase 2 entry (Day ~91) keeps a hard-gate on the *human's understanding of what novel findings look like* — this is `day7_publication_review_gate` generalized. The human must have completed enough of the reading to evaluate novelty meaningfully. Concretely: the Phase-1-exit attestation requires the human to attest "I have read enough to evaluate the next hypothesis the loop generates." If not, Phase 2 stays paused; the loop continues to produce hypotheses, but they queue in `human_gates_pending` for review.

---

## 7. Concurrent agent coordination

Today's `agent/orchestration.md` (formerly `AGENT_PLAN.md`) supports 4 named tracks (A/B/C/D) launched manually by the human, with file-boundary tables that are enforced by convention and conflict-resolved at merge time. Scaling to "~80% of system development driven by orchestrator-dispatched coding agents" needs three things this plan adds: (a) ownership at file granularity, (b) a claim/lock protocol, (c) the dispatch pattern itself.

### 7.1 New file: `agent/ownership.yaml`

Machine-readable ownership registry, replacing the prose tables in `AGENT_PLAN.md`. One entry per zone:

```yaml
zones:
  - id: orchestrator
    paths: ["orchestrator/**", "workers/**", "agent_wrapper/**"]
    primary_track: A
    dispatchable: false           # only Track A may touch
  - id: pipeline
    paths: ["pipeline/**", "ingest/**", "cron/**"]
    primary_track: C
    dispatchable: true            # orchestrator may dispatch a coding agent here
  - id: tests-shared
    paths: ["tests/test_<module>.py"]
    primary_track: <module-owner>  # whoever owns the module
    dispatchable: true
  - id: experiments
    paths: ["experiments/exp001_repeated_pd/strategies*.py",
            "experiments/exp001_repeated_pd/quicklook.py",
            "experiments/exp001_repeated_pd/analysis/**"]
    primary_track: C
    dispatchable: true
  - id: ui
    paths: ["ui/**", "ui_plan.md"]
    primary_track: D
    dispatchable: true
  - id: state-file
    paths: ["run_state/**"]
    primary_track: A
    dispatchable: false           # never dispatched; only Track A writes
  - id: schemas
    paths: ["schema/**"]
    primary_track: B
    dispatchable: true
  - id: docs
    paths: ["*.md", "human/**", "agent/**"]
    primary_track: A
    dispatchable: true            # docs are dispatchable but conflict-prone; claim protocol mandatory
```

Every file in the repo maps to exactly one zone (a glob conflict is itself a planning bug). The `primary_track` is the default writer when no dispatch is active. The `dispatchable` flag governs whether an orchestrator-dispatched coding agent can be given this zone.

### 7.2 Claim / lock protocol

New file: `run_state/claims.jsonl` (append-only). Every agent that intends to write a file appends an entry:

```json
{"timestamp": "2026-05-23T14:12:03Z",
 "agent_id": "claude-track-c-day6-quicklook",
 "zone": "experiments",
 "paths": ["experiments/exp001_repeated_pd/quicklook.py",
           "tests/test_quicklook.py"],
 "intent": "write",
 "expires_at": "2026-05-23T16:12:03Z"}
```

Rules:
- Before writing, an agent appends a claim with a 2-hour expiry.
- Before writing, an agent scans the most recent claim per path. If a non-expired claim by another agent exists, the agent waits or escalates.
- On commit, the agent appends a `release` entry referencing the claim by timestamp.
- Track A is the only agent that can write to non-dispatchable zones; it does not need to claim (its primacy is unconditional).
- A small `tools/claims_check.py` sweeps for expired or overlapping claims and reports them — runs in the same cron as `gate_sla_check.py`.

This protocol is implemented now (Week 2 deliverable) so that by the time orchestrator-dispatched agents arrive, the infrastructure already works.

### 7.3 Orchestrator-dispatched coding agent pattern

The trajectory the user wants — ~80% of dev driven by orchestrator dispatches — is a Phase 2 outcome. The Phase 1 deliverable is the **plumbing** that makes it possible. Concretely:

- **Day 39 (Week 2)**: `agent_wrapper/dispatch_coding_agent.py` lands. Signature:
  ```python
  def dispatch_coding_agent(
      task_spec: dict,           # zone, paths, work description, success criteria
      worktree_prefix: str,      # "auto-task-NNN-{zone}"
      timeout_minutes: int = 120,
      autonomy_tier: str = "soft_gate"
  ) -> DispatchResult: ...
  ```
  Spawns a Claude Code session in a fresh worktree, hands it a scoped prompt assembled from `agent/prompts/dispatched_task.md` template + the task spec, monitors the worktree for sentinel completion, returns the merge candidate.

- **Day 40**: First dispatched task lands. Candidate: drafting Day-41 test scaffolds for a deterministic module. Soft-gate; human reviews via UI after.

- **Day 45**: Second dispatched task — a `cron/` script. Validates the protocol on a non-test path.

- **Day 50ish**: First orchestrator-only dispatched task — orchestrator decides to dispatch (not a human) based on a queue. Hard-gate the *decision* (human approves the queue ordering) until alignment evidence accumulates.

- **Phase 2 entry**: ≥50% of new code lands via dispatched agents.

- **Day 90 milestone target**: 80% — aspirational, captured in `PHASE_1_ROADMAP.md` §2.7 as an open target, not a commitment.

### 7.4 Collision avoidance — concrete patterns

Beyond the claim protocol, three additional disciplines:

1. **Worktree-per-task.** Every dispatched agent gets its own git worktree (extends the existing `claude --worktree` pattern). No two agents share a working tree. Merge conflicts surface at integration time, not at edit time.

2. **Append-only state files.** `run_state/*.jsonl` files are append-only by every agent except Track A. Track A is the rectifier — it can rewrite if a malformed line appears. Other agents that need to log progress write to `notes/<agent-id>.log`.

3. **Plan.yaml is read-only for dispatched agents.** Only Track A modifies `plan.yaml`. Dispatched agents read it to understand task specs. This prevents two agents both editing the canonical plan.

### 7.5 Phase-aware concurrency unlocks

Parallels §1.3 but for *who can dispatch*, not for *what's autonomous*:

| Phase | Concurrent agents (typical) | Who dispatches |
|---|---|---|
| Week 1 | 4 (A/B/C/D) | Human launches each manually |
| Week 2 unlock | 4–6 | Human still launches; orchestrator can dispatch *one* coding agent per day to a dispatchable zone |
| Weeks 3–4 unlock | 6–8 | Orchestrator can dispatch up to 3 concurrent coding agents; human attests the queue |
| Phase 2 entry | 8–12 | Orchestrator dispatches autonomously; human attests weekly via UI |
| Phase 2+ | unbounded | Orchestrator dispatches; human spot-checks; 80% target |

The unlocks are gated on the same `consistent alignment` definition (§1.3) plus a **claim-protocol-clean week**: no overlapping claims, no expired-claim writes, no merge conflicts caused by ownership-zone violations.

### 7.6 What this adds to the file restructure

Additions to §3.2:

| Action | File | Notes |
|---|---|---|
| Create | `agent/ownership.yaml` | §7.1 — registry |
| Create | `agent/collision_protocol.md` | §7.2 — prose spec of the claim protocol |
| Create | `agent/prompts/dispatched_task.md` | §7.3 — template for orchestrator-dispatched agents |
| Create | `run_state/claims.jsonl` | empty + schema header |
| Create | `tools/claims_check.py` | ~80 lines; sweeps claims, reports overlaps + expiries |
| Edit | `ARCHITECTURE.md` | new §5.2 "Multi-agent coordination" tying §7 to the loop architecture |
| Edit | `agent/orchestration.md` (formerly AGENT_PLAN) | absorbs the 4-track tables but defers ownership to ownership.yaml; gains a "Beyond 4 tracks" section pointing to §7.3 |
| Edit | `plan.yaml` | adds `dispatchable: true|false` + `target_zone: <zone-id>` to each task |
| Edit | `PHASE_1_ROADMAP.md` | days 39, 40, 45, ~50, ~90 milestones from §7.3 |

---

## 5. Verification

End-to-end check before declaring the restructure done:

### 5.1 Static checks

- `grep -RIn 'HUMAN_PLAN.md\|AGENT_PLAN.md' .` returns zero hits after migration (no stale links).
- `python3 -c "import yaml; yaml.safe_load(open('plan.yaml'))"` exits 0 (plan.yaml still parses).
- Every task in `plan.yaml` has a non-null `autonomy_tier` value (loop with grep/yq).
- Every file referenced in `START_HERE.md`'s doc map exists.
- `jsonschema.Draft202012Validator.check_schema(json.load(open('schema/worker_contract.schema.json')))` still exits 0 (no schema regression).

### 5.2 Behavior checks

- Track A session can be launched (`env -u MOCK_LLM claude --worktree day7-main` once Day-6 lands) and reads CLAUDE.md → agent/autonomy.md → plan.yaml → run_state — no missing files, no broken pointers.
- A soft-gate attestation cycle works end-to-end: trigger a soft-gate (e.g., a faked determinism mismatch), confirm an entry appears in `run_state/attestations.jsonl`, manually clear it, confirm the cleared-state entry is visible to `tools/inspect_run.py`.
- A hard-gate escalation works: trigger a hard-gate, wait past the SLA (use a 60-second SLA in a test config), confirm an entry appears in `run_state/escalations.jsonl` and the gate stays halted.
- `tools/gate_sla_check.py --dry-run` lists current gates and their SLA status without making changes.
- **Block 1 decoupling check.** Open `plan.yaml`, confirm zero Block 2 tasks have a Block 1 task in their `preconditions:`. Run a dry-run of Day-6 resume logic with `day6_block1_reading` marked NOT complete — confirm Block 2 tasks are still listed as runnable.
- **Claim-protocol check.** Write a tiny fixture that appends two overlapping claims to `run_state/claims.jsonl`; run `tools/claims_check.py`; confirm it flags the overlap and exits non-zero. Append a `release` entry for one; confirm the overlap is cleared.
- **Ownership-zone integrity.** `tools/claims_check.py --validate-ownership` confirms every file in the repo maps to exactly one zone in `agent/ownership.yaml` (no zone covers a path another zone also covers).

### 5.3 Human checks (read-through, not executable)

- Open `human/daily_plan.md` from scratch — can the researcher start a day from this file alone, without reading `agent/`?
- Open `CLAUDE.md` + `agent/autonomy.md` from scratch as Track A — can a session resume without reading `human/`?
- Open `PHASE_1_ROADMAP.md` — does the slip mechanism + 30-day plan + 60/90-day milestones read as a single coherent plan?
- Open `GLOSSARY.md` — does every load-bearing term appear, with one short definition, and a pointer to the deepest canonical reference?
- Open `human/learning_track.md` — is the reading sequence intelligible on its own, with no implied daily deadline?
- Open `agent/ownership.yaml` + `agent/collision_protocol.md` together — can a fresh coding agent understand what zone it owns and how to claim a file before writing it, without reading any other docs?

### 5.4 Out of scope (explicitly)

- No changes to source code under `agent_wrapper/`, `pipeline/`, `orchestrator/` (does not exist yet), `experiments/`, `tests/`, `tools/inspect_run.py`, or any data under `chroma_db/`.
- No changes to `run_state/week1.state.json` or `run_state/week1.run.jsonl` content — they are append-only history; the restructure only adds new sibling JSONL files.
- No changes to ongoing Track A (Day 6) or Track C (day6-quicklook) worktrees. The restructure lands as a separate commit on main, after Day 6 merges. Track A is the only writer; this work waits.
- No deletion of any DECISIONS.md entries.
- No retroactive reclassification of completed Day 1–5 tasks in the run log.
