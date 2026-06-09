# Runbook — exp008 QAT live eval bring-up (:8002 scratch container)

**Status:** live-ready harness, human-attended bring-up.
**Scope:** EVAL-ONLY benchmark (D-039 DRAFT). It measures whether a Gemma 4
QAT build reproduces the production NVFP4 pin's judgements. It **never** swaps
the production pin, never touches the serial spine / `run_state/` / `ui/`, and
never writes `logs/calls.jsonl`.

> **Container bring-up (step 1) is the HUMAN's step.** A subagent / workflow
> agent does not run `docker run`, does not pull GPU weights, and does not
> issue real (`env -u MOCK_LLM`) model calls. The agent's role is the offline
> dry-run check and drafting only. Everything below the "HUMAN STEP" banners is
> executed by the human at a live terminal.

---

## 0. Safety invariants (CLAUDE.md inviolate rules 2 + 10)

These hold for every step. If any is violated, STOP.

- **Production `:8000` is off-limits.** Arm A is the *already-running*
  production server, read-only. Nothing in this runbook launches,
  reconfigures, or hits `:8000`. The candidate container binds `:8002` only,
  under the distinct name `qat-eval-scratch`.
- **Verbatim pins (rule 2).** Arm C (vLLM) uses the pinned eval image
  `vllm/vllm-openai:v0.21.0`, CUDA 13.0 host driver. The QAT weights path is
  `/mnt/models/gemma-4-26b-a4b-it-qat-q4_0-unquantized` (arm C) /
  `/mnt/models/gemma-4-26b-a4b-it-qat-q4_0-gguf/model.gguf` (arm B). Confirm
  the literal placeholder paths in `serve_qat.sh` resolve to real files before
  launch; the script ships them as PLACEHOLDER.
- **MARLIN check (rule 2) applies to the PRODUCTION pin, NOT the scratch arm.**
  The production server (arm A) must already show
  `Using 'MARLIN' NvFp4 MoE backend` in its startup log — that is verified at
  the production endpoint, not re-launched here. The QAT scratch arms run a
  *different* launch profile on purpose (arm B is llama.cpp; arm C is
  unquantized weights, not NVFP4, so MARLIN/MTP args are deliberately absent).
  **Do NOT add `--moe-backend marlin` to the scratch arm-C launch** — these are
  not NVFP4 weights and the MoE-MARLIN backend does not apply.
- **MOCK_LLM (rule 10).** `MOCK_LLM=1` is set in the shell by default and
  silently stubs model calls. Every real eval below is prefixed with
  `env -u MOCK_LLM`. Every offline check below deliberately KEEPS `MOCK_LLM`.

---

## 1. Pre-flight — offline, MOCK_LLM kept (agent may run this)

Harness + config validate with no GPU and no network:

```bash
./.venv-chroma/bin/python -m pytest \
  tests/test_exp008_config.py \
  tests/test_exp008_analyze.py \
  tests/test_exp008_evals.py \
  -q -p no:cacheprovider
```

Inspect the scratch launch args WITHOUT executing docker:

```bash
bash experiments/exp008_qat_eval/serve_qat.sh up B --dry-run
bash experiments/exp008_qat_eval/serve_qat.sh up C --dry-run
bash experiments/exp008_qat_eval/serve_qat.sh down --dry-run
```

Confirm the dry-run for arm C shows the verbatim pin and the scratch port:

```
docker run -d --name qat-eval-scratch --gpus all \
  -v /mnt/models/gemma-4-26b-a4b-it-qat-q4_0-unquantized:/models/qat-unquantized:ro \
  -p 8002:8002 vllm/vllm-openai:v0.21.0 \
  --model /models/qat-unquantized \
  --served-model-name gemma-4-26b-a4b-qat-unquantized \
  --host 0.0.0.0 --port 8002 --max-model-len 32768 --trust-remote-code
```

