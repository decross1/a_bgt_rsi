# UI build notes

Running log of what was built, surprises, and data-contract questions
for the human. See `ui_plan.md` §8 (handoff) and §9 (open questions).

## Step 6.1 — sampler (2026-05-18)

Built `ui/sampler/`: a 1 Hz telemetry daemon writing
`ui/logs/telemetry.jsonl`. Four source readers (`nvidia_smi`,
`vllm_metrics`, `psutil_procs`, `thermal`), schema at
`ui/schema/telemetry.jsonl.schema.json`, tests pass (3/3).

### Surprises

- **GB10 unified memory.** On the real hardware `nvidia-smi
  --query-gpu=memory.used,memory.total` returns `[N/A]` — GB10 shares
  one memory pool. The sampler now parses each GPU field independently:
  it keeps util/temp/power and writes the memory fields as `null`
  rather than discarding the whole `gpu` object. `gpu.*` fields are
  number-or-null in the schema. Observed idle: 0% util, 38 °C, ~5.5 W
  (consistent with day-1 firmware's "5 W idle").
- Decision: kept the UI layer entirely under `ui/` (schema, logs,
  venv, requirements) instead of the apparatus's shared `schema/` and
  `logs/` dirs, to avoid any clash with the concurrent week-1 build.
  `ui_plan.md` revised to r3 to match.

### Questions for the human

- None blocking. The GB10 "GPU memory" tile on the dashboard will show
  n/a — confirm that is acceptable, or whether unified-memory usage
  should be sourced another way (e.g. treated as host memory).

## Step 6.2 — backend HTTP + chain walker (2026-05-18)

Built `ui/backend/`: a FastAPI service (`tailer.py` incremental reader,
`chain.py` parent_request_id walker, `app.py` endpoints) plus a fixture
generator. Endpoints: `/api/health`, `/api/chain/{task_id}`,
`/api/recent_tasks`, `/api/state`. 17 backend tests pass (20 total with
the sampler); smoke-tested with a running server on a port against
generated fixtures.

### Decisions

- **No `logs/calls.jsonl`.** Confirmed against `plan.yaml`: the call log
  is `logs/day*.jsonl` + `logs/exp*.jsonl`. The walker globs both and
  indexes by `request_id` (`chain.py`). The day-2 *schema* file is named
  `calls.jsonl.schema.json` but no such log file is ever produced.
- **Fixture generator** (`backend/tests/fixtures/gen.py`) commits only to
  the structural fields `ui_plan.md` §4.2 marks stable. Run it as a CLI
  to get a log dir; point the backend at it with `UI_LOGS_DIR`.
- Backend serves on port **8700** (8000 is vLLM's).
- `WS /api/live` deferred to build step 6.4 as planned.

### Questions for the human

- **Worker-invocation node.** `ui_plan.md`'s inspector tree is
  "dispatch → worker invocation → wrapper calls", but the orchestrator
  log (§4.3) has only one record type per task. The walker currently
  uses the orchestrator dispatch as the root node and the first call
  (`caller_tag: "worker"`) as its single child — there is no separate
  "worker invocation" record. Confirm the day-6 schema does not add one;
  if it does, the walker needs a third node kind.
- **Tool-call linkage** (already in `ui_plan.md` §9): the generator
  models tool calls as their own call-log lines with their own
  `request_id`. If day-4's real tool calls are instead embedded inside a
  wrapper call's record, the walker and inspector need adjusting.

## Step 6.3 — frontend call-chain inspector (2026-05-18)

Built `ui/frontend/`: React 19 + Vite + TypeScript + Tailwind v4 SPA.
Route `/chain/:taskId` is the inspector (collapsible chain tree,
per-node generic detail dump, raw-JSONL toggle, malformed-cycle banner);
`/` is a recent-task list standing in for the dashboard until step 6.5.
`npm run build` is clean, 2 vitest tests pass.

### Surprises

- **vLLM metric names drift, confirmed live.** With vLLM up, the real
  v0.20.0 `/metrics` names differ from what was first coded: KV cache is
  `vllm:kv_cache_usage_perc` (not `gpu_cache_usage_perc`); prefix-cache
  hit rate has no gauge — computed from `prefix_cache_hits_total` /
  `prefix_cache_queries_total` deltas. Scraper updated. This is the
  §7 hazard; the candidate-name design absorbed it.
- **No speculative-decoding metrics exported.** The running vLLM exposes
  no `vllm:spec_decode_*` series, so `mtp_acceptance_rate` and the
  `mtp_*` token fields stay null. The dashboard MTP tile (§5.3) will
  show "MTP off / metric absent" until a build exports them.
- `CLAUDE.md`'s vLLM image pin changed to `vllm/vllm-openai:v0.20.0`
  (apparatus-side change). No UI code depends on the image tag.

### Questions for the human

- Whether MTP speculative decoding is actually expected to be on. If it
  is, the running vLLM is not exporting the metrics for it — worth a
  flag to the apparatus build.

## Step 6.4 — live WebSocket /api/live (2026-05-18)

Added `WS /api/live` to the backend: tail-based (byte offset + 0.5 s
poll, no inotify), forward-only — lines present before a client
connects are not replayed. One message per new line, `{source, line}`.
The handler races a `pump` task against a `drain` task so a client
disconnect is noticed promptly. Added `JsonlTailer.seek_to_end()`,
`websockets` to `requirements-ui.txt`, and the frontend `api/ws.ts`
auto-reconnecting client (unused until the 6.5 dashboard consumes it).
2 backend tests added (24 tests total); smoke-tested against the live
sampler stream.

### Decisions

- **Forward-only stream** (one of `ui_plan.md` §9's open questions): the
  WS does not backfill the last N seconds on connect. The 6.5 dashboard
  will seed its sparklines from a one-shot history fetch instead, or
  this can be revisited if backfill proves nicer.
- Poll interval 0.5 s (telemetry is 1 Hz) to keep lag well under a
  sample period.

## Steps 6.5-6.7 — live dashboard (2026-05-18)

Built the dashboard at `/`: header (hostname, apparatus day, live/stale
indicator), the 5-tile health strip (GPU util/mem/temp/power, CPU temp)
with 5-min sparklines and colour-coded thresholds, the orchestrator
queue (running + recent, rows link into the inspector — that is step
6.6), the vLLM internals panel (queue, KV-cache, prefix-cache, MTP,
decode tok/s), the per-process grid, and the healthy-baseline reference
card (step 6.7). Telemetry streams over the WebSocket via the
`useTelemetryStream` hook, seeded from a new `GET /api/telemetry/recent`
endpoint so sparklines populate on first paint. 1 frontend test added
(3 total); 23 Python tests pass. **All of ui_plan.md §6 (steps 6.1-6.7)
is now built.**

### Decisions

- Added `GET /api/telemetry/recent?limit=N` (bounded tail read) so the
  dashboard seeds 5 minutes of sparkline history instantly rather than
  waiting 5 minutes for the forward-only WS to fill it.
- Added `hostname` to `/api/health` for the dashboard header.
- Baseline card is hardcoded constants for now (CUDA 13.0, idle ≈5 W,
  tok/s floor 40, MTP deferred). `ui_plan.md` §9 still wants it
  data-driven from `bench/day1.csv` once the apparatus commits that.

### Surprises

- `CLAUDE.md` (apparatus-side) now records **MTP deferred** and the
  vLLM image re-pinned to `v0.20.0`. The baseline card and the MTP
  tile reflect this: the tile shows "metric absent", expected decode
  tok/s is the NVFP4 baseline (~52), not the MTP figure (~96).

### Open

- The orchestrator queue has no "Waiting" section: `orchestrator.jsonl`
  (§4.3) records dispatches, not a pending-queue depth. Shown as
  Running + Recent only. Revisit if the day-6 schema exposes a queue.

## P0 — resolve ui_plan.md §9 open questions (2026-05-19)

Track D improvement pass. The §6 build ladder (6.1–6.7) is complete;
this is the first of the improvement priorities.

### Tool-call rendering shape (§9 first bullet) — resolved

Audited `chain.py` and `ChainTree.tsx` against both shapes:
- **Separate call-log lines** (tool calls with their own `request_id` /
  `parent_request_id`): already handled — the ordinary
  `parent_request_id` walk attaches them as children. Covered by
  `gen.py`'s `day6_task_01` / `exp001_round_07` fixtures and
  `test_nested_tool_calls_reconstructed`.
- **Embedded in a wrapper record** (`tool_calls` array): was NOT
  covered — the walker ignored it and the inspector would only have
  dumped it inside the generic `raw` JSON.

Resolution: both shapes now converge to one inspector tree. The chain
walker synthesizes embedded `tool_calls` entries into `kind="tool"`,
`embedded=true` child nodes (`request_id=null`). Embedded-tool latency
is summed into `total_latency_ms` exactly as a separate-line tool
call's latency already is — so a chain's `node_count` and
`total_latency_ms` do not depend on which shape the wrapper used.
(`total_latency_ms` stays a labelled rough sum, not wall-clock.) The
frontend renders `kind="tool"` nodes with a `tool · <name>` label and
an `embedded` badge; the raw-JSONL dump skips embedded nodes since they
are not their own log lines.

(Initially this excluded embedded latency from the total to avoid
double-counting; a code review caught that it left the total
shape-dependent — separate-line tool calls were still summed — and
broke the "converge" claim. Corrected to sum both.)

Added: `gen.py` `day6_task_04` fixture (embedded shape, inserted before
`exp001_round_07` so the latest-dispatch test is unaffected),
`test_embedded_tool_calls_reconstructed` (backend), and a frontend
embedded-badge test. `ui_plan.md` bumped r3 → r4.

### Inspector chain-diffing (§9 third bullet) — deferred to v2

Formally deferred. A side-by-side two-chain diff would roughly double
the inspector layout work for marginal value — the week-1 CLI already
gives a textual diff via
`diff <(tools/inspect_run.py --task-id X) <(tools/inspect_run.py --task-id Y)`.
Rationale committed to `ui_plan.md` §0 r4.

### Experiment-level views (§9 second bullet) — deferred, sketched

Not built. Drafted `ui/ui_plan_v2.md`: a one-page sketch of a v2
results browser (per-experiment cooperation rates, per-round behavior,
opponent breakdown) and the data contracts it needs. Key finding: v2
is blocked on an experiment-result *schema* that does not exist yet —
filed for Track A in `notes/track-d-observations.md`. Placed the sketch
under `ui/` rather than the repo root to stay inside Track D's write
boundary.

## P1 — data-driven healthy-baseline card (2026-05-19)

The baseline card hardcoded day-1 constants (idle ~5 W, tok/s floor 40,
CUDA 13.0). §5.3 and §9 both call for it to be data-driven. Done.

New `backend/baseline.py` + `GET /api/baseline`: sources decode tok/s
from `bench/day1.csv` (median of the `decode_tok_per_s` column) and
`run_state/week1.state.json`'s `metric_log.day1_tokens_per_sec`. Each
returned row is annotated `source: "measured"` or `source:
"documented"`; measured rows also carry the documented expectation so
drift is visible. The endpoint degrades to the documented §5.3
constants per-row when a source file is absent or unparseable — Track A
may still be on day 1.

`BaselineCard.tsx` now fetches `/api/baseline` and renders a measured /
documented badge per row, with the expected figure shown beneath
measured rows. It seeds with the documented constants and keeps them if
the backend is unreachable, so the card never goes blank.

### Surprises

- Both source files already exist on disk: `bench/day1.csv` (5-prompt
  sweep) and `metric_log.day1_tokens_per_sec` = 32.03. So the decode
  row is **measured** today, not documented. The measured ~32 tok/s
  sits well below the documented expected band [80,130] and even the
  NVFP4-no-MTP ~52 figure — exactly the kind of drift the data-driven
  card is meant to surface. The card shows both side by side; it does
  not interpret the gap (operating-contract rule 8). `metric_log` also
  records MTP deferred to Week 2+, consistent with the dashboard's
  existing "MTP metric absent" tile.

Tests: `backend/tests/test_baseline.py` (6 cases — measured, documented
fallback, state-only, unpopulated metric_log, malformed csv, non-decode
rows stay documented), `test_baseline_endpoint` in `test_api.py`, and
`frontend/tests/test_baseline_card.tsx` (measured badge + unreachable
fallback). 31 Python + 6 frontend tests pass.

### Decisions

- Only the decode-tok/s row goes data-driven. Idle power and the
  temp/power threshold bands have no committed measurement source
  (`bench/day1.csv` carries no power column; `metric_log` has no idle
  figure) — they stay `documented`. If a source lands later, add a row
  branch in `compute_baseline`.

### Questions for the human

- **Embedded tool-call key name.** The §9-resolution (r4) for the
  embedded tool-call shape assumes the wrapper record carries its tools
  under a `tool_calls` key. The day-4 tool-call work has not landed, so
  this is a guess. If day 4 uses a different key, the fix is one line
  (`EMBEDDED_TOOL_KEY` in `backend/chain.py`) — no rework — but please
  confirm the key name when day 4 lands. Also filed in
  `notes/track-d-observations.md` for Track A.
- **v2 results browser is contract-blocked.** `ui/ui_plan_v2.md`
  sketches the deferred experiment results browser. It cannot be built
  until the apparatus commits an experiment-result schema (experiment
  id, round index, agent/opponent actions, payoff). Not a v1 blocker;
  a heads-up for whoever scopes v2 and for the day-7 experiment work.
