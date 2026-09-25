# v2 alignment audit and lab goals (2026-09-22)

> **Historical source port — reconciliation required (2026-09-25).** The body
> below is the exact committed `a4ccb77e` source snapshot and contains
> point-in-time implementation/status statements. It is not a present-state
> report or activation authority. Read
> [the reconciliation](THESIS_GOVERNANCE_RECONCILIATION_2026-09-25.md) before
> relying on it operationally.

Status: **ratified as D-084 (owner, 2026-09-22).** The goal plan in §6 is wired into
Oracle's daily contract (`oracle_system/prompts/daily_loop.md`) and the meta-oracle's
review (`agent/prompts/meta_oracle.md`).
Produced by the meta-oracle from five read-only investigations (design intent,
runtime, documentation, the Now page, and the thesis-to-market path). Every
headline claim below was spot-checked against the files. The goal plan (§6) is
what Oracle's daily plans work toward: every plan item names a goal ID.

## 1. Summary

The lab has not done research since **2026-09-20 06:00 UTC** (about 65 hours).
Every coordinator cycle since then is `focus_pending` (`run_state/coordinator_cycles.jsonl`).
A research focus selected by hand on 09-21 holds all new-topic intake until its
next gate, `THESIS_DISPOSITION.md`, is satisfied. That file has existed since
09-21 01:52, but no code reads it. The focus model has no terminal state
(`orchestrator/research_focus.py:26`, `STAGES = {needs_clean_refinement, blocked}`),
and no code can select, close or replace a focus (`select_focus` has no caller).
The lab is deadlocked on a gate that only a hand edit can clear.

The deadlock is a symptom. v2 was **decided** as a campaign- and evidence-ladder
design (`LOOP_V2.md`), and parts were **added** since, by hand and in drafts: the
"one thesis until closed" focus, the daily-ops page and the seven-day plan. They
were never joined into a lifecycle that runs by itself. The iteration engine is
still the v0 chain (`orchestrator/nara.py:1`, "the LOOP_V0 orchestrator"). The
Now page shows hand-curated files that stopped changing on 09-21. The entry-point
docs still describe the Gemma/Qwen system that stopped on 09-19.

## 2. Why this was not caught

1. **No owner for the lifecycle.** v2's decided unit is the campaign, which closes
   through a hand-written receipt, and succession is an operator act
   (`docs/v2/DAILY_RESEARCH_OPERATIONS.md:93-94`). The focus/thesis layer arrived on
   09-20 as a hand-operated patch. Its designers deferred the terminal state
   explicitly: "no proposed terminal enum becomes canonical from a handoff"
   (seven-day `SEVEN_DAY_PLAN_FINAL_CHALLENGE.md:21`). Nobody picked it up again.
2. **Idle was not treated as failure.** `loop_health` turns red after 12 hours by
   design, but red has been the steady state for days. The daemon wakes every 30
   minutes, sees "work", and records an empty gated cycle
   (`nara_daemon.py:234-258` ignores the focus). The lab looked alive in its logs.
3. **Many writers, no single spec.** Codex sessions, Claude sessions, Oracle and
   hand edits each updated what they touched. Four documents claim merge authority
   (CLAUDE.md, AGENTS.md, D-079 and D-082), and the meta-oracle loop is in no
   decision.
4. **The UI was built on hand-curated snapshots.** `daily_ops_brief.json`,
   `daily_ops_work_plan.json` and the focus receipt have no writer in the repo.
   `research_ops_status.py:21` hard-codes the 09-15 pilot. These are the one-day
   data shapes the owner does not want.
5. **Applied work stalled silently.** The Polymarket line uses settled prices, which
   is look-ahead (`experiments/exp007_polymarket/market_data.py:73-82`). The
   "pre-resolution snapshots next" step was never built. The crypto capture timer is
   not installed, and its last capture was 09-16.

## 3. Findings by area

