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

## P2 — MTP sync pass (2026-05-19)

The UI was built (steps 6.1–6.7, P0, P1) while the apparatus had MTP
deferred and vLLM pinned to `v0.20.0`. Day 2 then closed by resolving
its throughput abort: **D-022 enabled MTP speculative decoding and
re-pinned vLLM `v0.20.0` → `v0.21.0`** (decode 32 → 69 tok/s, sweep
aggregate 56.09). This pass brings the UI's data sources and copy in
line with that. All under `ui/`; nothing apparatus-side touched.

### Baseline card → MTP (`backend/baseline.py`, `BaselineCard.tsx`)

`bench/mtp.csv` (the MTP-enabled sweep, committed by D-022) is now a
decode-tok/s source. `compute_baseline` takes a third `mtp_csv` arg;
when the file exists it drives the decode row (median ≈69 tok/s over
the 5-prompt sweep) and the pre-MTP `bench/day1.csv` / `metric_log`
figure (~32) rides alongside as `pre-MTP …` so the speed-up is visible.
`/api/baseline` wires it via `DEFAULT_MTP_CSV` / `UI_MTP_CSV`.

Stale `DOCUMENTED` strings fixed: decode row dropped "MTP (≈96)
deferred"; the stack row now reads `vLLM v0.21.0 · MTP enabled`. The
`BaselineCard` fallback rows (used only when the backend is
unreachable) were updated to match, and the card title dropped
"(day 1)" since the decode row is now a day-2 measurement.

### MTP tile + sampler (`VllmPanel.tsx`, `sampler/sources/vllm_metrics.py`)

The MTP acceptance tile no longer renders flat: a present rate is
green at ≥50% (the §5.3 "MTP engaged" signal) and amber below; the
null label is now "MTP off / metric absent". The sampler's
speculative-decoding candidate names were broadened to cover the v1
engine's counter names with and without the Prometheus `_total`
suffix, and the "verified against v0.20.0" comment corrected.

### Surprises / open

- **The measured MTP decode (~69 tok/s) still sits below the
  documented expected band [80,130]** — between the hard floor (40)
  and the band. The card shows measured and documented side by side;
  it does not interpret the gap (operating-contract rule 8). This is
  the same drift the data-driven card is built to surface.
- **vLLM v0.21.0 spec-decode metric names are not verified live.** The
  candidate-name lists in `vllm_metrics.py` are a best effort against
  the v1 engine's exported counters; the sampler can only be confirmed
  against a running v0.21.0 `/metrics` endpoint. Until then the MTP
  tile may still show "metric absent" even with MTP on. Filed as a
  live-check item — not a code blocker (the candidate-list pattern
  absorbs a rename without a rewrite).
- **Open question — what MTP acceptance rate counts as healthy?** The
  MTP tile colours green/amber at a `≥0.5` (50%) draft-acceptance
  threshold. `ui_plan.md` §5.3 says to colour "against the baseline
  card's expected range", but the baseline card has no acceptance-rate
  row and §5.3's "MTP-engaged signal ≥ 50" is a *decode tok/s* figure,
  not an acceptance fraction. So the 0.5 boundary in `VllmPanel.tsx` is
  a chosen heuristic, not plan-derived. For the human: confirm a real
  expected acceptance range (it depends on `num_speculative_tokens=4`
  and the Gemma 4 drafter) — then the threshold should move to the
  data-driven baseline card alongside the decode-tok/s row.

### Real schema + day-2 logs (`backend/tests/test_real_schema.py`)

The chain walker was built against fixtures while only the structural
call-log fields were pinned. The apparatus has since committed
`schema/calls.jsonl.schema.json` and the first real call log,
`logs/day2.jsonl` (50 standalone calls — `parent_request_id` null,
chains start day 4). The backend's `DEFAULT_LOGS_DIR` already points at
the real `logs/`, so the gap was test coverage, not wiring. Added
`test_real_schema.py`:

- structural fields the walker keys on are present + required in the
  committed schema (a real schema-drift guard — fails loudly on a
  rename);
- every `logs/day2.jsonl` record validates against the committed
  schema (`jsonschema` Draft 2020-12);
