# Current day — day_1: hardware online, stack verified

_Active-day tracker. Authoritative plan: `plan.yaml`. State:
`run_state/week1.state.json`. Run log: `run_state/week1.run.jsonl`._

**Day goal:** vLLM serves Gemma 4 26B MoE; curl returns coherent text;
tokens/sec recorded; NemoClaw onboarded or fallback logged.

**Status as of 2026-05-18:** all Day 1 pre-flight + Block 1 complete.
Block 2 — the technical build (hardware, vLLM, benchmark) — NOT yet run.

## Pre-flight

| Task | Type | Status |
|------|------|--------|
| `preflight_credentials_staged` | agent | ✅ passed — 5 keys in `~/.config/bgt_rsi/secrets` |
| `preflight_software_prestaged` | agent (hard checkpoint) | ✅ passed — 3 bookmarks, 4 clones, 3 model dirs |
| `preflight_failure_walkthroughs` | human-only | ✅ done (human attestation 2026-05-18) |
| `preflight_physical_setup` | human-only | ✅ done (human attestation 2026-05-18) |

## Block 1 — Foundations (human-only, NO AI)

> HALT. Reading: O&R *A Course in Game Theory* Ch. 6 §6.1–6.3.
> Problem set: O&R 6.1, 6.2, 6.3 — pen and paper, by hand.
> Claude does not assist, summarize, or solve. Mark complete only after
> the time window elapses.

✅ `day1_block1_reading` + `day1_block1_problemset` marked complete by
human attestation, 2026-05-18 — no AI involvement.

## Block 2 — Build (agent-executable)

| # | Task | Hard checkpoint | Status |
|---|------|-----------------|--------|
| 3 | `day1_block2_unbox` | no | ⬜ blocked on pre-flight |
| 4 | `day1_block2_firmware` | **yes** | ⬜ |
| 5 | `day1_block2_docker_config` | no | ⬜ |
| 6 | `day1_block2_vllm_serve` | **yes** | ⬜ |
| 7 | `day1_block2_bench` | no | ⬜ |
| 9 | `day1_block2_nemoclaw_router` | no | ⬜ |
| 10 | `day1_block2_nemoclaw_primary` | no | ⬜ |
| 11 | `day1_block2_nemoclaw_fallback` | no | ⬜ |

## Block 3 / end of day

| # | Task | Status |
|---|------|--------|
| 8 | `day1_block3_journal` | ⬜ |
| 12 | `day1_end_of_day_artifacts` | ⬜ |

## Open blockers / next steps

Pre-flight (all 4 tasks) and Block 1 are complete. **Day 1 Block 2 —
the technical build — has NOT been run.** It is the real Day 1 work and
remains entirely pending:

1. **Block 2 agent tasks #3–#12 unrun** — hardware verify (`nvidia-smi`,
   dashboard reachability), Docker config, vLLM serve (HARD CHECKPOINT),
   tok/s benchmark, NemoClaw onboarding, end-of-day artifacts. None
   executed; none can be marked done without actually running them.
2. **`infra/vllm_patches/gemma4_mtp.py` not staged** — must be fetched
   from vLLM PR #41745 head before `day1_block2_vllm_serve` (task #6).
3. **Day 2 is gated on Day 1's vLLM server** — Day 2's 50-call sweep
   needs the running endpoint, so Day 2 cannot start until Block 2's
   vLLM hard checkpoint passes.

## Decisions log

- 2026-05-18: `/mnt/models` chosen as the shared cross-project model
  store on the DGX Spark (owner `decross1`, mode 755 — readable by other
  processes and by container `:ro` bind mounts).
- 2026-05-18: stale `human_gates_pending` entry cleared after
  `preflight_credentials_staged` passed; moved to `completed_tasks`.
- 2026-05-18: `clones/dgx-spark-playbooks` and `clones/open_spiel`
  cloned successfully.
- 2026-05-18: applied human-approved MTP / model-stack update to
  `plan.yaml` (6 edits — weights size ~19 GB, MTP drafter pinned,
  `day1_block2_vllm_serve` launch + validation extended, tok/s band
  → [80, 130], Appendix C + `infra/bookmarks.txt` updated).
- 2026-05-18: `/mnt/models` created (sudo; owner decross1, mode 755);
  staged gemma-4-26b-a4b-nvfp4 (18 GB), bge-m3 (4.3 GB), and the
  gemma-4-26b-a4b-it-assistant MTP drafter (832 MB) via huggingface_hub
  (`.venv-staging`).
- 2026-05-18: cloned the final 2 repos per human decision —
  `clones/autoresearch` = karpathy/autoresearch (substitutes the plan's
  matt-langston/autoresearch), `clones/game-reasoning-arena` =
  SLAMPAI/game_reasoning_arena. `preflight_software_prestaged` passed
  (exit 0); task #2 complete.
- 2026-05-18: human-only tasks marked complete by human attestation
  (decross1) — preflight_failure_walkthroughs, preflight_physical_setup,
  day1_block1_reading, day1_block1_problemset. Recorded in state file +
  run log. Day 1 Block 2 (the technical build) remains unrun.
