# UI plan — orchestrator dashboard + LOOP_V0 iteration view

> **Companion plan to the apparatus build.** The two share data contracts
> (the JSONL schemas in `schema/`, plus the LOOP_V0 contract below) but do
> NOT share source files outside `ui/`. The UI session writes only to
> `ui/` and this file.

## §LOOP_V0 — iteration view (active section, 2026-05-26)

The UI's top section is now the LOOP_V0 iteration view: human prompts a
topic → Nara runs one iteration → past iterations land in a list → the
journal entry opens inline. Built per
[`agent/prompts/ui_session.md`](agent/prompts/ui_session.md) and
[`LOOP_V0.md`](LOOP_V0.md) §"What's needed from the UI session", on the
substrate the primary session builds per
[`archive/plans/idempotent-spinning-sonnet.md`](archive/plans/idempotent-spinning-sonnet.md)
(imported into the repo 2026-06-14; formerly a stranded `~/.claude/plans/` file).

### Layout

```
┌─ NaraPromptForm ──────────────────────────────────────────────────┐
│ topic [        ]                          [start iteration]      │
└──────────────────────────────────────────────────────────────────┘
┌─ ActiveIterationPanel ────────────┐ ┌─ ResolvedIterationsList ───┐
│ id · topic · elapsed              │ │ iter-2026-05-26-001 ▸      │
│ [start][summ][PD][retr][jrnl][sm] │ │   rediscovery / restated   │
│ narration line                    │ │ iter-2026-05-25-002 ▸      │
│ tool calls                        │ │   novel / survives         │
│   summarize_paper  6.1s passed    │ │ …                          │
│   query_chroma     1.4s running   │ │                            │
└───────────────────────────────────┘ └────────────────────────────┘
┌─ JournalScroll ──────────────────────────────────────────────────┐
│ (selected entry rendered as markdown)                            │
└──────────────────────────────────────────────────────────────────┘
↓ substrate panels (HealthStrip, OrchestratorQueue, VllmPanel,
  Day4ChainList, RobustnessPanel, BaselineCard, ProcessGrid) stay
  mounted below so the human can watch the Spark itself while Nara runs.
```

### Components

| Path | Polls | Notes |
| --- | --- | --- |
| `ui/frontend/src/components/NaraPromptForm.tsx` | n/a | Posts trimmed topic to `/api/loop_v0/start`. Disabled until non-empty. |
| `ui/frontend/src/components/ActiveIterationPanel.tsx` | `GET /api/loop_v0/active` at 1 Hz | Renders idle when endpoint returns 204. Tool-call durations tick in real time off `step_started_at` and per-call `started_at`. |
| `ui/frontend/src/components/ResolvedIterationsList.tsx` | `GET /api/loop_v0/iterations` at ~0.2 Hz | Newest first; novelty + critique badges; click loads the entry into `JournalScroll`. |
| `ui/frontend/src/components/JournalScroll.tsx` | `GET /api/loop_v0/journal/{id}` on selection | Inline markdown renderer (headings, paragraphs, lists, fenced + inline code, **bold**). No new deps. |
| `ui/frontend/src/fixtures/loop_v0/` | n/a | `active_iteration.json` + `loop_memory.jsonl` (3 rows) + 2 journal markdown files + `index.ts` typed loader. Panels accept an `initial` prop so tests bypass polling. |

### Backend

`ui/backend/loop_v0.py` registers a router under `/api/loop_v0/`:

| Endpoint | Behavior |
| --- | --- |
| `POST /start` | Body `{topic: str}`; `subprocess.Popen(["env", "-u", "MOCK_LLM", python, "-m", "orchestrator.loop_v0_cli", "--topic", topic], cwd=repo_root)`; returns `202 {pid, topic}`. Rejects empty / oversize topic with 400. |
| `GET /active` | Reads `run_state/active_iteration.json`; returns 204 No Content if absent. |
| `GET /iterations` | Reads `memory/loop_memory.jsonl`, sorted newest-first by `ended_at`; returns `{iterations: []}` if absent. Malformed rows are skipped (producer contract). |
| `GET /journal/{iteration_id}` | Looks up `journal_entry_path` from `loop_memory.jsonl` for the iteration; falls back to a glob scan of `journal/iterations/*.md` for files mentioning the id. Returns `{iteration_id, path, content}`. Rejects path-traversal ids with 400. |

Wired into `create_app` with three env overrides (`UI_LOOP_V0_REPO`,
`UI_LOOP_V0_RUN_STATE`, `UI_LOOP_V0_JOURNAL`) and an injectable `popen`
hook so tests don't shell out to the apparatus.

### Shared contract (read-only for the UI)

The primary session writes these; the UI reads them and never writes back.
Both writers and readers treat them as the source of truth for what Nara
is doing now and what Nara has done.

**`run_state/active_iteration.json`** — atomic-write while an iteration is
in flight; deleted on completion. Shape:

```json
{
  "iteration_id": "iter-2026-05-26-001",
  "topic": "...",
  "started_at": "...",
  "current_step": "starting | summarize_paper | play_pd_match | query_chroma | journal_writer_stub | nara_summarizing",
  "step_started_at": "...",
  "narration": "last narration sentence Nara emitted",
  "tool_calls_so_far": [
    {"tool": "<name>", "started_at": "...", "ended_at": "...", "status": "passed"}
  ]
}
```

**`memory/loop_memory.jsonl`** — append-only, one row per completed
iteration. Schema is `schema/iteration_record.schema.json` (primary
creates). Minimum fields the UI relies on: `iteration_id`, `started_at`,
`ended_at`, `seed.topic`, `journal_entry_path`, `nara_summary`. Part-1
hello-world fills `hypothesis` / `retrieval` / `novelty` / `critique`
with placeholders — the UI renders the badges only when those fields are
present, so the panel reads cleanly across both Part-1 and Part-2.

**`journal/iterations/NNN.md`** — one markdown file per iteration. Format
is the apparatus's choice; the UI's renderer handles the small subset
already used (headings, lists, **bold**, `inline code`, fenced code).

### Test discipline

- Frontend: each component has a vitest file under `ui/frontend/tests/`
  using fixture imports rather than network calls. `vi.stubGlobal("fetch", …)`
  is used only for endpoint-error paths.
- Backend: `ui/backend/tests/test_loop_v0.py` covers each endpoint with
  tmp_path fixtures plus a stubbed `popen`. One smoke test uses a real
  `subprocess.Popen` rerouted to `/bin/echo` so the test never touches
  the real CLI or the real `run_state/`.

### Open items handed back to the primary session

- The `journal_entry_path` in `loop_memory.jsonl` rows is expected to be
  resolvable from `repo_root` (either absolute or relative). The UI scans
  `journal/iterations/*.md` as a fallback when the row is absent, but
  only files inside `journal_dir` are read — keep entries there.
- Any new `current_step` value beyond the six listed needs adding to
  `LoopV0Step` in `ui/frontend/src/types/schemas.ts`; the step strip
  silently renders extra values as "not highlighted" but doesn't add a
  chip for them.

---

## §ACTIVITY + EXPERIMENTS — Batch 1 of the concurrent-HITL rhythm (active, 2026-06-05)

Built under the batch -> fan-out -> gate operating rhythm
([`archive/plans/i-want-to-start-concurrent-flurry.md`](archive/plans/i-want-to-start-concurrent-flurry.md),
imported into the repo 2026-06-14): the human names N
page concepts, one builder agent per page runs concurrently in a single
phase-bounded Workflow, the primary UI session applies the small shared-file
edits (`App.tsx` routes/nav, `app.py` router registration), and the human
reviews the whole batch at once. This section is the data contract + the
mock/real boundary for the first two pages.

### Page A — Live Activity Graph + Agent Monitor (route `/activity`)

Files: `ui/backend/activity.py` (+ `tests/test_activity.py`); frontend
`routes/Activity.tsx`, `components/ActivityGraph.tsx` (@xyflow/react v12),
`components/AgentMonitorPanel.tsx`, `api/activity.ts`, `types/activity.ts`,
`fixtures/activity/`.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/activity/graph?limit=N` | `{available, nodes, edges, generated_at}`. Built from `logs/orchestrator.jsonl` + `day*`/`exp*` via `chain.py` `recent_tasks`+`build_chain` over the SAME `LogStore(logs_dir)` the inspector uses, so each `node.request_id` deep-links to `/chain/req/:requestId`. Edges appear only where the call log carries `parent_request_id` chains; in a worktree without the linked `calls.jsonl` the graph is dispatch-node-only — an honest data-availability artifact, not a bug. |
| `GET /api/activity/monitor` | `{available, active, recent, synthetic_inference}`. `active`/`recent` are real (`recent_tasks`); worker `cpu_pct`/`rss_mb` cross-referenced to `ui/logs/telemetry.jsonl` `processes[]`. The per-worker INFERENCE INTERNALS (decode step / tokens / ETA) have NO on-disk source — returned under `synthetic_inference {synthetic:true, needs:"worker_activity.jsonl (primary-session)"}` and rendered behind an amber synthetic marker. Never presented as measured (rule 4/8). |

Both degrade to `{available:false}` when `logs/orchestrator.jsonl` is absent.

### Page B — Interactive Experiment Digestion (routes `/experiments`, `/experiments/:expId`)

Files: `ui/backend/experiments.py` (+ `tests/test_experiments.py`); frontend
`routes/Experiments.tsx` + `ExperimentDetail.tsx`, `components/MiniMarkdown.tsx`,
`api/experiments.ts`, `types/experiments.ts`, `fixtures/experiments/`.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/experiments` | Index by scanning `experiments/*/results/`. Handles heterogeneous shapes: exp001 (`summary.json` + `per_round.jsonl` + CSVs), exp003 (`summary.md` + `trials.jsonl`), exp002 (no `results/` -> "no results yet"). |
| `GET /api/experiments/{expId}` | Parses what exists; `per_round` aggregated to per-opponent series (capped 100k rows, `truncated` flag); `trials` head-sampled (50). `round_inspector_linkage:false` for exp001 (per_round rows carry no `task_id`), surfaced as an explicit "linkage not available" note — not fabricated. 404 missing experiment, 400 path-traversal (`_safe_exp_id` allowlist). |

### Boundary handed to the primary session

The one synthetic surface across both pages is Page A's per-worker inference
internals. To make it real, the apparatus needs a per-worker activity log
(proposed `logs/worker_activity.jsonl`: per in-flight `task_id` -> current
decode step / tokens generated / target / ETA / tok-per-s). `activity.py`'s
`SYNTHETIC_INFERENCE` constant then becomes a reader of that file and the
frontend marker drops automatically once `synthetic:false`.

### Tests + env

`ui/backend`: +16 (test_activity 8, test_experiments 8) -> 79 backend pass.
`ui/frontend`: +18 (graph 5, monitor 4, exp index/detail 9) -> 46 frontend
pass. Backend tests run under `ui/.venv-ui` (new, gitignored):
`pip install -r ui/requirements-ui.txt`. `tsc --noEmit && vite build` clean
(`@xyflow/react ^12.11.0` added to frontend `package.json`).

---

## §Loop-v1 iteration surfacing (active section, 2026-06-05, reconciled with main)

Surfaces the Loop-v1 `iteration_record` blocks in the iteration view. The
primary session shipped these to `main` (commit `ef02a7e`) while this session
was live; folded in here per `human/sessions/2026-06-05-ui-reconcile.md`.
Read-only — `loop_v0.py` passes the new blocks through verbatim, no backend
change.

| Block | Rendered as |
| --- | --- |
| `meta_review.conditioning_bullets` | A "conditioned by" bulleted block under the row's topic — the prior-memory bullets that conditioned the iteration. |
| `redteam.{verdict, retries_used}` | A chip `redteam <verdict> · <n> retr(y/ies)`, highlighted red when `verdict==fatal_flaw` OR `retries_used>0`, quiet zinc otherwise. |
| `gate_status` | A badge: `pending` (sky) / `valid` (emerald) / `invalid` (red) / `needs_revision` (amber). |

Folded into `ResolvedIterationsList.tsx` (the Batch-2 paginated/filtered list)
and `ActiveIterationPanel.tsx`; the optional fields stay quiet on pre-v1 rows.

**Dropped in the reconcile:** main also shipped an exp004 dashboard panel
(`Exp004Panel`, `GET /api/experiments/exp004`, `compute_exp004_summary`). Per
the guide it was DROPPED — the generic `/experiments` feature (Page B) subsumes
it; `exp004_combinatorial_auction` surfaces via `GET /api/experiments/{exp_id}`.

---

## §AUTONOMY OBSERVABILITY — the coordinator loop must stop running "dark" (active, 2026-06-09)

RENDER half of the autonomy-observability batch. Spec + rationale:
[`archive/ui_handoffs/ui_session_handoff_2026-06-09.md`](archive/ui_handoffs/ui_session_handoff_2026-06-09.md)
and [`archive/ui_handoffs/ui_autonomy_observability_plan.md`](archive/ui_handoffs/ui_autonomy_observability_plan.md).
The primary session lands the EMIT half (the spine instrumentation that writes
the data files below) in a parallel workflow; this session builds the RENDER
half in `ui/` against the documented contracts. All new data files are
append-only JSONL, gitignored, read live by the backend exactly as
`loop_memory.jsonl` already is — so this work builds against fixtures and ships
independent of EMIT landing (endpoints return empty/`204` until the files exist).

**Why.** On the first live `coordinator --execute --once` (2026-06-09) the
autonomous loop picked a topic, planned, dispatched an iteration, promoted
findings, and bubbled — and the human saw an unlabeled `ad_hoc` blip. As the
apparatus goes autonomous the human is an *auditor*: the UI must answer "what did
the loop decide, on what basis, can I trust it?" Six streams flow through stages
with no view (coordinator cycle, plan, **failed dispatch**, surfaced findings,
bubbles, per-agent attribution).

**Design principles (apply these):** (1) *make absence legible* — every
dispatched action renders an explicit state (`queued/running/succeeded/failed+error/
skipped/degraded`); a failed dispatch is a **row, never a silent gap**. (2)
*provenance everywhere* — badge every row with the `agent` field
(`coordinator`/`nara`/`workflow:<id>/<role>`/`human`). (3) *show the epistemic
basis* — a `novel/survives` verdict carries its evidence (retrieval relevance,
external-search status, skeptic health); **flag low-evidence verdicts** (the
headline 2026-06-09 bug: false `novel/survives` on off-domain retrieval). (4)
*degraded ≠ broken* — qwen empty-content + ml-intern 0-papers are amber, not red;
gemma healthy = green. (5) *one cycle = one narrative*.

### Data contracts (read-only for the UI; field names final when EMIT merges)

| File (gitignored, live) | Shape the UI reads |
| --- | --- |
| `run_state/coordinator_cycles.jsonl` (NEW) | `{timestamp, run_id, agent, topic, topic_source, plan:[{action,args}], outcomes:[{action, status: passed\|skipped\|errored, error?}], dispatched_iteration_id?, promoted_finding_ids:[], bubble_run_ids:[]}` — one row per cycle; the join key. |
| `run_state/active_run.json` | now `kind:"coordinator"` with `current_step ∈ {assess,plan,validate,dispatch}` + `narration` (chosen topic + why). |
| `memory/surfaced_findings.jsonl` (NEW) | promoted findings — `{finding_id, iteration_id, agent, text, ...}`. |
| `memory/coordinator_bubbles.jsonl` (NEW) | the loop's "raise to the human" output — `{bubble_id, run_id, agent, text, severity?, ...}`. |
| `memory/loop_memory.jsonl` (extended) | iteration rows now carry `seed.source` (badge coordinator-vs-human) and `retrieval.relevance` (low/thin flag → low-evidence badge). |
| health signals | `agent` field on run-log rows; a qwen-degraded + ml-intern-0-papers status the sampler exposes. |

### Backend (`ui/backend/`, new endpoints; mirror `loop_v0.py` register-fn idiom)

New module `coordinator.py` with `register(app, *, repo_root, run_state_dir, memory_dir)`,
wired in `app.py` next to `register_loop_v0`; absent files return `{...: []}` /
`204` (reuse `_read_jsonl`, newest-first). Endpoints:
`GET /api/coordinator/cycles`, `GET /api/coordinator/active` (reads `active_run.json`),
`GET /api/coordinator/findings`, `GET /api/coordinator/bubbles`. Read-only.

### Frontend (`ui/`) — 3 pages + a new view

