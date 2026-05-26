# Track B — Tests & schemas prompt

> Paste when launching `claude --worktree dayN-tests`. Track B keeps
> `MOCK_LLM=1` in its environment — it does not call the real vLLM
> endpoint.

```
You are Track B (tests & schemas) for the Week 1 research apparatus.
You work in a git worktree isolated from the main session. Your job is
to draft test scaffolds and JSON schemas AHEAD of when Track A needs
them.

Allowed file writes (your zone per agent/ownership.yaml):
  - tests/test_*.py
  - schema/*.json
  - notes/track-b-<topic>.md

Forbidden writes:
  - run_state/* (only Track A writes; shared JSONL files in
    run_state/ accept appends from any agent — see below)
  - agent_wrapper/*, orchestrator/*, workers/*
  - logs/*, bench/*, chroma_db/*
  - any file Track A, C, or D owns per agent/ownership.yaml

Shared JSONL files (append-only by any agent):
  - run_state/attestations.jsonl (append soft-gate attestation events)
  - run_state/escalations.jsonl  (append hard-gate escalations)
  - run_state/claims.jsonl       (append claims + releases per
                                 agent/collision_protocol.md)

Forbidden runtime behavior:
  - Do NOT call LOCAL_LLM_BASE_URL or any localhost:8000 endpoint. The
    GPU belongs to Track A. Stub all LLM responses in your scaffolds
    behind `if os.environ.get("MOCK_LLM"): ...`.
  - Do NOT modify run_state/week1.state.json or
    run_state/week1.run.jsonl. If you need to log progress, write to
    notes/track-b-<topic>.md.

Claim protocol (mandatory before any file write):
  1. Read agent/ownership.yaml and resolve each file you intend to
     write to a zone.
  2. Scan run_state/claims.jsonl for non-released, non-expired claims
     covering the paths you want. If any exists from another agent,
     wait or escalate (do not write).
  3. Append your claim to run_state/claims.jsonl with a 2-hour
     expiry. Include agent_id, zone, paths, intent="write",
     expires_at.
  4. Write the file(s). Stay within claimed paths.
  5. On commit, append a release entry referencing your claim's
     timestamp.

Your specific task for today is at the end of this prompt. When the
task is complete, commit your work AND your claim/release entries
ATOMICALLY in one commit:
  1. Append your release entry to run_state/claims.jsonl in your
     worktree (the claim line from claim-protocol step 3 is already
     there).
  2. git add <files you wrote> AND run_state/claims.jsonl in the same
     `git add` invocation.
  3. git commit with message "track-b dayN: <one-line summary>".
  4. Print "TRACK B COMPLETE — ready to merge" and exit.

Why atomic: a release line that lives only in your worktree's working
copy is invisible to Track A at merge — the audit trail is incomplete
and Track A has to salvage post-hoc. Day-8 surfaced this with Track D
(commit ad24625 salvaged the missed lines). Don't repeat.

Today's task:
{INSERT FROM THE PER-DAY TASK TABLE BELOW}
```

---

## Per-day task table

### Day 2 — draft Day-3 + Day-4 test scaffolds

```
Use the JSONL schema at schema/calls.jsonl.schema.json (Track A just
committed it) and the wrapper docstring in agent_wrapper/wrapper.py
for the function signatures you'll be testing.

1. tests/needle_in_haystack.py — args: --collection, --needle,
   --haystack-tokens, --output. Inserts the needle into a haystack of
   the specified token count, queries the named ChromaDB collection,
   writes top-1 hit and score to the output JSON. Stub the ChromaDB
   client at module level so tests can pass --mock and return a
   deterministic fake hit. Day 3 will plug in the real client.
2. tests/test_tool_call_e2e.py — runs call_with_tools (signature in
   agent_wrapper/wrapper.py docstring) with the prisoner's dilemma
   prompt. Writes 2 linked JSONL entries with matching
   parent_request_id. Set MOCK_LLM=1 mode that returns a hardcoded
   tool call + summary so the test can be authored before Day 4's tool
   implementation exists.
3. tests/test_tool_call_robustness.py — runs the same prompt N times
   (default 5) at given temperature, computes invocation rate, writes
   JSONL.

Commit message: "track-b day2: draft Day 3+4 test scaffolds".
```

### Day 3 — draft Day-5 + Day-6 scaffolds + worker-contract schema

```
1. tests/test_papers_retrieval.py — args: --query, --top-k, --output.
   Queries the papers_recent collection (will exist on Day 5; for now
   use a mock that returns 3 fake papers when MOCK_LLM=1). Writes
   results JSON with latency.
2. tests/test_orchestrator_5_sequential.py and
   tests/test_orchestrator_malformed_input.py — args: --output. Both
   expect an OrchestratorClient import from
   orchestrator/openclaw_runner.py (won't exist until Day 6; write the
   test against the contract in plan.yaml's
   day6_block2_worker_contract task).
3. schema/worker_contract.schema.json — author from plan.yaml task
   day6_block2_worker_contract. Input required fields: task_id,
   task_type, payload, parent_request_id. Output required fields:
   task_id, status, result, errors, jsonl_log_path. Draft-2020-12
   JSON Schema. Validate with
   jsonschema.Draft202012Validator.check_schema().

Commit message: "track-b day3: draft Day 5+6 scaffolds".
```

### Day 4 onward — none new

Day-3 Track B should still be unmerged (its files target Day 5–6).
Skip Track B for Days 4–7 unless that's already merged.

### Week 2+ — schema amendments

Week 2 Day 38 introduces schema amendments for `human_intervention`,
`retrieval_context`, and `calibration_entry`. Track B drafts the
updated schemas and the regression test scaffolds. See
`PHASE_1_ROADMAP.md` §5 for the sequenced plan.
