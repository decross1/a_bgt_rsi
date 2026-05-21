# Track C — Day 5 — `tools/inspect_run.py`

Scratch + handoff notes for `track_c_day5_draft_inspect_run`
(plan.yaml), consumed by `day6_block2_inspect_run_cli`.

## Deliverables

- `tools/inspect_run.py` — CLI that reconstructs an orchestrated run's
  causal chain from JSONL logs.
- `tests/test_inspect_run.py` — 21 `unittest` tests (run standalone or
  under pytest).

## What it does

`python3 tools/inspect_run.py --task-id <id>` reads the orchestrator /
wrapper JSONL logs and follows `parent_request_id -> request_id` links
to print the full chain, indented by depth, with timestamps + durations:

```
orchestrator_dispatch  ->  worker_invocation  ->  wrapper_request  ->  wrapper_response
```

## How to run it (Day 6 consumer)

The plan's command (`day6_block2_inspect_run_cli`) is:

```
python3 tools/inspect_run.py --task-id "$(jq -r '.task_id' logs/day6_5seq.jsonl | head -1)"
```

That works as-is: with no `--log`, the tool reads `logs/orchestrator.jsonl`
**and auto-discovers sibling `*.jsonl` in `logs/`** (so the wrapper-call
records in `logs/day6.jsonl` join the chain without being named). Pass
`--no-discover` to disable, or `--log PATH` (repeatable) to name files
explicitly.

`--request-id <uuid>` roots the chain by request_id instead — needed for
wrapper-call logs (`logs/dayN.jsonl`) that have no `task_id` field.

## Design decisions

1. **Schema-tolerant field access.** `logs/orchestrator.jsonl` does not
   exist until Day 6 and its field names are not frozen, so every
   accessor (`rec_id`, `rec_parent`, `rec_task`, `rec_time`,
   `rec_duration`, `rec_level`) tries a list of candidate keys. This
   means the tool already works against the existing `calls.jsonl`-schema
   wrapper logs (`request_id` / `parent_request_id` / `latency_ms`) and
   will keep working whatever the Day 6 orchestrator schema settles on.
2. **Level inference.** If a record has no explicit `level`/`stage`/etc.
   key, the stage is inferred from shape: `prompt_messages`+`completion`
   => `wrapper_call`; `task_type`+`payload` => `worker_input`;
   `status`+`jsonl_log_path` => `worker_output`.
3. **Cross-file chains.** Orchestrator records carry `task_id`; bare
   wrapper-call records do not. `--task-id` finds the orchestrator-side
   roots, then `build_tree` follows `parent_request_id` into *all* loaded
   records — so wrapper records attach even though they lack `task_id`.
4. **Breakage is reported, never coerced** (CLAUDE.md rule 4). Malformed
   JSON lines, missing files, duplicate `request_id`s, dangling parent
   references, cycles and fragmented chains (>1 root for a task) all emit
   a `warning:` to stderr; the tool still prints whatever chain it can.
   Exit code is 1 only for "selector not found" / "no records".

## Recommended `logs/orchestrator.jsonl` schema (for Day 6 Track A)

The tool is tolerant, but the cleanest record for a 4-level chain is:

```json
{"timestamp": "...Z", "request_id": "<uuid4>",
 "parent_request_id": "<uuid4|null>", "task_id": "<id>",
 "level": "orchestrator_dispatch|worker_invocation|...",
 "task_type": "summarize_paper", "status": "...", "duration_ms": 12.4}
```

Per `schema/worker_contract.schema.json`, the orchestrator log holds
3 entries (dispatch -> worker invocation -> receipt); the 4th level
(wrapper request/response, the actual vLLM call) lives in the wrapper
log `logs/day6.jsonl` and is joined via `parent_request_id`. For the
join to land, the worker-invocation record's `request_id` must be the
`parent_request_id` of the wrapper call it makes.

## Testing

- Fixtures are generated inline (`four_link_chain()`) into a per-test
  temp dir — the real `logs/` directory is never written.
- Two tests read the committed read-only logs (`day4_e2e.jsonl` 2-link
  chain, `day2.jsonl` singletons) and assert the file mtime is unchanged.
- No LLM endpoint is contacted; the CLI subprocess test runs with
  `MOCK_LLM=1` set.

Run: `python3 tests/test_inspect_run.py` — 21 tests, all pass.

## Constraints honored

- Wrote only `tools/inspect_run.py`, `tests/test_inspect_run.py`,
  `notes/track-c-day5-inspect-run.md`.
- No writes to `run_state/`, `logs/`, `agent_wrapper/`, etc.
- stdlib only (`argparse`, `json`, `pathlib`) — no package installs.
- No `LOCAL_LLM_BASE_URL` / localhost:8000 calls.