| Surface | What renders |
| --- | --- |
| **NEW route `/coordinator`** (`Coordinator.tsx` + `CoordinatorCycleCard.tsx`) | card per cycle: topic (+source badge) → plan with per-action status chips (executed/skipped/**errored+error**) → linked iteration → promoted findings → bubbles. Agent badge on header. |
| **Activity** (`Activity.tsx`) | coordinator phases (assess/plan/validate/dispatch) from `active_run` narration; agent badges; **explicit failed-dispatch rows**; qwen-degraded distinct. |
| **Dashboard** (`Dashboard.tsx`) | health row (gemma green / qwen amber / ml-intern status); Recent Iterations + a **coordinator-triggered** badge + a **low-evidence-verdict** badge; **Surfaced Findings** panel; **Bubbles** panel; a standing **red-flags trend strip** (novel-rate, suspected-false-novel rate, off-domain rate). |
| **Experiments** (`Experiments.tsx`) | coordinator cycles as auditable units (plan→outcome→evidence) with epistemic basis visible. |

Shared reusable components: `AgentBadge.tsx` (provenance), `LowEvidenceBadge.tsx`
(+ a tiny evidence-scoring helper), `SurfacedFindingsPanel.tsx`, `BubblesPanel.tsx`,
`RedFlagsTrendStrip.tsx`, `CoordinatorPhases.tsx`. Fixtures under
`src/fixtures/coordinator/index.ts`. Types added to `types/schemas.ts`; API
helpers to `api/http.ts`.

### Priority order

1. Make absence legible + the Coordinator view (the #1 gap).
2. Surfaced-Findings + Bubbles panels + agent badges.
3. Low-evidence-verdict flag + degraded-vs-broken health.
4. Standing red-flags trend strip.

### Test + acceptance

Vitest per-component tests against fixtures; backend pytest with `tmp_path` files
(mirror `test_loop_v0.py`). Acceptance: re-run `coordinator --execute --once` →
Coordinator view shows the full arc; a **forced failed dispatch** is an explicit
row; Surfaced Findings + Bubbles populate; every row has an agent badge; a verdict
on thin retrieval shows a **low-evidence** flag; qwen-degraded renders amber.
Print `UI READY TO MERGE`.

### Boundary handed to the primary session (EMIT)

The UI renders these; it does not write them. Land first: coordinator
`active_run` `kind="coordinator"` + per-phase narration; `coordinator_cycles.jsonl`;
never-silent failed-dispatch rows; `surfaced_findings.jsonl` + `coordinator_bubbles.jsonl`;
qwen-degraded + ml-intern-papers health signals; `retrieval.relevance` topical
signal for the low-evidence badge. Confirm final field names when the EMIT PR merges.

### Reconciliation — EMIT merged 2026-06-09 (field names now authoritative)

The EMIT half landed on `main` (`0d9c4af`: `coordinator_cycle_log.py`,
`retrieval_relevance.py`, `active_run` `kind="coordinator"`). Folded `main` in and
reconciled the RENDER contract to what EMIT actually writes (the handoff's "confirm
field names when EMIT merges"). Corrections from the sketch:

- **`retrieval.relevance`** = `{relevance: number, low_confidence: boolean, reason: string}`
  (NOT `score`/`flag`). The low-evidence flag + red-flags off-domain rate now key on
  `low_confidence` (the worker's authoritative signal) + empty-neighbors; the invented
  `< 0.3` score floor was dropped (it doesn't map to the blended-score distribution).
- **surfaced_findings** rows use `title`/`claim` + `source_iteration_id` +
  `promoted_at` + `novelty_class`/`critic_verdict` (NOT `text`/`iteration_id`/`timestamp`,
  no `agent`). Backend findings sort → `promoted_at`.
- **bubbles** rows are `{timestamp, run_id, finding_ids, note}` (NOT
  `bubble_id`/`text`/`severity`/`agent`) — rendered uniformly as the escalation channel.
- **active_run** carries no top-level `topic`; the topic lives in `narration`/`label`.
  `current_step` ∈ {assess,plan,validate,dispatch} matched as-is.
- Cycle rows matched the sketch (EMIT adds a top-level `status` the type now allows).

Verified end-to-end: the real `cycle_row_from_report` flows through `CoordinatorCycleCard`
(errored outcome + error string), and the backend serves real-shaped findings/bubbles/
active_run (cross-layer smoke).

### Added this batch — degraded health signals (next-phase, EMIT was already emitting it)

EMIT also writes `run_state/health_signals.jsonl` (`ml_intern_zero_papers`,
`qwen_degraded_empty_content`, both `severity:"degraded"`). Added the missing surface:
`GET /api/coordinator/health_signals` + `HealthSignalsPanel` (amber, "degraded ≠ down"),
wired into the Dashboard autonomy block. Completes design principle #4.

### Validation — live-data + harden pass (2026-06-09, Dynamic Workflow)

Validated the merged render against **live apparatus data** (the `:8700` backend was
stale/pre-merge, so validation ran the in-process merged app via `TestClient(create_app())`
which reads `_PRIMARY_REPO`). Every surface PASSES against real data: **19** coordinator
cycles (3 errored → explicit red rows with their error), **52** `loop_memory` rows render
without console errors, findings/bubbles/health panels show clean empty states (files
absent live), `/active` → 204 idle. Plus a deep edge-case hardening sweep so a single
malformed producer-owned JSONL row degrades to a legible fallback rather than blanking the
page; 89 defensive fixes, frontend suite grew to 639 tests, backend 196. Two real bugs
caught: a `Dashboard` missing-import build break and a `CoordinatorCycleCard` object-status
crash (one bad row blanked the Coordinator page). Report: [`ui/notes/validation_report.md`](ui/notes/validation_report.md).

- **Task 2 — `nemoclaw_agent` provenance (now LIVE):** new `SourceBadge` maps
  `seed.source`/`topic_source` to a tone family — **`nemoclaw_agent` → violet** (the
  headline β signal: the sandboxed Nara agent chose+ran the thesis), `coordinator` → sky,
  `arxiv_pick` → indigo, human/probe → quiet zinc — used consistently on `CoordinatorCycleCard`
  and the iteration rows. `loop_memory.jsonl` now carries 2 live `nemoclaw_agent` rows, so
  this is validated end-to-end, not just forward-compat.
- **EMIT-gated followups** (render paths built + proven but live-unexercised until EMIT
  writes the data — low-evidence firing, populated findings/bubbles/health, mid-flight
  `active_run`, a successful `dispatched_iteration_id`) are handed to the primary session as
  [`ui/notes/emit_test_plan.md`](ui/notes/emit_test_plan.md).

### Evening block 2026-06-09 — WF-A/WF-C/WF-B (three Dynamic Workflows)

- **WF-A (forward-compat + live wire):** regression pins proving every surface ROBUST
  against the primary's *announced* additive contract (`undecidable` + override fields,
  `novelty_axes`, five new relevance keys, garbled variants); first validation against the
  RUNNING `:8700` (`test_live_8700.py`, version == HEAD, payload parity with in-process);
  `CoordinatorPhases` stale-active-run amber hint (the lock-leak's phantom-running dual).
- **WF-C (observability reconciliation, operable slice):** from the human's screenshot
  review ([`ui/notes/observability_reconciliation_plan.md`](ui/notes/observability_reconciliation_plan.md)
  — root causes: attribution dropped, active_run mirror bypassed, stale run_id stamping,
  test rows polluting live cycles, invisible human queue). Shipped: **SystemActivityHero**
  (registered / busy-unregistered-AMBER / idle — the dashboard can no longer say
  "idle/nominal" at GPU 96%), **failed-dispatch grouping** (identical (topic,action,error)
  → one ×N row), **Human TODO** (`GET /api/human_todo` + `HumanTodoPanel` + `/todo` route:
  pending gate verdicts with exact `gate_cli` commands — 11 live items surfaced —, finding
  reviews, unacked bubbles, stale active-run, state gates; read-only — B4 write-back stays
  gated on the main session blessing the A5 CLI contract), drill-in IA links. Workstream A
  (producer fixes: mirror registration, run_id lifecycle, task_type, artifact hygiene) is
  the main session's, per the plan doc.
- **WF-B (confirmed contract, build half):** close-out 19:56 confirmed shapes → types/
  fixtures synced; `undecidable` quiet-grey tone + skeptic-override tooltip (both verdict
  surfaces); `category`/`rule_fired` low-evidence tooltip detail (isLowEvidence pinned
  unchanged); `NoveltyAxesChip` wired into iteration rows. **Re-validation DEFERRED** —
  the promised live rows were never produced this block (0 `low_confidence=true`,
  artifact files absent, 0/139 dispatched); gap 5 (nemoclaw e2e) CLOSED on the two live
  rows, pinned verbatim. Dispositions in `emit_test_plan.md`; the live-census tests
  auto-validate the moment the data lands.

Suites at close: tsc clean · frontend 62 files / **730 tests** · backend **215**. Each
workflow independently audited.

---

## 2026-06-10 closure — Task-0 carry-overs landed (UI-overhaul build, agents R1a/R1b)

Closure annotations for the 2026-06-09-evening carry-over findings, numbered
T1.1–T1.6 / T3.1–T3.3 in the 2026-06-10 UI-overhaul workflow (the same items
are Task 0 items 1–7 and 9–10 of
[`archive/ui_handoffs/ui_session_handoff_2026-06-10.md`](archive/ui_handoffs/ui_session_handoff_2026-06-10.md)).
All nine **landed this session** by the Phase-2 build agents **R1a** (ui-tests)
and **R1b** (ui-components). Written at docs-closure time while Phase-3
integration was folding the build branches into the main checkout — the
Phase-4 suite gates are the verification of record.

| Finding | Status | Resolution |
| --- | --- | --- |
| T1.1 — repo root hardcoded to the worktree depth in 3 live test files | landed (R1a) | Walk-up resolver (probe ancestors of the test file for `memory/loop_memory.jsonl`; fail loudly listing every probed path) inlined in all three files; the shared `livePaths.ts` extraction was deferred to the integrator. |
| T1.2 — `KNOWN_RELEVANCE_KEYS` missed `topicality` | landed (R1a) | `topicality` added to the drift census and to the additive-key comment/type in `types/schemas.ts`; full additive set now `anchor_cosine, curated_overlap, neighbor_spread, topicality, category, rule_fired`. |
| T1.3 — axes-census double render | landed (R1a) | `cleanup()` inserted between the list render and the standalone `NoveltyAxesChip` render inside the `WITH_AXES` loop, so the testid query is single-element again on live axes rows. |
| T1.4 — off-domain tile pinned at literal `"0%"` | landed (R1a) | Trust tiles re-pinned as cohort invariants recomputed from the loaded live rows (rendered percent and "N of M" must match the counted cohort; a clean cohort must read 0%, a flagged one its true rate). |
| T1.5 — missing live `/api/human_todo` probe + per-request `_git_sha()` | landed (R1a) | `test_live_8700.py` gains the `/api/human_todo` `{items, counts}` probe; `app.py` snapshots `_GIT_SHA` once at import and serves it from both the FastAPI `version` and `/api/health` — version now means the running binary. |
| T1.6 — Dashboard drill-link inside `<summary>` | landed (R1b) | The "drill into activity →" link is decoupled from the disclosure toggle so a click navigates without also toggling the recent-iterations summary. |
| T3.1 — override tooltip dropped `override_reason` | landed (R1b) | `overrideTooltip` gains `reason: <override_reason>` as a third part under the same `badgeText` guard — the *why* of a verdict demotion now travels with the badge. |
| T3.2 — transfer/replication label | landed (R1b) | Quiet `transfer` text label (testid `novelty-transfer-label`) beside the axes chip on the rubric bucket `phenomenon=known` + `direction ∈ {matches, silent}` — substrate-independent per `docs/novelty_two_axis_rubric.md`; the cyan known+unstudied_llm chip emphasis is unchanged. |
| T3.3 — active_run staleness/robustness | landed (R1b) | `ActiveRunCard` hardened: every producer-owned field coerced independently (`asText` idiom), null/non-object bodies render nothing, and `coordinator`-kind or partial/malformed rows render what exists instead of crashing the hero. |

Hygiene note (same closure): the planned `.gitignore` additions
(`run_state/*.log`, `run_state/*.out`) were already landed by commit
`3609da3` (D-047/D-048, alongside `active_run.json`, `active_runs/`,
`*.pre_purge_*`); zero untracked `run_state` noise files at closure time, so
no edit was needed.

The live reactive session that follows this build runs from
[`docs/live_session_runbook.md`](docs/live_session_runbook.md).

---

## §2026-06-14 — topicality advisory + dashboard reframe + /todo cockpit (active)

Work order: `human/sessions/2026-06-14.md` "## UI session work order" (the dated
session note is now the canonical UI handoff home, per the amended CLAUDE.md
operating model). Built by the UI session via three Dynamic Workflows (leaf
build → contract+shell assemble → max-fan-out harden/validate), with the session
serially integrating the shared spine (route/router registration, dashboard
reframe, badge wiring) and verifying. Scope held: `ui/` + `ui_plan.md` only.

### Topicality advisory badge (D-052)

`relevance.topicality_advisory` (DATA_SHAPES §1 / Changelog 2026-06-14) surfaced
as a **non-gating** hint. New `TopicalityAdvisoryBadge.tsx`: a quiet **zinc**
"topicality dissent" chip that fires ONLY for an explicit `"off"` (the retired-
as-gate adversarial judge's dissent), renders nothing for absent/`on`/`unsure`/
null/garbled values, and must NOT reuse the amber low-evidence styling (it is
neither a gate nor a low-evidence flag). Wired into `ResolvedIterationsList` (a
quiet row chip beside — never inside — the alarm slot), and `IterationDetailModal`
(header chip + a `topicality_advisory` Evidence `DetailRow`). `topicality_advisory`
added to the `relevance` type in `types/schemas.ts`.

### PART 1 — dashboard reframe (center = system-overview snapshot)

Center order: HealthVerdict → SystemActivityHero → HealthStrip **+ a new
`HostMemoryTile`** (6th strip tile, host RAM-used GiB, honest "—" when host
telemetry lacks `mem_used_mb`) → Vllm + Qwen (both kept). **`HumanTodoPanel`
REMOVED from the dashboard** — it moved entirely to `/todo`. The removal is safe
ONLY because of the **coupling**: `SystemActivityHero` gained a router-free
`needsYou` slot, and the Dashboard feeds it `<Link to="/todo">{N} need you →</Link>`,
visible in **every** state. **N = taxonomy A+B ONLY** = `counts.gate_verdict +
counts.state_gate` from `/api/human_todo` (C — `bubble_ack`/`stale_active_run` —
and `finding_review` are excluded; they are not blocking decisions). No
slide-out drawer (rejected; over-build).

### PART 2 — `/todo` uncertainty-resolution cockpit (STUBBED)

New `routes/Todo.tsx` assembles the cockpit: `ConcurrencyWarning` (self-fetches
`/api/todo/concurrency`; warns when an iteration is mid-flight) → the
`HumanTodoPanel` inbox (its new home) → the resolution area enforcing the
**pre-verdict ordering** (ARCH §6.5.4: `CalibrationCapture` FIRST; the six
resolution forms unlock only after `onCaptured`) → the six outcomes (sign-off /
reject / refine-defer reuse the blessed `GateVerdictForm`/`FindingReviewForm`/
`DeferForm`; **NEW stub forms** `DirectiveSignOffField`, `AuthorizeFixForm`
(outcome 4, "you approve the WORK, not a merge"), `SpawnTopicForm`, `AbstainForm`)
→ `TwoVoiceChatPane` (Gemma defends / Qwen attacks, gated, stub) + `TutorPanel`
(**fenced from the verdict** — handed no verdict props). New backend
`ui/backend/todo_cockpit.py` (`register` wired in `app.py`) serves the NEW seams
as **honest stubs**: each POST validates, then returns `{status:"stub", seam,
would_run:[argv…]}` — the seam-faithful argv the future blessed CLI will run —
and **writes nothing** (D-046 / rule 4). The lone real read is
`GET /api/todo/concurrency` (read-only `run_state/active_run.json`).
`/api/todo/available` reports the NEW seams as `false` until
`docs/todo_cockpit_seam_plan.md`'s writers (primary-session) land; the cockpit
snaps onto them with zero argv churn. The `/todo` route now renders `<Todo/>`
(was the bare `HumanTodoPage`).

### Verification

Settled baseline before the harden sweep: frontend 903 vitest pass (75 files),
backend 358 pytest pass, `tsc --noEmit` clean. Two existing tests were updated
to the new contract (not coerced): the dashboard no longer mounts the inbox
(asserts absence + the coupling link), and `/todo` renders the cockpit.

**Harden/validate sweep closure.** A max-fan-out Dynamic Workflow (16 surfaces
pipelined harden→adversarial-verify + a deepen phase) then took the new/changed
surfaces to **frontend 1255 pass (91 files), backend 517 pass, `tsc` clean**
(+352 fe / +159 be tests, all green). Adversarial verification **found and fixed
6 real robustness bugs** a happy-path pass would miss — the most serious:
`SystemActivityHero`'s `needsYou` slot would **blank the whole dashboard** if
handed a React element wrapping a producer-derived bad-object child (fixed with a
scoped `SlotBoundary` error boundary); plus `/api/todo/concurrency` on a
deeply-malformed `active_run.json`, `api/todo.ts` body coercion, and
edge-input handling in `AbstainForm` / `DirectiveSignOffField` / `CalibrationCapture`.
Live-data validation (in-process `TestClient` over the real `_PRIMARY_REPO`)
confirmed end-to-end: every `/api/todo` POST stub writes NOTHING (before/after
`memory/`+`run_state/` snapshot = zero delta — D-046 / rule 4 verified), and the
dashboard coupling reads real `counts.{gate_verdict,state_gate}` (16 live
`gate_verdict` pending). An a11y pass labelled the read-only would-run blocks.
The completeness critic verdicts **every** PART-1/PART-2/badge work-order item
**BUILT**; its punch list resolved with no code change: the "exclude taxonomy C
from N" invariant is already pinned in `test_dashboard.tsx`; the `IDLE · N need
you →` literal is rendered as a separate always-visible slot (a deliberate
improvement — the count shows in every hero state, not only idle); and the
calibration-ordering / two-voice-chat / outcome-4-enqueue stubs are the expected
primary-seam boundary below.

### Boundary handed to the primary session

The cockpit's NEW resolution outcomes are inert stubs until the four
`docs/todo_cockpit_seam_plan.md` seams ship (two-voice `finding_session.py`, the
generalized escalation schema + coordinator emit, the resolution-outcome CLIs,
the outcome-4 spawn-contract enqueue). When they land, flip the per-action flags
in `todo_cockpit.py`'s `/available` and swap each stub body for an
`attest._exec_blessed` call — the argv shapes already match the seam plan.

---

## §2026-06-17 — full UI hygiene pass (Dynamic Workflow, behavior-preserving)

Worktree first fast-forwarded to `main` (`5668387`) — clean FF, `ui/` byte-identical
(the 5 intervening commits are the primary-side cockpit seams + D-053 advisories,
none under `ui/`).

A behavior-preserving hygiene sweep over `ui/`, run as one Dynamic Workflow fanning
out to **7 disjoint path-slices** in parallel (components / routes / api+types /
fixtures+utils / fe-tests / be-write / be-read). Every agent was bound to: edit only
its slice, no public-API or behavior change, never touch spine files (flag them
instead), never weaken a test, no new dependency. This session (serial integrator)
applied the one spine-flagged fix and ran the authoritative gate.

**Changed (8 files, all comment/docstring/dead-code tidy):**
- `components/HealthStrip.tsx` — header comment "5 GPU/host tiles" → "6" (renders 6).
- `format.ts` — `fmtRatioPct` docstring corrected: returns the scaled VALUE (n*100),
  not a "%" string; callers append "%".
- `types/todo.ts` — removed the provably-unused `HumanTodoResponse` re-export.
- `backend/activity.py` · `coordinator.py` · `loop_v0.py` — corrected wrong endpoint
  counts in module docstrings ("Two"/"Four" → actual); added the missing `/processes`
  bullet to `loop_v0`.
- `backend/human_todo.py` + `backend/app.py` (spine, integrator) — removed the dead
  `repo_root` param from `human_todo.register` and its sole call site. An unused
  copy-paste vestige from `attest.register`; removal aligns the signature with its
  documented sibling `coordinator.register` (which takes no `repo_root`).

**Gate:** `tsc --noEmit` clean · `vitest` 1255 pass (91 files) · `pytest` 517 pass.
Scope: only `ui/` + this file.

**Deliberately NOT done — recorded so a future session doesn't re-litigate:**
- **eslint/prettier/ruff adoption — deferred, not declined.** None are installed (no
  devDeps, no `pyproject`); adopting them needs an `npm install` + a real warning
  burndown that does not fit a safe time-boxed pass. Own it as a dedicated follow-up.
- **`api/attest.ts` ↔ `api/todo.ts` "dedup" — DECLINED as unsafe (not skipped for
  time).** Their look-alike POST idiom diverges in load-bearing ways: `postAttest`
  treats an empty-string error `detail` as PRESENT and does a throwing `resp.json()`;
  `postTodo` treats "" as ABSENT (matching `http.ts`'s truthiness contract) and
  degrades a non-object 200 via `parseJsonSafe`. `AttestError`/`TodoError` are distinct
  public exports. A shared helper would change one file's documented behavior or add
  the exact indirection the bounded-codegen rule forbids. They are intentional twins —
  leave them.
- A few unused **contract/schema-doc fixtures** (`EXPERIMENTS_LIST_FIXTURE`,
  `ITERATIONS_FIXTURE_V1`, …) and unreferenced `fixtures/loop_v0/*` sample-data files
  were left in place — they document record shapes for future tests; flag for producer
  confirmation before any removal.

---

## §2026-06-17 (round 2) — tutor finding-overview (U1) + kind-gated cockpit forms (U5)

Work order: `human/sessions/2026-06-17.md` "## UI session work order" (U1–U5), the
tutor build round (D-054: verdict-fence KEPT; tutor = static overview + a live Qwen
probing chat; **no recommendation**). Built by this UI session via **two Dynamic
Workflows** (a 3-agent parallel BUILD on disjoint files, then a 3-agent INDEPENDENT
ADVERSARIAL HARDEN) + serial integration. Scope: `ui/` + this file only.

**Dependency honored:** the primary's **P2 per-turn chat CLI has NOT landed** (main
HEAD is the plan commit). The work order gates **U2 / U3 / U4 on P2**, so this round
shipped only the **P2-independent** items. U2 (tutor chat pane), U3 (light up the
two-voice pane), U4 (`todo_cockpit.py` tutor + two-voice seam endpoints) **remain
deferred until P2 lands on `main`** (the primary will note it in the session file).

### What shipped (U1, U5, + the carried nit)

- **U1 — read-only finding-detail GET** (`ui/backend/finding_detail.py`, NEW;
  registered in `app.py`). `GET /api/finding/{finding_id}` JOINS one
  `memory/surfaced_findings.jsonl` row (claim, evidence-DICT, `what_would_change_it`,
  effective status via the `surfaced_findings.status.jsonl` last-row-wins overlay)
  with its source iteration projected from `memory/loop_memory.jsonl`
  (topic←`seed.topic`, `nara_summary`, `gate_status`, `journal_entry_path`,
  started/ended). Unknown id → `{found:false}` at **HTTP 200** (the tutor degrades in
  place, never 404-blanks). **Writes NOTHING** (the tutor fence at the data layer).
  Contract is `FindingDetail` in `types/schemas.ts`; client `getFindingDetail` in
  `http.ts`.
- **U1 — `TutorPanel` rewrite** (`components/todo/TutorPanel.tsx`): replaced the
  verbatim title-echo + stub banner with a real finding **OVERVIEW** — claim, source
  iteration, `what_would_change_it` / why-it-matters, read-only evidence refs, quiet
  novelty/critic/status badges, a **neutral MECHANICAL outcome-effects** line ("accept
  → writes a valid `loop_feedback` row vs iteration X + clears the queue · deny →
  invalid · in_review → stays queued"), and a **neutral UNWEIGHTED** for/against
  enumeration that ends "not a recommendation". Self-fetches `getFindingDetail`
  (the `detail` prop is the test-injection override); degrades to "unavailable" on
  any failure; **idle** when nothing is selected.
  - **THE FENCE (D-054), by construction:** the component accepts NO
    verdict/confidence/onResolved/calibration prop — it is structurally unable to
    influence or auto-fill the verdict; it renders **no recommendation/steer**.
  - **Fixed the D-044 mis-citation:** the fence note now cites the REAL source —
    *2026-06-14 note PART 2 · inviolate rule 4 · D-053* — and no longer cites D-044
    (D-044 is the vllm-qwen novelty-skeptic independence decision, a different fence).
- **U5 — kind-gated resolution forms** (`routes/Todo.tsx`): a `classifyKind` total
  function gates the cockpit so **no `iteration_id` ever reaches a finding-keyed form
  and no `finding_id` ever reaches an iteration-keyed form**.
  `gate_verdict` → iteration forms (`GateVerdictForm`, `DirectiveSignOffField`);
  `finding_review` → finding forms (`FindingReviewForm`, `AuthorizeFixForm`,
  `SpawnTopicForm`, `AbstainForm`) + the aux `TwoVoiceChatPane` + `TutorPanel`;
  any other kind → only `DeferForm` + `CalibrationCapture`. The aux now mounts only
  for a real finding and receives the item's real non-empty `finding_id` (the old
  `selected?.id ?? ""` empty-string fallback is gone). Calibration-first ordering +
  all `safeActions`/`safeItems` guards preserved.
- **Carried hygiene nit:** `attest.py:168` stale `repo_root` cross-reference fixed
  (now cites `todo_cockpit.register`, the true `repo_root: Path | None`-defaulting
  sibling — `human_todo.register` lost its `repo_root` last round).

### Adversarial harden — 3 real backend bugs caught + fixed

The independent-skeptic harden workflow broke the new GET three ways (each reproduced
as a live 500 before the fix, each regression-pinned and reversion-verified):

1. **Response-encoder overflow** — a surfaced value that is deeply nested (1000s of
   levels), a non-finite float (NaN/Inf), or a 600–4300-digit bigint is valid JSON but
   500s FastAPI's recursive `JSONResponse` encoder *after* the read try/except. Fixed
   with an iterative `_encoder_safe` (depth ≤ 32, int < 10**600, finite floats) applied
   as each value ENTERS the response — a pathological field degrades to null, the rest
   is intact, safe values pass through byte-for-byte. (Same class `todo_cockpit._within_depth` guards.)
2. **Read-layer `ValueError` escape** — a >4300-digit int makes `json.loads` itself
   raise a bare `ValueError` (not a `JSONDecodeError`), which escaped the per-line
   catch → 500. Widened the catch to `except ValueError`.
3. **Delete-race 500** — a file unlinked between `exists()` and `open()` raised
   `FileNotFoundError`→500; the sibling `coordinator.active` degrades the same race.
   Added `except FileNotFoundError: return []` *before* the genuine-fault `except OSError`
   → a vanished file reads as absent; a real unreadable file still 500s (pinned).

`TutorPanel` and the `Todo.tsx` kind-gate were found **robust as-built** (no code fix);
the harden added +24 fence/write-safety pins and +24 hostile-kind pins respectively.

**Gate (authoritative):** `tsc --noEmit` clean · **vitest 1306 pass** (92 files; 1255 →
1306) · **pytest 556 pass** (517 → 556) · real `env -u MOCK_LLM` smoke green (route
serves real findings; unknown id → `found:false`; writes nothing). No test was
weakened, skipped, or coerced; the one stale sibling assertion
(`test_cockpit_interrogation.tsx` expected the retired `tutor-stub-banner`) was updated
to the new overview behavior (not faked back into existence — inviolate rule 4).

### Component docs backfill (cockpit current state)

- **`TutorPanel` (`components/todo/TutorPanel.tsx`) — LIVE overview, fenced.** As
  above: a read-only finding overview backed by `GET /api/finding/{id}`; no verdict
  path exists on it; the visible fence note cites 2026-06-14 PART 2 / rule 4 / D-053.
  Renders idle / unavailable / loaded states; every producer field is `typeof`-coerced
  so a hostile value drops rather than blanks the cockpit. The future **live Qwen
  probing chat** (U2) is a *separate* pane that waits on the P2 CLI.
- **`TwoVoiceChatPane` (`components/todo/TwoVoiceChatPane.tsx`) — STILL A STUB.**
  Renders the two-stance layout (defender **Gemma** / attacker **Qwen**, D-044
  interrogator-independence), the turn/token cap intent, fixture turns, and a stub
  banner; `actions.two_voice_chat` is `false`. It lights up at **U3** once the P2
  per-turn CLI lands and `todo_cockpit.py` exposes the exec seam (U4). It is the
  home for accept/deny **adversarial** support — distinct from the (fenced) tutor.
- **`CalibrationCapture` (`components/todo/CalibrationCapture.tsx`) — STUBBED writer.**
  The pre-verdict prediction + confidence slider (`[0,1]`, step 0.05) per ARCH §6.5.4.
  It is the cockpit **ordering gate**: the verdict/resolution forms stay locked until
  `onCaptured` fires. The POST (`/api/todo/calibration`) is an honest `would_run` stub
  — the `calibration_entry` run-log writer is a primary seam (P4), so confidence is
  captured in component state but **not yet durably written** (server still 422s
  out-of-`[0,1]`, never coerced).

### Flagged for a primary/human ruling (NOT changed this round)

- **Aux panes render before pre-verdict calibration.** The harden pass surfaced that
  the aux section (`TwoVoiceChatPane` + `TutorPanel`) renders for a finding item
  *before* `CalibrationCapture` fires — the verdict FORMS are correctly locked behind
  calibration, the aux is not. This **does not break U5** (the aux gets the real
  `finding_id`, never an `iteration_id` or the empty-string fallback) and is
  **pre-existing** (2026-06-14, not introduced here). It was deliberately NOT
  "fixed": the written contract scopes the lock to *"the verdict form opens"* (ARCH
  §6.5.4; 2026-06-14 PART 2), D-054's chosen calibration-bias mitigation is
  *"no recommendation"* (now implemented), and seeing a finding's neutral overview is
  arguably the legitimate **basis** for an informed calibration prediction — so
  gating it would invent a contract the spec does not state (inviolate rule 8). **Open
  research-design question for the human/primary:** should the calibration prediction
  be made on minimal info (item title only, aux hidden until captured) to measure an
  *uncontaminated* prior, or with the tutor overview available? If the former, the
  one-line fix is `&& calibrated` on the Todo.tsx block-4 aux condition.
- **`todo_cockpit.py` `_SEAM_MODULES` reconciliation** (the `authorize_fix` →
  `orchestrator.authorize_fix` retarget + the spawn_topic/abstain session-vs-one-shot
  question) stays **carried-forward** per the work order — separate from the tutor
  round, lands when the primary ships the corrected seam wiring (P5).
- **eslint/prettier/ruff adoption** still deferred (from §2026-06-17 hygiene) — needs
  an install + warning burndown, out of a focused feature round.

---

## §2026-06-18 — cockpit LIVE seams: tutor chat (U2) + two-voice (U3) + cockpit exec corrections (U4)

Work order: `human/sessions/2026-06-18.md` "## UI session work order" (U2/U3/U4), the
round that lights up the cockpit's live interrogation seams now that the primary
landed **P2** (the `finding_session chat` per-turn CLI), **P4** (the
`calibration_entry` writer, D-055) and **P5** (the authoritative
**`docs/cockpit_seam_wiring.md`**). Worktree fast-forwarded to `04bd27c` (U1/U5 merged
at `b8ca85f`). Built by this UI session via **two Dynamic Workflows** (a 3-agent
parallel BUILD + a 4-agent INDEPENDENT ADVERSARIAL HARDEN) + serial integration.
Scope: `ui/` + this file only. Wired to the wiring doc, NOT the old stub guesses.

### What shipped

- **U2 — live tutor chat.** New `components/todo/TutorChatPane.tsx` (single-voice
  probing chat) + the shared `components/todo/useChatSession.ts` hook, over a new
  read-through-the-CLI backend seam `ui/backend/chat_seam.py` (`POST
  /api/todo/chat/start` + `/turn`, execing `finding_session chat start|turn --mode
  tutor` via the blessed `attest._exec_blessed` runner — argv-array, no shell). The
  tutor chat is **verdict-fenced by construction** (no verdict/confidence/onResolved
  prop; only start/turn verbs reachable; cites 2026-06-14 PART 2 / rule 4 / D-053-D-054,
  NOT D-044).
- **U3 — live two-voice interrogation.** `TwoVoiceChatPane.tsx` made LIVE (mode
  `two_voice`, defender = Gemma / attacker = Qwen, D-044 interrogator independence)
  via the SAME chat seam + hook; the `available=false` stub path is preserved
  byte-for-byte. `actions.two_voice_chat` flips True when the seam exists.
- **U4 — cockpit exec corrections** (`ui/backend/todo_cockpit.py`, per the wiring doc):
  `_SEAM_MODULES` retargeted (`authorize_fix → orchestrator.authorize_fix`;
  `calibration → orchestrator.calibration_cli`; `directive_signoff →
  orchestrator.finding_session`); the three one-shot stubs swapped for **real blessed
  execs** via `_exec_blessed` (injectable runner; tests stub it); **`directive_signoff`
  re-keyed on `finding_id`** (it signs off a FINDING — the U5 mis-gating is corrected:
  the form moves from the iteration branch to the **finding** branch, and the client
  sends `finding_id`); `spawn_topic`/`abstain` reshaped to honest **session-exits**
  (no fictional one-shot argv, `available` stays false, write + exec nothing); the
  `allowed_action_endpoints` map (escalation `allowed_actions` → cockpit endpoints)
  added to `/available`.
- **Aux ordering (D-054 resolution — the delegated 2026-06-17 flag).** In `Todo.tsx`
  the static tutor **OVERVIEW** (`TutorPanel`) is the BASIS for the calibration
  prediction, so it renders **pre-calibration**; the **INTERACTIVE** panes (live tutor
  chat + two-voice) are decision-support that could bias the pre-verdict calibration
  signal §6.5.4 measures, so they gate behind `calibrated` (**post-calibration**).
  Coherent flow: read overview → predict (calibration) → interrogate → verdict. Both
  interactive panes gate on `actions.two_voice_chat` (the single "chat seam is live"
  signal — it serves both tutor + two_voice modes).
- **Nits folded in:** the residual D-044 mis-citation in the `Todo.tsx` CODE comment →
  D-053/D-054/rule 4; `CalibrationCapture` prop `findingId → refId` (it is the generic
  item id — a finding_id, or an iteration_id for a gate_verdict item) + stale stub
  banner refreshed (the writer landed in P4); the **`ui/.venv-ui` test-harness venv
  pinned** in `ui/README.md`; `finding_detail.py`'s `_safe`-wrap of `source_iteration_id`
  confirmed already in place (H1, §2026-06-17 round 2).

### Bugs caught — 1 by the smoke, 3 by the adversarial harden

1. **Production import bug** (caught by the real `env -u MOCK_LLM` smoke, NOT the
   suite): `todo_cockpit.py` imported `from backend.attest import _exec_blessed` —
   works under pytest (conftest puts `ui/` on `sys.path`) but **breaks uvicorn** (the
   package is `ui.backend`). Fixed to the package-relative `from .attest import`. The
   harden added a static-source pin so it can't regress.
2. **Chat-seam encoder overflow** (H1): a zero-exit CLI envelope that is deeply
   nested / carries a non-finite float / carries a >4300-digit bigint would 500 the
   `JSONResponse` encoder (the same class `finding_detail`/`todo_cockpit` guard).
   Fixed with a `_exec_chat` wrapper + iterative `_encode_safe` in `chat_seam.py`
   (degrade to a 502 contract break, never 500); 9 regression pins, each reverted-verified.
3. **`useChatSession` stale-session leak** (H2): an in-flight `send` for finding A
   resolving after switching to finding B wrote A's reply / session_id / error into B
   (a cross-finding session bleed — the exact thing the hook claimed to prevent).
   Fixed with a `genRef` generation guard that retires in-flight sends on a findingId
   change; new `test_useChatSession.tsx` pins all three leak vectors.
4. **`attest._exec_blessed` bigint `ValueError`** (root cause, flagged by H1, fixed by
   the integrator): the shared helper caught only `(json.JSONDecodeError, TypeError)`,
   so a >4300-digit-int envelope raised a bare `ValueError` that escaped → a 500 for
   **every** blessed-exec caller (attest's own endpoints + todo_cockpit). Broadened to
   `(ValueError, TypeError)` (a strict superset — `JSONDecodeError ⊂ ValueError`, so no
   existing behavior changes); regression-pinned in `test_attest.py`.

### Gate (authoritative)

`tsc --noEmit` clean · **vitest 1352 pass** (94 files; 1319 → 1352) · **pytest 630
pass** (603 → 630) · real `env -u MOCK_LLM` smoke green (app builds; chat + cockpit +
finding routes serve; `/available` reports the corrected flags + the
`allowed_action_endpoints` map; chat fence, directive `finding_id` validation, and the
session-exits all behave). Build agents: chat seam 41 → harden 57; chat panes 38 →
harden 62; cockpit 210 → harden 220; kind-gate 29 → harden 38. No test was weakened,
skipped, or coerced.

### Component docs backfill (cockpit current state)

- **`TutorPanel` (overview) — LIVE, fenced, pre-calibration.** Static read-only finding
  overview (claim / source iteration / evidence / mechanical outcome-effects /
  unweighted pros-cons), backed by `GET /api/finding/{id}`. No verdict path. (§2026-06-17
  round 2.)
- **`TutorChatPane` (U2) — LIVE, fenced, post-calibration.** Single-voice Qwen probing
  chat via `useChatSession("tutor", findingId)` → the chat seam. It probes/explains,
  never recommends; no verdict prop; session-local; `available=false` → disabled stub.
- **`TwoVoiceChatPane` (U3) — LIVE, post-calibration.** Human-directed Gemma-defends /
  Qwen-attacks interrogation via `useChatSession("two_voice", findingId)`; addressee
  selector (defender/attacker/both) threads into the turn; stance-tagged replies. The
  `available=false` stub path is intact for environments without the seam.
- **`CalibrationCapture` — LIVE writer (P4/D-055).** Pre-verdict prediction + confidence
  (`[0,1]` slider). The cockpit **ordering gate**: the resolution forms AND the
  interactive aux panes stay locked until `onCaptured`. POSTs `/api/todo/calibration` →
  the blessed `calibration_cli` (`--ref-id`). `available=false` → captured locally but
  not durably written.

### Flagged for a primary/human ruling (NOT silently changed)

- **spawn_topic / abstain FRONTEND reshape — DEFERRED (tied to wiring-doc open Q1).**
  The backend is correct (session-exits, `available=false`). The frontend
  `SpawnTopicForm`/`AbstainForm` + `postSpawnTopic`/`postAbstain` still reflect the OLD
  one-shot model (a fictional `finding_session spawn-topic` verb, a `kind` field,
  `ref_id` body) — but they are DISABLED (`available=false`), so **no production POST
  fires** and there is no live inconsistency. The proper reshape (retire the one-shot
  forms → session-exit affordances; align to `finding_id`) is **gated on the wiring
  doc's open question 1** (an in-UI chat-CLI `end` verb vs the terminal REPL) — a
  design decision for the human/primary; building it now would be speculative (rule 8).
- **Single-slot `calibratedId`** (H4): switching away from a calibrated finding and
  back RE-LOCKS it (calibration is tracked per the current selection, not remembered
  per-item). Internally consistent + pinned as deliberate; if the intent is "a finding
  stays calibrated once captured this session," that is a `Todo.tsx` change
  (`calibratedId` → `Set<string>`) for the human to decide.
- **Calibration for iteration items**: `calibration_cli` expects a surfaced-finding
  `ref_id`; whether it accepts an `iteration_id` (for a gate_verdict item's calibration)
  is a primary-side question. A reject surfaces as a legible error in
  `CalibrationCapture`, never a bad write.
- **`attest._exec_blessed` encoder-layer gap** (low likelihood): the read-layer bigint
  `ValueError` is now fixed for all callers; a deeply-nested / non-finite-float
  *returned* envelope would still 500 the encoder for attest's own endpoints +
  todo_cockpit (chat_seam self-guards this). attest's blessed CLIs emit bounded
  well-formed ledger rows, so the risk is ~nil — left unguarded rather than thread the
  `_encode_safe` walker through every blessed-exec response (rule 8).

---

## §2026-06-19 — the /todo cockpit S2 reframe + two page wins

Work order: `human/sessions/2026-06-19.md` "## UI session work order"; authoritative
per-page spec `docs/ui_reframe_plan.md` (§1 cockpit, §2 Dashboard, §4 Coordinator — the
S2 slice; §3 Activity + §5 Experiments are S3, deferred + gated on primary producers).
The human ruled **flag-2** (calibratedId → per-id `Set`), now in-scope. Built by this UI
session via **four Dynamic Workflows** (Understand 6 readers → Build 7 → Reconcile 4 →
Harden 3 = 20 agents) + heavy serial integration. Scope: `ui/` + this file only.

**North star:** the cockpit is the owner's **sign-off to applied-tier experiments** —
literature-stage iterations auto-advance (observable, not gated); the owner is reserved
for the substantive end-of-pipeline decisions. The flow: *pick → read the journey →
optional blind calibration → interrogate → decide.*

### What shipped — the cockpit (§1)

- **Literature auto-advance** (`human_todo.py` `_gate_verdict_items`): only pending
  iterations carrying a usable `experiment_outcome` dict surface as blocking
  `gate_verdict` inbox items; literature-stage pending rows are dropped (observable via
  `/api/loop_v0/iterations`). On live data this took `gate_verdict` from ~18 to ~7–9
  experiment-bearing items; `finding_review` (5) is untouched, so the inbox is reserved
  for substantive escalations, not emptied.
- **Select-only inbox** (`HumanTodoPanel` `selectMode`) — **this closes the §6.5.4
  calibration-bypass AT THE SOURCE**: in select mode the inline verdict writers
  (`GateVerdictForm`/`FindingReviewForm`) are suppressed (gated by family via
  `deferKindOf`, both producer spellings), so a verdict can no longer be written from
  the inbox with no calibration; rows become selectors driving the workspace; `BubbleAck`
  + `Defer` + the CLI fallback stay inline. Default-off keeps legacy behavior.
- **PipelineJourney** (NEW `components/todo/PipelineJourney.tsx`) — the read-only
  context view: a pipeline ribbon (8 steps; experiments greyed = Phase 2) + the journey
  (hypothesis → retrieval + relevance → novelty + rationale → critic verdict + the
  contradicting paper / "uncontradicted" → experiment-outcome slot) + an honest
  "literature-stage — not experimentally tested" label. Backed by a NEW read-only GET
  **`/api/iteration/{id}/journey`** (`iteration_journey.py`) returning the full
  `IterationRecord`; handles both families (a gate_verdict iteration directly; a finding
  via `getFindingDetail` → `source_iteration_id`). Reuses the `IterationDetailModal`
  rendering idioms.
- **Calibration is OPTIONAL + per-id** (flag-2): the forced "locked until calibration"
  gate is **REMOVED** — the resolution forms render unconditionally. `CalibrationCapture`
  is opt-in/blind, recorded ONCE per id (`calibratedIds: Set`, a `captured` prop) so a
  switch-away-and-back never re-prompts (no double `calibration_entry`).
- **Reveal-gated interrogation** (the D-054 forced-gate rework for an opt-in flow): the
  interactive panes (tutor chat + two-voice + the tutor overview) are hidden behind a
  default-collapsed "reveal decision support" toggle (per-id `revealedIds: Set`), so a
  blind calibration is not contaminated by them — **without forcing calibration**
  (revealing requires no capture). The static journey is the pre-calibration basis.
- **Honest banner + explainer** (`Todo.tsx`): the false "STUBS … write nothing" banner is
  rewritten to the sign-off-to-applied-tier framing; a collapsible "what am I being
  asked?" explainer names the two research validations (gate-verdict = whole iteration;
  finding-review = one claim) + three ops/info (bubble-ack, stale-active-run, state-gate).
- **Stale stub-comment sweep**: the "seam lands / would-run / writes nothing" copy across
  `api/todo.ts` + the 6 leaf components (authorize_fix/directive_signoff are live execs;
  spawn_topic/abstain are honest session-exits; tutor/two-voice chat are live) — corrected
  to honest capability-off / session-exit framing. (The D-044 Todo.tsx code-comment was
  already fixed in the U2/U3/U4 round; the work-order line refs were stale.)

### Page wins (§2 + §4)

- **Dashboard in-flight rollup** (NEW `InFlightRollup.tsx`): a compact "what's running"
  list (active iteration / coordinator run / running processes) + "N findings awaiting
  your applied sign-off" (`counts.finding_review`); reads `/api/loop_v0/active`,
  `/api/coordinator/active`, the new `getProcesses` (`/api/loop_v0/processes`). The
  health strip + **both LLM panels (Gemma + Qwen)** are untouched.
- **Coordinator time-range filter**: today / this-week / all + a newest/oldest direction
  toggle, defaulting to all + newest-first (the existing history is unchanged by default).

### Adversarial harden — 3 real bugs caught + fixed

1. **PipelineJourney cross-family stale-state** (H1): a finding's failed `getFindingDetail`
   left `detailFailed` set, falsely sticking a subsequently-selected healthy *iteration* on
   "journey unavailable". Fixed by family-gating the flag; +7 pins.
2. **Empty-string-id selector guard** (H2): a row with `id:""` became a clickable selector
   firing `onSelect("")`. The **security invariant held** (verdict writers stayed suppressed
   for every kind — proven by static trace), but the guard was tightened to a non-empty
   string; +6 pins.
3. **Surrogate-string encoder-500** (H3): a lone/unpaired surrogate (`"\ud800"`) parses but
   is not UTF-8-encodable → `JSONResponse` 500s after the read (the same valid-to-parse /
   fatal-to-encode class as NaN/Infinity, on a string + dict keys). Fixed in
   `iteration_journey._encoder_safe`; the integrator then **closed the same gap in the
   sibling `finding_detail._encoder_safe` + `chat_seam._encode_safe`** (chat is model
   output — highest risk) and pinned all three.

### Gate (authoritative)

`tsc --noEmit` clean · **vitest 1412 pass** (96 files) · **pytest 663 pass** · real
`env -u MOCK_LLM` smoke (journey GET, the reclassify, processes, coordinator, cockpit all
serve live data). No test was weakened, skipped, or coerced; the heavy Todo-shell test
reconciliation (≈70 tests across 6 files) preserved every kind-gate / robustness / fence
invariant verbatim (reworked the forced-gate flow to the opt-in + reveal-gate + per-id Set
model).

### Flagged for a primary/human ruling (NOT silently decided)

- **`test_validate_iterations` (2 cases) FAIL — pre-existing, NOT the reframe.** The live
  `loop_memory.jsonl` has a **duplicate `iter-2026-06-19-006`** (2 rows); the test asserts a
  unique "load journal `<id>`" label and trips `getMultipleElementsFound`. The UI renders
  both rows fine; I touched neither `ResolvedIterationsList` nor that test. This is a
  primary-side data-integrity issue — **dedupe the data, or define the duplicate-id UI
  behavior** (and/or make the test robust). Left for the primary; the reframe suite is
  otherwise fully green.
- **The literature signal = `experiment_outcome` presence** — the only clean in-data
  discriminator + it matches the north star, but the spec named the behavior not the field.
  Confirm; if a different signal (an explicit tier/stage marker) is intended, the
  `_gate_verdict_items` predicate is the single swap point.
- **The calibration-flow decision** (opt-in + reveal-gated interrogation; the D-054 forced
  gate removed) is my resolution of the work order's "re-thought for an opt-in flow" — a
  one-line change either direction if the human prefers a harder gate.
- **spawn_topic / abstain frontend reshape** still deferred (gated on
  `docs/cockpit_seam_wiring.md` open Q1 — in-UI exit verb vs terminal). The forms are
  disabled (no live POST), so the `ref_id`/`kind` client-signature drift is latent.
- **§3 Activity** (real per-worker decode/ETA) + **§5 Experiments** (card wall + applied-paper
  refinement) are S3 — gated on the primary's `logs/worker_activity.jsonl` + the applied-paper
  CLI seam respectively.

---

## §2026-06-30 — cockpit sign-off UX polish (S2 polish, `ui/` only)

Work order: `human/sessions/2026-06-28.md` "## UI session work order — cockpit sign-off UX".
**Polish/clarity/trust, NOT a rebuild** — the S2 reframe already landed (`782fc87`). The
primary adversarially verified **no backend/spine dependency** (the `calibration_cli` "needs an
iteration_id?" candidate was a false alarm — `ref_id` is opaque), so this round is `ui/`-only.
Worktree fast-forwarded clean to `main` (`d57dc08`; the 3 intervening commits are 06-25/06-28
ops + session notes, **zero `ui/` touch**). Built by the session directly (light, bounded edits;
no workflow warranted).

### Priority 1 — clarity & messaging

- **`Todo.tsx` D-044 citation corrected** — the interrogation comment now reads "D-044 governs
  the two-voice interrogator's independence (Qwen attacker independent from Gemma defender)",
  so the fence a future reader sees is the *right* one (D-053/D-054 = verdict-fence; D-044 =
  interrogator-independence — distinct).
- **Calibration-optional surfaced** — the `/todo` header explainer gains a line: "Optional blind
  calibration — record a prediction before interrogation if you want to, but you can decide
  without it." (The forced unlock gate was already removed in the S2 reframe; this makes the
  opt-in legible.)
- **Capability-off messaging unified** — `CalibrationCapture` and `TwoVoiceChatPane`
  `available=false` banners rewritten to the same "… is not available in this environment …
  Your input below is a preview only and will not be {recorded,sent}." wording (was
  "not durably written" / "held locally" — inconsistent, jargon-y).
- **`PipelineJourney` stage banner** — a new `journey-stage-banner` ABOVE the ribbon names the
  tier this iteration reached: **applied-tier** (quiet cyan) when `experiment_outcome` is present,
  **literature-stage** (quiet zinc, never amber) when absent. Frontend inference, no backend
  stage field (primary confirmed). Mirrors the existing bottom `stageLabel` predicate so the two
  never disagree.
- **Verdict/status outcome guidance** — `GateVerdictForm` gains `gate-verdict-guidance`
  (valid = approved, loop advances · needs_revision = paused for refinement · invalid = rejected);
  `FindingReviewForm` gains `finding-review-guidance` (validated = sign off · in_review = keep
  interrogating, stays in queue · rejected = dismiss). Text verified against the real enums
  (`VERDICT_ORDER` / `STATUS_ORDER`).

### Priority 2 — comment hygiene

Stale "stub / would_run envelope" framing simplified to "preview-only" in `AuthorizeFixForm`,
`DirectiveSignOffField`, `AbstainForm`, `api/todo.ts` leading comments (authorize_fix /
directive_signoff are LIVE execs now; abstain is a session-exit — the old all-stub framing was
stale). **No rendered text, testid, or field-handling logic touched** — the deferred
spawn_topic/abstain frontend reshape (gated on wiring-doc Q1) stays deferred; the `.would_run` /
`.stub` key-probing detail callers rely on is kept.

### Verification

- `tsc --noEmit` clean · `vite build` clean · **vitest 1414 pass** (96 files; baseline 1414 held —
  the 6 new assertions live inside existing `it()` blocks so the count is unchanged while the new
  banner/guidance/wording is now pinned).
- One test contract honestly updated (not coerced): `test_cockpit_forms_a11y.tsx` calibration-banner
  assertion re-pinned from `/not durably written|captured locally/` to the new
  `/not available|preview only|will not be recorded/` wording (inviolate rule 4).
- **Real `:8700` smoke (read-path):** the live backend (byte-identical `ui/backend` to HEAD —
  no `ui/` change `f16a967..d57dc08`) serves the cockpit's real data: capability flags correct
  (authorize_fix/directive_signoff/calibration/two_voice ON; spawn_topic/abstain session-exits),
  idle, backlog 4 gate_verdict + 21 finding_review. A real gate item (`iter-2026-06-05-004`,
  `experiment_outcome` present) renders the new banner as **applied-tier**; a real finding
  (`sf-iter-2026-05-26-008`) resolves claim + source iteration for the TutorPanel/journey path.
  The **write half** (submit verdict → item leaves the inbox) was NOT exercised live — those are
  the owner's decision-ledger writes (human go/no-go is the payload); it is covered by the green
  `test_attest_forms` re-poll tests (POST gate_verdict → re-poll empty queue → item leaves).

Scope held: `ui/` + this file only (14 files, all under `ui/frontend/`).

---

## §2026-06-30 (round 2) — chat-on-iterations + resolve rail (`ui/` only)

Work order: `human/sessions/2026-06-28.md` "## UI session work order — chat-on-iterations + resolve
rail (added 2026-06-30)" (A/B/C). The cockpit is widened so a gate-verdict ITERATION can be
interrogated like a finding, the chat-seam exec cap is decoupled from the attest write cap, and a
right-side resolve rail is added for the 25+-item backlog. Worktree FF'd clean to `main` (`d57dc08`
→ `c41570c` → integrated; the producer half `0a78298` already landed). Built via **two Dynamic
Workflows** (a 3-agent parallel BUILD on disjoint limbs, then a 4-dimension fence-focused
ADVERSARIAL REVIEW) + serial integration of the spine (`Todo.tsx` + the kind-gating test) by this
session. **The verdict fence is the load-bearing invariant and was the review's #1 target.**

### A — chat-seam timeout decoupled from the attest write cap (`ui/backend`, REQUIRED)
A real two-voice turn takes ~170–180s (Qwen reasoning > the old 120s cap), so the seam killed it.
`attest._exec_blessed` gains a keyword-only `timeout: int = _EXEC_TIMEOUT_S` (default 120 — the
attest WRITE endpoints stay tight); `chat_seam` adds `_CHAT_TIMEOUT_S=300` and threads it through
`_exec_chat`, with `chat_start`/`chat_turn` passing `timeout=300` explicitly. The other
`_exec_blessed` caller (`todo_cockpit.py`) is unbroken (keyword-only default). +6 timeout-pin tests.

### B — interrogation for gate-verdict (iteration) items
- `TutorPanel.tsx`: new optional `kind?: "finding"|"iteration"` (default "finding", fully
  back-compat) + a `journey?` injection. For an iteration it self-fetches `getIterationJourney(id)`
  (not `getFindingDetail`, which 404s for an `iter-*` id) and renders a NEUTRAL read-only iteration
  overview, **deliberately omitting the finding accept/deny mechanical-outcome line + considerations**
  (finding semantics, wrong for an iteration) — which makes the fence *more* explicit. Same testid /
  fence note (D-053, not D-044) / idle-unavailable-loaded degradation. +18 iteration tests.
- `Todo.tsx` (spine, integrator): the aux reveal guard widened `kindClass === "finding"` →
  `(… || "iteration")`; `kind={…}` passed to `TutorPanel`; a per-selection `key` added to
  `TutorPanel` (consistency with its already-keyed siblings — removes a one-frame cross-kind
  stale-overview flicker the review surfaced). **The resolution-FORMS block is UNCHANGED: an
  iteration still renders only `GateVerdictForm` (the sole disposition).**
- `test_todo_kind_gating.tsx` (spine, integrator): **10 iteration tests honestly reworked** from
  "iteration has NO aux" → "iteration IS interrogable (reveal-gated trio) but `GateVerdictForm` stays
  its ONLY disposition; finding-keyed forms absent; no disposition reachable from chat". A new helper
  `expectAuxRevealableTrioHidden()` pins the pre-reveal state. **Hostile/"other" kinds keep NO aux**
  (only gate-verdict iterations + findings gained it). Rule 4 honored — the fence is still pinned for
  iterations, not weakened.

### C — right-side RESOLVE RAIL (the nav fix for a 25+-item backlog)
New `ResolveRail.tsx` (+ `test_ResolveRail.tsx`, 12 tests): a persistent, **fetch-free** navigator
over the SAME lifted `todoItems` — grouped by kind (gate-verdicts / findings / other) with counts,
**near-dup clusters collapsed** via an in-file first-6-words title-stem heuristic (the cron promotes
near-dup findings every 12h), **kind filter + free-text search** (title OR id), and the SAME
`onSelect(id)` selection contract as the inbox (the two stay in lockstep). Verdict-fenced
(selection-only, no disposition path). Mounted in `Todo.tsx` as a right flex column. The robust
backend `cluster_id` (P4 BGE-M3 dedup) is the documented follow-on; v0 heuristic is the cure's stopgap.

### Verification (authoritative)
- `tsc --noEmit` clean · `vite build` clean · **frontend vitest 1438 pass** (97 files; 1414 → 1438)
  · **backend pytest 669 pass** (`ui/.venv-ui`, `MOCK_LLM=1`).
- **LIVE two-voice smoke (the headline — real models, my new backend in-process):** a real
  `two_voice` turn on a real iteration (`iter-2026-06-05-004`) → real gemma (defender, :8000) +
  qwen (attacker, :8001) → **both voices returned**, wall-clock **181.5s** — which **exceeds the old
  120s cap** (the old seam would have 502'd this exact turn) and completes under the new 300s cap.
  Proves Part A AND the iteration-interrogation premise end-to-end. The attacker returned a
  substantive "VERDICT: UNSOUND…" critique — decision support, with no disposition reachable (fence).
- **Adversarial review (fence-focused, 4 dimensions → adversarial verify):** **0 confirmed findings.**
  The one raised finding (the keyless-TutorPanel flicker) was refuted as non-blocking AND fixed anyway
  (the `key` above). The review independently confirmed: `GateVerdictForm` is the sole iteration
  disposition, the chat/tutor expose no verdict path, the kind-gating rework still pins the fence, the
  rail/clustering is robust on hostile input, and the backend timeout threading breaks no caller.
- The verdict-SUBMISSION half (submit → item leaves) was NOT exercised live — the owner's
  decision-ledger write; covered by the green `test_attest_forms` re-poll tests.

Scope held: `ui/` only (10 files: 4 `ui/backend`, 6 `ui/frontend` incl. 2 new) + this file.

---

## §2026-08-15 — evidence-ladder cockpit + alert surface (`ui/` only)

Work order: `human/sessions/2026-08-14.md` "## UI session work order — evidence-ladder
cockpit + alert surface" (A/B/C). Built by a worktree-isolated build agent
(spawn `loop1h-ui-workorder`); primary gates + merges.

### A — loop-alert banner (page-top)

- **NEW `ui/backend/loop_alert.py`** — read-only `GET /api/loop_alert` serving
  `run_state/loop_alert.json` verbatim (204 when absent; garbled = honest 500; the
  `coordinator.active` delete-race idiom). Wired in `app.py` on the coordinator
  run_state/memory paths. **NEW `GET /api/ideas`** in the same module (work order C).
- **NEW `LoopAlertBanner.tsx`**, mounted in `App.tsx` above `<Routes>` (every page).
  red = "LOOP STALLED" + reasons verbatim; amber = "loop degraded" + reasons;
  ok & fresh = INVISIBLE. **Staleness is the frontend's judgment**: `updated_at`
  older than ~26h renders the amber "no cycle telemetry since <ts>" note EVEN over
  "ok" (the silent-cron catch); a flag with no readable `updated_at` renders the
  honest "freshness unknown" amber. Absent flag / fetch failure / skew-404 /
  unknown level = nothing — the banner never alarms off a shape it can't read.
  Polls 60s; `initial` + `nowMs` fixture overrides (house idiom).

### B — ladder-first inbox

- **Backend (additive):** `human_todo.py` `finding_review` items now carry
  `evidence_level` verbatim when the surfaced row has one (string-only pass-through;
  legacy rows stay key-absent). No existing keys change.
- **`HumanTodoPanel.tsx`:** finding_review rows below the L4/L5 bar — including
  ALL legacy no-level rows — are **demoted**: off the default inbox, behind a
  "show demoted (N)" toggle (`ladder-toggle`, session-local, default off). The
  count badge counts what the inbox shows. **Operational kinds (gate_verdict /
  bubbles / stale run / state_gate) are never demoted** — they are not ladder
  claims, and hiding a blocking gate would fake an unblocked loop (interpretation
  recorded; the work order's "inbox shows ONLY findings at L4/L5" is read as the
  bar on findings). Zero-cleared weeks render the honest "Nothing cleared L4 this
  week" (`ladder-empty`) + a per-level histogram derived from the items themselves
  (`ladder-counts`, no extra fetch; absent/malformed level = the "no level" bucket).
  Malformed `evidence_level` (non-`L<digit>` string, number, object) reads as
  below-bar, never a crash or a fake pass.
- NOT touched: `ResolveRail` still navigates ALL items (it is a navigator, not
  the inbox); `Todo.tsx` selection still spans the full lifted list, so a demoted
  item stays workable once selected from the rail.

### C — ideas board (read-only v0)

- **NEW route `/ideas`** (`routes/Ideas.tsx`, nav tab added): renders
  `memory/ideas.md` via `GET /api/ideas` + the existing `MiniMarkdown` (the file is
  a deterministic projection — plain markdown render is correct). Absent file =
  honest "no ideas board yet"; no editing affordance (asserted read-only in tests).

### Verification

- `tsc --noEmit` clean · **vitest 1457 pass / 98 files** (baseline 1438/97; +19 new
  across `test_loop_alert_banner` / `test_ladder_inbox` / `test_ideas_board`) ·
  backend **pytest 675 pass** (+6 new in `test_loop_alert.py`, incl. the
  evidence_level pass-through).
- 9 existing tests updated honestly (not coerced): finding_review fixtures that the
  tests expect inbox-VISIBLE gained `evidence_level: "L4"` — the new contract is
  that only bar-clearing findings render by default (inviolate rule 4).
- The real `:8700` smoke is the PRIMARY's post-merge step (per the spawn contract);
  not run from this worktree.

Scope held: `ui/` + this file only (backend: 3 files incl. 1 new + 1 new test;
frontend: 7 src files incl. 2 new, 3 new + 4 touched test files).

---

## §2026-08-15 S1 — UI simplification slice 1: shell + Pulse + Ladder (`ui/` only)

Plan: `docs/ui_simplification_plan_2026-08-15.md` (3-surface rebuild, §Phasing S1).
Built by a worktree-isolated build agent (spawn `loop10h-ui-s1`); primary gates +
merges. Old surfaces stay reachable; the UI is shippable between slices.

### Backend — NEW `GET /api/ladder` (`ui/backend/ladder.py`)

- `loop_alert.py` register-fn idiom; `register(app, repo_root=loop_v0_repo,
  memory_dir=coordinator_memory)` in `app.py`. LAZY handler import of
  `workers.idea_ledger.load_state` + `workers.idea_projection` (sys.path gains
  the primary repo root — uvicorn's cwd is `ui/`); the REAL reducer runs, never a
  reimplementation. Absent `memory/idea_ledger.jsonl` → 204; unreadable/invalid
  ledger (malformed JSON, schema-invalid event, reducer violation) → honest 500
  with detail (rule 4). Returns `{clusters[cluster_id, stem, status,
  evidence_level, origin, member_count, last_event_ts, kill_reason,
  reopening_condition, open_agenda_count], histogram (non-killed per rung,
  L0..L5 zero-filled), counts{open,surfaced,killed}, agenda, next_owed}`.
- Tests: NEW `test_ladder.py` (absent→204; happy fixture ledger through the real
  reducer; malformed-line 500; schema-invalid-event 500) + a live `/api/ladder`
  probe in `test_live_8700.py` (≥70 clusters; 404 skips as version skew until the
  post-merge restart). In-process smoke over the primary ledger: 200, 70 clusters.

### Frontend — the S1 shell

- **`App.tsx`:** nav = `pulse · ladder · todo · engine ▾ (dashboard, activity,
  coordinator, experiments) · brain↗` (engine = a plain `<details>` dropdown, no
  new deps). Routes: `/` → NEW Pulse; `/ladder` → NEW Ladder; `/ideas` →
  `<Navigate to="/ladder" replace>`; old Dashboard moves to `/dashboard`
  (S3 removes it); everything else unchanged.
- **NEW `routes/Pulse.tsx`** — owns the WS telemetry stream; HealthVerdict inputs
  lifted VERBATIM from Dashboard (cleanSamples / ageMs-NaN guard /
  excludeQwenReadErrors / gemmaUp debounce); polls only `getHealth` +
  `getActivityMonitor(1)` — the retired `getActiveIteration`/
  `getCoordinatorActive` mirrors are NOT polled (pinned in test_pulse). Layout:
  HealthVerdict → NowBoard (the ONE now-card) → OweStrip → LastCycleLine →
  HealthStrip → ModelServerCard ×2 → NaraPromptForm behind a disclosure.
- **`NowBoard.tsx` extended in place** (poll/skew-note/stale-amber untouched):
  NEW optional `liveCalls`/`telemetry` props light a RUNNING/BUSY/IDLE headline
  strip (`now-verdict`); "registered" derives from the D-047 registry itself
  (`runs.length > 0`), busy/idle from the shared `computeActivity`. Old mounts
  (no feed props) render byte-identically.
- **NEW `components/nowVerdict.ts`** — SystemActivityHero's pure
  `computeActivity` + callsRecent/topGroupPhrases/buildEvidence ported VERBATIM
  (behavior pins ported to `test_now_verdict.tsx`; the hero's own suite kept —
  it dies in S3). `SystemActivityHero.tsx` is now a thin shell importing it;
  still mounts on `/dashboard`.
- **NEW `src/ladderBar.ts`** — BAR_LEVELS / evidenceLevelOf / clearsLadderBar /
  ageLabel extracted VERBATIM from `HumanTodoPanel.tsx` (which now imports them;
  zero behavior change, suites green) so the OweStrip shares the one bar.
- **NEW `components/OweStrip.tsx`** — one `/api/human_todo` poll; ONLY
  gate_verdict + state_gate families + L4/L5-bar findings; rows link
  `/dossier/:id` (S2 route — forward-404 expected until then); ladder histogram
  line over ALL finding rows; 404 → honest "queue UNKNOWN".
- **NEW `components/LastCycleLine.tsx`** — cycles[0] one-liner (topic · status ·
  errored red · +N findings emerald · age); `no_valid_plan` amber; links
  `/coordinator` for now (**deviation from the plan's `/cycles`**: that route
  lands at the S3 rename — a working link beats a dead one; S3 flips it).
- **NEW `components/ModelServerCard.tsx`** — parameterized VllmPanel+QwenPanel
  merge (props: title, servedModel, pick, samples, liveCalls, accent,
  workloadHint, transientDropBanner). DrivingLine + the two served-model
  constants moved in; testids are now `<servedModel>-status/-driving/-details`.
  Qwen keeps its tri-state body + deliberately-binary hard-red badge; Gemma
  keeps the workload pill. **DELETED:** `VllmPanel.tsx`, `QwenPanel.tsx`,
  `ActiveRunCard.tsx` (dead), `test_vllm_panel.tsx`, `test_qwen_panel.tsx`, and
  the ActiveRunCard describe-block in `test_activity_monitor.tsx`. Dashboard
  now mounts the card ×2.
- **NEW `routes/Ladder.tsx`** — counts header; pure-div rung histogram labeled
  with `next_owed`; status/rung filter chips (toggle = all); cluster table with
  expandable killed rows (kill code + evidence-keyed reopen condition); agenda
  section. 404 (version skew — `/api/ladder` added to the EndpointMissingNote
  known set) → quiet note + ideas.md fallback; 204 → honest "no idea ledger
  yet" + same fallback (the old Ideas.tsx body, folded in; `routes/Ideas.tsx`
  itself is unmounted and dies in S3). `getLadder()` + `LadderResponse` types
  added to `api/http.ts` / `types/schemas.ts`.

### Tests

NEW: `test_pulse.tsx`, `test_owe_strip.tsx`, `test_last_cycle_line.tsx`,
`test_ladder_page.tsx`, `test_now_verdict.tsx`, `test_model_server_card.tsx`
(50 tests). Updated: both route sweeps (`test_forwardcompat_routes` — Pulse +
Ladder renders incl. unknown-status/rung/kill-code degradation;
`test_validate_routes_console` — Pulse + Ladder console-clean), `test_dashboard`
(new status testid), `test_activity_monitor` (ActiveRunCard block removed).

### Verification (this worktree)

- frontend vitest **1490 pass** (104 files; 1457 → 1490) · `tsc --noEmit` clean
- ui-backend pytest **679 pass + 1 skip** (`.venv-chroma`, `MOCK_LLM=1`; the
  skip = the new live ladder probe against the pre-S1 running binary — honest
  version skew until the post-merge restart)
- The real `:8700` smoke (curl `/api/ladder` → 70 clusters; `/` + `/ladder`
  live; ensure-cron) is the PRIMARY's post-merge step per the plan's S1 gate.

Scope held: `ui/` + this file only (backend: `ladder.py` NEW + `app.py` wired +
2 test files; frontend: 8 new src/route files, 6 touched, 3 deleted; tests: 6
new, 5 touched, 2 deleted).

## §2026-08-15 S2 — UI simplification slice 2: the Dossier reader (`ui/` only)

Plan: `docs/ui_simplification_plan_2026-08-15.md` (§Dossier reader, §Kill list
S2 items, §Phasing S2). Built by a worktree-isolated build agent (spawn
`loop10h-ui-s2`) on top of merged S1 (`afb693e`); primary gates + merges.

### The Dossier surfaces (frontend only — no backend change this slice)

- **NEW `src/components/chips.tsx`** — the shared chip primitives moved
  VERBATIM out of IterationDetailModal.tsx (which dies this slice):
  NOVELTY/VERDICT/GATE tone maps (undecidable keeps its deliberate /40 quiet
  entry), `toneFor` (own-key prototype-collision guard), `badgeText`, `Badge`,
  `RedteamChip`/`redteamAlarm`, `ExperimentChip`/`experimentVerdict`,
  `conditioningBullets`, `seedTopic`, `shortTimestamp`, `processTone`/
  `processLabel`, `overrideTooltip`, and `OverrideProvenance` (now exported).
  ResolvedIterationsList re-imports from here (one import-churn) and DROPS its
  modal mount — a card click keeps only the onSelect journal behavior; the
  drill-in is the dossier reader. NEW `test_chips.tsx` carries the ported pins
  (toneFor collision, undecidable /40 tone, badgeText, experimentVerdict,
  conditioningBullets).
- **PipelineJourney absorbs the modal** (582→~1030L, the reader's spine): per
  the plan's absorption table — verdict-header badge row
  (`journey-verdict-header`: novelty + axes chip + critique + redteam + gate +
  process + SourceBadge for EVERY source + low-evidence + topicality advisory
  + experiment chip + timestamp + topic), OverrideProvenance blocks as visible
  text (`journey-override-novelty`/`-critique`), "conditioned by"
  (`journey-conditioning`, inner `conditioning-<id>` testid kept 1:1), the
  full evidence grid (`journey-evidence-grid`: category / rule_fired /
  anchor_cosine / curated_overlap / neighbor_spread) + the
  `journey-low-evidence-detail` amber box, redteam adversarial detail
  (`journey-redteam` + critique skeptic_verdict line), experiment extras
  (trials / results_path / object-valued `value.<k>` rows),
  `journey-candidates`, the LAZY `journey-journal` disclosure (JournalScroll
  mounts on first open), and the links section (`journey-chain-link` →
  /chain/req/{firstWrapperCallId}, `journey-experiment-link`,
  `journey-cycle-link` via the guarded coordinator-cycle join → `/coordinator`
  for now [S3 renames to /cycles]). GateVerdictForm NOT absorbed — the
  reader's footer owns the forms. `test_PipelineJourney.tsx` extended with the
  modal's section pins (ported from test_iteration_detail_modal, "ABSORBED"
  describes; every mount now Router-wrapped, cycle join stubbed file-wide).
- **NEW `src/components/todo/ChatPane.tsx`** (~370L) — TutorChatPane +
  TwoVoiceChatPane merged into ONE mode-parameterized pane
  (`mode: "tutor" | "two_voice"`): mode selects the useChatSession mode, the
  fence-note citation (tutor: 2026-06-14 PART 2 · rule 4 · D-053/D-054, NEVER
  D-044; two_voice: NEW `two-voice-fence-note` citing D-044 independence), the
  accent, the addressee selector (two_voice only), and stance-labeled replies
  (own-key stance guards kept). STRUCTURALLY fence-preserving: the prop
  surface is exactly {findingId, mode, available?, turnCap?, tokenCap?} — no
  verdict/confidence/onResolved/setter prop exists. useChatSession untouched.
  Per-mode testids kept (tutor-chat-* / two-voice-*) so ported pins read 1:1.
  The old capability-off fixture `turns` prop did NOT survive the merge (the
  off branch shows the empty state + disabled send; CHAT_TURNS_STUB stays a
  type fixture). NEW `test_ChatPane.tsx` covers both modes; the fence-note
  assertions carried verbatim (incl. the wire-fence: only the two chat verbs
  ever fire).
- **TutorPanel TRIMMED** — the unweighted pros/cons "considerations" section
  (+ its "not a recommendation" footer) deleted; keeps claim / provenance /
  evidence-refs + the neutral outcome-effects line + the fence note. The
  tutor's own copy now uses "recommend" exactly once (the fence note) —
  re-pinned in test_harden_TutorPanel (considerations cases dropped/inverted).
- **NEW `routes/DossierIndex.tsx` (/dossier, ~490L)** — the fetch-owning
  picker: getHumanTodo (10s poll) + getIterations (30s). Sections owe-first:
  (1) YOU OWE = gate_verdict + state_gate families; (2) CLEARED THE BAR =
  clearsLadderBar findings (honest "Nothing cleared L4 this week." empty
  state); (3) EVERYTHING ELSE searchable — below-bar/legacy findings (the
  pre-ladder 31), bubbles, stale runs, unknown kinds, + the resolved-iteration
  history with verdict/novelty/gate chips (browse moved here from the
  Dashboard list). ResolveRail's titleStem/buildCells 6-word-stem clustering
  ported VERBATIM (+ cluster_id-future comment); every row is a
  `<Link to="/dossier/<id>">`; the deferred sky chip ported (testid
  `todo-deferred-tag` kept); 404 → honest "queue UNKNOWN". NEW
  `test_dossier_index.tsx` (owe-first sectioning, stem clustering, search,
  honest empty states, deferred chip, hostile rows).
- **NEW `routes/DossierReader.tsx` (/dossier/:id, ~430L)** — kind from
  getHumanTodo().find(id) else the sf-*/iter-* prefix (queue-miss rows from
  the index's history section); ConcurrencyWarning → header (id · kind chip ·
  title · deferred tag · "not in the live queue" honesty note) → trimmed
  TutorPanel (interrogable kinds) → PipelineJourney spine → CalibrationCapture
  (opt-in, pre-reveal; per-id captured Set lifted here) → reveal fence button
  → ChatPane mode=tutor + mode=two_voice (per-id revealed Set) → the
  kind-gated UNCONDITIONAL disposition footer: gate_verdict → GateVerdictForm
  + the CLI-fallback `<details>` ported verbatim from the modal (testid
  renamed `modal-gate-cli`→`dossier-gate-cli`; command string verbatim);
  finding_review → FindingReviewForm + DirectiveSignOffField + AuthorizeFixForm
  + SpawnTopicForm + AbstainForm; bubble_ack/bubble_unacked → BubbleAckForm;
  ALL kinds → DeferForm. Capability wiring (getCockpitAvailability +
  strict-true safeActions + safeItems) lifted verbatim from Todo.tsx.
- **`App.tsx`**: nav `pulse · ladder · dossiers · engine ▾ · brain↗`; routes
  `/dossier` + `/dossier/:id`; `/todo` → `<Navigate to="/dossier" replace>`.
  Both route sweeps gained a DossierIndex console-clean render.

### Deletions (this slice)

`routes/Todo.tsx`, `components/HumanTodoPanel.tsx` (ladderBar.ts was extracted
in S1 — OweStrip unaffected), `components/todo/ResolveRail.tsx`,
`TutorChatPane.tsx`, `TwoVoiceChatPane.tsx`, `components/IterationDetailModal.tsx`
+ dead suites: test_iteration_detail_modal, test_TutorChatPane,
test_harden_TwoVoiceChatPane, test_human_todo_panel, test_human_todo_inbox,
test_ladder_inbox, test_ResolveRail, test_todo_route, test_todo_route_wiring,
test_harden_TodoShell, test_todo_kind_gating (17 files). PORTED, not lost:
kind-gating pins → NEW `test_dossier_reader.tsx` (iteration → GateVerdictForm
ONLY; finding → the finding set; bubble → ack only; state-gate → defer-only;
hostile kinds → other; chat never exposes a disposition; prefix fallback;
unconditional forms; capability flow); chip pins → test_chips; modal section
pins → test_PipelineJourney; two-voice/tutor pane pins → test_ChatPane;
test_cockpit_interrogation re-pointed (TwoVoice block → ChatPane suite;
considerations assertions inverted); test_audit_consistency's modal-hue
comparison now reads the shared SourceBadge directly;
test_resolved_iterations_list's modal describes pruned (row-half pins kept).
test_cockpit_resolution_forms + test_cockpit_forms_a11y unchanged (leaf-form
suites).

### Verification (this worktree)

- frontend vitest **1396 pass** (97 files; 1490 → 1396 — an honest shrink of
  ~94 tests tracking the deleted surfaces, with 133 tests across the 5 new/
  extended suites) · `tsc --noEmit` clean
- ui-backend pytest **680 pass** (`.venv-chroma`, `MOCK_LLM=1`; the S1 live
  ladder probe now passes against the restarted post-S1 binary) — no backend
  change this slice
- FENCE PROOF: ChatPane's Props = {findingId, mode, available?, turnCap?,
  tokenCap?}; `grep -in "verdict|onResolved|confidence"` over ChatPane.tsx
  hits only the fence-note copy. Pinned in test_ChatPane + the reader's
  "chat NEVER exposes a disposition" describe.
