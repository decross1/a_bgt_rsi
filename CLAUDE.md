# Operating contract for Claude Code

This file is auto-loaded into every Claude Code session in this repo.
It is the operating contract: the rules that don't bend, and the
pointer set for what's being built right now.

New sessions read [`START_HERE.md`](START_HERE.md) first for orientation,
then this file. The active build plan is [`LOOP_V0.md`](LOOP_V0.md).
The current session's working note is the most recent file under
[`human/sessions/`](human/sessions/).

## Operating model (effective 2026-05-26)

**One primary session at a time, plus at most one concurrent UI session.**

- The **primary session** builds the apparatus and runs experiments.
  It can write anywhere except `ui/`.
- The **UI session** (optional, parallel) runs in a separate worktree
  and writes only to `ui/` + `ui_plan.md`. Its prompt is
  [`agent/prompts/ui_session.md`](agent/prompts/ui_session.md).

No other concurrent sessions. No dispatched coding agents. No
multi-worktree per-day matrices. The previous track-A/B/C/D /
autonomy-tier / claim-and-lock machinery has been retired and lives
under [`archive/`](archive/) for historical reference only — do not
treat those files as active rules.

At the start of each working day, the human and the primary session
agree on a session focus and write a working note at
`human/sessions/YYYY-MM-DD.md`. That note is the session's plan; it is
updated at end-of-session with what was actually done and what to do
next.

## How to start a primary session

1. Read this file ([`CLAUDE.md`](CLAUDE.md)) in full.
2. Read [`START_HERE.md`](START_HERE.md).
3. Read [`LOOP_V0.md`](LOOP_V0.md) — the active build plan.
4. Read the most recent file in [`human/sessions/`](human/sessions/)
   — that's the current session's focus and prior-session handoff.
5. Read `run_state/week1.state.json` if you need historical task state.
   (The `week1` naming is a legacy artifact; the file is still the
   authoritative history of completed work. New work logs to the same
   run log: `run_state/week1.run.jsonl`.)
6. If a `human_gates_pending` entry remains in the state file, halt
   on it until the human explicitly clears it.

## How to start the UI session

In a separate terminal:

```bash
env -u MOCK_LLM claude --worktree ui-session
```

Then read [`agent/prompts/ui_session.md`](agent/prompts/ui_session.md).
The UI session writes only to `ui/` and `ui_plan.md`. It does not
touch `run_state/`, `workers/`, `orchestrator/`, `agent_wrapper/`,
or any other path outside `ui/`.

When the UI session has work ready to merge it prints `UI READY TO
MERGE` and the primary session merges from `worktree-ui-session` with
`git merge --no-ff`. If the UI session has gone idle without printing
the sentinel, verbal attestation is acceptable — surface the state to
the user and let them attest.

## Inviolate rules

These do not bend.

1. **No Block 1 help.** Block 1 readings are human-only. If the
   current session note marks a Block 1 reading, print the reading
   and problem set and HALT. Do not execute, assist, summarize,
   derive, or solve the problem set. Block 2 build work proceeds in
   parallel — it is decoupled from whether the human has finished
   today's reading.

2. **Version pins are verbatim.** Canonical list in
   [`ARCHITECTURE.md`](ARCHITECTURE.md) §2. Summary:
   - vLLM image: `vllm/vllm-openai:v0.21.0` (NOT `:gemma4`,
     `:gemma4-cu130`, or `:v0.20.0` — D-022: v0.21.0 enables Gemma 4
     MTP).
   - OpenShell cluster: `ghcr.io/nvidia/openshell/cluster:0.0.13`.
   - CUDA: 13.0 (NOT 13.2 — gibberish on low-bit quants).
   - Embedding: BGE-M3 (NOT all-MiniLM-L6-v2).
   - vLLM MoE backend: `--moe-backend marlin`; startup log MUST
     contain `Using 'MARLIN' NvFp4 MoE backend`. If the log shows
     `CUTLASS_FP4`, the flag did not pick up — STOP.
   - Weights path: `/mnt/models/gemma-4-26b-a4b-nvfp4` (NVFP4, not BF16).

3. **Human gates are blocking.** When the human marks a step as
   needing review (a "gate"), HALT and print the gate notice.
   Clear the gate only when the human explicitly says so.

4. **Validations are never silently coerced.** Each pass/fail check
   stands on its own. "Below band but close" is a failure unless the
   source explicitly bands it as informational. Report mismatches;
   never recode them.

5. **State file is authoritative on resume.** `run_state/week1.state.json`
   records completed work and any pending human gates. Honor pending
   gates across restarts.

6. **Logging is mandatory.** Every executable task appends a row to
   `run_state/week1.run.jsonl`:
   `{timestamp, task_id, status, observable_actual, observable_expected, duration_ms}`.
   State transitions and fallback selections log as first-class entries.

7. **Fallbacks are explicit, logged, and time-capped.** When a
   primary approach fails, switching to a fallback requires: a stated
   time cap, a logged selection, and clear naming. No silent
   degraded paths.

8. **Code-generation is bounded.** Resist abstraction. The wrapper's
   code budget is ~100 lines. A bug fix doesn't need surrounding
   cleanup. A one-shot operation doesn't need a helper. Don't design
   for hypothetical future requirements.

9. **The retrospective and research-journal prose are the human's.**
   Print prompts, append answers verbatim. Do not write, summarize,
   or interpret the human's reflective writing.

10. **`MOCK_LLM` discipline.** `MOCK_LLM=1` is set in the user's shell
    by default; it silently stubs embedders. For any real model or
    pipeline run, prefix commands with `env -u MOCK_LLM`. Memory:
    `mock-llm-track-a-env` (still applicable post-track retirement).

## Out-of-scope guardrails

- Polymarket live trading — design-only until CFTC compliance work
  is done (Phase 2+).
- Continuous-running orchestrator — not yet; LOOP_V0 is single-shot,
  human-triggered iterations.
- Fine-tuning / training runs — not in LOOP_V0.
- Second model — excluded; the apparatus is single-model on
  Gemma 4 26B-A4B-NVFP4 (D-033). Same-model novelty scoring stays
  mitigated by logged human sampling per ARCHITECTURE.md §6 step 6.

## Where things live

| Need | Read |
| --- | --- |
| Orientation | [`START_HERE.md`](START_HERE.md) |
| Active build plan | [`LOOP_V0.md`](LOOP_V0.md) |
| Today's session focus | most recent file in [`human/sessions/`](human/sessions/) |
| Technical architecture | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Project background | [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) |
| Why a decision was made | [`DECISIONS.md`](DECISIONS.md) |
| System diagrams (the spec) | [`docs/diagrams/`](docs/diagrams/) |
| Terminology | [`GLOSSARY.md`](GLOSSARY.md) |
| Run state + run log | `run_state/week1.state.json`, `run_state/week1.run.jsonl` |
| Historical journal entries | [`journal/`](journal/) |
| Retired track/tier docs | [`archive/`](archive/) (reference only) |
