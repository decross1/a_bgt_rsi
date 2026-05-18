# Current day — day_1: hardware online, stack verified

_Active-day tracker. Authoritative plan: `plan.yaml`. State:
`run_state/week1.state.json`. Run log: `run_state/week1.run.jsonl`._

**Day goal:** vLLM serves Gemma 4 26B MoE; curl returns coherent text;
tokens/sec recorded; NemoClaw onboarded or fallback logged.

**Status as of 2026-05-18:** pre-flight in progress; Block 2 not started.

## Pre-flight

| Task | Type | Status |
|------|------|--------|
| `preflight_credentials_staged` | agent | ✅ passed — 5 keys in `~/.config/bgt_rsi/secrets` |
| `preflight_software_prestaged` | agent (hard checkpoint) | ⏳ failing — see blockers |
| `preflight_failure_walkthroughs` | human-only | ⬜ pending |
| `preflight_physical_setup` | human-only | ⬜ pending |

## Block 1 — Foundations (human-only, NO AI)

> HALT. Reading: O&R *A Course in Game Theory* Ch. 6 §6.1–6.3.
> Problem set: O&R 6.1, 6.2, 6.3 — pen and paper, by hand.
> Claude does not assist, summarize, or solve. Mark complete only after
> the time window elapses.

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

## Open blockers

1. **`preflight_software_prestaged` failing:**
   - `clones/autoresearch` — clone needs auth (private repo or wrong URL). Unresolved.
   - `clones/game-reasoning-arena` — repo URL unknown. Unresolved.
   - `/mnt/models` — to be created on this DGX Spark as a shared, cross-project model store.
   - Models not yet downloaded: `gemma-4-26b-a4b-nvfp4` (~19 GB),
     `bge-m3` (~1–2 GB), `gemma-4-26b-a4b-it-assistant` MTP drafter (~870 MB).
2. **`infra/vllm_patches/gemma4_mtp.py` not staged** — the MTP bugfix
   file must be fetched from vLLM PR #41745 head before
   `day1_block2_vllm_serve` (task #6) can run. See
   `infra/vllm_patches/README.md`.

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
