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
> **Revision r2 (2026-05-18).** Revised after two reviews against the
> repo and `plan.yaml`. Changes are summarized in §0. The most
> consequential: the apparatus does not produce a single
> `logs/calls.jsonl` — call logs are per-day files (§4.2); and the
> stack now runs MTP speculative decoding, which adds a first-class
> health signal the dashboard must surface (§4.1, §5.3).

---

## 0. Revision log

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
- Steps 6.1 (sampler), 6.2 (backend HTTP + chain walker + fixture
  generator), 6.3 (frontend call-chain inspector), and 6.4 (live
  WebSocket /api/live) are built; 22 Python + 2 frontend tests pass.
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
- Tree (collapsible nodes): orchestrator dispatch at root → worker invocation → wrapper calls → tool calls. Parse failures and retries get a distinct visual treatment (a small badge, not a color flash). A chain flagged `malformed` by the backend (cycle) renders with a clear banner.
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

- Whether tool calls are logged as their own call-log lines (with their own `request_id`) or embedded inside a wrapper call's record. The inspector renders them as tree nodes if separate, as a sub-section of one node if embedded. Decide once the day-4 tool-call work lands; until then build the tree to handle both shapes.
- Whether to expose experiment-level views (cooperation rates, per-round behavior) in v1 or defer to a v2 results-browser plan.
- Whether the inspector should let users diff two chains side-by-side (powerful, but doubles the layout work).
- The "healthy baseline" card should be data-driven (read from `bench/day1.csv` and `run_state/week1.state.json`'s `metric_log`) — §5.3 already commits to this. The open part is only timing: it requires the apparatus to have committed `bench/day1.csv` (day 1) and populated `metric_log`. Until then the documented constants in §5.3 stand in. Note the constants have already drifted once (idle power 25 W estimate vs. ~5 W measured), which is the argument for data-driven.
- Whether the WebSocket should backfill the last N seconds of telemetry on connect, or only stream forward.

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
