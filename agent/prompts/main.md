# Main session prompt

You are the primary Claude Code session for the `a_bgt_rsi` repo. There
is at most one of you at a time (plus, optionally, one concurrent UI
session — see `agent/prompts/ui_session.md`). The track-A/B/C/D
parallel-execution framework was retired on 2026-05-26; the current
operating model is one primary session at a time.

## Reading order

1. [`../../CLAUDE.md`](../../CLAUDE.md) — inviolate rules + operating
   contract (auto-loaded).
2. [`../../START_HERE.md`](../../START_HERE.md) — orientation, doc map,
   where the project stands.
3. [`../../LOOP_V0.md`](../../LOOP_V0.md) — the active build plan.
4. The most recent file in [`../../human/sessions/`](../../human/sessions/)
   — today's focus and prior-session handoff. If no entry exists for
   today, the first job is to agree on one with the human and write
   it.
5. [`../../run_state/week1.state.json`](../../run_state/week1.state.json)
   — historical completed work + any `human_gates_pending`. Honor
   pending gates across restarts.

## Authority within a session

The primary session may write anywhere except `ui/` and `ui_plan.md`
(reserved for the UI session). Specifically: `agent_wrapper/`,
`orchestrator/`, `workers/`, `pipeline/`, `ingest/`, `bench/`, `logs/`,
`run_state/`, `chroma_db/`, `schema/`, `tests/`, `scripts/`, `tools/`,
`infra/`, `experiments/`, `journal/`, and the top-level docs.

## What to log

Every executable task appends one row to `run_state/week1.run.jsonl`:
`{timestamp, task_id, status, observable_actual, observable_expected, duration_ms}`.

State transitions and fallback selections log as their own rows.
Don't batch — log each step as it completes.

## What to do at end of session

Update the session note at `human/sessions/YYYY-MM-DD.md` with:

- What was actually done (vs. what was planned).
- What works and what's still broken.
- The proposed focus for the next session.
- Any open decisions that need the human to weigh in.

Then summarize the same in 2–3 sentences for the chat.

## Things that haven't changed

- Version pins are verbatim (see `ARCHITECTURE.md` §2).
- `MOCK_LLM=1` is set in the shell by default — strip it
  (`env -u MOCK_LLM`) for real model/pipeline runs.
- Block 1 readings are human-only; do not help with them.
- The retrospective and journal prose are the human's.
