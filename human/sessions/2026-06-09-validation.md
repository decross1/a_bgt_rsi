# Session — 2026-06-09 (afternoon): validation session

> Second session of the day (sibling to [`2026-06-09.md`](2026-06-09.md), the
> morning de-risk). Plan: [`docs/validation_session_plan.md`](../../docs/validation_session_plan.md).
> Goal: validate end-to-end on real infra — (1) the UI autonomy render, (2) NemoClaw
> running an autonomous research thesis, and — per the human's framing — (3) whether
> the **literature pipe falsifies with high accuracy or needs refinement**, plus
> thinking about the **classical-game → semi-synthetic** experiment ladder.

## How it ran
One Dynamic Workflow (`wf_30c6fa6a-51b`, 5 build/probe/design limbs + synthesis) →
serial integration by the primary session (verify-gate → demos → commit). Spawn
ledger + run-log per discipline (rules 3, 6). Two commits: **`d655da0`** (the
validated apparatus changes) + **`e1e2bb2`** (the Nara SKILL.md + autonomy blocker).

## What landed (all verify-gated: suite 866 passed/1 xpassed + framework code-review clean + 2 real smokes)
- **`run_loop_iteration` host tool** (`orchestrator/tool_plane.py`) — the FIRST
  non-read-only host tool: server-side topic gate + one-at-a-time (`active_run.json`)
  + wraps `nara.run_iteration(source="nemoclaw_agent")`. +16 tests. Schema enum
  `seed.source += "nemoclaw_agent"` applied (integrator spine edit).
- **Runnable 2-tool Nara bundle** (`agent/nemoclaw_nara/`) wired to the proven
  `host.openshell.internal:8077` + local Gemma harness + research persona, plus
  `docs/nemoclaw_agent_run_runbook.md` and `SKILL.md`.
- **Literature-falsification battery** (`experiments/lit_falsification_battery/`,
  13 labelled cases + harness + 15 self-tests) — the measurement instrument for
  the human's headline question.
- **`docs/thesis_to_experiment_construction.md`** — the surviving-thesis →
  classical-game → semi-synthetic construction spec + Qwen-skeptic diagnosis.
- **UI**: backend + tool plane restarted (both were serving STALE code);
  `:8700/api/coordinator/*` now serves the 13 live cycles; `:8077/tools` lists both
  tools. Live-render PASS/FAIL checklist + 404 baseline in `docs/ui_validation_report.md`.

## Headline findings

### 1. β WRITE-CAPABLE SEAM — PROVEN (DEMO 2a) ✓
From **inside nara-sandbox**, a real `run_loop_iteration` POST traversed
egress→gateway→host tool plane and drove a **full host LOOP_V0 iteration**
(`iter-2026-06-09-003`, `seed.source=nemoclaw_agent`, novel/survives, journal 066).
The tool plane logged the inbound POST from the sandbox IP. The sandbox can now
trigger host research compute, bounded by server-side validation + one-at-a-time +
scoped egress + capability absence.

### 2. LITERATURE PIPE — NEEDS FURTHER REFINEMENT (DEMO 1) — the human's headline question, answered
Real battery run (12 scored cases): **verdict accuracy 50%**, **off-domain
low-confidence gate recall 0/2**, the 2026-06-09 FASE-class `survives` bug
**recurs**. Three precise, empirical weaknesses + one positive:
- **The relevance gate is lexical-overlap-based and vocabulary-gameable.** It fires
  only when hypothesis↔neighbor lexical overlap < 0.05. The real FASE bug (overlap
  0.043) is caught, but an off-domain hypothesis phrased with GT vocabulary
  (`fase_off_01`, overlap **0.127**) sails through. It keys on surface vocabulary,
  not semantic topicality.
- **Corpus drift compounds it.** The off-domain DB-tuning hypothesis (`fase_off_02`,
  overlap **0.193**) retrieved drifted multi-agent **ML arXiv papers** (Belief
  Engine, MUSE-Autoskill, ATOM) — non-GT content inflates overlap. (Connects to the
  known `day3_*` fixture pollution + `ml_intern_fetched`.)
- **The critic over-applies `survives`.** All 3 on-domain rediscoveries (TFT, folk
  theorem, QRE) → `survives` (not `restated`) even with CORRECT on-domain retrieval.
  The critic only down-ranks on a *direct contradiction*; it does not recognise
  *restatement* or *off-domain irrelevance*.
- **POSITIVE:** both falsifiable claims (finite-PD "cooperate to the end"; "TFT is
  dominant") were **correctly falsified** — the falsification machinery works when a
  contradicting result is retrieved. The gap is restatement-detection +
  off-domain-tempering, NOT falsification per se.

→ **Answer:** the research/thesis pipe runs end-to-end (mechanically sound), but the
literature pipe **does** need refinement. Concrete next work below.

### 3. FULL IN-SANDBOX AGENT AUTONOMY — CARRYOVER (DEMO 2b, fallback taken, rule 7)
The in-sandbox OpenClaw `main` agent ran on local Gemma and the `nara-research-cycle`
SKILL.md installed + validated — but the agent has only `tool_search_code` natively
(**no shell/exec tool**), so it cannot execute the SKILL.md `curl` (path b). It
honestly reported the missing tool rather than confabulating. Full autonomy needs
the host tools registered as **native MCP tools** (path a: an `openclaw.json`
MCP-server block at `host.openshell.internal:8077`; the v2026.5.18 schema is unknown
— do NOT guess into a live config). Fallback (~20-min cap): DEMO 2a stands as the
proven seam; the agent invoking the tools *itself* is the named carryover.

## For the human (decisions / ops — surfaced, not blocking)
- **Literature-pipe refinement** (the main research-quality decision): the relevance
  gate needs a *semantic* topicality signal (not just lexical overlap — e.g. centroid
  cosine vs a GT-domain anchor, or an LLM topicality check), the critic needs explicit
  **restatement-detection** + an off-domain-temper rule, and the corpus needs
  **de-drifting** (constrain `retrieve_literature` to curated GT collections; the ML
  arXiv / `day3_*` pollution defeats the gate). Worth a decision entry.
- **D-041 ratification + independent skeptic (D-014/ToS):** Qwen cross-model signal is
  obtainable now (token starvation; `finding_promotion` already at 3072) — but
  promoting on it autonomously is D-041-gated; the off-box Claude-skeptic alternative
  is the D-014/ToS call. (See `docs/thesis_to_experiment_construction.md` Part 2.)
- **Path-a MCP wiring** for full agent autonomy: confirm the v2026.5.18 `openclaw.json`
  MCP-server block schema, then register the tool plane. (Carryover.)
- **Reverse-path build greenlight** (surviving-thesis → classical game → semi-synthetic):
  design is ready (`docs/thesis_to_experiment_construction.md`); building is a separate
  greenlight. Fine if no thesis survives to promotion — the path is validated as sound.

## Carryover (next session)
1. Literature-pipe refinement (gate semantics + critic restatement-detection + corpus
   de-drift) — re-run the battery as the regression check (bar: ≥80% acc, gate recall
   1.0, 0 ungated off-domain survives).
2. Full in-sandbox agent autonomy via path-a MCP registration.
3. (Optional) build the reverse-path thesis→experiment constructor.
4. UI live-render validation finish-up: the FASE low-evidence badge needs the off-domain
   iteration re-run to stamp `low_confidence=true`; the `nemoclaw_agent` provenance badge
   is the UI session's Task-2 (`docs/ui_validation_handoff.md`).
