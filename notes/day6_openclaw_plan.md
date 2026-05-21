# Day 6 — OpenClaw orchestrator install plan

**Pre-staged Day 5 EOD for `day6_block2_orchestrator_*`. Decision:
attempt OpenClaw; fall back to Python `multiprocessing` if the
OpenClaw + NemoClaw integration does not come up.**

## Day 6's first task is NOT the orchestrator

`day6_block2_worker_contract` runs first and is a **hard checkpoint**.
It is `command: null` / human-assisted: the human sketches the worker
contract on paper, then authors `schema/worker_contract.schema.json`.
The contract is fixed:

- **input**  — `{task_id, task_type, payload, parent_request_id}` (exactly these four)
- **output** — `{task_id, status, result, errors, jsonl_log_path}` (exactly these five)

The agent only validates the schema (valid Draft 2020-12; the two
`required` arrays match the field lists above). Get this wrong and
everything downstream pays — do not paper over it.

## Orchestrator: attempt OpenClaw, fall back to multiprocessing

`day6_block2_orchestrator_router` decides the path:

```
nemoclaw status 2>/dev/null | grep -q healthy || echo "fallback"
```

- **on_success → `day6_block2_orchestrator_with_nemoclaw`** — install
  OpenClaw per its README, run workers in NemoClaw sandbox containers.
- **on_failure / on_timeout (10 min) → `day6_block2_orchestrator_with_fallback`**
  — Python `multiprocessing` for orchestration; sandbox isolation is
  re-added in Week 2 (CLAUDE.md inviolate rule 7).

### Expectation: the fallback path is likely

`state.fallbacks_taken.day1_nemoclaw` = *"NemoClaw onboarding skipped
(binary not installed) — hardened plain-Docker fallback verified
working."* NemoClaw was never installed on Day 1, so the router's
`nemoclaw status` probe will almost certainly fail and route to the
Python-`multiprocessing` fallback. That is an expected, logged path,
not a defect — but the human may choose to install NemoClaw first if
sandbox isolation is wanted on Day 6 rather than Week 2.

## Version pins (inviolate — verbatim)

- OpenShell cluster image: `ghcr.io/nvidia/openshell/cluster:0.0.13`.
- If OpenClaw is installed, **pin its version** in the launch script
  (same discipline as the vLLM image digest, D-017).

## The one Day-6 task type

`summarize_paper(arxiv_id)` — the worker retrieves the abstract from the
`papers_recent` ChromaDB collection (built today, Day 5 — 138 papers),
asks Gemma 4 via `agent_wrapper/wrapper.py` to summarize it in ~100
words, and returns the summary. Success criterion: one worker, one task,
end-to-end, with 3 linked JSONL entries (orchestrator dispatch → worker
invocation → orchestrator receipt) sharing a `parent_request_id` chain,
and a 60-second worker timeout.

## Carry-over note for Day 6 — `papers_recent` location

The Day-5 `papers_recent` collection lives in **this worktree's**
`chroma_db/` (`.claude/worktrees/day5-main/chroma_db/`), which is
git-ignored (only `chroma_db/manifest.json` is tracked). A Day-6 session
in a fresh worktree will not see it. Options for Day 6: run from the
`day5-main` worktree, point `--db-path` at it, or re-run
`cron/daily-arxiv.sh` / the Day-5 pipeline to rebuild the collection in
the Day-6 working directory. Decide this before `summarize_paper` needs
the abstracts.

## Selection record (filled after the Day-6 router fires)

| Step | Status | Notes |
| ---- | ------ | ----- |
| `nemoclaw status` probe | TBD | Day-6 morning |
| OpenClaw install per README (if NemoClaw healthy) | TBD | pin the version |
| If router → fallback: Python `multiprocessing` orchestrator | TBD | log to `state.fallbacks_taken` |
