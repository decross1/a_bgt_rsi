# UI reframe plan — the four pages, repurposed (the UI session's spec)

This is the authoritative spec for the UI reframe in the 4-session roadmap
([`docs/roadmap_full_loop.md`](roadmap_full_loop.md)). The UI session writes only `ui/`
+ `ui_plan.md`; the primary writes/gates/merges. Each page: **current → target → concrete
changes (files) → which session.** Ground every interaction in the intended flow
(*pick → read the journey → optional blind calibration → interrogate → decide*), and the
two-validation model (gate-verdict = a whole iteration; finding-review = one claim) + the
honest pipeline stage (literature today; experiments = Phase 2).

> **North star for the owner's role:** the cockpit is the **sign-off to applied-tier
> experiments** — the rigorous go/no-go *before* the applied world. Literature-stage
> iterations **auto-advance** (observable, not gated); the owner is reserved for the
> substantive end-of-pipeline decisions.

---

## 1. `/todo` — the cockpit (the main piece) · **S2**

**Current:** an inbox (`HumanTodoPanel`) that *also* resolves inline (the §6.5.4 calibration
bypass the UX audit found) + a separate calibration-gated resolution area + a stale "STUBS …
write nothing" banner + a raw-id chip chooser.

**Target:** literature items are observable not gated; the inbox is reserved for substantive
escalations; ONE calibrated decision surface; a context-rich journey view; calibration optional.

**Changes:**
- `ui/backend/human_todo.py` (`_gate_verdict_items`, ~147-169): **stop surfacing literature-stage
  `gate_verdict` iterations as blocking "needs you"** — reclassify as observable journeys (readable on
  Activity/Resolved). Inbox = substantive escalations only.
- `ui/frontend/src/components/HumanTodoPanel.tsx` (299-312): add a `selectMode`/`onSelect` prop. When
  set, **suppress the inline `GateVerdictForm`/`FindingReviewForm`** (the §6.5.4-gated writers); each row
  becomes a selector calling `onSelect(id)`. Keep `BubbleAckForm` + `DeferForm` + CLI fallback inline
  (not calibration-gated). **This closes the calibration bypass at the source** — copy can't, since the
  buttons write on click.
- `ui/frontend/src/routes/Todo.tsx`: render `<HumanTodoPanel selectMode onSelect={setSelectedId}>`; lift
  a SINGLE `/api/human_todo` fetch and pass it down (the inbox + workspace can never disagree); **delete
  the raw-id chip chooser** (selection now comes from the inbox).
- **Context-rich journey view** (new component, e.g. `PipelineJourney.tsx`): a pipeline ribbon (which of
  the 8 steps; experiments greyed = Phase 2) + the full journey read-only from `loop_memory.jsonl` /
  the `finding_detail` GET (hypothesis → retrieval + relevance → novelty + rationale → critic verdict +
  the contradicting paper or "uncontradicted" → an experiment-outcome slot) + an honest stage label
  ("literature-stage — not experimentally tested").
- **Calibration optional** (`CalibrationCapture.tsx`): opt-in, kept blind if used; remove the forced
  unlock gate. Fix the `findingId→refId` calibratedId to a **per-id `Set`** (flag-2: prevents a double
  `calibration_entry` on switch-away-and-back).
- **Two-voice critique** as the decision-support (`TwoVoiceChatPane`, already live).
- **Rewrite the stale banner** (`Todo.tsx:188-193`, now false); add a collapsible **"what am I being
  asked?" explainer** (2 research validations + 3 ops/info). Fix the D-044 mis-citation in the
  `Todo.tsx:329-330` code comment; sweep the stale `// stub / would-run` comments in `api/todo.ts`,
  `AuthorizeFixForm`, `DirectiveSignOffField`, `CalibrationCapture`.

---

## 2. Dashboard — health + top-level + in-flight research · **S2 (small)**

**Current:** health-first hero + system-activity hero + autonomy block (red-flags, findings, bubbles) +
collapsed iterations; `needsYouCount` is the only forward signal.

**Target:** full health + "what's happening / important research steps" + **all in-flight research
tracked**.

