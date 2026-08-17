# Qwen qualification windows — executable run plan (D-072)

> Scheduled by the owner 2026-08-17 (~04:20Z): "weights go, schedule the qwen
> windows for tomorrow" — target day **2026-08-18** (or the owner's next
> working session). Ratification rows: `D072_weights_go`,
> `D072_windows_scheduled` in `run_state/overrides.jsonl`. This plan executes
> DECISIONS.md **D-072** and nothing beyond it: no cutover, no production-pin
> change; the adoption rule is pre-declared (quality equal → retain 3.6).

## 0. Acquisitions (launched 2026-08-17 ~04:20Z, verify before any window)

| Artifact | Pin | Dest | Verify |
| --- | --- | --- | --- |
| Qwen/Qwen3.6-27B-FP8 | rev `e89b16ebf1988b3d6befa7de50abc2d76f26eb09` | `/mnt/models/qwen3.6-27b-fp8` | 66 files; safetensors total **30,866,866,928 B** exactly |
| Qwen/Qwen3.8-27B-FP8 | rev `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a` | `/mnt/models/qwen3.8-27b-fp8` | 66 files; safetensors total **30,866,866,928 B** exactly (byte-equal pair); note upstream `safetensors-md5sum.txt` is EMPTY (known); `crc32.txt` present |
| Eval runtime | `vllm/vllm-openai@sha256:4a2f33a884222f7049b983263ad9976f89452bb81affecf5b67d89ad35c1bc31` | docker (by digest, never by tag) | `docker images --digests` shows the digest; ARM64 manifest `541e0e47…` |

Provenance caveats binding on all reporting (D-072 amendments): the eval
image is an Inferact fork build (source-unauditable, CUDA 13.0.1) and does
NOT contain the vLLM #51812 fix on its default `triton` spec path — harmless
for MTP-off arms (the path never executes); MTP-on arms are a symmetric-bug
A/B until a stable v0.27.2 re-pin. Each arm uses its OWN tokenizer/chat
template (they differ between 3.6 and 3.8).

## Window discipline (every window)

1. `touch run_state/pause_coordinator` (kill switch ON; watchdog stands down
   only for `vllm-qwen-ab` names — use that container name for eval serves).
2. `bash experiments/exp008_qat_eval/preflight_mem.sh <need>` must PASS
   before serve; `preflight_mem.sh 0` with steady-state residents after.
3. `sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'` before any SOLO
   boot (UMA cudaMemGetInfo boot-check gotcha, vLLM #35313 — weight files
   just written sit in page cache).
4. Restore production EXACTLY (`cron/serve-models.sh` functions), re-verify
   Gemma's `Using 'MARLIN' NvFp4 MoE backend` line after ANY container churn
   (inviolate rule 2), `rm run_state/pause_coordinator`.
5. Every step logs rule-6 rows; every serve records image digest + model
   revision + full flag set in the run artifact.

## Window A — runtime-regression isolation (co-resident, ~45 min)

Purpose: D-072 step 1 — isolate eval-RUNTIME effects before any model
comparison. Gemma stays UP (same memory shape as production).

- Serve the CURRENT production artifact `/mnt/models/qwen3.6-27b-nvfp4-mtp`
  on the EVAL image (digest above), container name `vllm-qwen-ab`, port
  8002, with the production-canonical flags (`--quantization modelopt
  --language-model-only --max-model-len 16384 --max-num-seqs 2
  --kv-cache-dtype fp8 --gpu-memory-utilization 0.25 --reasoning-parser
  qwen3 --speculative-config '{"method":"qwen3_5_mtp","num_speculative_tokens":3}'
  --enable-auto-tool-choice --tool-call-parser qwen3_coder`).
- Run the 22-case stage-3a battery (fixed driver) against :8002 at cap
  12288; capture per-call tok/s and the spec-decode acceptance counters
  (`vllm:spec_decode_num_accepted_tokens_total` /
  `num_draft_tokens_total` — ui/sampler already computes the ratio). This
  closes measurement gap R8 (no local Qwen tok/s or MTP acceptance ever).
- Regression read: parse rate + verdict set vs the production-pin behavior.
  A runtime that changes verdicts on the SAME weights disqualifies the eval
  image for Window B until understood.

## Window B — the D-072 core: matched FP8 comparison (SOLO — Gemma STOPPED)

28.75 GiB weights per arm: FP8 arms cannot co-reside with Gemma under the
30 GiB margin (D-072 amendment 3). Arms run SEQUENTIALLY on the eval image.

Serve shape per arm (identical, only the model dir + its own chat template
differ): container `vllm-qwen-ab`, port 8002, `--language-model-only
--max-model-len 32768 --max-num-seqs 2 --gpu-memory-utilization 0.45
--reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser
qwen3_coder`. **MTP OFF** (no --speculative-config) and **BF16 KV** (no
--kv-cache-dtype) per D-072 step 2 — the #51812 path never executes. No
--quantization flag: the checkpoints' own fine-grained-FP8 config drives it;
the boot log must show fp8 loading and "Model loading took ~28-29 GiB" (FAIL
the window if materially higher). Memory: 0.45 × 121.7 = 54.8 GiB budget −
~29 weights − overhead ⇒ ~20 GiB KV at bf16 (~2× fp8 cost) — ample at 32k;
predicted MemAvailable ≈ 55 GiB > 30.