| Area | Current state | Gap | Evidence |
|---|---|---|---|
| Lifecycle | Campaign ladder L0–L5; focus hold; hand-selected focus | No terminal focus state; nothing consumes a disposition; no regeneration | `research_focus.py:26,199-200,321-393`; `coordinator.py:1467-1519` |
| Engine | v0 5-step chain (hypothesize, retrieve, novelty, critic, journal) | Produces L0/L1 literature evidence only; cannot plan or run a study | `nara.py:290-307`; `coordinator_actions.py:102-113` |
| Execution | Bespoke per-study runners run by hand or by one-off timers; `run_experiment` deferred; one verifier registered | No scheduler runs a registered study; a new study needs `orchestrator/` edits; `known_opponent_utility/loop_bridge.py` calls `run_iteration` without the admission request V2 requires (probable latent break) | `experiment_admission.py:382-383,724`; `nara.py:564-567`; campaign manifest `:50-53` |
| Nara | Lane builds code only (network-less, `MOCK_LLM=1`) | No way to hand Nara a study to run | `nara_lane.py`; `oracle_mailbox.py:45` |
| Applied | exp007 forecasts closed markets; crypto H1 paper driver `not_tested`, 0 orders | Look-ahead in exp007; no snapshot collector; capture timer not installed | `exp007/market_data.py:73-82`; `ui/backend/applied_data_collection.py:37-51` |
| Now page | Live: health, model runtime, telemetry, active runs, cycles. Stale: brief, work cards, focus, research ops, human todo (291 items, 251 dead bubble acks) | Owner's four wants are missing or partial; new sources (mailbox, daily plans, meta findings) not shown; two competing daily plans | `ui/frontend/src/routes/Pulse.tsx`; `ui/backend/daily_ops_bridge.py:822-915`; `human_todo.py` |
| Docs | README, FLASH_RESIDENT, MODEL_TOPOLOGY_POLICY current | START_HERE, ARCHITECTURE, CLAUDE.md rule 2 and roles, GLOSSARY, PROJECT_CONTEXT describe the stopped Gemma/Qwen system; research_program_v2 points to LOOP_V1; DECISIONS at HEAD jumps D-077 to D-082; no entry point links the Oracle/Nara/meta docs | `START_HERE.md:24-27`; `ARCHITECTURE.md:39,54-75,99-129`; `CLAUDE.md:216-227,288-291`; `research_program_v2.md:42` |

## 4. The decision (ratified as D-084, 2026-09-22)

**Owner authority and the validation ladder.**

1. **The only owner-required gate is live trading.** Anything that places a real
   order, connects a funded account, or implements a live-trading path needs the
   owner's explicit approval. Everything else, including focus selection, study
   registration, research gates, merges and timers, may proceed without the owner
   once it has passed its reviews (Oracle plan, meta-oracle review, the tests and the
   ladder below). This supersedes the operator-only rule on `select_focus` (D-082)
   and the human gates on registration and research. It keeps: D-061 (frontier
   models review and never generate research content or findings); L5 as the
   owner's verdict (a human `valid` verdict remains the top rung, not a gate on
   progress); pause files as kill switches; and the Polymarket live-trading
   guardrail.
2. **A thesis advances only through three validation stages**, each with a
   preregistered design, an independent review and retained results, negative ones
   included:
   - **T, theory.** A game-theoretic model of the hypothesis tested in simulation
     (OpenSpiel is installed in `.venv-chroma`; Nara, Oracle or the meta-oracle may
     design the experiment). The result must uphold the hypothesis under its
     preregistered decision rule.
   - **S, semi-synthetic applied game.** The mechanism tested in a simulated applied
     setting beyond pure theory: LLM agents on local Flash, or another measurable
     medium, with a preregistered outcome.
   - **A, applied proposal.** A written proposal for testing it in one of the three
     candidate markets (options preferred, prediction markets, crypto only if
     justified; `docs/v2/APPLICATION_RESEARCH_AGENDA.md:34-40`) by paper trading or
     another no-capital method, with its data readiness audited. Running the paper
     trial is allowed. Going live is the owner's gate.
3. **A thesis is pursued until it is killed, then a new one is generated.** A kill
   is a recorded disposition (failed at T, S or A under its decision rule, or closed
   for low expected value) with its reason and reopening conditions. It is retained
   as negative knowledge and never deleted. A kill immediately triggers successor
   generation (§5), without waiting for the owner.

