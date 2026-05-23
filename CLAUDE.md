# Operating contract for Claude Code

New sessions read `START_HERE.md` first for orientation. The canonical
plan is `plan.yaml`. The human-facing daily plan is
[`human/daily_plan.md`](human/daily_plan.md). The parallel-execution
orchestration is [`agent/orchestration.md`](agent/orchestration.md);
the autonomy framework (tiers, SLAs, alignment) is
[`agent/autonomy.md`](agent/autonomy.md); the file-ownership registry
is [`agent/ownership.yaml`](agent/ownership.yaml); the claim/lock
protocol is [`agent/collision_protocol.md`](agent/collision_protocol.md).
The 30/60/90-day roadmap is [`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md).
The terminology reference is [`GLOSSARY.md`](GLOSSARY.md).

The original source human-readable plan (`week1_days_31-37_plan.md`)
is not yet committed to the repo; until it is, `plan.yaml` plus this
contract are the operative authority — where a summary disagrees with
`plan.yaml` on task content, `plan.yaml` wins.

This file is read by **Track A (Main)** sessions by default. Track B,
C, and D sessions receive their own scoped prompts at launch (see
[`agent/prompts/`](agent/prompts/)). If you are not certain which
track you are, you are Track A.

## How to start a Track A session

1. Read this file (`CLAUDE.md`) in full.
2. Read [`agent/autonomy.md`](agent/autonomy.md) for tier semantics
   (every task in `plan.yaml` carries an `autonomy_tier`).
3. Read [`agent/ownership.yaml`](agent/ownership.yaml) and
   [`agent/collision_protocol.md`](agent/collision_protocol.md) for
   file-write rules.
4. Read `plan.yaml` preamble + Appendix C, then today's day section.
5. Read [`agent/orchestration.md`](agent/orchestration.md) — at minimum
   the file-boundary rules and the per-day parallel schedule.
6. Read `run_state/week1.state.json`. Resume at the first incomplete
   task in `current_day`. Earlier days are not re-run.
7. If `human_gates_pending` is non-empty, do NOT proceed past the gate
   until a human explicitly marks it complete.
8. Append every agent-executable task to `run_state/week1.run.jsonl`
   per the run-log entry schema in `plan.yaml`.

## Inviolate rules

These rules **do not bend** regardless of phase boundary, alignment
evidence, or task pressure.

1. **No Block 1.** Every Block 1 task is `human_only: true` and tier
   `hard_gate` with no SLA. Print the reading and problem set, set a
   wall-clock timer, and HALT. Do not execute, assist, summarize,
   derive, or solve. There is no "let the agent help just this once"
   condition.

   Block 1 is **decoupled** from Block 2 in `plan.yaml`. The agent
   proceeds on Block 2 work regardless of whether the human has
   finished today's reading. Tasks that require human understanding
   for their *content* (not as background) carry
   `requires_human_understanding: true` and stay hard-gate — see
   [`agent/autonomy.md`](agent/autonomy.md) §7.

2. **Version pins are verbatim.** Canonical list in
   [`ARCHITECTURE.md`](ARCHITECTURE.md) §2. Summary:
   - vLLM image: `vllm/vllm-openai:v0.21.0` (NOT `:gemma4`,
     `:gemma4-cu130`, or `:v0.20.0` — D-022: v0.21.0 enables Gemma 4
     MTP).
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
   gate only when a human explicitly marks it complete. Hard-gates
   carry a 48h SLA after which the agent escalates but stays halted
   (see [`agent/autonomy.md`](agent/autonomy.md) §2). The publication
   gate has no auto-clear — it never expires.

4. **Validations are never silently coerced.** Each bullet under a
   `validation:` block is a separate check with its own `pass_signal`
   / `fail_signal`. Mismatches are reported, never recoded. "Below
   band but close" is a failure unless the source explicitly bands it
   as informational.

5. **State file is authoritative on resume.** At startup read
   `run_state/week1.state.json`. `human_gates_pending` is honored
   across restarts. Track A is the only writer for the state file
   and `run_state/week1.run.jsonl`. Other agents append to shared
   JSONL files (`attestations.jsonl`, `escalations.jsonl`,
   `claims.jsonl`).

6. **Hard checkpoints abort the day.** Tasks tagged
   `hard_checkpoint: true` write `day_aborted` to the run log on
   failure and halt the day. The next day's Block 2 is gated on the
   prior day's success unless the source explicitly allows continuation.
   A failed hard-gate that's salvageable can also declare a **slip**
   (`current_subday = N.1`); see
   [`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md) §2.

