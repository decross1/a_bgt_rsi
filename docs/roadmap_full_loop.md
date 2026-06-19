# Roadmap — the full loop in 4 sessions (3 demonstration loops + the 4-page UI reframe)

Committed source-of-truth for the approved plan (the `~/.claude/plans/` copy is scratch).
Goal: reach the apparatus's payload — **novel idea → research pipeline → human go/no-go →
applied tier** — and demonstrate it with **three loops** + give each of the four pages a
purpose, in **4 sessions** (S1 done).

## The three loops (capability ladder)
1. **Falsification** — kill a known-refutable hypothesis (proves the critic refutes).
2. **Rediscovery** — a known idea is flagged + not progressed (proves the novelty gate gates).
3. **Full novel → applied** — novel ideation → classical experiment → synthetic → bubble →
   **cockpit go/no-go** → applied (**paper**, CFTC-safe) → interactive applied, with in-flight
   tracking.

## The 4-page reframe
Dashboard = health + in-flight research · `/todo` = sign-off to applied-tier · Activity =
deep-dive on running processes · Coordinator = orchestration **history** · Experiments =
interactive applied refinement + card wall (→ lifecycle + findings). Detailed per-page spec:
[`docs/ui_reframe_plan.md`](ui_reframe_plan.md).

## Skill-signals — embedded (D-056)
The framework asked the runtime to emit a skill-friction stream; we reviewed it adversarially
([`docs/skill_signals_contract.md`](skill_signals_contract.md), D-056), **shipped the (b) GAP /
(c) MISUSE helper** `orchestrator/skill_signals.py` (`59d1b07`), and the framework's reply
**cleared us** (our contract is self-standing — no dependency on their ingest). **Remaining,
folded into this roadmap:**
- **(a) FRICTION (form i)** — the deferred trigger; the helper already accepts the full enum, so
  this is call-sites only (emit on a genuine run-log-skill misfit, never on a non-framework-enum
  status). → **S2.**
- **"Emit on friction" as build discipline** — the workflows we run this roadmap (loop runs,
  experiment wiring, UI gates) should **call `emit_skill_signal` when a build/runtime agent hits
  friction with a framework skill** (run-log / validate / fallback / …). This is how the work
  itself feeds the stream rather than reconstructing drift after the fact. → woven through S2–S4.

## Session breakdown

### S1 — DONE (2026-06-19)
Reference-passing verified (already shipped `39ba954`); **Loops 1 & 2 demonstrated** with 3 real
iterations (`iter-2026-06-19-001/002/003`: rediscovery/restated, nonsense/falsified, novel/survives);
the 3-iteration LOOP_V0 exit materially met; the UI reframe work order authored. (Skill-signals
(b)/(c) shipped earlier, `59d1b07`.)

### S2 — Loop 3 part 1 (experiment chain) + the cockpit reframe + skill-signals (a)
**Primary:**
- Loop 3 step 1–2: take a novel finding that maps to a built experiment (or run a built one
  standalone) → run a **classical experiment** (exp001 repeated-PD) via `orchestrator/autoresearch.py`
  (committed-results bridge first; `run_real` only with reason) → **bridge** the `experiment_outcome`
  into a loop iteration → **replicate in a synthetic tier** (exp003/exp004) → the cross-tier finding
  **bubbles to the cockpit**.
- Skill-signals **(a) FRICTION** call-sites (form i) + make `emit_skill_signal` part of the
  workflow/build discipline.
**UI session (work order in the 2026-06-19 session note → `docs/ui_reframe_plan.md`):** the cockpit
reframe (observable literature, one calibrated surface, context-rich journey, calibration optional,
explainer, bypass fix) + the Coordinator time-range filter + the Dashboard in-flight rollup.

### S3 — Loop 3 part 2 (applied tier) + Experiments + Activity
**Primary:** the cockpit go/no-go → **send to applied (exp007 paper)** → an **interactive applied
refinement** seam (blessed CLI, mirrors the chat-seam; zero trading) + emit `logs/worker_activity.jsonl`
for the Activity deep-dive.
**UI session:** the **Experiments page** reframe (card wall → lifecycle + findings + the interactive
applied surface) + the **Activity** real worker-internals.

### S4 — automate + harden (close the loop)
**Primary:** auto-orchestration — hypothesis→experiment routing, automatic cross-tier replication, and
the **experiment-outcome → loop_memory feedback edge** (the Phase-2 *closed* loop); pre-resolution
snapshots for the applied audit trail; final end-to-end integration so all three loops run as designed.

## Verification (per loop)
- **Loop 1:** a known-false hypothesis → `falsified` with the contradicting paper cited (✓ S1).
- **Loop 2:** a known result → `rediscovery`/`restated`, auto-handled not bubbled (✓ S1 research;
  not-bubbled lands with the cockpit reframe, S2).
- **Loop 3:** end-to-end novel → classical → synthetic → cockpit sign-off → applied-paper interactive,
  visible as in-flight research (Dashboard/Activity) and as a card with full lifecycle + findings
  (Experiments).
- Skill-signals: `emit_skill_signal` called at real friction moments; `run_state/skill_signals.jsonl`
  grows append-only; the D-048 zero-live-rows invariant holds.