## 5. Target lifecycle

```
generate ──> screen (novelty, literature) ──> select focus ──> T (theory) ──> S (semi-synthetic) ──> A (applied proposal) ──> paper trial ──> [owner: live]
     ^                                                          │ kill          │ kill                │ kill
     └──────────── successor generation from negative knowledge ┴───────────────┴─────────────────────┘
```

- **Focus states:** `active`, `blocked`, `killed` and `graduated` (passed A). Each
  transition is a receipt with its evidence.
- **Who does what:** Oracle plans and builds the machinery (states, runners,
  verifiers, UI). Nara generates hypotheses, writes and runs experiments on local
  weights, and records dispositions. The meta-oracle reviews every stage transition
  and every design, and never authors hypotheses or findings (D-061).
- **Refinement (D-086):** a failed or surprising result is recorded unchanged, explained in an anomaly note, and may spawn a new, separately preregistered branch; a killed parent with a promising branch hands its place to the branch.
- **Regeneration:** after a kill, Nara proposes 3–5 successor hypotheses from the
  retained negative knowledge plus recent literature. Each has a named mechanism, a
  T-stage falsifier and a candidate market. Oracle screens them and selects one. The
  meta-oracle reviews the selection.

## 6. Goal plan (Oracle's daily plans cite these IDs)

Ordered by bottleneck. Each goal gives the owner lane (O = Oracle develops, N =
Nara builds or runs) and a done-when check.