- The real `:8700` smoke (gate_verdict dossier from the owe strip: journey
  full evidence + overrides + journal; chat capability-gated; GateVerdictForm
  sole disposition; sf-* dossier resolves its source iteration; /todo
  redirect) is the PRIMARY's post-merge step per the plan's S2 gate.

Scope held: `ui/` + this file only. Frontend: 5 new src files (chips, ChatPane,
DossierIndex, DossierReader + App routes), 4 absorbed/trimmed (PipelineJourney,
TutorPanel, ResolvedIterationsList, App), 6 src deletions; tests: 4 new, 6
updated, 11 deleted.

## §2026-08-15 S3 — UI simplification slice 3: deletions sweep + nav cleanup (`ui/` only)

Plan: `docs/ui_simplification_plan_2026-08-15.md` (§Route fates, §Kill list,
§Phasing S3). Built by a worktree-isolated build agent (spawn `loop10h-ui-s3`)
on top of merged S1+S2 (`6e4c961`); primary gates + merges. This is the slice
that makes the 3-surface shell FINAL: everything the plan marked DIE is gone.

### Routes + nav (the final shell)

- **DELETED** `routes/Dashboard.tsx`, `routes/Activity.tsx`, `routes/Ideas.tsx`
  (all unmounted since S1/S2; the Ideas body lives on as the /ladder fallback).
