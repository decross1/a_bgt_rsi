# Track B — Day 3.5 schema additions (D-025)

Worktree `day3_5-schemas` (branch `worktree-day3_5-schemas`). Implements
the two schema-touching proposals from the 2026-05-19 adversarial review
that were approved for Week 1:

| Proposal | File | Kind |
|---|---|---|
| P1 — `human_intervention` event type        | `schema/events.jsonl.schema.json` (new) | oneOf member |
| P2 — `retrieval_context` field on call records | `schema/calls.jsonl.schema.json` (edit)  | optional, nullable |
| P3 — `calibration_entry` event type         | `schema/events.jsonl.schema.json` (new) | oneOf member |

Source: `notes/research/2026-05-19-adversarial-review/5_frozen_plan_change_proposals.md`.
None of these touches `plan.yaml`, `CLAUDE.md`, or any version pin.

## P2 — `retrieval_context` on `calls.jsonl.schema.json`

- Added as an OPTIONAL, nullable property; NOT in `required[]`. Legacy
  records without the key remain valid.
- Type accepts `array` or `null`. When an array, each element has
  `doc_id`, `content_hash`, `chunk_offset`, `chunk_length`, all
  required, `additionalProperties: false`.
- `chunk_offset` and `chunk_length` are non-negative integers.
- Empty list is permitted (semantics: a retrieval call returned zero
  hits; distinct from `null` which means no retrieval ran).

Self-validation: `Draft202012Validator.check_schema(schema)` passes.
Re-validation against `logs/day2.jsonl` (50 records, the Day-2 sweep)
produced **zero failures**. `logs/day1.jsonl` does not exist in the
current tree; the test detects "any legacy logs found" and validates
each. If a Day-1 log lands later, the same test path picks it up.

## P1 / P3 — `events.jsonl.schema.json`

New file. Root is `oneOf` over two members; each member has
`additionalProperties: false`. Discriminated on `event_type` via a
`const`:

- **`human_intervention`** — required: `event_type`, `timestamp`,
  `task_id`, `subtype`, `reason`, `context_hash`. `subtype` enum:
  `edit_prompt | edit_code | reject | redirect | manual_decision`.
- **`calibration_entry`** — required: `event_type`, `timestamp`,
  `experiment_id`, `metric_name`, `pre_experiment_expected_range`,
  `post_experiment_observed`, `within_range`, `human_attestation`.
  `pre_experiment_expected_range` is a 2-element `[low, high]` number
  array; `within_range` is a bool.

These records live in a future `run_state/events.jsonl` (Track A's
file). This Track B work delivers the schema only — wrapper
instrumentation that emits the events is Track A's job and is out of
scope for D-025.

### Discriminator behaviour

A `human_intervention` payload that also carries
`calibration_entry`'s required fields fails validation:

- the matching branch (`human_intervention`) rejects the extras due to
  `additionalProperties: false`;
- the other branch (`calibration_entry`) rejects because its
  `event_type` const does not match.

`oneOf` therefore validates against neither member. The symmetric case
(calibration record carrying intervention fields) fails by the same
mechanism. Both are asserted in `tests/test_events_schema.py`.

## Tests

| File | Cases |
|---|---|
| `tests/test_calls_schema_retrieval_context.py` | 11 cases |
| `tests/test_events_schema.py`                  | 21 cases |

Run:

```
python3 tests/test_calls_schema_retrieval_context.py
python3 tests/test_events_schema.py
```

Both files exit cleanly under `unittest` and `pytest`. No network. No
`LOCAL_LLM_BASE_URL` calls. No writes to `run_state/`, `logs/`, or
`bench/`.

## Forward hooks (NOT in this PR)

- **Wrapper plumbing for P2.** Track A's `agent_wrapper/wrapper.py`
  needs to thread the retrieval results (from the Day-4 tool-call
  pathway) into the call record. The schema is now ready for it; no
  code in `agent_wrapper/` was touched.
- **Event emission for P1 / P3.** Track A will pick a destination file
  (likely `run_state/events.jsonl`) and append `human_intervention`
  events as humans interrupt agent tasks, and one `calibration_entry`
  per experiment outcome on Day 7. The schema validates such a stream
  line-by-line; no aggregation logic in this PR.

## What this PR does NOT do

- Does not edit `agent_wrapper/`, `run_state/`, `logs/`, `bench/`,
  `chroma_db/`, `CLAUDE.md`, `plan.yaml`, or any Track A / Track C file.
- Does not emit any event records itself.
- Does not change the existing `required[]` list on the calls schema.
- Does not call the local vLLM endpoint.