**Changes:** add an **"in-flight research" rollup** (`Dashboard.tsx`) — a compact list of what's running
(active iteration / coordinator run / experiment bridging) + the important next steps (e.g. "N findings
awaiting your applied sign-off"). Reads `/api/loop_v0/active`, `/api/coordinator/active`,
`/api/loop_v0/processes`. Keep the health strip + both LLM panels (gemma + qwen — do not remove Qwen).

---

## 3. Activity — deep-dive on running processes · **S3**

**Current:** live-vs-history strip, Active-now hero (NowBoard, ActiveIterationPanel, ActiveWorkersPanel),
CoordinatorPhases + FailedDispatches, a collapsed react-flow graph.

**Target:** real deep-dive on actively-running processes (per-worker tokens / tok-per-s / ETA).

**Changes — PRODUCER ALREADY LANDED (the stale "needs a producer" note is wrong).**
`agent_wrapper/worker_activity.py` emits `logs/worker_activity.jsonl` (one honest row per `call_sync`:
`tokens_generated / tokens_target / tok_per_s / eta_s / task_id / run_id / backend / model`; no fabricated
ETA — per-decode-step needs streaming, future work), and `ui/backend/activity.py::_real_inference` already
reads it (returns `synthetic:false` for rows within a 30s window; the synthetic fixture is the honest IDLE
fallback, not a gap). **So §3 is mostly DONE** — remaining UI work is just to confirm `ActiveWorkersPanel`
renders the real block during a live run and the synthetic marker drops. **No primary dependency outstanding.**

---

## 4. Coordinator → history · **S2 (small)**

**Current:** already a history of cycles (one `CoordinatorCycleCard` per `coordinator_cycles.jsonl` row,
newest-first, plan→outcome→evidence). On-target already.

**Target:** an orchestration **history** over a time frame.

**Changes:** add a **time-range filter** (`Coordinator.tsx`) — today / this-week / all, oldest-first or
newest-first. Small; the data is already there. Optionally rename the page header to "Orchestration
history."

---

## 5. Experiments — interactive applied refinement + card wall · **S3 (the biggest)**

**Current:** a research index grouped by tier (synthetic / semi-synthetic / applied); each card = id +
title + verdict chip + bridge badges; a separate `ExperimentDetail.tsx` (outcome + metrics + charts).
**Findings are orphaned** in Coordinator cycles, not surfaced here; no lifecycle metadata; no interactivity.

**Target:** interactive **applied-tier refinement** + a card wall of ALL experiments → click a card → full
**lifecycle + findings**.

**Changes:**
- **Card wall** (`Experiments.tsx`): each card shows status + the linked finding(s) + tier + sign-off
  state (applied-tier cards show "awaiting your sign-off" when bubbled). Click → the detail.
- **Lifecycle + findings in detail** (`ExperimentDetail.tsx`): add the *lifecycle* (when run, which loop
  iteration seeded it, the bridge, cross-tier replications) + the **findings it surfaced** (join the
  coordinator-cycle `promoted_findings` / `surfaced_findings` for this experiment, currently orphaned).
- **Interactive applied refinement — CLI LANDED (2026-06-19); the UI seam is yours.** The primary built
  the blessed refine CLI `python -m experiments.exp007_polymarket.refine_cli` (start/turn verbs, mirrors
  `finding_session chat`; **zero trading** — it re-runs the exp007 PAPER forecast against the offline
  fixture and scores Brier): `start --session-id <id>` → `{ok, params, tunable:{seed,temperature,n}, note}`;
  `turn --session-id <id> [--param seed:42|temperature:0.4|n:8] [--message <intent>]` → `{ok, params,
  n_forecast, brier, sample[], elapsed_s}`. **Build:** a `ui/backend` seam mirroring `chat_seam.py`
  (`_exec_blessed` runner over `experiments.exp007_polymarket.refine_cli`, argv-array, no shell;
  `POST /api/exp007/refine/start|turn`) + the Experiments interactive surface (param controls → turn →
  render the new Brier + sample). The owner drives it after signing off a finding to applied in the cockpit.

---

## Acceptance (per the roadmap verification)

- Literature items no longer show as "N blocked on you"; the inbox holds only substantive escalations; no
  resolution path bypasses calibration when calibration is used; calibration is opt-in.
- The journey view shows the full pipeline context for a selected item; the banner is honest; the explainer
  exists.
- Coordinator has a time-range filter; Dashboard shows in-flight research.
- Experiments has a card wall → lifecycle + findings; the applied-paper interactive surface works end to end.
- UI suites green (`vitest` 94+ files / `pytest`); a real `env -u MOCK_LLM` smoke against the live `:8700`.
