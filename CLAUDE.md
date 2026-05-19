# Operating contract for Claude Code

New sessions read `START_HERE.md` first for orientation. The canonical
plan is `plan.yaml`. The human-only blocker list is `HUMAN_PLAN.md`. The
parallel-execution orchestration plan is `AGENT_PLAN.md`. The original
source human-readable plan (`week1_days_31-37_plan.md`) is not yet
committed to the repo; until it is, `plan.yaml` plus this contract are
the operative authority — where a summary disagrees with `plan.yaml` on
task content, `plan.yaml` wins.

This file is read by **Track A (Main)** sessions by default. Track B
and Track C sessions receive their own scoped prompts at launch (see
`AGENT_PLAN.md` "Per-track prompts"). If you are not certain which
track you are, you are Track A.

## How to start a Track A session

1. Read this file (`CLAUDE.md`) in full.
2. Read `plan.yaml` preamble + Appendix C.
3. Read `AGENT_PLAN.md` — at minimum the file-boundary rules and the
   "Per-day parallel schedule" section for today.
4. Read `run_state/week1.state.json`. Resume at the first incomplete
   task in `current_day`. Earlier days are not re-run.
5. If `human_gates_pending` is non-empty, do NOT proceed past the gate
   until a human explicitly marks it complete.
6. Append every agent-executable task to `run_state/week1.run.jsonl`
   per the run-log entry schema in `plan.yaml`.

## Inviolate rules

1. **No Block 1.** Every Block 1 task is `human_only: true`. Print the
   reading and problem set, set a wall-clock timer, and HALT. Do not
   execute, assist, summarize, derive, or solve. This rule does not
   bend. There is no "let the agent help just this once" condition.

2. **Version pins are verbatim.**
   - vLLM image: `vllm/vllm-openai:v0.21.0` (NOT `:gemma4`,
     `:gemma4-cu130`, or `:v0.20.0` — see DECISIONS.md D-022; v0.21.0
     enables Gemma 4 MTP speculative decoding).
   - OpenShell cluster: `ghcr.io/nvidia/openshell/cluster:0.0.13`.
   - CUDA: 13.0 (NOT 13.2 — gibberish on low-bit quants).
   - Embedding: BGE-M3 (NOT all-MiniLM-L6-v2).
   - vLLM MoE backend: `--moe-backend marlin`; startup log MUST
     contain `Using 'MARLIN' NvFp4 MoE backend`. If log shows
     `CUTLASS_FP4`, the flag did not pick up — STOP.
   - Weights path: `/mnt/models/gemma-4-26b-a4b-nvfp4` (NVFP4, not BF16).

3. **Human gates are blocking.** The Day 7 publication review gate
   (`day7_publication_review_gate`) is the most important. Do NOT
   auto-publish results. HALT and print the gate notice. Clear the
   gate only when a human explicitly marks it complete.

4. **Validations are never silently coerced.** Each bullet under a
   source "Validation:" line is a separate check with its own
   `pass_signal` / `fail_signal`. Mismatches are reported, never
   recoded. "Below band but close" is a failure unless the source
   explicitly bands it as informational.

5. **State file is authoritative on resume.** At startup read
   `run_state/week1.state.json`. `human_gates_pending` is honored
   across restarts.

6. **Hard checkpoints abort the day.** Tasks tagged
   `hard_checkpoint: true` write `day_aborted` to the run log on
   failure and halt the day. The next day's Block 2 is gated on the
   prior day's success unless the source explicitly allows continuation.

7. **Fallbacks are explicit, logged, and time-capped.** NemoClaw →
   plain Docker (90-min cap, Day 1). ML-Intern → direct Semantic
   Scholar API (45-min cap, Day 5). OpenClaw+NemoClaw → Python
   multiprocessing (Day 6). Each fallback selection writes to
   `state.fallbacks_taken`.

8. **Logging is mandatory.** Every agent-executable task appends to
   `run_state/week1.run.jsonl` with `{timestamp, day_id, task_id,
   status, observable_actual, observable_expected, duration_ms}`.
   State transitions and fallback selections log as their own entries.

9. **Code-generation is bounded.** Tasks marked `agent_assisted` with
   `command: null` indicate the agent prepares scaffolding only; the
   human (or a sub-agent with explicit file-write authority) writes
   the implementation. Resist abstraction — the wrapper's code budget
   is ~100 lines.

10. **The retrospective is the human's.** On Day 7 print the
    retrospective questions and append the human's answers to the run
    log. Do NOT write, summarize, or interpret the retrospective.

## Parallel-track rules (Track A)

Track A is the only track that may:

- Write to `run_state/`, `logs/`, `bench/`, `chroma_db/`,
  `agent_wrapper/`.
- Call `LOCAL_LLM_BASE_URL` (the vLLM endpoint).
- Make end-of-day commits and tag releases.
- Clear human gates (only after the human explicitly attests).
- Decide whether to merge or discard a side-track branch.

If a Track B or C session has finished and printed `TRACK <X> COMPLETE
— ready to merge`:

1. Verify file boundaries were respected (`git diff --name-only
   main..worktree-<branch>` should show only files in that track's
   allowed list).
2. Merge with `git merge --no-ff worktree-<branch>` from the main
   checkout.
3. Run validation tests on the merged files before consuming them in
   today's task.
4. If validation fails, Track A's version of any conflicting file
   wins; discard the side track's conflicting edits with `git checkout
   --ours <path>`.

If a side track has gone idle without printing the completion message,
do not merge it. Treat it as work-in-progress that needs the human's
attention.

## Things that are NOT in scope for Week 1

- Polymarket API calls (design-only in Phase 1).
- Autoresearch overnight runs (Week 2+).
- Second model — Qwen 3.6 deferred to Week 2–3.
- Concurrency in workers — sequential only on Day 6.
- Fully autonomous loop — Day 7 result requires human review.
- Fine-tuning.
- Week 2 planning is a separate task; do not begin it after the Day 7
  retrospective even if asked.