**Pre-flight gate (all must hold before bring-up):**
- [ ] test suite green (26 passed)
- [ ] dry-run arm C shows `vllm/vllm-openai:v0.21.0` and `-p 8002:8002`
- [ ] dry-run shows container name `qat-eval-scratch` (never `vllm-gemma4`)
- [ ] dry-run shows NO `:8000`, NO `--moe-backend marlin`, NO MTP args
- [ ] PLACEHOLDER weight paths in `serve_qat.sh` resolve to real files
- [ ] `config.yaml` `PLACEHOLDER_REVISION` / `PLACEHOLDER_SHA256` filled for
      every arm you intend to run (pins the result to an exact checkpoint)

---

## 2. HUMAN STEP — bring up the :8002 scratch container

> **HUMAN ONLY.** Real GPU launch. Do not delegate to an agent.

Pre-launch host check (CUDA 13.0 — rule 2; NOT 13.2):

```bash
nvidia-smi | grep -i 'CUDA Version'      # MUST read CUDA Version: 13.0
docker images | grep 'vllm/vllm-openai'  # MUST list v0.21.0 (for arm C)
ls -l /mnt/models/gemma-4-26b-a4b-it-qat-q4_0-unquantized   # arm C weights
# (arm B only) ls -l /mnt/models/gemma-4-26b-a4b-it-qat-q4_0-gguf/model.gguf
```

Confirm production `:8000` is untouched and stays up (read-only baseline):

```bash
curl -fsS http://localhost:8000/v1/models | head    # arm A — DO NOT restart
```

Launch the scratch arm (pick ONE; C is the like-for-like-engine arm vs A):

```bash
# Arm C — unquantized QAT under vLLM (same engine as production -> cleanest
# vs-A comparison). Verbatim image pin vllm/vllm-openai:v0.21.0.
bash experiments/exp008_qat_eval/serve_qat.sh up C

# OR Arm B — QAT Q4_0 GGUF under llama.cpp (engine confound vs A; see README).
bash experiments/exp008_qat_eval/serve_qat.sh up B
```

`serve_qat.sh up` removes any prior `qat-eval-scratch`, launches detached, and
polls `:8002/health` / `:8002/v1/models` for up to ~15 min, dumping container
logs and exiting non-zero if the container dies early.

**Scratch-arm startup-log check (NOT the production MARLIN check):**

```bash
docker logs qat-eval-scratch 2>&1 | tail -40
curl -fsS http://localhost:8002/v1/models      # served-model-name visible
```

Expected, by arm:
- **Arm C (vLLM):** the server reaches "ready"; `/v1/models` lists
  `gemma-4-26b-a4b-qat-unquantized`. These are unquantized weights, so the
  startup log will **not** carry `Using 'MARLIN' NvFp4 MoE backend` — that is
  the NVFP4-only production signature and its absence here is correct, not a
  failure. (The production MARLIN/MTP signature is verified on `:8000`, not
  re-checked on the scratch arm — see §0.)
- **Arm B (llama.cpp):** the server reaches "ready"; `/v1/models` lists
  `gemma-4-26b-a4b-qat-q4_0`. No vLLM/MARLIN log lines apply at all.

If the container exits early, `serve_qat.sh` already printed the tail of
`docker logs`. STOP and triage before any eval call. Do not silently retry on a
degraded profile (rule 7 — fallbacks are explicit, logged, time-capped).

---

## 3. HUMAN STEP — run the evals (real model, `env -u MOCK_LLM`)

> **HUMAN ONLY.** Real model calls. Each eval is greedy (temperature 0), one
> request at a time. All eval calls log to
> `experiments/exp008_qat_eval/runs/*.jsonl` and to the eval-local
> `runs/calls_<arm>.jsonl` — **never** to production `logs/calls.jsonl` (the
> eval-local call-log redirect is wired: `eval_novelty.run_eval` passes
> `log_path=runs/calls_<arm>.jsonl` into the real worker, overriding its
> default `logs/calls.jsonl`).

