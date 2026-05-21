# UI plan — orchestrator dashboard + call-chain inspector

> Companion plan to `plan.yaml` (week 1, days 31–37). The week 1 plan
> builds the research apparatus. This plan builds the observability
> layer on top of it. Both plans share the same repo (`a_bgt_rsi`).
>
> **You are a concurrent Claude instance.** A different Claude is
> executing `plan.yaml` (the week 1 apparatus build) on the DGX Spark.
> This plan is yours. The two plans share data contracts (the JSONL
> schemas in `schema/`) but do NOT share source files outside `ui/`.
> Read the operating contract below before doing anything.
>
> **Revision r7 (2026-05-21).** All build steps (6.1–6.7) plus five
> improvement passes are done; full history is in §0. The latest pass
> (r7, Track D day-5) aligns the UI to the *real* Track A day-4
> artifacts, which differ in shape from the synthesized fixtures the
> day-4 sync (r6) was built against: `read_robustness` now consumes
> `logs/day4_robust.jsonl` as a chained call log (deriving the
> invocation rate from whether each run-root call emitted a tool call,
> not a per-trial `invoked` flag — the r6 reader scored the real file a
> misleading 0%); the chain walker gained a third tool-call synthesis
> path that parses an OpenAI-style tool call out of the `completion`
> field (the shape Track A actually uses); `EventsViewer` switched from
> generic key/value rendering to a per-type renderer driven by the now
> committed `schema/events.jsonl.schema.json`; and the UI's
> `retrieval_context` keys were verified against the committed
> `schema/calls.jsonl.schema.json` whitelist (no drift) with a
> drift-guard test added.

---

## 0. Revision log

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
