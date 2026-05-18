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
