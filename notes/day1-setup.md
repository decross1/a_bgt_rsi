# Day 1 setup notes — 2026-05-18

DGX Spark `spark-7eeb`, user `decross1`, LAN IP `10.0.0.73`.
Authoritative record: `run_state/week1.run.jsonl`. Rationale: `DECISIONS.md`.

## What was done

- **Pre-flight** — 5 API credentials staged (`~/.config/bgt_rsi/secrets`);
  4 repos cloned to `clones/`; 3 models staged to `/mnt/models/`
  (Gemma 4 NVFP4 ~18 GB, BGE-M3 ~4.3 GB, MTP drafter ~832 MB).
- **Block 2 #3–#5** — DGX dashboard reachable; `nvidia-smi` shows GB10 /
  CUDA 13.0 / 5 W idle; Docker set to `default-cgroupns-mode: host` with
  a 30-min `drop_caches` cron.
- **Block 2 #6 — vLLM serving** — after two failures on the original pin
  (`:gemma4-cu130` shipped vLLM 0.19.1.dev6 and could not load the NVFP4
  checkpoint), the image was re-pinned to `vllm/vllm-openai:v0.20.0`
  (DECISIONS.md D-020). vLLM serves Gemma 4 26B NVFP4 on `localhost:8000`
  — MARLIN MoE backend confirmed, curl round-trip ok.
- **Block 2 #7 — benchmark** — median single-stream 32 tok/s, below the
  plan's 40 floor; accepted as the Day-1 baseline. Cause assessed
  structural (GB10 SM12x has no native FP4). See `day1-bench-debug.md`.
- **Block 2 #9–#11 — sandbox** — NemoClaw binary not installed; the
  hardened plain-Docker fallback was verified (seccomp +
  `no-new-privileges` + `cap-drop=ALL`).

## Deferred / follow-up

- MTP speculative decoding — Week 2+ (D-019); needs a post-PR-#41745 image.
- vLLM throughput tuning — optimization pass (KV-cache sizing, attention
  backend); the server is at 32 tok/s vs the plan's ~52 calibration.
- `plan.yaml` validation fixes — `day1_block2_docker_config` (the
  `cgroupns` key + the `docker info` cgroup check) and
  `day1_block2_vllm_serve` check #2 (the `FLASHINFER_CUTLASS` log line)
  both encode assumptions that do not hold on this stack; flagged for
  correction.
