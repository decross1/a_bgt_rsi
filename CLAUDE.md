# Operating contract for Claude Code

The authoritative plan is `plan.yaml`. Read its preamble before parsing
the frontmatter. The source human-readable plan is
`week1_days_31-37_plan.md`; discrepancies resolve in favor of the source.

## How to start a session

1. Read `plan.yaml` preamble + Appendix C (these rules, restated).
2. Read `run_state/week1.state.json`. Resume at the first incomplete
   task in `current_day`. Earlier days are not re-run.
3. If `human_gates_pending` is non-empty, do NOT proceed past the gate
   until a human explicitly marks it complete.
4. Append every agent-executable task to `run_state/week1.run.jsonl`
   per the run-log entry schema in `plan.yaml`.

## Inviolate rules

1. **No Block 1.** Every Block 1 task is `human_only: true`. Print the
   reading and problem set, set a wall-clock timer, and HALT. Do not
   execute, assist, summarize, derive, or solve. This rule does not
   bend. There is no "let the agent help just this once" condition.

2. **Version pins are verbatim.**
   - vLLM image: `vllm/vllm-openai:gemma4-cu130` (NOT `:gemma4`).
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

## Things that are NOT in scope for Week 1

- Polymarket API calls (design-only in Phase 1).
- Autoresearch overnight runs (Week 2+).
- Second model — Qwen 3.6 deferred to Week 2–3.
- Concurrency — sequential workers only on Day 6.
- Fully autonomous loop — Day 7 result requires human review.
- Fine-tuning.
