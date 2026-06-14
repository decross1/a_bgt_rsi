> Imported from ~/.claude/plans/i-want-to-start-concurrent-flurry.md on 2026-06-14; scratch original; reference-only.

# /activity — "active-now hero" rework

## Context

`/activity` is supposed to answer **"which agents are active right now and what
are they doing?"** Today it does the opposite: the historical react-flow graph
takes 75% of the width regardless of whether anything is running, the live
"Active now" worker table is a cramped sidebar, and the synthetic inference
block sits co-equal with real data. When idle it still leads with a big history
graph. This rework (the deferred item from the 2026-06-05 cross-page proposal)
**inverts the hierarchy**: live agents become the hero, the history graph drops
to a secondary on-demand surface, and the synthetic block is subordinated.

Decisive finding from exploration: the hero can be **real, not mock**. The
orchestrator records already carry a human-readable `detail` ("spawning worker
process for 2605.21448 (timeout 60s)", "worker returned summary (747 chars)")
and per-stage `timestamp`s — both currently dropped by the monitor's
`enrich()`. Surfacing them gives "what each worker is doing" + live elapsed with
**no new data source**. The richest "what" signal — Nara's current loop step,
narration, and per-tool durations — already exists at `/api/loop_v0/active` and
is rendered by `ActiveIterationPanel`. Hero scope (confirmed): **both** the
active LOOP_V0 iteration and in-flight orchestrator workers.

## Design

New `/activity` top-to-bottom:
1. **Status strip** (refined) — "N active now" vs "Idle".
2. **HERO — Active now** (full width):
   - **Active iteration** — mount the full `ActiveIterationPanel` (Nara's
     current step strip + narration + live per-tool durations). Self-polls
     `/api/loop_v0/active`; renders its own idle/204 state.
   - **Active workers** — in-flight orchestrator tasks as rich rows: task +
     `task_type` + `status` + **`detail`** ("what it's doing") + **live
     elapsed** (now − row timestamp) + cpu/rss.
   - **Idle empty-state** — when no active iteration AND no active workers:
     a clear "No agents active — last activity {elapsed} ago" hero, not a graph.
3. **Synthetic inference internals** — subordinated behind a `<details>`
   disclosure, keeping the amber `synthetic — needs worker_activity.jsonl`
   marker (rule 4/8: never presented as measured).
4. **Recent history** (secondary) — the existing `ActivityGraph` + overview/full
   toggle, relabeled "recent history", inside a collapsible `<details>` below
   the hero (not the default focal element).

## Changes

### Backend — `ui/backend/activity.py`
- In `enrich()` (the `/api/activity/monitor` row builder) add two fields already
  present in `recent_tasks()` output: `"stage": task.get("stage")` and
  `"detail": task.get("detail")`. Pure passthrough of real orchestrator data.
- Add `last_activity_at` to the monitor response = max `timestamp` across
  `recent_tasks` (drives the idle "last activity … ago"). `{available:false}`
  degrade path unchanged; `SYNTHETIC_INFERENCE` block unchanged.
- Extend `ui/backend/tests/test_activity.py`: monitor rows carry `detail`/`stage`;
  `last_activity_at` present; idle (no active) path.

### Frontend
- **Shared time util (dedupe):** extract `useNow` + `elapsed` (+ `toolDuration`)
  into a new `ui/frontend/src/time.ts`; import from `ActiveIterationPanel.tsx`,
  `Dashboard.tsx` (both currently define `useNow` verbatim), and the new active-
  workers component. Reuse, don't re-implement.
- **Split `AgentMonitorPanel.tsx`** into:
  - `ActiveWorkersPanel.tsx` — the hero worker table (rich rows above; reuse
    `statusTone`, `fmt`, and `elapsed` from `time.ts`).
  - `SyntheticInferencePanel.tsx` — the synthetic block, marker preserved, now
    a subordinate disclosure.
- **`Activity.tsx`** — invert the layout per Design above. Keep the existing
  poll discipline (monitor 1 Hz, graph 5 s, graph change-detection) and the
  overview/full graph toggle (now inside the "recent history" disclosure). Mount
  `ActiveIterationPanel` in the hero (it self-polls). Compute idle from
  `monitor.active.length === 0` && active-iteration 204.
- **`ActivityGraph.tsx`** — unchanged logic; just relabeled/wrapped as secondary.
- **Types** `ui/frontend/src/types/activity.ts`: `MonitorWorker += detail?,
  stage?`; `MonitorResponse += last_activity_at?`.
- **Fixtures** `ui/frontend/src/fixtures/activity/index.ts`: add
  `detail`/`stage`/`timestamp` to active workers; add an idle fixture; reuse the
  `loop_v0` `ACTIVE_FIXTURE` for the hero iteration in tests.
- **Tests**: `test_activity_monitor.tsx` (rich rows + live elapsed + synthetic
  now subordinate), a new active-workers + idle-empty-state test, and confirm
  the history graph renders inside the disclosure. `ActiveIterationPanel` tests
  are unaffected (reused as-is).

### Additional — mirror `QwenPanel` to the new `VllmPanel` layout
Batch 3 restructured `VllmPanel` (Gemma) into **always-visible core health**
(decode tok/s + KV-cache, with sparklines) plus **operator internals**
(running/waiting requests, prefix-cache, MTP acceptance) behind a
`<details data-testid="vllm-details">` "show internals" disclosure, with a
`● up/down` status badge in the header. `QwenPanel` still renders every row flat
and has no status badge. Mirror the structure onto `QwenPanel.tsx`:
- Add a header `● up/down` status badge (`data-testid="qwen-status"`).
- Split into core health (Decode tok/s + KV-cache usage, always visible) and an
  internals `<details data-testid="qwen-details">` disclosure (running/waiting,
  prefix-cache, MTP acceptance).
- Keep Qwen's richer empty states (the "endpoint unreachable" no-data banner and
  the "dropped on latest sample" transient banner) and the intentional omission
  of the workload-regime pill (no Qwen-side equivalent — already noted in-file).