| ID | Goal | Lane | Done when |
|---|---|---|---|
| **G0** | **Unblock research** | | |
| G0.1 | **Done 2026-09-22 (meta-oracle, owner request).** Terminal focus states (`killed`, `graduated`) and a close-focus function with reason and reopening conditions; update every consumer (coordinator, research_ops_status, loop_health, UI bridge) | O | Tests cover each transition; closing a focus releases the intake hold |
| G0.2 | **Done 2026-09-23 (Oracle, merged 2cbe6db-e339318).** A focus-selection CLI callable by Oracle after a meta review (per §4.1), writing the receipt by compare-and-swap | O | CLI plus tests; no hand-written receipts afterwards |
| G0.3 | Close the payoff-assistance line: final `THESIS_DISPOSITION` (closed for low expected value, reopening conditions) written on local weights | N | Focus `killed` by receipt; research cycles resume |
| G0.4 | The daemon stops counting a gated queue as work; the coordinator's `dry_run=True` log line is fixed (`coordinator.py:2078`) | O | No empty 30-minute cycles; log matches the run mode |
| **G1** | **Regenerate** | | |
| G1.1 | Successor generation per `docs/v2/THESIS_BRIEF_2026-09-23.md` (D-086: information and beliefs; 3–5 candidates on local weights, each with mechanism, T/S/A design, falsifier and anomaly map) | N (candidates) + O (screen) | One candidate set produced, screened by Oracle, reviewed, and one focus selected by the owner through G0.2 |
| G1.2 | Literature scouting linked to the thesis (D-086): every ingested paper stays embedded; while a focus is active each new paper gets a relevance score for it, and related papers are linked as related work, prior art or evidence; unrelated one-off hypotheses stop being the default cycle output | O (wiring) + N (scoring tool) | A related paper appears on the thesis within a day of ingestion; unrelated papers are only stored |
| G1.4 | Conviction ledger and calibration benchmark (D-087): `run_state/thesis_convictions.jsonl` (append-only forecasts from Nara, Oracle and the meta-oracle), the kill proposal at p_dead_end ≥ 0.8 or interest ≤ 2, and per-forecaster Brier scores and reliability when outcomes resolve | N (ledger tool) + O (wiring, UI) | Forecasts recorded at selection; a resolved stage produces a score per forecaster |
| G1.3 | Refinement protocol (D-086): anomaly notes and preregistered branch hypotheses linked to their parent; the meta-oracle checks for HARKing | O | An anomaly note and a branch can be recorded and shown with their parent |
| **G2** | **Stage T: theory runner** | | |
| G2.1 | Generic OpenSpiel experiment runner: preregistered design, seed policy, decision rule, retained results; a generic verifier registered for admission | O (admission and verifier) + N (runner) | A toy game study runs end to end and is admitted |
| G2.2 | Hand Nara a registered study to run: mailbox `run_study` kind or a `nara_run` lane bound to a `study_manifests` entry, and a daemon "due study" signal | O | A registered study runs without a human command |
| G2.3 | Fix the `loop_bridge` admission break (`known_opponent_utility/loop_bridge.py:111-116` vs `nara.py:564-567`) | O | Regression test |
| **G3** | **Stage S: semi-synthetic runner** | | |
| G3.1 | Agent-simulation harness: Flash-driven agents play the applied game under a preregistered protocol; reuse the known-opponent and payoff runners where they fit | N + O | One S study runs and is reviewed |
| **G4** | **Stage A: applied path** | | |
| G4.1 | Market data readiness audit for the active thesis's market; for prediction markets, a pre-resolution snapshot collector that removes exp007's look-ahead | N | Audit filed; snapshots accruing |
| G4.2 | Paper-trial driver scheduled on due trials (crypto H1 `paper_driver` or its successor); capture timers installed by the owner as needed | O + owner (timers) | One forward paper trial preregistered and running, 0 live orders |
| **G5** | **Now page (owner's view)** | | |
| G5.1 | `/api/now` read model from live sources only: completed work (mailbox fold plus merged SHAs, last 7 days); today's agenda (newest `daily_plans/*.json` with item status); thesis progression (focus state plus T/S/A stage per thesis, dispositions, week_alignment); blocked on the owner (open owner questions, `owner_decision` items, held items); **machinery health** (served model and window, Flash health, GPU/CPU/memory/temperature from the existing telemetry) | O | Every section shows its source age and a "producer idle since…" banner past 24 hours |
| G5.2 | Retire the hand-curated brief and work plan, the hard-coded pilot in `research_ops_status.py`, and the sealed planner's competing agenda (C8); age out the 251 dead bubble acks | O | No Now section reads a file without a scheduled writer |
| **G6** | **Docs consolidation** | | |
| G6.1 | Rewrite the entry points to the current system: START_HERE (current state), ARCHITECTURE (Flash only; pair as rollback appendix; Actors section), README health checks, research_program_v2 (LOOP_V2), GLOSSARY (current terms first) | O | A fresh session reading only the entry points describes today's system correctly |
| G6.2 | One operating-model doc: merge ORACLE_NARA_MAILBOX, ORACLE_NARA_BUILDOUT_PLAN, META_ORACLE_DAILY_LOOP and daily_lab_workspace | O | Old files are stubs pointing to the new one |
| G6.3 | Archive about 25 superseded docs (Flash benchmark, Qwen-era, June-era, point-in-time reviews; list in the 2026-09-22 drift inventory) and add "Historical" banners to LOOP_V0 and PROJECT_CONTEXT | O | DOCUMENTATION_INDEX lists only live docs and is linked from START_HERE |
| G6.4 | Record the decisions: §4, the meta-oracle loop, and a single merge authority. CLAUDE.md rule 2 re-pinned to the Flash deployment (owner edit, since that rule is inviolate) | owner + O drafts | DECISIONS has no numbering gap; CLAUDE.md matches the deployment |
| **G7** | **Daily loop hardening** | | |
| G7.1 | Lab state packet (d4), continuity canary v1.2, and the plan-review timing fix; timers after the owner's timer discussion | N + O | Loop runs unattended for five days at Stage 0 with no severe finding |

**Suggested order:** G0 first, because the research loop is dead. G5.1 and G6.1
early, so the owner can see what is happening and fresh sessions stop being misled.
Then G1, G2, G3 and G4 in sequence as the first new thesis moves through its
stages. G6.2–G6.4 and G7 fill capacity around them.

## 7. What the meta-oracle checks against this plan

- Every plan item names a goal ID. Work outside the plan needs a stated bottleneck.
- A stage transition (T to S to A) needs a preregistration, an admitted run, an
  independent review and a recorded decision. Results that do not support the
  hypothesis are kept, not re-run to a better outcome.
- No UI section or document is built for one day's data shape.
- Nothing implements live trading.