Per arm, in order:
1. **Six sentinels** (pinned, deterministic order): `novel_on_01_quant_lockin`,
   `redisc_on_01_tft_reciprocity`, `canary_on_01_ultimatum_plain`,
   `falsifiable_01`, `falsifiable_02_dominant_tft`,
   `camo_off_04_raft_punishment` (includes the kill pair + the two repeat
   cap-empty offenders). **STOP the window** on any: empty completion,
   provenance mismatch, call > 10 min, CUDA error/OOM/hang, missing call
   record, sustained swap growth, or 30 GiB margin breach.
2. **Full 22-case battery** (only after a clean sentinel pass), cap 12288,
   temp 0.2 / top_p 0.95 (production skeptic sampling — frozen), calls-log
   verified non-empty per case (the earlier 12288 void-run lesson).
3. **Tool/schema probe**: the 10-turn scripted tool-call session against
   :8002 (structured tool_calls arrays? JSON-string argument replay? —
   role_setups R5), identical script both arms.
4. Capture tok/s per call; record model revision + digest in every artifact.

**Frozen provenance across both arms (D-072 step 2):** identical prompt
bytes, retrieved docs + hashes, case order, seeds, sampling, image digest —
the driver records sha256 of every prompt and the doc-id set per case.

Comparison read (adoption rule, pre-declared): quality equal → retain 3.6.
3.8 advances only with zero critical gate failures, no tool/schema
regression, stable memory/soak, and the latency/quality trade-off explicitly
priced. Then and only then: Window D (Inferact NVFP4 as deployment
optimization) on a later day.

## Window C — skeptic-seat items on the PRODUCTION pin (checklist track)

Piggybacked because serve swaps dominate window cost (role_setups R2):
1. **3.8-NVFP4 kill-check rerun** at cap 12288 (checklist Rank-1; SOLO,
   production image, canonical flags, 3.6 stopped exactly as window #2).
   At minimum the 3 cap-empty cases; ideally all 22.
2. **3.6-NVFP4 control through the FIXED stage-3a driver** (co-resident,
   production image) — the missing A-side row for the D-0zz table.
3. Stages **3b/3c/3d** (promotion multi-vote / two-voice attacker / restate
   hook) — drivers DO NOT EXIST yet; run only if built dark by then,
   otherwise explicitly deferred in the window report.

## Build gaps before the windows (dark, no serve needed)

- `bench/fp8_ab/` driver: sentinel-first sequencing + stop conditions +
  frozen-provenance capture (prompt sha256, doc hashes, seeds) + tok/s +
  acceptance-counter scrape + 12288 cap + arm parametrization (endpoint,
  model name, template). Reuses the fixed stage-3a case contract.
- Tool/schema 10-turn probe script (deterministic, both arms).
- (Optional, C3) 3b/3c/3d drivers — defer if time is short; deferral is
  stated, never silent.

## Readiness (verified 2026-08-17 ~04:45Z — everything below is DONE)

- ✅ Both FP8 checkpoints on disk, **byte-exact**: 66 safetensors each,
  totals exactly 30,866,866,928 B, MTP shards exactly 477,202,224 B.
- ✅ Eval image pulled at the immutable digest; `docker inspect` confirms
  build-commit `3a0914114…`, created 2026-08-11T15:57:37Z (ARM64 fork build,
  matching the D-072 verification record).
- ✅ `bench/fp8_ab/` driver + tool probe built dark: 20 tests, suite 2080/0.
  Sentinel `falsifiable_01` resolved at build time to the exact id
  `falsifiable_01_finite_pd_cooperate`; runtime re-verifies all six ids and
  fails loudly on mismatch. Both CLIs refuse under MOCK_LLM (rule 10). Real
  invocations must pass `--image-digest sha256:4a2f33a8…` and the per-arm HF
  revision from §0. Known soft spot: probe turn t08 uses
  `tool_choice="required"` — if the fork build rejects it, the turn records
  the HTTP error as data and the probe continues.
- Still owed at window time (operator/integrator): rule-6 rows per step;
  3b/3c/3d drivers remain unbuilt (Window C item 3 defers unless built).

## Adopted instruments (D-073 authorization, from the verified external brief)

Future windows and the D-0zz battery add, alongside the stage batteries:
- **Two decode fixtures**: edit-heavy (patch an existing ~2K-line file) AND
  generation-heavy (new module from spec + new analytical prose) — spec
  decode acceptance collapses on generation-heavy work (~99% vs ~29%
  third-party measured), so edit-heavy numbers never stand in for the gate.
- **Wall-clock per solved task** as the verbosity-honest capability metric
  (3.8 reasons ~2-3× longer; t/s alone hides it).
- **Prefill curves** (4K/8K/32K/64K) with unique prompts, max_tokens=1.
- **Temp-0 byte-equivalence check** for prefix caching on/off before any
  hybrid-model serve relies on caching (upstream correctness evidence is
  currently NEGATIVE for caching on hybrids — production keeps it OFF).

Watch triggers (re-price the pin amendment when they land): vLLM PR #52197
merged+released (DSpark on vLLM); v0.27.2 stable (#51812 GDN fix).

## Reporting

One run artifact per window under `bench/fp8_ab/runs/` (JSON, one per arm);
rule-6 rows per step; the D-0zz battery table gets its first real rows
(A-side control + both FP8 arms + kill-check). Results land in the session
note and, when the battery is complete, the D-0zz decision entry — which is
filed at CUTOVER time only (D-072; G6 stands).
