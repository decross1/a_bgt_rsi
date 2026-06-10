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
`/home/decross1/.claude/plans/idempotent-spinning-sonnet.md`.

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
(`.claude/plans/i-want-to-start-concurrent-flurry.md`): the human names N
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
[`docs/ui_session_handoff_2026-06-09.md`](docs/ui_session_handoff_2026-06-09.md)
and [`docs/ui_autonomy_observability_plan.md`](docs/ui_autonomy_observability_plan.md).
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
[`docs/ui_session_handoff_2026-06-10.md`](docs/ui_session_handoff_2026-06-10.md)).
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