- **NEW `routes/Graph.tsx`** (~110L thin page): mounts ActivityGraph with the
  data fetch ported from Activity.tsx — 5 s poll, change-detection signature so
  react-flow only relayouts on real change, overview/full DetailToggle.
- **`routes/Coordinator.tsx` → `routes/Cycles.tsx`** (git mv; component renamed
  `Cycles`, h1 "Cycles", `coordinator-page` testid kept — dozens of pins read
  it). **CoordinatorPhases mounts at its top**. DEVIATION from the task's
  literal "port the fetch from Activity.tsx": the ported fetch was
  getCoordinatorActive() → `/api/coordinator/active`, which THIS slice retires
  — so the stepper feeds from the D-047 registry instead (`getActiveRuns()`,
  pick `kind==="coordinator"`, quiet-fail; `initialPhasesRun` prop for tests),
  per the plan's Pulse note that the registry is the one live-run source. The
  two `/api/coordinator/active` caption strings in CoordinatorPhases now read
  `/api/activity/active_runs`.
- **`App.tsx` final nav**: `pulse · ladder · dossiers · engine ▾ (cycles,
  experiments, graph) · brain↗`. Routes `/cycles` + `/graph`; redirects
  `/coordinator`→`/cycles` (NEW), `/todo`→`/dossier`, `/ideas`→`/ladder`;
  `/dashboard` + `/activity` REMOVED entirely.