- `LogStore` ingests the real day-2 log, indexing all 50 by
  `request_id`, with no orchestrator dispatches (none until day 6).

All three skip cleanly if Track A has not committed the artifacts, so
the suite still passes on a fresh checkout. Also fixed `gen.py`'s
fixture `vllm_image_tag` — it carried `vllm/vllm-openai:gemma4-cu130`,
a CLAUDE.md rule-2 forbidden tag; now `v0.21.0`, matching the real
`logs/day2.jsonl`. Fixtures are otherwise left structural-narrow by
design (ui_plan.md §10) — they were not validated against the real
schema because they intentionally model future shapes (embedded
`tool_calls`, `parse_error`) the day-2 schema's `additionalProperties:
false` would reject.

Tests: `test_baseline.py` +3 (mtp source, absent-mtp fallback,
mtp-only), `test_api.py` +1 (`test_baseline_endpoint_uses_mtp_csv`;
`_client` now isolates the real `bench/mtp.csv`), new
`frontend/tests/test_vllm_panel.tsx` (3 — MTP tile null/green/amber),
new `backend/tests/test_real_schema.py` (3 — see above).
38 Python + 9 frontend tests pass; `npm run build` clean.
`ui_plan.md` bumped r4 → r5.

## Day-4 sync (2026-05-20)

Track D side-track on `worktree-day4-ui-sync` for the day-4 surfaces.
Day 3.5 and day 4 have not landed in Track A — built forward-compatible
against synthesized fixtures (`write_day4_fixtures` in
`backend/tests/fixtures/gen.py`). Detailed notes in
`notes/track-d-day4-ui.md`; summary below.

- **Wrapper-rooted chain walker** (`build_chain_by_request_id`) +
  `GET /api/chain_by_request/{rid}` + new inspector route
  `/chain/req/:requestId`. Day-4 chains begin before day 6's
  orchestrator, so they have no dispatch root.
- **Day-4 chain list** on the dashboard (`Day4ChainList.tsx`) reads
  `GET /api/day4/chains` — wrapper-rooted records from
  `logs/day4_e2e.jsonl`, with a red `malformed` badge when a chain
  carries any parse-error nodes.
- **Malformed-JSON `tool_calls` banner.** The inspector renders a red
  banner counting affected nodes; `ChainTree.tsx` adds a per-node
  `malformed tool_calls` badge. No silent format-fixing — raw record
  shown as stored.
- **Forward-compatible `retrieval_context`.** Surfaced as a typed list
  only when the record carries a list of objects; wrong-shape values
  are dropped. Each node shows a `ctx N` badge and a collapsible
  doc_id / content_hash / offset / length table.
- **Robustness panel** (`RobustnessPanel.tsx`) reads
  `GET /api/robustness` — invocation rate, median latency
  (`statistics.median`), per-outcome counts, per-trial table.
- **Events viewer** at `/events` (`EventsViewer.tsx`) reads
  `GET /api/events`. Type-aware rendering for `human_intervention` and
  `calibration_entry`; generic fallback for any other event_type. The
  reader is intentionally schema-light (only `event_type` enforced)
  because the day-3.5 schema is not committed yet.
- **Available-false defaults.** Every new endpoint degrades to
  `available: false` when its source file is absent, so panels read
  "not present yet" rather than 500 while Track A is still pre-day-4.

15 new backend tests + 8 new frontend tests. 53 Python + 17 frontend
pass; `npm run build` clean. `ui_plan.md` bumped r5 → r6.

### Asks for Track A / human

- The current `schema/calls.jsonl.schema.json` has
  `additionalProperties: false`. Day 3.5 cannot add `retrieval_context`
  to a call record without first lifting that constraint or whitelisting
  the new field. Heads-up for whoever lands day 3.5.
- `events.jsonl` schema is not committed yet — the viewer reads it
  generically. When required per-type fields land, `EventsViewer`
  should switch from key/value rendering to a per-type renderer.
- The UI assumes day-4 chains are wrapper-rooted (parent_request_id
  null in `day4_e2e.jsonl`). If day 4 instead emits a separate dispatch
  record, the `/api/day4/chains` rule needs adjustment.