**Arm-label convention (load-bearing for §4).** `analyze.py` keys its verdict
on arm labels **`pin`** (the reference) and **`qat`** (the candidate). The
scratch container is the candidate, so pass `--arm qat`. The production
reference is collected separately against `:8000`-read-only with `--arm pin`.
Do NOT use the raw `A`/`B`/`C` ids from `config.yaml` as the `--arm` value for
the eval drivers — `analyze.py` will not recognize them and will return
INSUFFICIENT.

### 3a. Candidate arm (scratch :8002 -> `--arm qat`)

```bash
ENDPOINT=http://localhost:8002/v1

# Novelty agreement (real worker over the 10 calibration fixtures)
env -u MOCK_LLM ./.venv-chroma/bin/python \
  experiments/exp008_qat_eval/eval_novelty.py \
  --arm qat --endpoint "$ENDPOINT" --model gemma-4-26b-a4b-qat-unquantized

# Tool-call adherence (real bridging parser over the 12 tool prompts)
env -u MOCK_LLM ./.venv-chroma/bin/python \
  experiments/exp008_qat_eval/eval_toolcall.py \
  --arm qat --endpoint "$ENDPOINT" --model gemma-4-26b-a4b-qat-unquantized

# Robustness sweep (seed x prompt-wrapper)
env -u MOCK_LLM ./.venv-chroma/bin/python \
  experiments/exp008_qat_eval/eval_robustness.py \
  --arm qat --base-url "$ENDPOINT" --model gemma-4-26b-a4b-qat-unquantized
```

(For arm B substitute `--model gemma-4-26b-a4b-qat-q4_0`.)

### 3b. Reference arm (production :8000, READ-ONLY -> `--arm pin`)

The control is the production server. It is read-only — you do **not** launch
or reconfigure it; you only send eval reads. The drivers refuse `:8000` by
default, but the `--reference` flag opens a guarded, read-only exception scoped
to the **pin arm only** (a candidate label under `--reference` is rejected, so
a mistyped `--arm` cannot route candidate traffic at production). The worker
call log is still redirected to `runs/calls_pin.jsonl`, so production
`logs/calls.jsonl` is never written. Collect the reference with:

```bash
env -u MOCK_LLM ./.venv-chroma/bin/python experiments/exp008_qat_eval/eval_novelty.py  --arm pin --reference --endpoint http://localhost:8000/v1 --model gemma-4-26b-a4b
env -u MOCK_LLM ./.venv-chroma/bin/python experiments/exp008_qat_eval/eval_toolcall.py --arm pin --reference --endpoint http://localhost:8000/v1 --model gemma-4-26b-a4b
```

Robustness for the pin arm runs offline (the deterministic stub) and is
informational only, so no `:8000` call is needed there.

### Expected observables per eval

| eval | stdout JSON keys | run-dir artifact | live "good" signal |
| --- | --- | --- | --- |
| `eval_novelty.py` | `agreement_rate`, `calibration_error_mae`, `n` (=10), `confusion` | `runs/novelty_<arm>.jsonl` + `runs/metrics_novelty_<arm>.jsonl` + `runs/calls_<arm>.jsonl` | `n=10`, `agreement_rate` near arm A's; off-diagonal confusion small |
| `eval_toolcall.py` | `adherence_rate`, `adherent`, `n` (=12) | `runs/toolcall_<arm>.jsonl` + `runs/metrics_toolcall_<arm>.jsonl` | `adherence_rate` at/above the 0.90 floor (see §4) |
| `eval_robustness.py` | stdout: `mean_modal_share`, `max_score_variance` | `runs/robustness_<arm>.jsonl` (one `kind:summary` + detail rows) | `mean_modal_share >= 0.80`; low `max_score_variance` |

With no `--endpoint`/`--base-url` (or under MOCK_LLM for novelty/toolcall) each
driver reports `status: offline` and makes NO live call — the safe default.

---

## 4. HUMAN STEP — aggregate + D-039 disposition