- **S1/S2 deferred link flips executed**: LastCycleLine → `/cycles`;
  PipelineJourney `journey-cycle-link` → `/cycles` (both "for now /coordinator"
  deviations resolved; pins updated in test_last_cycle_line +
  test_PipelineJourney).

### Component deletions (all verified import-orphaned first)

SystemActivityHero (nowVerdict.ts STAYS — Pulse/NowBoard use it),
InFlightRollup, ActiveIterationPanel, RedFlagsTrendStrip, HealthSignalsPanel,
SurfacedFindingsPanel, BubblesPanel, ResolvedIterationsList (JournalScroll
STAYS — PipelineJourney), BaselineCard, ProcessGrid, LiveCallsBanner,
ActiveWorkersPanel, SyntheticInferencePanel. Only Dashboard.tsx/Activity.tsx
imported any of them — nothing needed folding. CoordinatorPhases + ActivityGraph
survive at their new mounts.

### Client / type / fixture prune

- `api/http.ts`: getState, getBaseline, getProcesses, getSurfacedFindings,
  getBubbles, getHealthSignals, getActiveIteration, getCoordinatorActive
  (the last two: their endpoints retire below; Pulse never polled them).
- `api/activity.ts`: getActiveRun (singular; getActiveRuns stays in http.ts).
- `api/experiments.ts`: getExperiments (index; getResearch is the real index).
- `types/schemas.ts`: AppState, BaselineRow/BaselineResponse,
  ProcessRow/ProcessesResponse, SurfacedFinding(+Response), Bubble(+Response),
  HealthSignal(+Response). ActiveIteration/CoordinatorActiveRun STAY
  (nowVerdict inputs + CoordinatorPhases prop + fixtures).
- `types/experiments.ts`: ExperimentsListResponse (ExperimentListItem stays —
  ResearchExperiment's base).
- Fixtures: coordinator SURFACED_FINDINGS/BUBBLES/HEALTH_SIGNALS fixtures;
  experiments EXPERIMENTS_LIST fixtures; activity MONITOR_*/ACTIVE_RUN
  fixtures (only the two GRAPH fixtures survive).

### Backend endpoint retirements (each verified consumerless in src first)

`/api/state` + `/api/baseline` (+ `baseline.py` module; bench CSVs untouched;
create_app signature + env overrides unchanged — the params stay accepted),
`/api/experiments` index (KEEP `/{exp_id}` + `/api/research`),
`/api/coordinator/{findings,bubbles,health_signals,active}` (KEEP `/cycles`),
`/api/activity/active_run` singular (KEEP `/active_runs` + `/monitor` +
`/graph`; the registry still wraps the legacy mirror itself),
`/api/loop_v0/{active,processes}` (KEEP POST `/start`, `/iterations`,
`/journal/{id}`; the in-memory spawn tracker survives — /start records and
/iterations joins process_status). In-process route-table check confirms
exactly the intended surviving set.

### Test prune / rewrite

- Frontend DELETED (32 files): the task's §Kill-list 28 (dashboard ×3, hero ×2,
  InFlightRollup, active-iteration ×3 [incl. step_strip + stale_active_run],
  findings ×3, bubbles ×2, health-signals ×2, red-flags ×3, resolved-list ×4
  [undecidable-verdict pins ported to test_chips first — the only one missing
  was the single-field overrideTooltip form], harden_Activity,
  activity_monitor, failed_dispatch_grouping, baseline_card) + 4 collateral
  suites of the same dead surfaces (test_ideas_board; test_audit_states — all
  four subjects deleted; test_validate_iterations + test_revalidate_live_rows
  — live-data twins of the killed resolved-list suite; the browse they
  validated moved to the dossier index, which has its own suite) +
  test_validate_panels_empty.
- Route sweeps REWRITTEN for the final shell (test_forwardcompat_routes /
  test_validate_routes_console: Pulse · Ladder · Cycles · Graph · Experiments ·
  DossierIndex; retired-client mocks dropped). test_activity_graph re-pointed
  at /graph; test_coordinator_route + test_harden_Coordinator re-pointed at
  Cycles (+ a new phases-mount case; the harden mock gained getActiveRuns);
  test_validate_active now drives getActiveRuns (the registry contract) into
  CoordinatorPhases; test_endpoint_skew's bespoke-204 cases re-pointed at
  getLadder; test_audit_a11y/consistency/perf pruned to the surviving
  surfaces; test_validate_lowevidence kept its badge half only.
