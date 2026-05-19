# Track B — Day 3+4 test scaffolds

Drafted in worktree `day2-tests` (branch `worktree-day2-tests`, off
`3eb31ed`). Three deliverables, all runnable today in mock mode:

| File | Day | Mock switch |
|------|-----|-------------|
| `tests/needle_in_haystack.py`      | 3 | `--mock` (stubs ChromaDB) |
| `tests/test_tool_call_e2e.py`      | 4 | `MOCK_LLM=1` |
| `tests/test_tool_call_robustness.py` | 4 | `MOCK_LLM=1` |

Smoke-tested in mock mode: all three pass. The 8 mock JSONL records
emitted by the Day-4 scaffolds were validated against Track A's real
`calls.jsonl.schema.json` (read out of commit `b6fba26`) — all valid.

## Discrepancies found vs. the task brief

1. **`schema/calls.jsonl.schema.json` is not on this worktree branch.**
   Only `schema/.gitkeep` is present here. Track A *did* commit the
   schema, but in `b6fba26` ("day 2: wrapper + JSONL schema + 50-call
   sweep"), which is on the **main repo's** `main` — not this worktree,
   which branched earlier. The scaffolds therefore validate against the
   schema **only if the file is present**, and fall back to a structural
   required-fields check otherwise. Once Track A's work merges into this
   branch, full schema validation activates automatically — no code
   change needed. The 14 required fields are mirrored as `_REQUIRED_FIELDS`
   in each Day-4 test.

2. **`call_with_tools` has no published signature.** The wrapper
   docstring only reserves the name: "Day 4 adds: call_with_tools (max
   recursion depth 3)." There is no parameter list to test against, so
   the scaffolds *assume* a contract. Every assumption is tagged
   `DAY4-CONTRACT` in the source — `grep -rn DAY4-CONTRACT tests/`.

3. **The call schema cannot represent a tool call directly.** Track A's
   `calls.jsonl.schema.json` has `additionalProperties: false`, a plain
   string `completion`, and no `tool_calls` field — but its message
   `role` enum *does* include `"tool"`. The scaffolds therefore model a
   tool round-trip as **two linked call records**: the tool result rides
   in the second record's `prompt_messages` under `role: "tool"`. If
   Day 4 instead adds a `tool_calls` field, the schema and these
   scaffolds both need updating. Flagging for Track A.

## Assumed `call_with_tools` contract (DAY4-CONTRACT)

```
call_with_tools(messages, tools, *, temperature=0.0, top_p=1.0, seed=None,
                max_tokens=None, caller_tag="unspecified",
                parent_request_id=None, log_path=None, model=None,
                max_depth=3)
```

- `tools`: list of `{"spec": <openai-tool-schema>, "impl": <callable>}`.
  The wrapper needs the callables, not just the JSON specs, to execute
  tools — so the scaffolds pair each spec with its `impl`.
- Writes one schema-valid JSONL record **per model call** in the chain
  to `log_path` (same as `call_sync`). A single tool round-trip ⇒ 2
  records.
- Chain linkage: the follow-up call's `parent_request_id` equals the
  initiating call's `request_id`; the first call's is `null`.
- `max_depth=3` matches the wrapper docstring's "max recursion depth 3".

The tests do **not** depend on `call_with_tools`' return value — they
read the JSONL log back. A run "invoked a tool" iff any of its records
carries a `role: "tool"` message. This keeps the tests robust to
whatever return shape Day 4 actually picks. If Day 4 diverges from the
above, update the `DAY4-CONTRACT`-tagged lines.

## Day-3 caveat for `needle_in_haystack.py`

`get_chroma_client(mock=False)` raises `NotImplementedError` — Day 3
must implement it. **Critical:** create the collection with an explicit
**BGE-M3** embedding function. ChromaDB's default embedder is
`all-MiniLM-L6-v2`, which CLAUDE.md inviolate-rule #2 forbids. Do not
let `get_or_create_collection` fall back to the default.

Token counts in the haystack builder are whitespace approximations;
Day 3 may want the real tokenizer for parity with embedding chunking.
The mock client ranks chunks by word overlap, so pass a needle-derived
`--query` to retrieve the needle; for a genuine recall test Day 3
should pass a paraphrased `--query`.

## Scope adherence

Files written: `tests/needle_in_haystack.py`,
`tests/test_tool_call_e2e.py`, `tests/test_tool_call_robustness.py`,
`notes/track-b-day3-4-scaffolds.md`. No writes to `run_state/`,
`agent_wrapper/`, `logs/`, `bench/`, `chroma_db/`, or `schema/`. No
calls to the vLLM endpoint. The day was not advanced.