- Reads stay on `samples[i].vllm_qwen`. Add a `QwenPanel` test for the status
  badge + the internals disclosure.

## Reuse (do not rebuild)
- `ActiveIterationPanel.tsx` — `useNow` (≈L19), `elapsed` (≈L28), `toolDuration`
  (≈L38), step strip, narration, tool-duration rendering; mount whole in hero.
- `AgentMonitorPanel.tsx` — `statusTone`, `WorkerRow`, the synthetic block +
  `data-testid="synthetic-marker"` (carry forward, don't drop the marker).
- `ui/backend/chain.py` `recent_tasks()` — already returns `stage` + `timestamp`;
  `enrich()` only needs to pass them through.
- `ui/frontend/src/api/http.ts` `getActiveIteration()` — used by ActiveIterationPanel.
- `format.ts` `fmt`/`fmtRatioPct`.

## Execution
Phase-bounded `Workflow`, **build → adversarial review → fix**, run as **two
concurrent workstreams over disjoint files**:
- **A — activity rework** (activity files + new `time.ts` + `activity.py`).
  Review focuses on: idle/active correctness (both empty → empty-state; either
  present → hero), live-elapsed accuracy, synthetic block staying subordinate +
  marked, no regression to the graph deep-link/toggle, and the `time.ts`
  extraction not breaking Dashboard/ActiveIterationPanel.
- **B — Qwen panel mirror** (`QwenPanel.tsx` + its test). Review focuses on
  parity with `VllmPanel` (status badge + core-vs-internals split), the
  no-data/dropped states preserved, the workload-pill omission intentional.

No file overlap: A owns the activity files + `time.ts` (imported by
Dashboard/ActiveIterationPanel) + `activity.py`; B owns only `QwenPanel.tsx`.

## Verification
- **Backend:** `cd ui && env -u MOCK_LLM .venv-ui/bin/python -m pytest backend/tests/test_activity.py -q` — `detail`/`stage`/`last_activity_at` present; idle path.
- **Frontend:** `cd ui/frontend && npx vitest run tests/test_activity tests/test_qwen*` + full `npm test`; `npm run build` (tsc + vite) clean. Qwen panel shows the `qwen-status` badge + a `qwen-details` disclosure (parity with `vllm-details`).
- **E2E (on `:5173` after merge):** with an iteration/workers active, the hero dominates with real `detail` + ticking elapsed and the active iteration's step/narration; when idle, the empty-state shows "last activity … ago" and the history graph is tucked in its disclosure; synthetic internals only under their disclosure with the marker.
- **Land it:** on green + review, merge `worktree-ui-session` → `main` (`--no-ff`), then restart the detached `:8700`/`:5173` servers from the main checkout to pick up the backend change.

## Constraints
`ui/`-only; reuse over new code; **synthetic data never presented as measured**
(the marker is preserved); hero data is real orchestrator + loop data, mock only
behind its disclosure. This is an internal research tool — match the existing
component idiom for consistency (it already uses `▸/▾` disclosures), but
product-polish / emoji / dark-mode rules are NOT gating. Consults
`docs/DATA_SHAPES.md` (active_iteration canonical shape = `schema/active_iteration.schema.json`).
