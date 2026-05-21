# Track D day-5 — UI sync to real day-4 artifact shapes

Session date: 2026-05-21. Branch: `worktree-day5-ui-sync`. All changes
under `ui/` + `ui_plan.md` + this note.

## Context

The day-4 sync (merged as `fb1fbaf`) was built against synthesized
fixtures because Track A had not yet produced the day-4 artifacts. The
real artifacts are now on disk and differ in shape from the fixtures.
This session aligned the UI to the real shapes. The
`track-d-day5-followups` memory note flagged two of the four items.

## What the real artifacts actually look like

- `logs/day4_robust.jsonl` — a **chained call log** (10 records = 5
  runs × {root, child}), the same record shape as `day4_e2e.jsonl`. Not
  per-trial summary records. Each run-root has `parent_request_id` null
  and `caller_tag` `test_tool_call_robustness/run<N>`; its `completion`
  is the model's tool call.
- `logs/day4_e2e.jsonl` — a 2-record chain. The tool call is in the
  `completion` field as an OpenAI-style JSON string
  (`[{"id":..., "type":"function", "function":{"name","arguments"}}]`),
  **not** an embedded `tool_calls` array.
- `schema/calls.jsonl.schema.json` — `retrieval_context` is whitelisted
  as a property; `additionalProperties: false` kept.
- `schema/events.jsonl.schema.json` — committed; a `oneOf` of
  `human_intervention` and `calibration_entry`.

## Changes

1. **`read_robustness` rewritten** (`ui/backend/day4.py`). Consumes the
   chained-call shape: a "run" is a wrapper-root call; it "invoked" the
   tool when its root `completion` parses as a tool call. Children
   (`parent_request_id` set) are excluded from the trial count.
   Outcomes: `ok` / `missed` / `malformed`. The pre-sync reader keyed on
   an `invoked` flag and scored the real file 0%; it now reports the
   true 1.0 (all 5 real runs invoked).

2. **Third tool-call synthesis path** (`ui/backend/chain.py`). New
   `parse_completion_tool_calls` + `tool_call_name`. `_call_node`
   synthesizes a `kind="tool"` child from a `completion`-field tool call
   via the existing `_tool_node` — inspector tree shape unchanged.
   Completion tool calls carry no own latency (the wrapper `latency_ms`
   covers them) → contribute 0 to `total_latency_ms`. A completion that
   opens like a tool-call array but fails to parse sets the existing
   `tool_calls_malformed` flag (banner/badge fire) — surfaced, not fixed.

3. **`EventsViewer` per-type renderer** (`ui/frontend/src/routes/`).
   Per-type cards for `human_intervention` and `calibration_entry`
   driven by the committed schema's per-type fields; generic dump
   fallback for any other `event_type`; an "incomplete record" flag when
   a typed event misses a schema-required field. `logs/events.jsonl`
   still does not exist — the `available: false` degrade path is intact;
   the backend `read_events` stays schema-light.

4. **`retrieval_context` keys verified.** The committed schema's item
   keys (`doc_id`, `content_hash`, `chunk_offset`, `chunk_length`) match
   the UI's `RetrievalDoc` type and `ChainTree` table exactly — no
   drift, no change. Added `test_retrieval_context_whitelisted_keys_match_ui`
   as a drift guard.

## Verification

- 65 Python tests (`pytest ui/backend/tests ui/sampler/tests`) +
  20 frontend tests (`npm test`) pass; `npm run build` clean.
- `test_real_schema.py` gained real-artifact tests (skip cleanly if
  absent): real `day4_*` logs validate against the committed schema;
  `read_robustness` on the real file reports `invocation_rate == 1.0`;
  the real `day4_e2e.jsonl` chain synthesizes a tool node from the
  `completion` field.
- Smoke-tested the API against the real `logs/`: `/api/robustness` →
  5 runs, 1.0 invocation rate, median 385.7 ms; `/api/day4/chains` →
  the e2e chain renders `call → [tool:get_payoff_matrix, call]`.

## Notes for a future session

- The malformed-completion detection is a narrow heuristic (`completion`
  opens `[` and contains `"function"` but fails `json.loads`). The real
  data has no malformed completions; this is defensive. If Track A
  starts emitting partial completions for non-tool reasons, revisit.
- Per-node and `total_latency_ms` values are raw floats from the real
  logs (e.g. `1745.9975…`). `read_robustness` rounds its own latencies
  to 0.1 ms, but the chain inspector still shows raw floats — a display
  polish pass (not a shape issue) could format them in `format.ts`.
- `notes/track-d-observations.md` still carries the day-4 asks to
  Track A; the events-schema and embedded-key questions in it are now
  resolved by the committed schema and shape 3 respectively.
