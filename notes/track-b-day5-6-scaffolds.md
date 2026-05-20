# Track B — Day 5+6 test scaffolds

Drafted on Day 3 in worktree `day3-tests` (branch `worktree-day3-tests`),
ahead of when Track A consumes them. Four deliverables, all verified
today in mock mode.

| File | Consumed by | Mock switch |
|------|-------------|-------------|
| `tests/test_papers_retrieval.py`            | `day5_block2_retrieval_test`  | `MOCK_LLM=1` |
| `tests/test_orchestrator_5_sequential.py`   | `day6_block2_robustness_mini` | `MOCK_LLM=1` |
| `tests/test_orchestrator_malformed_input.py`| `day6_block2_robustness_mini` | `MOCK_LLM=1` |
| `schema/worker_contract.schema.json`        | `day6_block2_worker_contract` | — |
| `tests/_orchestrator_contract.py`           | shared helper (not a test)    | — |

Track B scope honored: no writes to `run_state/`, `agent_wrapper/`,
`logs/`, `bench/`, `chroma_db/`, `orchestrator/`, `workers/`,
`pipeline/`. No calls to `LOCAL_LLM_BASE_URL` or any localhost:8000
endpoint — every LLM/embedding step is stubbed behind `MOCK_LLM`.

## Verification (Day 3, mock mode)

- All four `.py` files compile (`py_compile`).
- `schema/worker_contract.schema.json` passes
  `Draft202012Validator.check_schema()`. `$defs.worker_input.required`
  is exactly the 4 fields; `$defs.worker_output.required` is exactly the
  5 fields. The root `oneOf` cleanly classifies a message as input XOR
  output (disjoint required sets + `additionalProperties:false`).
- `test_papers_retrieval.py` `MOCK_LLM=1`: returns 3 fake papers,
  on-topic paper ranked #1, latency recorded, JSON written. `--top-k`
  honored.
- `test_orchestrator_5_sequential.py` `MOCK_LLM=1`: 5/5 passed; the 5
  emitted JSONL records all validate against `#/$defs/worker_output`.
- `test_orchestrator_malformed_input.py` `MOCK_LLM=1`: 5/5 malformed
  shapes rejected cleanly (no crash); all 5 error records validate
  against `#/$defs/worker_output`.
- Guardrails: with no `MOCK_LLM` and no real orchestrator, the two
  orchestrator tests exit 2 with an actionable message rather than
  crashing.

## `schema/worker_contract.schema.json`

Authored from `plan.yaml` task `day6_block2_worker_contract`. Draft
2020-12. One file holds both halves of the contract as `$defs`:

- `#/$defs/worker_input` — required: `task_id, task_type, payload,
  parent_request_id`.
- `#/$defs/worker_output` — required: `task_id, status, result,
  errors, jsonl_log_path`.

Design choices beyond the bare field list (Track B inference — Track A
may tighten on Day 6):

- `status` is an enum `["passed", "error", "timeout"]`. `"passed"` is
  the token `day6_block2_robustness_mini` validation checks for
  (`status=passed`); `"timeout"` reflects the 60 s worker timeout.
- `task_type` is `string, minLength 1` (not an enum). Day 6 has one
  task type, `summarize_paper`, but the contract is "load-bearing for
  everything downstream" — enumerating it would force a schema edit per
  new task type. An unknown `task_type` is a runtime rejection, not a
  schema violation.
- `result` is `["object","null"]` — null whenever `status != "passed"`.
- `parent_request_id` mirrors `calls.jsonl.schema.json`: nullable,
  uuid-formatted when a string.

## Assumed `OrchestratorClient` contract (DAY6-CONTRACT)

`orchestrator/openclaw_runner.py` does not exist until Day 6
(`day6_block2_orchestrator_*`). The plan task `day6_block2_worker_contract`
fixes the *message* shapes (the JSON schema) but not the *class* API. The
orchestrator tests therefore assume an API, tagged `DAY6-CONTRACT`
throughout — `grep -rn DAY6-CONTRACT tests/`:

