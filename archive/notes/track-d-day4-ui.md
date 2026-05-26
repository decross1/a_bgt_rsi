# Track D day-4 UI sync (2026-05-20)

Side-track on `worktree-day4-ui-sync` to bring the UI in line with the
day-4 surfaces (and the day-3.5 surfaces that ride alongside). Built
against synthesized fixtures because Track A has not landed any of:

- `schema/calls.jsonl.schema.json` additions for `retrieval_context`
- `logs/events.jsonl`
- `logs/day4_e2e.jsonl`
- `logs/day4_robust.jsonl`

The current `schema/calls.jsonl.schema.json` has `additionalProperties:
false`, so the moment Track A adds `retrieval_context` (or any new
optional field), the schema must lift that constraint or whitelist the
new keys explicitly. Filed for whoever lands day 3.5.

## What landed in the UI

Backend (`ui/backend/`):

- `chain.py`: new `build_chain_by_request_id(store, root_request_id)`
  walks a wrapper-rooted tool-call chain. The day-4 chains begin
  before day 6's orchestrator runs — there is no dispatch root — so
  `build_chain` keyed by `task_id` cannot reach them. The two walkers
  share `_call_node` + the same `seen`-set cycle handling.
- `chain.py`: `_call_node` now flags `tool_calls_malformed: true` when
  a record's `tool_calls` field is the wrong type (anything other than
  a list of dicts). The chain response carries a `malformed_tool_calls`
  count so the inspector can render a red banner without iterating
  itself.
- `chain.py`: forward-compatible `retrieval_context` passthrough. The
  field is only surfaced as a typed list when the record carried a
  list; wrong-shape values are dropped rather than leaked to the UI.
- `day4.py` (new): `read_events(...)` and `read_robustness(...)`. Both
  degrade to `available: false` rather than 500 when their source file
  is absent — important while Track A is still pre-day-4.
- `app.py`: four new endpoints — `/api/chain_by_request/{request_id}`,
  `/api/day4/chains`, `/api/events`, `/api/robustness`.

Frontend (`ui/frontend/`):

- `routes/Inspector.tsx` now drives two routes from one component:
  `/chain/:taskId` (dispatch-rooted, day-6) and `/chain/req/:requestId`
  (wrapper-rooted, day-4). The inspector renders a red banner whenever
  `malformed_tool_calls > 0`.
- `components/ChainTree.tsx`: per-node `malformed tool_calls` badge
  and a `ctx N` badge when `retrieval_context` is present. Expanding
  a node shows a small `retrieval_context` table (doc_id,
  truncated content_hash, chunk_offset, chunk_length) before the
  generic raw-fields dump.
- `components/Day4ChainList.tsx` (new): dashboard panel listing
  wrapper-rooted chains from `day4_e2e.jsonl`. Polls every 5 s.
- `components/RobustnessPanel.tsx` (new): dashboard panel reading
  `day4_robust.jsonl` — invocation rate, median latency, per-outcome
  counts, per-trial table.
- `routes/EventsViewer.tsx` (new): `/events` route. Type-aware
  rendering for `human_intervention` and `calibration_entry`; falls
  back to generic for any other type that lands.

Fixtures (`ui/backend/tests/fixtures/gen.py`):

- `write_day4_fixtures(out_dir)` writes `day4_e2e.jsonl`,
  `day4_robust.jsonl`, and `events.jsonl`. Three day-4 chains: a
  two-tool wrapper, a one-tool wrapper, and a deliberately malformed
  chain (`tool_calls` as a string instead of a list). 10 robustness
  trials: 8 invocations (one a timeout), 2 missed. Two events: a
  `human_intervention` and a `calibration_entry`.

Tests: 53 Python pass (15 new in `test_day4.py`), 17 frontend pass
(8 new in `test_robustness_panel.tsx`, `test_chain_tree_day4.tsx`,
`test_events_viewer.tsx`). `npm run build` clean.

## Decisions

- **Median uses `statistics.median`.** For an even-length list of
  latencies it averages the two middle values. The fixture has 8
  invocation latencies; median is (140+150)/2 = 145, not 150. The
  fixture's `day4_robust_expected()` mirrors this so it stays the
  single source of truth.
- **Day-4 chains list is paged 5 s.** Same cadence as the
  orchestrator queue. Telemetry stays on the 0.5 s WebSocket.
- **`available: false` rather than 404 or 500.** Every day-4/3.5
  reader is fronted by a file-exists check; the panel renders a
  "not present yet" message rather than spamming the console with
  errors while Track A catches up.
- **No silent format-fixing.** If a wrapper record's `tool_calls`
  arrived as a string, the inspector shows the raw string in the
  generic dump and flags the node as a parse error. Operating-contract
  rule 8 (the dashboard surfaces problems, it does not auto-remediate)
  applies here.

## Open questions / asks for Track A (and human)

- **`retrieval_context` shape.** The UI assumes a list of
  `{doc_id, content_hash, chunk_offset, chunk_length}` per the task
  description. If the day-3.5 schema names the field differently, or
  any of those keys, the chain walker still passes through generically
  (only the typed `RetrievalContext` table needs key tweaks).
- **`events.jsonl` schema.** Built generically against `event_type`.
  When the schema lands and adds required per-type fields,
  `EventsViewer` should switch from generic key/value rendering to a
  per-type renderer.
- **`additionalProperties: false` on the call schema.** Day 3.5 cannot
  add `retrieval_context` to a call record without first lifting that
  constraint or whitelisting the new field. Heads-up for whoever lands
  day 3.5.
- **Where does `day4_e2e.jsonl` actually root chains?** This pass
  assumes wrapper-rooted (parent_request_id null). If day-4 instead
  emits a separate "day-4 dispatch" record analogous to day-6's
  orchestrator, the `/api/day4/chains` listing rule needs adjustment.