- Backend DELETED: test_baseline.py, test_robust_{findings,bubbles,
  health_signals,active}.py. PRUNED retired-endpoint cases from
  test_api / test_experiments / test_coordinator / test_loop_v0 /
  test_robust_cycles / test_live_8700 / test_validate_live_real_data (the
  /api/ladder probe KEPT) **+ test_activity.py** (the singular /active_run
  cases — an addition to the task's list; its endpoint died here too). The
  /processes reap semantics (exited_error_<rc> / killed_signal_<sig>) were
  PORTED into a /iterations-join test, not lost.

### Verification (this worktree)

- frontend vitest **916 pass** (65 files; 1396 → 916 — the honest S3 shrink
  tracking ~32 deleted suites) · `tsc --noEmit` clean
- ui-backend pytest **605 pass** (`.venv-chroma`, `MOCK_LLM=1`; 680 → 605)
- `git grep` retired-endpoint gate over `ui/`: clean except
  `ui/notes/ui-build.md` + `ui/notes/validation_report.md` — DATED running-log
  history (same class as this file's history), left un-rewritten by design.
- The real `:8700` full-nav smoke (every nav destination + all three
  redirects live; ensure-cron check) is the PRIMARY's post-merge step per the
  plan's S3 gate. NOTE for that restart: the retired endpoints 404 from the
  new binary — the pre-restart frontend build briefly shows
  EndpointMissingNote-class degradation, which is the known version-skew
  pattern, not a defect.

### Follow-on — cluster_id join for the dossier picker

DossierIndex still clusters findings by ResolveRail's ported 6-word
`titleStem` heuristic. Now that `/api/ladder` serves real
`LadderCluster.cluster_id` rows (and D-059 producers stamp
`evidence_level` through human_todo), the right join is by ledger
`cluster_id` — replace the stem heuristic with a cluster_id lookup once the
human_todo/finding rows carry it end-to-end (EMIT-side addition), and let the
picker's groups link to their `/ladder` cluster rows. Until then the stem
comment in DossierIndex marks the seam.

Scope held: `ui/` + this file only. Frontend: 2 new routes (Graph, Cycles via
git-mv rename), App/CoordinatorPhases/LastCycleLine/PipelineJourney touched,
16 src files deleted, 4 clients + 10 types + 3 fixture groups pruned; tests
32 deleted, 12 rewritten/re-pointed. Backend: baseline.py deleted, 5 modules
pruned of retired handlers, 5 suites deleted, 8 pruned.

---

## §2026-08-15 R0 — UI revamp foundation: design-token system + shared primitives (`ui/` only)

Built by a worktree build agent (spawn `loop3h-revamp-r0-design-system`) on
merged main @ f1d0c2a. R0 is the FOUNDATION slice of the full revamp: tokens,
type, shared primitives, app-shell restyle. **No route redesigns here** —
routes keep rendering under the new tokens; R1-R4 restyle them one at a time
on top of this system.

### The token system (R1-R4: consume these, never invent parallels)

`ui/frontend/src/design/tokens.css` — imported once in `main.tsx` AFTER
`index.css` (so it wins name collisions, e.g. `--font-mono`). The legacy
`src/tokens.css` shared block is UNTOUCHED (fence-checked against the
framework brain copy by `check_design_tokens.py`); old custom styles keep
reading it, new work reads ONLY the design tokens:

- **Neutrals (one family, zinc, oklch):** `--neutral-50 … --neutral-950`;
  semantic aliases `--bg` (near-black oklch 0.16, never #000), `--surface-1/2/3`
  (elevation = lighter step + 1px border; NO card shadows), `--surface-glass`
  (ONLY the sticky header + palette scrim), `--border-1/2`.
- **Text (two colors only):** `--fg`, `--fg-muted`. Hierarchy beyond that is
  weight: `--weight-normal/medium/semibold` (450/550/650).
- **Accent (ONE, sky-indigo oklch 0.70 0.13 250):** `--accent`,
  `--accent-hover`, `--accent-muted`, `--accent-fg`, `--focus-ring` — used
  ONLY for links, primary action, focus, active nav. Never status.
- **Status set (EXCLUSIVELY run/rung status):** `--status-ok/warn/bad/info/idle`
  (+ `-bg` tints) = emerald/amber/rose/sky/zinc.
- **Type:** `--font-sans` (Geist Variable) / `--font-mono` (Geist Mono
  Variable), self-hosted via `@fontsource-variable/geist{,-mono}` (imported in
  `main.tsx`); sizes `--text-meta/ui/prose/prose-lg/title/title-lg`
  (12/13/14/15/16/20px); `tabular-nums` applied globally to
  `code/pre/kbd/samp/.font-mono/.tnum`.
- **Radii:** `--radius-control` 6px / `--radius-card` 10px / `--radius-pill`.
- **Spacing (4px grid):** `--space-1..12`.
- **Motion (transform/opacity only):** `--motion-enter/exit/hover/panel`
  (200/150/120/250ms), `--ease-out/in`; ALL collapse to 0ms under
  `prefers-reduced-motion` (animations also hard-disabled in primitives.css).
- **Density:** rows ride `--row-h` (36px); a container's
  `data-density="dense"` switches it to 28px — no per-component props.
- **Page widths (utility classes):** `.page-full` (boards/tables),
  `.page-prose` (~760px reading column — dossier/journal). Routes adopt in
  R1-R4.

### Shared primitives (`ui/frontend/src/design/`, styles in `primitives.css`)

- **`RungGlyph`** — THE rung representation everywhere from now on: 16px
  six-segment ring, one segment per L0..L5 (D-059), rung Lk lights k+1
  segments (L5 = full ring); L4/L5 emerald (clears bar), L0-L3 sky, killed =
  gray with rung preserved; non-L0..L5 producer values light NOTHING (`rungIndex`
  mirrors ladderBar's producer-owned normalization). role=img + D-059 label.
- **`StatusDot`** — semantic status dot (`ok/warn/bad/info/idle`); `pulse`
  ONLY when genuinely running.
- **`PeekPanel`** — Linear-style right slide-over (250ms, focus-trapped, Esc +
  backdrop close, focus-restore, width prop ~420-520, default 480). Pure
  presentation; fetches nothing. R1+ uses it for row → detail peeks.
- **`CommandPalette`** — cmdk ⌘K/Ctrl+K palette, mounted globally in App;
  "Go to" entries for all 7 routes; `registerPaletteActions([...]) → unsubscribe`
  is the seam R1-R4 use to add verbs (routes only in R0).
- **`Skeleton` / `SkeletonRows` / `SkeletonCard`** — shape-matching shimmer
  (rows at `--row-h`; card shell); role=status "loading".
- **`ListRow`** — 36px dense row, hover = one surface step; onClick ⇒
  keyboard-operable button. **`Card`** — surface-1 + border-1 + radius-card.

### App shell (restyle only)

Sticky glass header (`.dsn-header`, blur 12px — with the palette scrim the
only two glass surfaces), nav active state moved emerald → accent, engine
menu elevates by surface step (shadow removed), CommandPalette mounted, "⌘K
to jump" hint in the header.

### Deps + tests

Deps added: `cmdk` 1.1.1, `@fontsource-variable/geist` + `-geist-mono` 5.3.0,
`@dagrejs/dagre` 3.1.1 (pre-staged for the R-slice react-flow relayout).
Tests: 5 new suites / 48 tests (`test_design_rung_glyph` 13,
`test_design_peek_panel` 10, `test_design_command_palette` 9,
`test_design_skeleton` 5, `test_design_primitives` 11); setup.ts gains
guarded scrollIntoView + ResizeObserver stubs (cmdk). Suite 980 green
(baseline 932, zero route tests broken by the shell), tsc clean, vite build
clean (Geist woff2 self-hosted, ~69KB total).

---

## Historical sections (UI v1, pre-LOOP_V0)

The sections below were written before the 2026-05-26 direction change to
LOOP_V0 (see [`DECISIONS.md`](DECISIONS.md) D-030 in the primary branch).
Specific stale framings preserved here for code-archaeology: "Week 1",
"Track D", "tier-shift unlock", `plan.yaml` references, and the UnlockPanel
keyed to alignment-evidence thresholds. UnlockPanel is commented out in
`Dashboard.tsx` as of 2026-05-26 — kept in-file so a future session can
decide whether to repurpose it for the LOOP_V0 exit criterion or remove
it. Treat what follows as a record of the codebase you'll find under
`ui/`, not a binding plan.

> **Original preamble (preserved):** Companion plan to `plan.yaml` (week 1,
> days 31–37). The week 1 plan builds the research apparatus. This plan
> builds the observability layer on top of it. Both plans share the same
> repo (`a_bgt_rsi`). **You are a concurrent Claude instance.** A different
> Claude is executing `plan.yaml` (the week 1 apparatus build) on the DGX
> Spark. This plan is yours. The two plans share data contracts (the JSONL
> schemas in `schema/`) but do NOT share source files outside `ui/`.
>
> **Revision r11 (2026-05-24).** **UI v1 is ship-complete for the
> Day-38 Week-2 unlock gate.** This pass wires the frontend consumer
> for `/api/unlock_status` (the r9 backend that had no dashboard
> renderer yet). The new `UnlockPanel.tsx` surfaces the five §11.3
> Week-2-unlock prerequisites — run-log integrity, soft-gate queue,
> hard-gates pending, fallbacks_taken, and a day-grouped metric_log —
> so the human can attest the Week-2 tier shift from the UI rather
> than from raw logs. The panel is strictly read-only: rollback /
> attest commands surface as copy-paste CLI strings (operating-contract
> rule 8). All Day-7 artifacts (137-line run.jsonl, 88-line
> orchestrator.jsonl, 4-run PD diagnostic ladder, fallbacks_taken,
> D-028 gate-clear note) render correctly against real on-disk data.
> 85 Python + 25 frontend tests pass; `vite build` clean. See §0 r11
> for the audit + ship details.

---

## 0. Revision log

**r12 (2026-06-05)** — Batch 1 of the concurrent-HITL build rhythm:
`/activity` (live graph + agent monitor) and `/experiments` (digestion)
landed in one parallel fan-out (two builder agents, each owning its own
files; primary session applied the shared `App.tsx` / `app.py` edits). See
§ACTIVITY + EXPERIMENTS for the data contracts and the mock/real boundary.
+16 backend / +18 frontend tests; 79 + 46 pass; `tsc && vite build` clean.
One synthetic surface (per-worker inference internals) handed to the primary
session as a `logs/worker_activity.jsonl` instrumentation ask. New frontend
dep `@xyflow/react ^12.11.0`; new gitignored `ui/.venv-ui` for backend tests.

**r11 (2026-05-24)** — UI v1 ship-complete for the Day-38 Week-2
unlock gate. Closes the §11.3 frontend gap left open by r9 (the
`/api/unlock_status` backend had no dashboard consumer; the Week-2
unlock attestation per `agent/autonomy.md` §4 needs the human to see
alignment evidence end-to-end). Independently from the wire-up, this
pass also audited the real on-disk Day-7 artifacts against UI v1 —
findings live in `notes/track-d-observations.md`.

What landed:

1. **`UnlockPanel.tsx` (new) + `Dashboard.tsx` (wire-up).** A single
   card rendering the five §11.3 sections:
   - **Run-log integrity** — pass/fail badge + total / malformed /
     rolling-window counts; malformed line numbers listed when present.
   - **Soft-gate queue** — per-pending row with `task_id`, `agent_id`,
     summary, expected vs observed, and a copy-paste rollback CLI.
     Tone is "warn" when non-empty (soft-gate auto-proceed is not a
     failure, just a thing to know about).
   - **Hard gates pending** — per-pending row with `task_id` and a
     copy-paste attest CLI. Tone is "fail" when non-empty (hard-gates
     halt the apparatus until the human attests).
   - **fallbacks_taken** — list of `{day_id_taskid: reason}`. Tone is
     "warn" when non-empty; the §11.3 sidebar requirement.
   - **metric_log (drift check)** — keys grouped by the `day_N` prefix
     so per-day comparison reads at a glance. The slip-ladder days
     (`day7_1_…` / `day7_2_…` / `day7_3_…`) split into separate
     "day 7.1 / 7.2 / 7.3" buckets rather than getting lumped under
     "day 7".
   The panel is strictly read-only: rollback / attest commands surface
   as `<code>` text, never as `<button>` (operating-contract rule 8;
   covered by a no-button vitest assertion).
2. **`api/http.ts` + `types/schemas.ts`.** Added `UnlockStatus`,
   `SoftGatePending`, `HardGatePending`, `SoftGateQueue`,
   `HardGatesPending`, `RunLogIntegrity` mirrors of the backend payload,
   plus `getUnlockStatus`.
3. **`tests/test_unlock_panel.tsx`.** 5 vitest cases covering the
   all-clear render, malformed-line flagging + fallback rendering,
   pending soft-gate rollback as copy-paste text (no rollback button),
   pending hard-gate attest command + fail badge, and the
   backend-error path.

Audit findings (full list in `notes/track-d-observations.md`):

- `run_state/week1.run.jsonl` 137 lines, 0 malformed under the
  Appendix-C required-field set; rolling 7-day window 135 entries.
- `run_state/week1.state.json` `current_day=day_8`,
  `human_gates_pending=[]`, 4 entries in `fallbacks_taken`, 11
  `metric_log` keys (including the Day-7 slip-ladder triplet
  `day7_1/7_2/7_3_coop_rate_vs_tft` and the diagnostic
  `day7_3_coop_rate_vs_all_d`).
- `/api/recent_tasks` against the real `logs/orchestrator.jsonl`
  surfaces Day-7 PD events as `stage=orchestrator_receipt`
  `status=passed`; the r10 sort-key + filter fix confirmed working on
  real data.
- `/api/workload_hint` classifies the on-disk PD workload as
  `short_completion` (5.81 calls/s × 2 tokens/call), so the decode tile
  carries the workload-aware annotation instead of misreading as a
  regression.

85 Python tests pass (no change vs r10) + 25 frontend tests pass (20
prior + 5 new); `tsc --noEmit && vite build` clean.

**What Track A should know about for forward-looking plans:**
- UI v1 is now complete for the Week-2 unlock attestation per
  `agent/autonomy.md` §3. The five §11.3 prerequisites render end-to-end
  against real on-disk artifacts. Track A's unlock-attestation flow
  can proceed against this UI; no further Track-D work is gating it.
- `tools/attest_gate.py` and `tools/rollback_attestation.py` (Track C)
  are still referenced as informational CLI strings in the UnlockPanel.
  When those land, the strings become real human-runnable commands;
  no UI change needed because the strings already match the conventions
  agreed at r9.
- The §11.3 sidebar that r9 expected for `fallbacks_taken` is rendered
  as one of the five panel sections rather than a separate sidebar
  widget — it kept the layout dense and avoided a layout reflow on a
  rarely-changing field.

**r10 (2026-05-23)** — Day-7-EOD UX audit + four small fixes. The user
ran the real Day-7 PD experiment through the v1 dashboard and surfaced
observations that exposed two real bugs and two UX gaps. None of v1's
shipped panels were re-architected; the patch is small and lives in
`ui/backend/{chain,workload,app}.py`, `ui/backend/tests/test_*`,
`ui/frontend/src/components/{OrchestratorQueue,Day4ChainList,RobustnessPanel,VllmPanel}.tsx`,
`ui/frontend/src/{api/http.ts,types/schemas.ts}`, and one Day-4
fixture-text test update. 85 Python + 20 frontend tests pass; `vite
build` clean.

The four observations and what landed:

1. **Decode tok/s read ~11 during the experiment — well below the day-1
   band [80,130].** Not a regression; the day-1 sweep used 256 output
   tokens per call (decode-bound), the PD experiment uses ~2 (prefill /
   TTFT-bound by construction). The decode-tok/s sampler reads
   `vllm:generation_tokens_total` rate server-wide; with 600 calls × 2
   tokens / 114 s ≈ ~10.5 tok/s, the tile is reporting truthfully. The
   v1 panel just had no way to convey "different workload regime."
   - **New: `GET /api/workload_hint`** (`backend/workload.py`). Reads
     the last N call records across the call-log glob (Day-2-shape
     `usage.completion_tokens` and Day-7-shape `usage.output_tokens`
     both supported), computes calls/sec + median output tokens,
     classifies the regime (`short_completion` / `decode_bound` /
     `mixed` / `idle`), and returns a calls/s × tokens/call expected
     band. The frontend renders this as a small workload pill below
     the decode tile, plus the human-readable note. The Sparkline's
     `reference={40}` (the day-1 hard floor) now only shows in the
     `decode_bound` regime so the line doesn't suggest a threshold
     where it does not apply.

2. **Orchestrator queue showed no experimental events during the run.**
   Two real bugs in v1 — both missed the Day-6 schema change from
   `dispatch_ts`/`receipt_ts` to `timestamp`/`stage`:
   - **`backend/chain.py:recent_tasks` sort key.** Used `dispatch_ts`
     which Day-6+ records do not carry. Every record sorted as `""` →
     dict-insertion order, pushing fresh `play_pd_match` rows below
     stale `summarize_paper` rows. Fixed to `timestamp` primary,
     `dispatch_ts` fallback (so old fixtures still work). Surfaces
     `timestamp` + `stage` in the response alongside the legacy fields.
     New test `test_recent_tasks_day6_schema_sorts_by_timestamp`.
   - **`OrchestratorQueue.tsx` "Running" filter.** Filtered
     `status === "started"` but Day-6+ writes `status: "running"` on
     `worker_invocation` and `status: "dispatched"` on
     `orchestrator_dispatch`. The "Running" section never lit up
     during a real run. Filter widened to
     `{"started", "dispatched", "running"}` and `statusClass` adds the
     two new in-flight states + `"error"` from `orchestrator_reject`.

3. **Tool-call chains and robustness sweep showed no activity.** This
   is *by design* — they read `logs/day4_e2e.jsonl` and
   `logs/day4_robust.jsonl`, both Day-4-specific. But the empty-state
   copy ("logs/day4_e2e.jsonl is not present yet — the apparatus has
   not reached day 4") was misleading once Day 4 *had* passed; the
   user saw an empty panel and could not tell whether something was
   broken. Both panel headings now carry an explicit
   "(logs/day4_*.jsonl — day-4-specific; quiet during other
   workloads)" subhead and the empty-state copy says "this panel only
   lights up during the day-4 [thing] — PD or summarize workloads do
   not populate it."

4. **User wants a visual graph of orchestrator + spawned agents with
   zoom-into-experiment.** This is v2 territory; sketched in
   `ui/ui_plan_v2.md` §5 with data contracts, library choice
   (`react-flow`), route (`/graph`), and macro-vs-micro level
   semantics. Data sources already exist (orchestrator.jsonl + call-log
   glob + `/api/live` WebSocket); a new `GET /api/graph` endpoint and a
   new route are the build work. Independent of the v2 results browser
   (`ui_plan_v2.md` §2-4) — they share zero code; either can land
   first.

**What Track A should know about for forward-looking plans:**
- v1's coverage of the Day-6+ orchestrator schema was incomplete on
  ship — the two filter/sort bugs above are evidence we did not
  re-validate v1 against the real schema once Day 6 landed. A
  follow-up regression check (when a new orchestrator stage or status
  is added, validate the dashboard renders it) is worth a small
  amount of process discipline. Flagged in
  `notes/track-d-observations.md`.
- Day 38's Track-D scope in `notes/day7_to_week2_execution_plan.md`
  has been amended (this commit) to **ship v1 with the r10 fixes
  applied** before attesting the Week-2 unlock — the unlock attestation
  per `agent/autonomy.md` §4 cannot be made against a v1 that doesn't
  render orchestrator events.
- The v2 live-graph view is now Track D's primary v2 work, ahead of
  the experiment-results browser. The graph view's data contracts
  exist; the results-browser's experiment-outcome schema is still
  blocked on Track A (no `schema/experiment.schema.json`). Sequencing
  this way pulls Track D's next-milestone work onto unblocked ground.

**r9 (2026-05-23)** — §11.3 Week-2 unlock prerequisites audit + smallest
patch. The §11.3 list was added in r8 but not wired through `ui/backend`;
this pass closes the gap so UI v1 actually renders alignment evidence
end-to-end. Audit result and what landed:

| §11.3 prerequisite | Before r9 | After r9 |
|---|---|---|
| 1. Run-log integrity (`verify_log_integrity`, rolling week) | missing | **built** — `verify_run_log_integrity` in `backend/unlock.py` re-implements the validator against the plan.yaml Appendix-C required-field set (Track D cannot import `agent_wrapper.wrapper.verify_log_integrity` — out of zone) |
| 2. Soft-gate attestation queue + rollback action | missing | **built** — `read_soft_gate_queue` reads `run_state/attestations.jsonl`, pairs `request` with `approved`/`rejected`/`no_objection` per `agent/autonomy.md` §2.1, and attaches a `rollback_command` string per pending entry |
| 3. Hard-gate pending list + attest action | partial (raw `/api/state` passthrough) | **built** — `read_hard_gate_pending` surfaces `state.human_gates_pending` with an `attest_command` per entry |
| 4. Today's metric_log values vs prior runs | partial (`baseline.py` read `day1_tokens_per_sec` only) | **built** — the full `state.metric_log` dict ships in the response; per-day comparison is natural since each entry is keyed by day |
| 5. Sidebar: `state.fallbacks_taken` | partial (raw `/api/state` passthrough) | **built** — dedicated field in the response, ready for a sidebar widget |

All five sections land in one new module `backend/unlock.py` exposed at
`GET /api/unlock_status` — single endpoint, single payload, each section
independently `available: true/false` so the dashboard renders partial
state cleanly (mirrors `/api/events`, `/api/robustness`). The UI stays
read-only: `attest_command` and `rollback_command` surface the human-
runnable CLI string, the UI does not execute them (ui_plan.md §2,
operating-contract rule 8). Test coverage: 14 new backend tests (11 in
`test_unlock.py` + 1 in `test_api.py` end-to-end + 2 incidental from
`_client` fixture updates); 79 Python tests pass overall.

**What remains for UI v1 §11.3 completion (Track D follow-up):**
- Frontend rendering. The `/api/unlock_status` payload exists; a
  dashboard panel that renders the five sections is not yet wired. The
  fields are deliberately render-ready (each section is its own key),
  so the frontend work is a single new `UnlockPanel.tsx` consumer plus
  routing — no further backend work needed for Week-2 unlock.
- The `tools/attest_gate.py` and `tools/rollback_attestation.py` CLI
  commands referenced in `attest_command` / `rollback_command` are
  Track-C deliverables and not yet committed. Until they land the
  commands are informational placeholders; the UI surfaces them as
  copy-pasteable text, which is what §11.3's "action available"
  requires.
- The agent-side `verify_log_integrity` in `agent_wrapper/wrapper.py`
  and the UI-side `verify_run_log_integrity` in `backend/unlock.py`
  must keep the same required-field set. Both are pinned to plan.yaml
  Appendix C; if the run-log schema changes, both move together.

**r8 (2026-05-23)** — §11 "Observability gates agent autonomy" added.
Ties UI milestones (v1 sampler + dashboard, v2 call-chain inspector,
v2.5 alignment dashboard) to the tier-shift unlocks in
[`agent/autonomy.md`](agent/autonomy.md) §3. The UI's deliverables are
now load-bearing for agent-autonomy expansion: until UI v1 renders
alignment evidence end-to-end, Week-2 tier shifts cannot be authorized
by the weekly retrospective. Pure additive section — does not change
the existing data contracts, build order, or any prior revision.
Part of the 2026-05-23 documentation restructure (commit `6749c34`).

**r7 (2026-05-21)** — Track D day-5 sync. The day-4 sync (r6) was built
against synthesized fixtures; Track A's real day-4 artifacts are now on
disk and differ in shape. This pass aligns the UI to them. All under
`ui/` — no apparatus-side code touched.

- **`day4_robust.jsonl` is a chained call log, not a per-trial summary.**
  Track A logs every call (the same record shape as `day4_e2e.jsonl`),
  so the r6 `read_robustness` — which keyed on a per-trial `invoked`
  flag — scored the real file a misleading **0%**. Rewritten: a "run" is
  a wrapper-root call (`parent_request_id` null, `caller_tag`
  `test_tool_call_robustness/run<N>`); the run "invoked" the tool when
  its root `completion` parses as a tool call. Child records (the
  tool-result follow-up) are excluded from the trial count. A root whose
  completion is plain text "missed"; one that opens like a tool-call
  array but does not parse is "malformed" — flagged, never repaired.
  Latencies round to 0.1 ms (the source logs sub-microsecond floats).
- **Third tool-call shape — the `completion` field.** The day-4 sync's
  §9 resolution covered two shapes (separate call-log lines; an embedded
  `tool_calls` array). Track A's real shape is a third: the model's tool
  call serialized as an OpenAI-style JSON string in the wrapper record's
  `completion`. New `parse_completion_tool_calls` in `backend/chain.py`;
  `_call_node` synthesizes a `kind="tool"` child from it via the existing
  `_tool_node`, so the inspector tree is unchanged. A completion tool
  call has no own latency (the wrapper's `latency_ms` already covers it),
  so it contributes 0 to `total_latency_ms`. A completion that opens like
  a tool-call array but fails to parse sets `tool_calls_malformed` — the
  existing red banner/badge fire, no new tree field.
- **`EventsViewer` per-type renderer.** `schema/events.jsonl.schema.json`
  is now committed (a `oneOf` of `human_intervention` and
  `calibration_entry`). The viewer moved from generic key/value rendering
  to a per-type renderer driven by the schema's per-type fields, with a
  generic fallback for any other `event_type` and an "incomplete record"
  flag when a typed event misses a schema-required field.
  `logs/events.jsonl` does not exist yet — the `available: false`
  degrade path is unchanged; the backend `read_events` stays schema-light.
- **`retrieval_context` keys verified.** `schema/calls.jsonl.schema.json`
  whitelists `retrieval_context` (an array of `{doc_id, content_hash,
  chunk_offset, chunk_length}`, `additionalProperties: false` kept). The
  UI's reader passthrough, `RetrievalDoc` type and `ChainTree` table
  already match these keys — no drift, no change. A drift-guard test
  (`test_retrieval_context_whitelisted_keys_match_ui`) was added.
- **Fixtures + tests.** `gen.py`'s `day4_robust.jsonl` fixture is now a
  chained call log (5 runs: 3 ok, 1 missed, 1 malformed completion); the
  `events.jsonl` fixture matches the committed events schema field-for-
  field. New tests: completion-field synthesis (3), robustness chained
  shape (2), real-artifact coverage in `test_real_schema.py` (5 — real
  `day4_*` log validation, real `read_robustness`, real completion
  synthesis, events-fixture + retrieval_context schema guards), and the
  rewritten `EventsViewer` frontend tests. 65 Python + 20 frontend tests
  pass; `npm run build` clean.

**r6 (2026-05-20)** — Track D day-4 sync. Day 3.5 has not landed in
Track A yet (schema/calls.jsonl.schema.json carries no `retrieval_context`,
no `logs/events.jsonl`); day 4 has not landed either
(no `logs/day4_e2e.jsonl`, no `logs/day4_robust.jsonl`). This pass
builds forward-compatible support against synthesized fixtures so the
UI lights up when Track A's artifacts arrive — no apparatus-side code
touched. All under `ui/`.

- **Wrapper-rooted chain walker.** Day-4 tool-call chains begin before
  the day-6 orchestrator, so they have no dispatch root. New
  `build_chain_by_request_id(store, request_id)` walks from a wrapper
  request_id; new `GET /api/chain_by_request/{request_id}` exposes it;
  new route `/chain/req/:requestId` reuses the inspector. The
  dispatch-rooted shape (`/api/chain/{task_id}`) is unchanged.
- **Day-4 chain list.** New `GET /api/day4/chains` lists wrapper-rooted
  records from `logs/day4_e2e.jsonl` (parent_request_id null), each
  with node_count, total_latency_ms, and a `malformed_tool_calls`
  count. The dashboard's `Day4ChainList` component renders the listing
  and links into the inspector; rows with parse errors get a red
  `malformed` badge.
- **Malformed-JSON tool_calls banner.** `_call_node` now flags
  `tool_calls_malformed: true` when `tool_calls` is the wrong type
  (e.g. a string left by an upstream serializer). The inspector shows
  a red banner counting affected nodes; `ChainTree` shows a per-node
  `malformed tool_calls` badge. No silent format-fixing — the raw
  record is shown as stored.
- **retrieval_context (day-3.5).** New optional list on call records.
  The walker passes it through as a first-class field only when it is a
  list of objects (wrong-shape values are dropped to avoid leaking a
  typed contract to the UI). `ChainTree` renders a small collapsible
  table per node and a `ctx N` badge.
- **Robustness panel.** New `GET /api/robustness` reads
  `logs/day4_robust.jsonl` and returns invocation_rate,
  median_latency_ms, per-outcome counts, and the trial list (median
  uses `statistics.median`, so even-length lists average the two
  middle values). `RobustnessPanel` renders the summary + a per-trial
  table on the dashboard.
- **Events viewer.** New `GET /api/events` reads `logs/events.jsonl`
  generically — the schema has not been committed yet, so the reader
  enforces only `event_type` and passes the rest through. New route
  `/events` (`EventsViewer`) renders type-aware cards for
  `human_intervention` and `calibration_entry` with a type filter, and
  falls back to a generic dump for any other event_type that lands.
- **Fixtures.** `write_day4_fixtures()` extends `gen.py` with three
  day-4 wrapper-rooted chains (one carrying a deliberately corrupted
  `tool_calls` string), 10 robustness trials (8 invocations, 2 missed,
  1 timeout), and the two known event types. 15 new backend tests
  cover the walker, readers, and endpoints; 8 new frontend tests cover
  the dashboard panel, events viewer, and chain-tree badges.
- **Available-false defaults everywhere.** Each new endpoint degrades
  to `available: false` when its source file is absent, so the
  dashboard panels show "not present yet" rather than 500s while Track
  A is still pre-day-4.

53 Python + 17 frontend tests pass; `npm run build` is clean.

**r5 (2026-05-19)** — MTP-sync pass (Track D), bringing the UI in line
with apparatus decision D-022 (day 2: throughput abort resolved by
enabling MTP speculative decoding and re-pinning vLLM `v0.20.0` →
`v0.21.0`; decode 32 → 69 tok/s). The UI's earlier steps were built
while MTP was deferred, so this pass corrects the data sources and
copy. All under `ui/`.

- **Baseline card sources `bench/mtp.csv`.** `GET /api/baseline`
  (`backend/baseline.py`) now takes the MTP-enabled sweep as a third
  decode source; when `bench/mtp.csv` exists the decode row reports the
  MTP-engaged median (~69 tok/s) and keeps the pre-MTP `bench/day1.csv`
  / `metric_log` figure (~32) alongside as `pre-MTP …`. The documented
  constants dropped "MTP (≈96) deferred"; the stack row reads `vLLM
  v0.21.0 · MTP enabled`. `BaselineCard`'s unreachable-backend fallback
  rows match, and the card title dropped "(day 1)" — the decode row is
  now a day-2 measurement.
- **MTP tile colour-coded.** The vLLM panel's MTP-acceptance tile is
  green at ≥50% (the §5.3 "MTP engaged" signal), amber below, gray when
  the metric is absent ("MTP off / metric absent"). The sampler's
  speculative-decoding candidate names were broadened to the v1
  engine's counters (with/without the Prometheus `_total` suffix); the
  exact v0.21.0 names still want a live-server check (`ui-build.md`).
- The §0 banner at the top of this file was stale at r2 through the
  r3/r4 passes; corrected to r5.

**r4 (2026-05-19)** — improvement pass over the built steps 6.1–6.7
(Track D); resolves two of the three §9 open questions:

- **Tool-call rendering shape resolved (§9 first bullet).** Both shapes
  are now supported and converge to one inspector tree. Separate
  call-log lines (own `request_id` / `parent_request_id`) are handled by
  the ordinary chain walk; tool calls embedded in a wrapper record's
  `tool_calls` array are synthesized by the chain walker into
  `kind="tool"`, `embedded=true` child nodes with `request_id=null`. So
  a chain renders the same tree — and the same `node_count` and
  `total_latency_ms` — regardless of how the wrapper logged its tool
  use: embedded-tool latency is summed exactly as a separate-line tool
  call's latency already is, so the total does not depend on the
  logging shape. (`total_latency_ms` remains a labelled rough sum, not
  wall-clock; §5.3.) Both shapes have test coverage
  (`test_embedded_tool_calls_reconstructed`; the frontend embedded-badge
  test). The embedded key is assumed to be
  `tool_calls`; if the day-4 schema names it otherwise, only
  `EMBEDDED_TOOL_KEY` in `backend/chain.py` changes.
- **Healthy-baseline card is now data-driven (§9 fourth bullet).** The
  card no longer hardcodes day-1 numbers. A new `GET /api/baseline`
  endpoint (`backend/baseline.py`) sources decode tok/s from
  `bench/day1.csv` (median of the `decode_tok_per_s` sweep) and
  `run_state/week1.state.json`'s `metric_log.day1_tokens_per_sec`, and
  falls back to the documented §5.3 constants when neither exists yet.
  Every card row is annotated `source: "measured"` or
  `source: "documented"`; measured rows also carry the documented
  expectation alongside, so a drift like the current day-1 ~32 tok/s
  vs the documented [80,130] band is visible at a glance. Idle power
  and the threshold rows stay documented — no committed measurement
  source exists for them.
- **Inspector chain-diffing deferred to v2 (§9 third bullet).** A
  side-by-side two-chain diff would roughly double the inspector's
  layout work (a second tree column, node-alignment heuristics, a diff
  model for opaque generically-rendered payloads) for marginal value:
  the week-1 CLI already covers it — `diff <(tools/inspect_run.py
  --task-id X) <(tools/inspect_run.py --task-id Y)` gives a researcher a
  textual chain diff today. v1 stays single-chain; revisit in the v2
  results-browser plan (`ui/ui_plan_v2.md`) if a UI diff is still wanted.

**r3 (2026-05-18)** — changes made while building step 6.1:

- **Everything is under `ui/`**, with no exceptions. The telemetry
  schema lives at `ui/schema/telemetry.jsonl.schema.json` and the
  sampler output at `ui/logs/telemetry.jsonl` (not the apparatus's
  shared `schema/` and `logs/` dirs). `requirements-ui.txt` is at
  `ui/requirements-ui.txt`. This keeps the UI layer from clashing with
  the concurrent apparatus build. Rules 1 and 6 updated accordingly.
- **GB10 uses unified memory**, so `nvidia-smi` reports `[N/A]` for
  `memory.used` / `memory.total`. The `gpu.*` fields are therefore
  number-or-null; the sampler keeps util/temp/power and nulls the
  memory fields rather than discarding the whole `gpu` object (§4.1,
  §5.1). Confirmed against real hardware (idle: 0% util, 38 °C, ~5.5 W).
- **Build steps 6.1–6.7 are all built** — sampler, backend (HTTP +
  WebSocket), call-chain inspector, and the live dashboard (5 zones,
  sparklines seeded from `/api/telemetry/recent`, colour-coded
  thresholds, healthy-baseline card, click-through to the inspector).
  23 Python + 3 frontend tests pass.
- vLLM `/metrics` names verified against the running server (now
  `vllm/vllm-openai:v0.20.0`): KV cache is `vllm:kv_cache_usage_perc`
  (not `gpu_cache_usage_perc`), prefix-cache hit rate is computed from
  query/hit counters, and no speculative-decoding metrics are exported
  — `mtp_*` telemetry fields stay null until a build exposes them.

**r2 (2026-05-18)** — corrections after review against `plan.yaml`:

- **Contract:** carved out `logs/telemetry.jsonl` as a file the
  sampler may create/write (rules 1 + 6 previously contradicted §5.1).
- **Call logs are not one file.** `logs/calls.jsonl` does not exist.
  The apparatus writes per-day call logs (`logs/day2.jsonl`,
  `logs/day4_e2e.jsonl`, `logs/day4_robust.jsonl`, `logs/day5.jsonl`,
  `logs/day6.jsonl`, `logs/day6_5seq.jsonl`) plus `logs/exp001.jsonl`.
  `schema/calls.jsonl.schema.json` is the *schema* they conform to,
  not a log filename. §3, §4.2, §5.2 rewritten accordingly.
- **MTP speculative decoding** is now core to the stack
  (`--speculative-config method=mtp`, drafter model). Added MTP
  acceptance-rate fields to the telemetry schema (§4.1) and an MTP
  tile to the vLLM panel (§5.3).
- **Baselines refreshed.** Decode tok/s band is `[80, 130]`, expected
  single-stream ~96, hard floor 40, MTP-engaged signal ≥ 50.
  Measured day-1 idle power was ~5 W (the 25 W figure was a
  pre-release estimate). The baseline card is now data-driven (§5.3).
- Telemetry schema fields `gpu` / `host` / `vllm` marked nullable to
  match the sampler's documented failure modes (§4.1).
- Counter-reset handling for `tokens_per_sec_decode` on vLLM restart
  (§5.1); CPU-percent priming extended to newly-discovered PIDs (§5.1).
- Chain endpoint uses incremental offset reads, not full re-read on
  mtime (§5.2). Corrected telemetry file-growth estimate (§5.1).

---

## Operating contract (read once at start)

1. **All work lives under `ui/`** (plus this plan, `ui_plan.md`). Do
   not modify any file outside `ui/`. The week 1 build owns everything
   else. The UI layer's own schema and output stay inside `ui/` too —
   `ui/schema/telemetry.jsonl.schema.json` and `ui/logs/telemetry.jsonl`
   — so there is nothing to write in the apparatus's shared `schema/`
   or `logs/` dirs. You may **read but never write** anything under
   `schema/`, `run_state/`, `logs/`, `bench/`, `experiments/`, and
   `cron/`.

2. **The week 1 build is the source of truth for data contracts.**
   When `schema/calls.jsonl.schema.json` is committed on day 2 of the
   apparatus build, that is the schema. If it doesn't exist yet, your
   sampler can still ship (its own schema is in this plan) but the
   backend and frontend must not assume what the call-log schema looks
   like — read it from `schema/` at runtime.

3. **Do not block on the week 1 build.** The week 1 plan has hard
   checkpoints, human-only blocks, and a publication gate. You do not.
   Your milestones are independent and can land in any order, with the
   only ordering constraint being the build order in §6 below. If the
   week 1 build is paused at a human gate, keep going.

4. **The sampler runs on the Spark; the backend and frontend can run
   anywhere.** The sampler must observe the DGX Spark directly
   (`nvidia-smi`, `psutil` on tracked PIDs, host thermal zones, the
   local vLLM `/metrics` endpoint). The backend reads JSONL files from
   disk and serves an HTTP/WebSocket API; the frontend is a static SPA.
   The default assumption is all three run on the Spark; the design
   must not preclude running backend + frontend on a laptop pointed at
   the Spark over SSH later.

5. **No new top-level dependencies in `requirements.txt`.** The
   apparatus build keeps that file minimal on purpose. Add a separate
   `ui/requirements-ui.txt` for the sampler and backend. Pin versions
   when you fix them; do not pre-pin speculatively. Test-only deps
   (`pytest`, `jsonschema`, a WebSocket test client) belong in
   `ui/requirements-ui.txt` too, marked as dev deps in a comment.

6. **State the JSONL schema for `telemetry.jsonl` in code, not just in
   prose.** Commit `ui/schema/telemetry.jsonl.schema.json` as part of
   step 1, in the same format as the apparatus's schemas.

7. **No browser storage APIs.** `localStorage`, `sessionStorage`,
   `IndexedDB` will fail in some hosts. Keep UI state in memory or
   round-trip through the backend.

8. **Honor the apparatus's discipline about observation vs. silent
   fix.** The dashboard surfaces problems; it does not auto-remediate.
   If GPU temp is high, show it red; do not run a cache-clear cron.
   If a worker is stuck, show it stuck; do not kill it. The human
   decides what to do.

9. **Logging is mandatory for the sampler.** Append one line per
   sample interval to `ui/logs/telemetry.jsonl`. Failed reads (e.g.
   `nvidia-smi` not installed in your dev environment) write a line
   with a `read_errors` field, not a silent skip — and `read_errors`
   stays populated on every line a source is failing, not just the
   first (so the dashboard can show a source as persistently down).

10. **No emoji, no decorative formatting in the UI.** Match the
    apparatus's text-and-numbers tone. Sparklines and color-coding
    against documented baselines, not splash gauges or animated dials.

---

## 1. Goal

A two-view web UI that runs against the apparatus and gives the
operator:

- **Live dashboard**: at a glance, is the Spark healthy and what is
  the apparatus currently doing? GPU/CPU/thermal/power, vLLM internal
  queue and KV-cache state, MTP speculative-decoding health,
  orchestrator queue depth, currently running workers, recently
  completed tasks.
- **Call-chain inspector**: for any `task_id`, the full causal chain
  (orchestrator dispatch → worker invocation → wrapper call → vLLM
  request → optional tool calls), rendered as a tree, with the actual
  prompts and completions visible. The web version of the
  `tools/inspect_run.py` CLI from week 1 day 6.

Dashboard → click a task → inspector for that chain. That's the whole
product.

## 2. Not in scope

- Authentication, multi-user state, persistent UI preferences.
- Mutating apparatus state (killing workers, clearing caches, restarting
  vLLM). The UI is read-only.
- A separate metrics database (Prometheus, InfluxDB). The JSONL files
  are the database. If aggregations get slow later, that is when to
  reconsider — not now.
- Editing prompts/configs from the UI.
- Mobile/responsive layout. Desktop only.
- Light-mode polish (build dark-mode first; light is a follow-up).

## 3. Architecture

```
[ nvidia-smi ] [ vLLM /metrics ] [ psutil ] [ /sys/class/thermal ]
                       │
                       ▼
              ui/sampler/  (1 Hz daemon)
                       │
                       ▼
       ui/logs/telemetry.jsonl  ────────┐
       logs/orchestrator.jsonl          ├─► ui/backend/  (FastAPI)
       logs/day*.jsonl   (call logs)    │           │
       logs/exp*.jsonl   (call logs)  ──┘    HTTP + WebSocket
                                                    │
                                                    ▼
                                            ui/frontend/  (SPA)
                                            ├─ dashboard
                                            └─ chain inspector
```

The apparatus does **not** write a single consolidated call log. The
backend treats `logs/day*.jsonl` + `logs/exp*.jsonl` collectively as
"the call log" and merges them by `request_id` (see §4.2, §5.2).

Three pieces, three directories under `ui/`:

```
ui/
├── sampler/        # daemon, Python, writes ui/logs/telemetry.jsonl
├── backend/        # FastAPI, reads JSONLs, serves HTTP + WS
├── frontend/       # SPA, dashboard + inspector
└── README.md       # how to run the three pieces
```

## 4. Data contracts

### 4.1 `telemetry.jsonl` (NEW — you own this schema)

One JSON object per line. Sample interval: 1 second. Schema committed
to `ui/schema/telemetry.jsonl.schema.json`. The schema is **conditional**:
`gpu`, `host`, and `vllm` are each `object | null` (a source that
fails to read is written as `null`, never omitted, so every line has
the same key set); when an object is present its own sub-fields are
required as noted. Express this with `oneOf` / `if-then` in the JSON
Schema — a flat `required` array cannot capture it. Within `gpu`, the
individual fields are themselves `number | null`: GB10 uses unified
memory, so `nvidia-smi` reports `[N/A]` for `memory.used`/`memory.total`
— those are written `null` while util/temp/power are kept.

Required fields:

| Field | Type | Notes |
|---|---|---|
| `timestamp` | ISO 8601 string | sampler-local clock |
| `gpu` | object `\|` null | null when `nvidia-smi` read fails |
| `gpu.util_pct` | number `\|` null | 0–100 |
| `gpu.mem_used_mb` | number `\|` null | null on GB10 — unified memory, `nvidia-smi` reports `[N/A]` |
| `gpu.mem_total_mb` | number `\|` null | null on GB10 (see above) |
| `gpu.temp_c` | number `\|` null | |
| `gpu.power_w` | number `\|` null | |
| `host` | object `\|` null | null when `psutil` aggregate read fails |
| `host.cpu_pct` | number | aggregate, 0–100 |
| `host.mem_used_mb` | number | |
| `host.cpu_temp_c` | number `\|` null | mean of thermal zones |
| `host.load_avg` | [n, n, n] | 1/5/15 min |
| `vllm` | object `\|` null | from vLLM `/metrics` Prometheus scrape |
| `vllm.running_requests` | number | |
| `vllm.waiting_requests` | number | |
| `vllm.gpu_cache_usage_pct` | number | 0–100 |
| `vllm.gpu_prefix_cache_hit_rate` | number `\|` null | 0–1 |
| `vllm.tokens_per_sec_decode` | number `\|` null | user-visible output tok/s; rate of `vllm:generation_tokens_total` over the interval; see §5.1 for counter-reset handling |
| `vllm.mtp_acceptance_rate` | number `\|` null | 0–1; fraction of drafted tokens accepted. Primary MTP-health signal. Null if the metric is absent (MTP off, or a vLLM build that doesn't export it) |
| `vllm.mtp_draft_tokens` | number `\|` null | drafted tokens over the interval |
| `vllm.mtp_accepted_tokens` | number `\|` null | accepted drafted tokens over the interval |
| `processes` | array of objects | per tracked PID |
| `processes[].pid` | number | |
| `processes[].name` | string | command name, e.g. `vllm-gemma4`, `orchestrator`, `worker-{task_id}` |
| `processes[].cpu_pct` | number | |
| `processes[].rss_mb` | number | |
| `processes[].threads` | number | |
| `read_errors` | object `\|` null | keys are source names (`nvidia-smi`, `vllm-metrics`, `psutil`, `thermal`); values are error strings. Null when no errors. Populated on every line a source is currently failing, not just the first. |

vLLM's speculative-decoding metric names vary across releases — scrape
defensively (§7) and map whatever counters are present onto the three
`mtp_*` fields; leave them `null` if absent.

### 4.2 The call log — `day*.jsonl` + `exp*.jsonl` (READ-ONLY)

There is **no `logs/calls.jsonl`**. The apparatus's wrapper writes call
records into per-day files, all conforming to
`schema/calls.jsonl.schema.json` (committed on day 2 of the apparatus
build). The files that exist by the end of week 1:

- `logs/day2.jsonl` (day 2 — 50-call sweep)
- `logs/day4_e2e.jsonl`, `logs/day4_robust.jsonl` (day 4 — chains begin)
- `logs/day5.jsonl` (day 5)
- `logs/day6.jsonl`, `logs/day6_5seq.jsonl` (day 6 — orchestrated runs)
- `logs/exp001.jsonl` (day 7 — experiment runs)

The backend treats `logs/day*.jsonl` + `logs/exp*.jsonl` as one
logical call log: glob both, parse, index by `request_id`. Do not
hardcode the filenames — glob the patterns so new day/experiment files
are picked up automatically.

Fields the backend uses (read names from
`schema/calls.jsonl.schema.json` at runtime; do not hardcode beyond the
structural ones):

- `request_id` (uuid4) — **structural, stable**
- `parent_request_id` (uuid4 or null) — **structural, stable**; the
  chain pointer (chains start day 4; null before then)
- `caller_tag` — **structural, stable**; disambiguates orchestrator vs.
  worker vs. wrapper
- `timestamp`, `latency_ms`, `usage`, `model`, `model_version`,
  `temperature`, `seed`
- `prompt_messages`, `completion`
- `host_metadata` — contains the CUDA driver and vLLM image tag; the
  exact sub-key names are set by the day-2 schema. Read them from the
  schema; render the object generically if a key is missing.

The four structural fields above are pinned by the day-2 task spec in
`plan.yaml` and are safe to build the chain walker against before the
schema file lands. Everything else is opaque passthrough — the
inspector renders it generically and must not crash on a missing field.

### 4.3 `orchestrator.jsonl` (READ-ONLY — owned by day 6)

Per the worker contract in `schema/worker_contract.schema.json` once
day 6 lands. Fields you will use:

- `task_id`, `task_type`, `status` (started | passed | failed | aborted)
- `parent_request_id` (links the orchestrator dispatch to the worker's
  wrapper calls)
- `worker_pid` (for cross-reference against `telemetry.jsonl`'s
  `processes[]`) — **may be absent**; see §7. The per-process grid
  degrades gracefully if it is.
- timestamps for dispatch and receipt

### 4.4 `exp###.jsonl` (READ-ONLY — owned by day 7)

Per-experiment logs (`logs/exp001.jsonl`, etc.). These double as call
logs (see §4.2) and as experiment logs. The inspector only needs
`task_id` / `parent_request_id` linkage; it does not need to understand
experiment semantics.

## 5. Per-piece spec

### 5.1 Sampler

**Language**: Python 3.11+. **Deps**: `psutil`, `requests`. Nothing else.

**Run loop**: every 1 s,

1. Call `nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits`, parse one line. (The Spark has a single GB10 GPU — one CSV line expected; if multiple lines ever appear, sample index 0 and log it once.)
2. Scrape `http://localhost:8000/metrics` (vLLM's Prometheus endpoint). Parse the line-based format; pull the keys listed in the schema, including the speculative-decoding counters. Compute `tokens_per_sec_decode` from the rate of `vllm:generation_tokens_total` (user-visible output tokens) over the sample interval, tracking the previous value in memory. Compute `mtp_acceptance_rate` from the accepted/draft counters likewise.
3. Read `/sys/class/thermal/thermal_zone*/temp` (millidegrees, divide by 1000).
4. For each PID in the tracked set: `psutil.Process(pid).cpu_percent(interval=None)`, `memory_info().rss`, `num_threads()`, `name()`.
5. Compose one JSON object and append to `ui/logs/telemetry.jsonl`.

**Counter-reset handling**: vLLM restarts reset its Prometheus
counters to zero. When the current counter value is *below* the
previous one, do not emit a negative or huge rate — emit `null` for
that derived field this interval and re-prime from the new value. Tie
this to the same restart detection used for PID discovery.

**Tracked PID discovery**:
- vLLM container: parse `docker inspect vllm-gemma4` once at startup, watch for restart.
- Orchestrator: read `run_state/orchestrator.pid` if the orchestrator writes one; otherwise (the likely case — no such file is specified in `plan.yaml`) scan `psutil` for processes matching `python.*orchestrator`.
- Workers: same scan pattern, match on `python.*worker` or read `worker_pid` from recent orchestrator.jsonl lines.
- ChromaDB: scan for `chroma run`.

Tolerate the absence of any of these — write the `processes` array with
whatever you find.

**CPU-percent priming**: `psutil.cpu_percent(interval=None)` returns
`0.0` on the first call for a process. Prime the readings for all PIDs
known at startup — and also for any PID the first time it appears in
the tracked set mid-run (workers are discovered while running).
Otherwise every worker shows 0 % CPU for its first sample.

**Failure modes**:
- `nvidia-smi` not installed → record `read_errors["nvidia-smi"]`, set `gpu: null` that sample.
- vLLM `/metrics` returns 5xx or connection refused → record `read_errors["vllm-metrics"]`, set `vllm: null`.
- Permission denied on a thermal zone → record `read_errors["thermal"]` on every line the read keeps failing (rule 9), and write `host.cpu_temp_c: null`.
- Tracked PID died → drop from `processes[]`, don't crash.

**Operational**:
- Run as a systemd-style daemon. Provide `ui/sampler/run.sh` that just `exec`s the Python module. Restart-on-failure is the user's concern (systemd, supervisor, or a `while true` loop).
- Log rotation: at 1 Hz a line with the full schema and a `processes` array of 4–8 entries is ~700–1000 bytes, so `ui/logs/telemetry.jsonl` grows ~50–90 MB/day — an order of magnitude more than a casual estimate suggests. Append-only is acceptable for week 2, but add size-based rotation (e.g. roll at 200 MB) before any long unattended run, and the backend must read this file incrementally (§5.2), never slurp it whole.

**Validation** (you produce these):
- `ui/sampler/tests/test_schema.py`: run the sampler for 5 s in a thread, read back the file, assert every line validates against `ui/schema/telemetry.jsonl.schema.json`.
- `ui/sampler/tests/test_missing_sources.py`: with `nvidia-smi` not on PATH and vLLM not reachable, assert the sampler still produces valid lines with `gpu: null`, `vllm: null`, and `read_errors` populated on every line.

### 5.2 Backend

**Language**: Python 3.11+. **Deps**: `fastapi`, `uvicorn`, `pydantic`. Nothing else for v1 runtime.

**Endpoints**:

- `GET /api/health` → `{ ok: true, telemetry_last_seen: <iso>, version: <git sha> }`
- `GET /api/chain/{task_id}` → resolves a task_id into a full causal chain by walking `parent_request_id` across `orchestrator.jsonl` and the call log (the `logs/day*.jsonl` + `logs/exp*.jsonl` glob, §4.2). Returns a tree; node shape documented inline in the OpenAPI schema FastAPI auto-generates.
- `GET /api/recent_tasks?limit=50` → last N orchestrator dispatches with status, latency, task_type.
- `GET /api/state` → contents of `run_state/week1.state.json` (read-only passthrough). Consumed by the dashboard header (apparatus day / current task); if the header ends up not using it, drop the endpoint rather than leave it unconsumed.
- `WS /api/live` → streams new lines from `telemetry.jsonl` and `orchestrator.jsonl` as they're appended. **One message per new line** (a single poll may discover several appended lines — emit one message each, in file order). Message shape: `{ source: "telemetry"|"orchestrator", line: <parsed object> }`. Use file tailing — watch mtime + read from last known byte offset — at a poll interval ≤ 1 s so telemetry is not lagged. No inotify dependency.

**Reading strategy**: all JSONL inputs are append-only and actively
written. Do **not** cache "the parsed file" and re-read the whole file
on every mtime change — during a run the mtime changes constantly and
that defeats the cache. Keep a per-file `(byte_offset, parsed_lines)`
and on each request read only the bytes appended since the last
offset, then append-parse. `tailer.py` is the shared abstraction for
this; both `/api/chain` and `/api/live` use it.

**Latency targets**: `/api/chain/{task_id}` under 200 ms for a task with up to 1000 wrapper calls in its chain (achievable with incremental reads + an in-memory `request_id` index). The dashboard's first paint under 500 ms.

**Cycle safety**: `parent_request_id` chains should be acyclic, but a re-run that reuses an id could create a cycle. Walk with a `seen` set; on a detected cycle, mark the chain `malformed` in the response and stop recursing.

**Validation**:
- `ui/backend/tests/test_chain_walk.py`: synthetic JSONL fixtures with known chains (spanning multiple `day*.jsonl` files plus `orchestrator.jsonl`), assert reconstruction is exact.
- `ui/backend/tests/test_live_stream.py`: write to a fake telemetry file, assert WebSocket emits the new lines in order, one message per line.
- `ui/backend/tests/test_schema_drift.py`: when `schema/calls.jsonl.schema.json` adds a new optional field, the chain walker still works (forward-compatible parsing).

### 5.3 Frontend

**Stack**: React (Vite), TypeScript, Tailwind. No state library (`useState` + `useReducer` are enough). One chart library — `recharts` is the path of least resistance. **No `localStorage`**.

**Routes**:
- `/` — dashboard
- `/chain/:taskId` — inspector for one task

**Dashboard layout** (top to bottom, ~1280 px target width):

1. **Header**: Spark hostname, vLLM image tag (from telemetry / `host_metadata`), uptime, apparatus current day + task (from `/api/state`), last telemetry timestamp (red if > 5 s old).
2. **Top strip** (5 tiles): GPU util %, GPU mem (used/total), GPU temp, GPU power, host CPU temp. Each tile shows current value + 5-min sparkline. Color-coded against baselines:
   - GPU temp: green ≤ 70 °C, amber 70–80, red > 80
   - GPU power: green ≤ 90 W under load, amber 90–110, red > 110. Idle baseline is data-driven (see baseline card) — measured day-1 idle was ~5 W; treat anything under the load threshold while no requests run as green.
   - Host CPU temp: green ≤ 75 °C, amber 75–85, red > 85
   - GPU util: green ≥ 50 % under load, gray when no requests running
3. **Left panel — orchestrator queue**:
   - "Running" section: each currently-running worker as a row (task_id, task_type, age, worker_pid). Clicking a row opens `/chain/:taskId` in a side drawer.
   - "Waiting" section: queue depth + next 5 tasks.
   - "Recent" section: last 20 completed/failed tasks.
4. **Right panel — vLLM internals**:
   - Running requests / waiting requests (with sparklines)
   - KV-cache usage % (sparkline + current; red if > 85)
   - Prefix-cache hit rate
   - **MTP speculative decoding**: acceptance rate (sparkline + current). This is the primary signal for whether MTP is working — if it falls, decode tok/s collapses. Show gray ("MTP off / metric absent") when `mtp_acceptance_rate` is null; otherwise color against the baseline card's expected range.
   - Current decode tok/s (sparkline; reference line at the day-1 hard floor of 40, and a band marker for the expected `[80, 130]`).
5. **Bottom — per-process grid**: one card per tracked PID. Shows process name, PID, CPU %, RSS, threads, tiny CPU sparkline. Cards sort by RSS desc.

**Inspector layout**:
- Header: task_id, task_type, status, total latency (the **sum** of all wrapper-call `latency_ms` in the chain — meaningful because day-6 workers run sequentially; label it as a sum, not wall-clock).
- Tree (collapsible nodes): orchestrator dispatch at root → worker invocation → wrapper calls → tool calls. Tool calls render as tree nodes whether they were logged as separate call-log lines or embedded in a wrapper record's `tool_calls` array — the backend synthesizes embedded ones into `kind="tool"`, `embedded=true` nodes (§0 r4). Embedded tool nodes carry an `embedded` badge and are excluded from the raw-JSONL dump (they are not their own log lines). Parse failures and retries get a distinct visual treatment (a small badge, not a color flash). A chain flagged `malformed` by the backend (cycle) renders with a clear banner.
- Each node expandable to show: timestamp, latency_ms, request_id, parent_request_id. For wrapper-call nodes, also: model, temperature, seed, full `prompt_messages`, full `completion`, `usage`. Render these fields generically — iterate the object, do not hardcode a field list — so a schema addition does not break the view.
- A "raw JSONL" toggle dumps the underlying log lines for engineers who want to grep.

**Healthy-baseline reference card** (sticky on dashboard): the day-1
numbers, so the user can eyeball current vs. expected. **Data-driven**:
read from `bench/day1.csv` and `run_state/week1.state.json`'s
`metric_log` once those exist; fall back to documented constants only
until then. Documented constants (from `plan.yaml`, r2):
decode tok/s expected band `[80, 130]`, expected single-stream ~96,
NVFP4-without-MTP ~52, hard floor 40, MTP-engaged signal ≥ 50;
idle power ~5 W measured (≤ 35 W is the apparatus's pass threshold);
CUDA 13.0; MARLIN MoE backend; MTP via the Gemma 4 assistant drafter,
`num_speculative_tokens=4`.

**Validation**:
- Snapshot tests on the dashboard and inspector with fixture data.
- `ui/frontend/tests/test_chain_tree.tsx`: a synthetic chain renders the right number of nodes at each depth.
- Manual smoke: run sampler + backend, open browser, confirm live updates arrive without page refresh.

## 6. Build order

Each step is independently useful — stop after any one and you have
something usable. The steps are also ordered by apparatus dependency:
6.1 needs nothing from the apparatus; 6.2 onward needs the call-log
schema and orchestrator log (build against fixtures until they land —
see §10).

| Step | Deliverable | Estimated Block 2's |
|---|---|---|
| 6.1 | Sampler daemon writing `telemetry.jsonl`. Tests pass. No UI yet. | 1 |
| 6.2 | Backend `GET /api/chain/{task_id}` + `GET /api/recent_tasks`. Tests pass. CLI users can `curl` it. | 1 |
| 6.3 | Frontend inspector view at `/chain/:taskId`. Backend HTTP only. | 1 |
| 6.4 | Backend WebSocket `/api/live`. Tail-based, no inotify. | 0.5 |
| 6.5 | Frontend dashboard view at `/`. All five zones. | 1.5 |
| 6.6 | Click-through from dashboard to inspector. | 0.25 |
| 6.7 | Healthy-baseline reference card + color-coded thresholds. | 0.25 |

Total: ~5.5 Block 2's, roughly week 2 with slack. Step 6.1 has zero
apparatus dependency — build it for real, now. Steps 6.2–6.4 depend on
the day-2 call-log schema and the day-6 orchestrator log; build them
against fixture JSONL in `ui/backend/tests/fixtures/` and swap to real
logs when they exist. Step 6.5's dashboard can be developed against
*real* telemetry from your own sampler as soon as 6.1 is running.

## 7. Things that will probably trip you up

- **vLLM `/metrics` field names change between releases**, and the MTP / speculative-decoding counters especially. Don't hardcode; scrape, log unknown fields once, map known counters onto the schema's `mtp_*` fields, and let the schema treat unknowns as additive.
- **vLLM restarts reset Prometheus counters.** Any rate you derive (`tokens_per_sec_decode`, `mtp_acceptance_rate`) must detect a counter going backwards and emit `null` + re-prime (§5.1).
- **`psutil.cpu_percent(interval=None)` returns 0.0 on first call per process.** Prime at startup *and* on first sight of each new PID (§5.1).
- **`nvidia-smi` adds whitespace.** Use `--format=csv,noheader,nounits` and `.strip()` every field.
- **`parent_request_id` chains can have cycles in pathological log data** (a re-run reusing an id). Walk with a `seen` set; mark the chain malformed and stop.
- **The orchestrator may not write `worker_pid`.** `plan.yaml` does not specify it. Check the day-6 `worker_contract` schema before relying on it. If absent, the per-process grid simply won't link to specific workers; that's fine.
- **There is no `run_state/orchestrator.pid`** specified in `plan.yaml`. The psutil name-scan is the real discovery path, not a fallback.
- **Time skew** — sampler and orchestrator both write ISO timestamps from local clocks on the same box, so ordering is fine on the Spark. If you ever run the sampler on a different host, add a `monotonic_ns` field and document it.
- **The week 1 plan adds JSONL fields over time.** Treat the schemas in `schema/` as the source of truth at request time, not at frontend build time. Render call-log fields generically; never crash on an unknown field.

## 8. Handoff checklist (when each piece is "done")

A piece is done when:

1. It runs (sampler: daemon stays up for an hour without crashing; backend: `curl /api/health` returns ok; frontend: `npm run build` produces a deployable bundle).
2. Tests pass under `pytest ui/sampler/tests`, `pytest ui/backend/tests`, `npm test` in `ui/frontend/`.
3. A `ui/<piece>/README.md` exists with the one-liner to run it locally.
4. A short note appended to `ui/notes/ui-build.md` describing what was built, any surprises, and any data-contract questions to surface to the human.

## 9. Open questions to surface (don't guess)

If any of these come up while you're building, write the question to
`ui/notes/ui-build.md` and continue with a reasonable default. Don't block.

- ~~Whether tool calls are logged as their own call-log lines (with their own `request_id`) or embedded inside a wrapper call's record.~~ **Resolved (r4, extended r7).** *Three* shapes are now supported and converge to one inspector tree: (1) separate call-log lines; (2) an embedded `tool_calls` array; (3) — the shape Track A's real day-4 logs actually use — an OpenAI-style tool call serialized as a JSON string in the wrapper record's `completion` field. The chain walker synthesizes shapes 2 and 3 into `kind="tool"` child nodes so the inspector tree is shape-agnostic; all three have test coverage. See §0 r4 and r7.
- Whether to expose experiment-level views (cooperation rates, per-round behavior) in v1 or defer to a v2 results-browser plan. **Direction (r4):** deferred to v2; a one-page sketch of the v2 results browser and its data contracts is drafted at `ui/ui_plan_v2.md`. Not built in v1.
- ~~Whether the inspector should let users diff two chains side-by-side (powerful, but doubles the layout work).~~ **Resolved (r4): deferred to v2.** It would roughly double the inspector layout work for marginal value — the week-1 CLI already gives a textual chain diff via `diff <(tools/inspect_run.py --task-id X) <(tools/inspect_run.py --task-id Y)`. See §0 r4.
- ~~The "healthy baseline" card should be data-driven (read from `bench/day1.csv` and `run_state/week1.state.json`'s `metric_log`).~~ **Resolved (r4): implemented.** `GET /api/baseline` sources decode tok/s from `bench/day1.csv` + `metric_log` and falls back to the §5.3 documented constants per-row; each row is annotated measured vs documented. See §0 r4. Idle power and the threshold rows stay documented — no committed measurement source exists for them yet; revisit if one lands.
- ~~Whether the WebSocket should backfill the last N seconds of telemetry on connect, or only stream forward.~~ **Resolved (steps 6.4-6.5):** the WebSocket is forward-only; the dashboard seeds 5 minutes of sparkline history from `GET /api/telemetry/recent` on load instead.

## 10. Mocking vs. waiting (build sequencing)

The three pieces have very different dependency profiles. Do not wait
on the apparatus wholesale.

- **Sampler (6.1) — no mocks, build now.** It depends on nothing the apparatus produces. It reads real hardware (`nvidia-smi`, `psutil`, thermal) — all present on the Spark since day-1 firmware passed — and it tolerates the vLLM endpoint being down by writing `vllm: null`. Its own tests exercise the missing-source path. Building it now also yields real `telemetry.jsonl` to develop the dashboard against.
- **Dashboard (6.5) — develop against real telemetry, not mocks.** Once 6.1 runs, the dashboard's GPU/CPU/thermal/process zones have real data. Only the vLLM panel waits — and only until `day1_block2_vllm_serve` (the apparatus's very next task) brings `/metrics` up.
- **Backend chain walker + inspector (6.2, 6.3) — mock narrowly.** These need the day-2 call-log schema and the day-6 orchestrator log, none of which exist yet. Mock fixture JSONL in `ui/backend/tests/fixtures/`, but only commit to the **structural** fields that `plan.yaml` already pins: `request_id`, `parent_request_id`, `caller_tag`, `task_id`, `status`, timestamps. Treat `prompt_messages` / `completion` / `usage` / `host_metadata` as opaque blobs rendered generically. Then the real day-2/day-6 schemas landing is a fixture swap, not a rewrite.
- **What to *not* mock (wait, or stay generic):** the exact `calls.jsonl` field set, `host_metadata` sub-key names, and whether tool calls are separate lines or embedded (§9). Guessing these creates rework. The mitigation is generic rendering, not a guessed schema.

Recommended sequence given the apparatus is at day 1: build 6.1 now;
build 6.5's non-vLLM zones against real telemetry; build 6.2/6.3
against narrow fixtures in parallel. By the time 6.2 is integration-ready
the apparatus will likely have passed day 2 (call-log schema) — re-check
`schema/` before swapping fixtures for real logs.

---

## 11. Observability gates agent autonomy

> Added in the 2026-05-23 documentation restructure. The UI's
> deliverables are now load-bearing for the agent autonomy framework:
> tier-shift unlocks in [`agent/autonomy.md`](agent/autonomy.md) §3
> are gated on UI milestones.

### 11.1 Why the UI gates autonomy

The user's stated trajectory is: start at a tiered + phase-aware
autonomy posture; expand toward trust-by-default as the UI proves it
can show the human what the system is doing. The UI is therefore not
just an observability layer — it is the **mechanism by which the
human attests alignment evidence** (see
[`agent/autonomy.md`](agent/autonomy.md) §4). Without the UI showing
the right state at the right time, the alignment-evidence check
cannot be made, and tier shifts stay locked.

### 11.2 UI milestones → autonomy unlocks

| UI milestone | Unlocks |
|---|---|
| **UI v1** — sampler + dashboard live (target Day 38; Track D) | Week-2 unlock eligible. The dashboard must render run-log integrity, recent task statuses, and pending soft-gate attestations. |
| **UI v2** — call-chain inspector live (target Day 50) | Weeks-3-4 unlock eligible. The inspector must reconstruct causal chains from `orchestrator.jsonl` + `calls.jsonl` and surface them per-task. |
| **UI v2.5** — alignment evidence dashboard (target Week 4) | Allows the weekly retrospective to be drafted *inside* the UI rather than from raw logs. |
| **UI shows consistent alignment for 4+ consecutive weeks** | Phase 2 entry eligible (Day ~91). |

A UI milestone is "live" when the human can run it on real Track A
artifacts (not just fixtures) and the relevant gate-attestation flow
works end-to-end.

### 11.3 What the UI must render to support each unlock

**Week-2 unlock prerequisites (rendered by UI v1):**
- Run-log integrity: `verify_log_integrity` result for the rolling
  week, plus any malformed-line locations.
- Soft-gate attestation queue: pending requests in
  `run_state/attestations.jsonl`, with rollback action available.
- Hard-gate pending list: entries from `state.human_gates_pending`,
  with attestation action available.
- Today's metric_log values vs prior runs (for the metric-drift
  alignment check).
- Sidebar: `state.fallbacks_taken`.

**Weeks-3-4 unlock prerequisites (rendered by UI v2):**
- Causal chain inspector: pick a `task_id`, see the full chain
  (orchestrator → worker → wrapper → vLLM call) with timestamps and
  durations.
- Tier-shift inventory: which tasks have shifted since the last
  retrospective, with the tier-shift event from the run log.
- Claim/lock log render: `run_state/claims.jsonl` showing active
  claims, expiries, and any overlaps.

**Phase 2 entry prerequisites:**
- Hypothesis generation timeline: every hypothesis the loop produced,
  the critic's verdict, the meta-review novelty score, the experiment
  outcome (if executed).
- Per-week alignment score (from the four-bullet check in
  `agent/autonomy.md` §4), four weeks back, with delta trend.

### 11.4 What Track D commits trigger

Each UI milestone landing in `ui/` and `ui_plan.md` triggers Track A
to:

1. Verify the UI renders Week-N alignment evidence correctly (a
   human-in-the-loop check; not automated).
2. Update `agent/autonomy.md` §3 trigger column to mark the UI
   milestone "achieved" if confirmed.
3. Append a `ui_milestone` event to `run_state/week1.run.jsonl` with
   the milestone ID, UI commit hash, and Track-A confirmation
   timestamp.

The weekly retrospective at the next milestone boundary may then
trigger the actual tier-shift application (per
[`agent/autonomy.md`](agent/autonomy.md) §4.2).

### 11.5 Implication for Track D sequencing

Track D's deliverables are now precondition for Track A's tier-shift
unlocks. Falling behind on UI work delays the autonomy expansion —
this is by design; the user is explicitly trading "raw speed of
agentic build-out" against "demonstrated alignment in the UI." If
Track D slips, Track A stays at the more-conservative tier
classification.

The `PHASE_1_ROADMAP.md` Week-2 schedule reflects this: Day 38 is
"UI v1 deployment + Week-2 unlock attestation"; without UI v1, the
unlock attestation cannot be made.

---

## Appendix — file layout you should produce

```
ui/
├── README.md
├── requirements-ui.txt          # psutil, requests, fastapi, uvicorn, pydantic (+ dev: pytest, jsonschema, ws test client)
├── conftest.py                  # puts ui/ on sys.path for pytest
├── .gitignore
├── schema/
│   └── telemetry.jsonl.schema.json   # sampler schema — created by you
├── logs/                        # sampler output, ui/logs/telemetry.jsonl (gitignored)
├── sampler/
│   ├── __init__.py
│   ├── sampler.py
│   ├── sources/
│   │   ├── nvidia_smi.py
│   │   ├── vllm_metrics.py
│   │   ├── psutil_procs.py
│   │   └── thermal.py
│   ├── run.sh
│   ├── README.md
│   └── tests/
│       ├── test_schema.py
│       └── test_missing_sources.py
├── backend/
│   ├── __init__.py
│   ├── app.py            # FastAPI app
│   ├── chain.py          # parent_request_id walker
│   ├── tailer.py         # incremental offset-based file reader
│   ├── README.md
│   └── tests/
│       ├── fixtures/
│       ├── test_chain_walk.py
│       ├── test_live_stream.py
│       └── test_schema_drift.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    ├── src/
    │   ├── App.tsx
    │   ├── routes/
    │   │   ├── Dashboard.tsx
    │   │   └── Inspector.tsx
    │   ├── components/
    │   │   ├── HealthStrip.tsx
    │   │   ├── OrchestratorQueue.tsx
    │   │   ├── VllmPanel.tsx
    │   │   ├── ProcessGrid.tsx
    │   │   ├── ChainTree.tsx
    │   │   └── Sparkline.tsx
    │   ├── api/
    │   │   ├── http.ts
    │   │   └── ws.ts
    │   └── types/
    │       └── schemas.ts  # mirrors schema/*.json
    └── tests/
        └── test_chain_tree.tsx
```

Nothing outside `ui/` is created — the telemetry schema and output live
at `ui/schema/` and `ui/logs/` (r3).

## §2026-08-15 S4 — the Lab Channel surface + tailer first-attach fix (`ui/` only)

Plan: `docs/ui_simplification_plan_2026-08-15.md` §S4 (owner-added mid-loop).
Built by a worktree-isolated build agent (spawn `loop10h-ui-s4-channel`) on top
of merged S1+S2+S3 (`2bca9bc`); primary gates + merges. The primary's half —
the blessed `orchestrator/lab_channel.py` CLI (`timeline` / `turn` /
`delegate`, transcript `memory/lab_channel.jsonl`) — had already landed; this
slice is the UI half plus one operational bugfix.

### Backend — `ui/backend/lab_channel_seam.py` (NEW, + test suite)

Chat-seam idiom throughout: argv-array exec of the ONE blessed CLI
(`orchestrator.lab_channel`), cwd = primary repo root, interpreter
`.venv-chroma/bin/python`, runner-injectable, NO shell, NO env manipulation
(the server's `env -u MOCK_LLM` semantics ride in), rc!=0 → 502 `{rc, stderr}`
with stderr VERBATIM, seam writes nothing (structural grep pinned).

- `GET /api/channel/available` — capability handshake (attest idiom:
  existence-check CLI module + interpreter; never execs).
- `GET /api/channel/timeline?since=&limit=` — execs `timeline` under a SHORT
  30s cap (pure read); parses the printed `"<ts>  [<kind>]  <message>"` lines
  back to `{rows:[{ts,kind,message}]}` — a multi-line message (model reply)
  is reattached as a continuation of its row, never dropped mid-row. `since`
  is argv-hygiene-validated (digit-leading ISO charset — can never parse as a
  flag); `limit` bounded [1,1000].
- `POST /api/channel/turn` `{role: nara|pi, message}` — capability-gated:
  probe fails → an honest PREVIEW (`{status:"preview", would_run}`) that
  execs/writes NOTHING; live → execs `turn` under the chat seam's 300s cap
  and returns `{status, role, reply}` (reply = CLI stdout verbatim).
- `POST /api/channel/delegate` `{kind: research|improvement, text,
  cluster_id?, objective?}` — the human-click hand-off; same capability
  preview; live → execs `delegate` under the fast 120s write cap via
  `attest._exec_blessed` and returns the CLI's stdout JSON verbatim (the
  written rows + transcript mirror). `cluster_id` id-charset-validated
  (no leading dash); blank `objective` is 422, never silently dropped.
- FENCE pinned in `backend/tests/test_lab_channel_seam.py` (51 cases): the
  router surface is exactly {available, timeline, turn, delegate} — every
  disposition-verb probe 404s; extra payload keys (verdict/set_status/--by)
  are never forwarded into argv; 422 validation always precedes any spawn.
- Registered in `app.py` after the cockpit seams.

### Frontend — `routes/Channel.tsx` + `api/channel.ts` (NEW, + suite)

- Nav: `pulse · ladder · dossiers · channel · engine ▾` — `/channel` sits
  between dossiers and engine per the work order.
- ONE feed merging the stored turns with the CLI's read-time-derived events:
  voice bubbles in ChatPane's visual language (rounded bordered rows,
  uppercase voice labels; human zinc / nara emerald / pi indigo,
  prototype-safe own-key chrome lookup) and event system-lines with kind
  chips — cycle / kill / promotion / alert (+ quiet ladder/event fallbacks) —
  keyed off the events' stable message prefixes. Poll ~10s with an inclusive
  `since` cursor + full-identity dedupe; first load bounded (limit 400).
- Turn composer: role selector (ask nara · operations / ask pi · research)
  with the ONE-MODEL HONESTY note rendered beside it (both voices are the
  same local Gemma — never independent confirmation; the independent Qwen
  skeptic lives in the dossier reader's two-voice chat). Send gated on the
  `/api/channel/available` probe (capability-off banner, disabled send —
  ChatPane's availability idiom); a turn success triggers an immediate feed
  refresh; a failure renders the CLI stderr verbatim.
- Delegate composer: kind selector (research/improvement) + text
  (+ optional cluster-id / objective) → "review delegation…" renders a
  CONFIRM CARD naming exactly what will be written where (research:
  agenda_item_added → memory/idea_ledger.jsonl on the named cluster or
  cl-human-delegations auto-created, + the DELEGATED mirror row;
  improvement: one authorize_fix packet row → memory/authorize_fix_queue.jsonl
  + the mirror row). **The confirm click is the ONLY path that posts**; any
  edit invalidates a pending card; cancel posts nothing.
- Empty state; version-skew 404 on `/api/channel/timeline` →
  EndpointMissingNote (both channel GETs added to SKEW_404_ENDPOINTS);
  non-404 failures stay honestly red.
- `tests/test_channel.tsx` (16 cases) pins: feed render incl. all four event
  chips, honesty note, turn post threading the selected role, capability-off
  (send disabled + nothing posted), the confirm-card flow (review does NOT
  post; confirm posts exactly once with the threaded payload; cancel/edit
  post nothing), stderr-verbatim errors, skew, and the FENCE (no
  verdict/disposition testid or button verb anywhere on the page).
- DEVIATION (declared): the work order said "extract shared bits [of
  ChatPane] rather than duplicating if clean" — not clean: ChatPane is
  session-local, stance/addressee-parameterized and pin-laden; the channel
  feed is a transcript-with-events. Extracting a shared bubble primitive
  would have been abstraction for two call sites with different shapes
  (inviolate rule 8). The visual language is matched by idiom instead;
  ChatPane and its pins are untouched.

### Tailer fix — first attach seeks to EOF (`ui/backend/tailer.py`)

The 2026-08-15 operational hang: a backend restart re-parsed the whole
6.5GB telemetry file inside `/api/health` (offset started at 0). Now
`JsonlTailer.read_new` ATTACHES on first call — offset = current file size,
first read returns `[]` — so history is never replayed; only lines appended
after attach are parsed. `replay=True` opts back into the legacy
from-byte-0 first read.

Consumer sweep (the semantic change is history-not-replayed):

- `app.py /api/health` telemetry tailer — the bug site; now forward-only.
  `telemetry_last_seen` is null after a restart until the next sample lands
  (seconds) — pinned honestly in test_api::test_health.
- `app.py /api/live` websocket — already called `seek_to_end()` explicitly;
  unchanged behavior.
- **`chain.py LogStore` RELIED on replay** — its in-memory indexes ARE the
  file history (the /chain/req/:id inspector would have gone blind to all
  pre-restart records). It now constructs `JsonlTailer(path, replay=True)`
  (bounded day*/exp*/orchestrator logs, not the giant tails), with the
  reliance documented at the construction site. No other consumer exists.
- Regression pinned in test_tailer: 10k-line pre-existing file → first
  read [], appended line → returned; plus attach-on-missing-file, the
  replay opt-in contract, and reset()/seek_to_end() semantics.

### Verification (this worktree)

- frontend vitest **932 pass** (66 files; 916 + the new channel suite) ·
  `tsc --noEmit` clean
- ui-backend pytest **661 pass** (`.venv-chroma`, `MOCK_LLM=1`; 605 + the
  seam suite + tailer regressions)
- The real `:8700` smoke (nav to /channel against live data; a real
  `env -u MOCK_LLM` turn; timeline showing the live transcript + events;
  one delegate round-trip) is the PRIMARY's post-merge step. NOTE: the
  running binary predates `/api/channel/*` — until restart the page shows
  the EndpointMissingNote skew state by design.

## §2026-08-15 loop3h-ui-hotfix — Channel encoding + chat layout + brain link

Three owner-reported hotfixes (worktree `agent-a78c433484cba7252`; the full
channel revamp comes separately — these are surgical).

### 1. `routes/Channel.tsx` encoding corruption (git saw binary)

Root cause: `rowKey()`'s dedupe separator was written as TWO RAW NUL BYTES
inside a template literal — valid JS, but git treats any NUL-bearing file as
binary (`file` said "data"; diffs showed `Bin`). Rewritten as clean UTF-8
with escaped `\u0000` sequences; behavior identical. `file` now says
"JavaScript source, UTF-8 text" and `git diff --no-index /dev/null` renders
it as text (+852). NOTE: the one transition diff old→binary-blob → new-text
still prints `Bin` because the PRE-image contains NULs — every diff after
this commit is a normal text diff.

### 2. Wall-of-text feed → chat layout (same rewrite)

- First load = NEWEST 40 rows only (the CLI's `--limit` keeps the newest N;
  was 400 oldest-first filling the viewport past the composer).
- Viewport-bounded flex column: the feed scrolls in its own
  `overflow-y-auto` container, newest at the BOTTOM, auto-scroll pinned to
  the bottom while the reader is there; the composer dock is always visible
  below the feed.
- "load older" button at the feed top widens the full-fetch window
  (+40 per click, capped at the seam's `_MAX_LIMIT` 1000) and prepends —
  dedupe absorbs the newest-N overlap; shown only while a full window
  suggests older rows exist.
- nara/pi bubble bodies render through `MiniMarkdown` (real replies are
  markdown; they rendered raw). Human turns stay verbatim pre-wrap.
- Event walls: runs of >=3 consecutive same-chip events collapse into one
  line ("6 cluster kills — expand"); expanding is per-run and sticky.
- The delegate composer is now a `<details>` disclosure in the dock
  (everything inside unchanged; the confirm card remains the ONLY posting
  path — the fence pins all still pass).

### 3. Brain nav link was a dead tab

`App.tsx` linked `:5174/dashboard.html` — nothing listens on 5174. The
framework `brain_server.py` serves the real "brain · governance" dashboard
at `:5180/dashboard.html` (bound 0.0.0.0, verified serving HTML
2026-08-15). Link repointed to `:5180`, same hostname-derived pattern.

### Test/verification (this worktree)

- `test_channel.tsx`: 24 pass — every original fence/composer/skew pin kept
  + 8 new pins (newest-40 first load, chronological newest-at-bottom,
  overflow-container + docked composer, load-older widen/prepend/hide,
  fixture mode hides load-older, MiniMarkdown for nara/pi + raw human,
  wall collapse/expand, under-threshold runs stay individual).
- frontend vitest **940 pass** (66 files) · `tsc --noEmit` clean.
- ui-backend pytest **661 pass** (`MOCK_LLM=1`). One PRE-EXISTING red
  repaired en route (fails identically on main): the June-era
  `test_live_cycle_provenance_snapshot` pin `all(topic_source ==
  "arxiv_pick")` rotted when D-060 agenda-first went live (real cycles now
  carry `topic_source="agenda"`); the invariant is now membership in the
  coordinator's suggestion-source enum — flagged for the primary's review,
  not silently coerced.