```
client = OrchestratorClient(log_path="logs/orchestrator.jsonl",
                            worker_timeout_s=60)
output = client.run_task(task)   # task: worker_input dict
                                 # output: worker_output dict
```

- `run_task` **never raises on bad input** — a malformed task yields
  `status="error"` with a non-empty `errors` list. The malformed-input
  test treats any raised exception as a failure ("orchestrator did not
  crash", per the plan validation).
- Each `run_task` call appends the task's causal chain to `log_path`
  (dispatch → worker invocation → receipt), linked by
  `parent_request_id`.

If Day 6 picks a different class API, update the `DAY6-CONTRACT` lines
in `tests/_orchestrator_contract.py` — the message schema should not
need to move. The tests gate only on the **output contract** (`status`,
schema-validity), never on the orchestrator log's internal shape, so
they are robust to whatever logging format Day 6 lands.

`tests/_orchestrator_contract.py` loads the real class via a normal
package import first, then a direct file load — so the tests work
**whether or not** Day 6 adds `orchestrator/__init__.py`. The real
client is preferred whenever it exists; `MockOrchestratorClient` is used
only when it is absent and `MOCK_LLM=1`.

## Day-5 caveat for `test_papers_retrieval.py`

The mock branch (`MOCK_LLM=1`) is fully verified. The **real branch**
(`_query_real`) is wired by Day 5 once `pipeline/embed_and_store.py` has
built the `papers_recent` collection. Two `DAY5-CONTRACT` items must be
reconciled on Day 5:

1. **Embedding function.** `papers_recent` is created with an explicit
   BGE-M3 embedding function (CLAUDE.md inviolate rule #2 forbids
   ChromaDB's `all-MiniLM-L6-v2` default). To *query* the collection the
   **same** embedding function must be passed to `get_collection` — or
   the query text is embedded differently from the corpus and retrieval
   silently degrades. The scaffold builds a
   `SentenceTransformerEmbeddingFunction(model_name=<bge-m3-weights>)`;
   if `embed_and_store.py` constructs its BGE-M3 function differently
   (model id, normalization, or a shared helper), import and reuse that
   helper here instead. **The two must match.**
2. **Collection metadata fields.** `_query_real` reads `arxiv_id`,
   `title`, `abstract`, `authors`, `semantic_scholar_id`,
   `citation_count` from each hit's `metadatas`. If Track C's
   `embed_and_store.py` stores those under different keys, adjust the
   mapping in `_query_real`.

`chromadb` is not in the base venv — Day 3 creates `.venv-chroma`. The
real branch runs only under that venv on Day 5; `import chromadb` is
deferred inside `_query_real` so the mock path needs nothing extra.

Latency is recorded as `latency_ms` in the output JSON. The plan's
sub-second target is gated via `--max-latency-ms` (optional; the Day 5
command does not pass it, so latency is recorded but not gated unless
asked). The ">=1 relevant paper in top-3" check is human review of the
written JSON — not gated by the script, per the plan.

## Notes for Track A on merge

- `git diff --name-only main..worktree-day3-tests` should show only:
  `tests/test_papers_retrieval.py`,
  `tests/test_orchestrator_5_sequential.py`,
  `tests/test_orchestrator_malformed_input.py`,
  `tests/_orchestrator_contract.py`,
  `schema/worker_contract.schema.json`,
  `notes/track-b-day5-6-scaffolds.md`.
- On Day 6, `tests/_orchestrator_contract.py` will pick up the real
  `OrchestratorClient` automatically once `orchestrator/openclaw_runner.py`
  exists — no test edit needed if the assumed API holds. If that file
  exists but fails to import, the tests exit non-zero with the load
  error; they never fall back to the mock over a broken real
  orchestrator (so a broken Day 6 build cannot pass as green).
- The Day 6 command writes test output to `logs/` (e.g.
  `logs/day6_5seq.jsonl`); the `--output` default is a tempdir path so a
  Track B smoke run never writes to `logs/`.