7. **Fallbacks are explicit, logged, and time-capped.** NemoClaw →
   plain Docker (90-min cap, Day 1). ML-Intern → direct Semantic
   Scholar API (45-min cap, Day 5). OpenClaw+NemoClaw → Python
   multiprocessing (Day 6). Each fallback selection writes to
   `state.fallbacks_taken`.

8. **Logging is mandatory.** Every agent-executable task appends to
   `run_state/week1.run.jsonl` with `{timestamp, day_id, task_id,
   status, observable_actual, observable_expected, duration_ms}`.
   State transitions, fallback selections, tier shifts, slip
   declarations, and dispatch events log as their own first-class
   entries.

9. **Code-generation is bounded.** Tasks marked `agent_assisted` with
   `command: null` indicate the agent prepares scaffolding only; the
   human (or a sub-agent with explicit file-write authority) writes
   the implementation. Resist abstraction — the wrapper's code budget
   is ~100 lines.

10. **The retrospective is the human's.** On Day 7 print the
    retrospective questions and append the human's answers to the run
    log. Do NOT write, summarize, or interpret the retrospective.
    The weekly retrospective is the alignment-evidence record that
    gates phase-boundary advances — see
    [`agent/autonomy.md`](agent/autonomy.md) §4.

## Autonomy posture (governed by `agent/autonomy.md`)

Every task in `plan.yaml` carries an `autonomy_tier` of `autonomous`,
`soft_gate`, or `hard_gate`. Tier semantics, SLAs, phase-aware
boundaries, and alignment-evidence definitions are in
[`agent/autonomy.md`](agent/autonomy.md). The Week-1 inviolate rules
above are tier-independent — they apply at all tiers.

Trust trajectory: start at the tiered + phase-aware posture; expand
toward trust-by-default as the UI proves it can show the human what
the system is doing. Autonomy unlocks are gated on alignment evidence,
not calendar dates.

## Parallel-track rules (Track A)

Track A is the only track that may:

- Write to `run_state/week1.state.json` and `run_state/week1.run.jsonl`.
- Write to `logs/`, `bench/`, `chroma_db/`, `agent_wrapper/`,
  `orchestrator/`, `workers/` (its primary zones per
  [`agent/ownership.yaml`](agent/ownership.yaml)).
- Call `LOCAL_LLM_BASE_URL` (the vLLM endpoint).
- Make end-of-day commits and tag releases.
- Clear human gates (only after the human explicitly attests).
- Decide whether to merge or discard a side-track branch.
- Apply tier shifts when alignment evidence clears (see
  [`agent/autonomy.md`](agent/autonomy.md) §4.2).

If a Track B, C, or D session has finished and printed `TRACK <X>
COMPLETE — ready to merge`:

1. Verify file boundaries were respected (`git diff --name-only
   main..worktree-<branch>` should show only files in that track's
   zone per [`agent/ownership.yaml`](agent/ownership.yaml)).
2. Merge with `git merge --no-ff worktree-<branch>` from the main
   checkout.
3. Run validation tests on the merged files before consuming them in
   today's task.
4. If validation fails, Track A's version of any conflicting file
   wins; discard the side track's conflicting edits with `git checkout
   --ours <path>`.

If a side track has gone idle without printing the completion message,
the sentinel is advisory — accept verbal attestation from the
auditor's MERGE decision (memory: `sidetrack-sentinel-attestation`).
Do not silently merge mid-flight work.

## Things that are NOT in scope for Week 1

- Polymarket API calls (design-only in Phase 1).
- Autoresearch overnight runs (Week 2+).
- Second model — Qwen 3.6 deferred to Week 2–3.
- Concurrency in workers — sequential only on Day 6.
- Fully autonomous loop — Day 7 result requires human review.
- Fine-tuning.
- Week 2 planning execution is post-Day-7; the **detailed plan**
  for Week 2 lives in [`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md) §5
  and is read-only for Week 1.
