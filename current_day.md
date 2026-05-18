# Current day — day_1: hardware online, stack verified

_Active-day tracker. Authoritative plan: `plan.yaml`. State:
`run_state/week1.state.json`. Run log: `run_state/week1.run.jsonl`._

**Day goal:** vLLM serves Gemma 4 26B MoE; curl returns coherent text;
tokens/sec recorded; NemoClaw onboarded or fallback logged.

**Status as of 2026-05-18:** ✅ **Day 1 complete.** vLLM v0.20.0 serves
Gemma 4 on `localhost:8000`; all Block 2 tasks closed; journal stub +
end-of-day artifacts committed. Next: Day 2 (Python wrapper + JSONL
logging) — start deliberately. NOTE: bench was 32 tok/s, below the 40
floor — human-accepted as the Day-1 baseline (see below).

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
| 3 | `day1_block2_unbox` | no | ✅ passed — ping 10.0.0.73 ok |
| 4 | `day1_block2_firmware` | **yes** | ✅ passed — GB10, CUDA 13.0, 5 W idle |
| 5 | `day1_block2_docker_config` | no | ✅ passed — cron + cgroupns (plan bug noted) |
| 6 | `day1_block2_vllm_serve` | **yes** | ✅ passed — vLLM v0.20.0 serving; MARLIN MoE; curl ok 1.45 s |
| 7 | `day1_block2_bench` | no | ⚠️ 32 tok/s — below 40 floor; human-accepted as Day-1 baseline |
| 9 | `day1_block2_nemoclaw_router` | no | ✅ probe → plain-Docker fallback branch |
| 10 | `day1_block2_nemoclaw_primary` | no | ⏭️ skipped (router branched to fallback) |
| 11 | `day1_block2_nemoclaw_fallback` | no | ✅ passed — hardened Docker sandbox verified |

## Block 3 / end of day

| # | Task | Status |
|---|------|--------|
| 8 | `day1_block3_journal` | ✅ stub generated — `journal/day1.md` |
| 12 | `day1_end_of_day_artifacts` | ✅ artifacts committed |

## Day 1 complete — next steps

**Day 1 is done.** All pre-flight, Block 1, and Block 2 tasks closed;
journal stub + end-of-day artifacts committed. vLLM v0.20.0 serves
Gemma 4 on `localhost:8000`. `state.json current_day` left at `day_1`
— advance to `day_2` deliberately when starting Day 2.

Carried into Day 2 / later:

1. **Day 2** — Python wrapper around vLLM; every call writes
   schema-valid JSONL; determinism verified. Day 2's Block 2 was gated
   on Day 1's vLLM server — now satisfied.
2. **tok/s 32 vs plan floor 40** — accepted as the Day-1 baseline;
   throughput tuning is an optimization-pass item (`notes/day1-bench-debug.md`).
3. **MTP** — deferred to Week 2+ (D-019).
4. **`plan.yaml` validation fixes** — `day1_block2_docker_config` and
   `day1_block2_vllm_serve` check #2 (see Plan bugs below).

## Plan bugs found (Block 2)

- `day1_block2_docker_config`: the command writes an invalid
  `daemon.json` key `cgroupns` (dockerd rejects it) — corrected to
  `default-cgroupns-mode` in `setup/day1_docker_config.sh`. Its
  validation `docker info | grep -i cgroup` → `host` also cannot pass:
  `docker info` never reports cgroup namespace mode. Both warrant a
  `plan.yaml` fix (pending human approval).
- `day1_block2_vllm_serve`: (a) the original pinned image
  `:gemma4-cu130` (vLLM 0.19.1.dev6) could not load the NVFP4
  checkpoint — re-pinned to `:v0.20.0` (D-020). (b) MTP deferred to
  Week 2+ — needs a post-PR-#41745 image (D-019). (c) v0.20.0 needs
  `--max-num-batched-tokens 8192` (multimodal MM-budget). (d) validation
  check #2 expects a `FLASHINFER_CUTLASS for NVFP4 GEMM` log line the
  GB10 never emits (no native FP4, SM12x) — needs correcting in `plan.yaml`.

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
- 2026-05-18: Block 2 #3 (unbox) passed — ping 10.0.0.73 3/3, 0% loss;
  #4 (firmware) passed — nvidia-smi GB10 / CUDA 13.0 / 5 W idle; #5
  (docker_config) passed with a noted plan bug — invalid daemon.json
  key `cgroupns` corrected to `default-cgroupns-mode`; docker daemon up.
- 2026-05-18: task #6 — MTP launch failed (image predated PR #41745);
  baseline launch on `:gemma4-cu130` also failed (NVFP4 expert
  `input_scale` KeyError); `day_1` aborted, then recovered. vLLM image
  re-pinned `:gemma4-cu130` → `:v0.20.0` (human-authorized, D-020);
  v0.20.0 serves Gemma 4 (MARLIN MoE, curl ok 1.45 s) — task #6 passed,
  abort lifted. MTP deferred to Week 2+ (D-019). Re-pin applied across
  `plan.yaml` / `CLAUDE.md` / `infra/bookmarks.txt` / docs.
- 2026-05-18: Day 1 closed — #7 bench 32 tok/s logged as a fault then
  human-accepted as the Day-1 baseline; #9 router → plain-Docker
  fallback; #11 fallback verified (seccomp + no-new-privileges +
  cap-drop); #8 journal stub written (`journal/day1.md`); #12
  end-of-day artifacts committed. **Day 1 complete.**
- 2026-05-18: post-Day-1 `plan.yaml` corrections applied (human-approved,
  3 of the "Plan bugs found" items): (1) `researcher` field `huchi` →
  `decross1`; (2) `day1_block2_vllm_serve` command gains
  `--max-num-batched-tokens 8192` (84c); (3) the un-passable
  `FLASHINFER_CUTLASS for NVFP4 GEMM` startup-log check removed from the
  task #6 `expected_observable` and `validation` blocks (84d) — GB10/SM12x
  has no native FP4, so vLLM uses the Marlin weight-only path and never
  emits that line; the MARLIN MoE-backend check remains. Still open: the
  authoritative source plan `week1_days_31-37_plan.md` referenced by
  `CLAUDE.md`/`plan.yaml` is not in the repo — needs to be committed or
  the contract amended to name `plan.yaml` canonical (human decision).