```bash
./.venv-chroma/bin/python experiments/exp008_qat_eval/analyze.py
```

Writes `experiments/exp008_qat_eval/RESULTS.md` and `results/summary.json`, and
prints one verdict: **H0 / H1 / INSUFFICIENT**.

### D-039 disposition checklist — what the numbers decide

`analyze.py` applies the PRE-REGISTERED thresholds mechanically (rule 4 — never
tuned to the result after the fact). Pre-registered values (default mirrors
`config.yaml`):

- materiality: `novelty_agreement` 0.05, `calibration_error` 0.02,
  `tool_call_adherence` 0.05
- `tool_call_adherence_floor` = 0.90 (hard guard for H1)
- `min_sample` = 10 scored items per arm per metric (decision-eligibility gate)
- `robustness_modal_share_min` = 0.80 (informational wobble flag)

Verdict logic and what it means for D-039:

- [ ] **INSUFFICIENT** — a `pin`/`qat` arm is missing, or any decision metric
      has `n < 10` on either arm. **Disposition: D-039 stays DRAFT.** Cannot
      decide. (The drivers now emit analyze-compatible metric rows and the
      tool-call set is 12 prompts, so a complete pin+qat run yields
      `n=10/10/12` and a real H0/H1 — INSUFFICIENT now means a genuinely
      missing arm or a truncated run, not a harness gap.)
- [ ] **H0** — no decision metric clears materiality, OR QAT gains exist but
      adherence `< 0.90`, OR QAT materially regresses anywhere.
      **Disposition: production NVFP4 pin is VINDICATED. Keep NVFP4. D-039
      resolves to "keep the pin".**
- [ ] **H1** — QAT materially better on >=1 metric, no material regression, AND
      `tool_call_adherence >= 0.90`. **Disposition: QAT clears the quality
      bar.** BUT per D-039 this still does **not** authorize a swap: there is no
      vLLM-native W4A16 QAT serving path for 26B-A4B (planning-confirmed
      blocker). H1 records "quality ceiling favorable"; a production swap is a
      separate, later decision gated on a real serving path existing.

Small-N caveat (config.yaml `materiality.small_n_caveat`): only ~10 novelty
fixtures, so one tier flip = 0.10 of the set. **Every result here is
DIRECTIONAL, not proof** — a signal to investigate on a larger set, never a
deployment call on its own. Tertiary metrics (tok/s, memory) are recorded but
NON-DECISION (different launch profile than production).

After `analyze.py`, the human updates the D-039 entry in `DECISIONS.md` from
DRAFT to its resolved disposition, citing `RESULTS.md`. (Decision-log edits are
the human's / integrator's, per the operating contract.)

---

## 5. HUMAN STEP — teardown

Always tear down the scratch container when the eval session ends — it holds a
GPU. The distinct name guarantees teardown can never hit production.

```bash
bash experiments/exp008_qat_eval/serve_qat.sh down
docker ps --format '{{.Names}}' | grep qat-eval-scratch || echo "scratch gone"
curl -fsS http://localhost:8000/v1/models | head    # production still up
```

Run-dir artifacts under `experiments/exp008_qat_eval/runs/` persist for audit;
they are the eval record and are not production logs.

---

## Quick reference — pins used here (verbatim, rule 2)

| thing | value |
| --- | --- |
| arm-C eval image | `vllm/vllm-openai:v0.21.0` |
| host CUDA | 13.0 (NOT 13.2) |
| arm-C QAT weights | `/mnt/models/gemma-4-26b-a4b-it-qat-q4_0-unquantized` |
| arm-B QAT GGUF | `/mnt/models/gemma-4-26b-a4b-it-qat-q4_0-gguf/model.gguf` |
| arm-B image | `ghcr.io/ggml-org/llama.cpp:server` |
| scratch port | `8002` (production is `8000`, read-only, untouched) |
| scratch container name | `qat-eval-scratch` |
| MARLIN MoE check | production-only (`:8000`); deliberately absent on scratch arms |
