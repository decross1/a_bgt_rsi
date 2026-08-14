# Qwen 3.6 → 3.8-27B upgrade checklist (LOOP_V1 P5 — prep only, NO cutover)

Status: PREP. Every step that touches a real server or real weights is behind a
human gate (LOOP_V1 P5: weight acquisition, A/B serve window, cutover
ratification). Nothing in this document authorizes a cutover; ratification is
the D-0zz entry below, filed at cutover time.

## 0. Current serve config (grounded 2026-08-14, read from `cron/serve-models.sh`)

The EXACT production `docker run` flags for the resident Qwen server
(`serve_qwen()`, verbatim from the script — the canonical launcher per D-057):

```
docker run -d --name vllm-qwen --restart unless-stopped --gpus all \
  -p 8001:8000 \
  -v /mnt/models/qwen3.6-27b-nvfp4-mtp:/models/qwen3.6-27b-nvfp4-mtp \
  vllm/vllm-openai:v0.21.0 \
  --model /models/qwen3.6-27b-nvfp4-mtp \
  --served-model-name qwen3.6-27b-nvfp4-mtp \
  --trust-remote-code \
  --quantization modelopt \
  --language-model-only \
  --max-model-len 16384 \
  --max-num-seqs 2 \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization 0.25 \
  --reasoning-parser qwen3 \
  --speculative-config '{"method":"qwen3_5_mtp","num_speculative_tokens":3}' \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder
```

Grounded facts (checked read-only at authoring time):

- Image pin: `vllm/vllm-openai:v0.21.0` (inviolate rule 2).
- `/mnt/models` today: `bge-m3`, `gemma-4-26b-a4b-it-assistant`,
  `gemma-4-26b-a4b-it-qat-q4_0-unquantized`, `gemma-4-26b-a4b-nvfp4`,
  `qwen3.6-27b-nvfp4-mtp`. **No 3.8 weights on disk.**
- `qwen3.6-27b-nvfp4-mtp` measures **19 GiB** on disk (`du -sh`).
- Filesystem holding `/mnt/models`: 3.1 TiB available (of 3.7 TiB) — the
  ~19 GiB needed for 3.8 **alongside** 3.6 is comfortably covered; disk is not
  the constraint, unified memory is (§2).

## 1. Acquisition (human gate: weight acquisition)

- [ ] Target artifact: Qwen 3.8-27B in **NVFP4 ModelOpt** quantization
      (`--quantization modelopt` must keep working) **with an MTP head**
      matching what 3.6 ships (3.6 uses speculative method `qwen3_5_mtp`).
- [ ] Destination path: `/mnt/models/qwen3.8-27b-nvfp4-mtp` (sibling of 3.6;
      3.6 is NOT deleted — §5 rollback).
- [ ] Disk: ~19 GiB free needed alongside 3.6. Verified available (3.1 TiB
      free at authoring). Re-check with `df -h /mnt/models` before download.
- [ ] **OPEN QUESTION (pin-amendment class, resolved by READING not pulling):**
      does vLLM `v0.21.0` support Qwen 3.8's MTP method and its
      reasoning/tool-call parsers? 3.6 runs `"method":"qwen3_5_mtp"` +
      `--reasoning-parser qwen3` + `--tool-call-parser qwen3_coder`. If 3.8
      needs a new speculative method name (e.g. a `qwen3_7_mtp`/`qwen3_8_mtp`
      successor) or new parser ids that `v0.21.0` does not know, the fix is a
      **version-pin amendment under inviolate rule 2** — a decision entry
      amending the pin in `ARCHITECTURE.md` §2 / `CLAUDE.md`, ratified by the
      human — **never** a workaround (no dropping `--speculative-config`, no
      falling back to a generic parser, no `:latest` image). Check the vLLM
      v0.21.0 release notes / supported-models source tree before acquiring.

## 2. Memory fit (GB10 unified pool; D-057 budget)

The box has ~121.7 GiB of UNIFIED memory shared by GPU and OS (2026-06-08
arm-C freeze — an over-commit hangs the machine, it does not cleanly OOM).

- [ ] Both weight sets are ~19 GiB and near-incompressible; the A/B window may
      require **stopping Gemma** to co-reside 3.6 + 3.8 — if so, say so in the
      run plan and restore Gemma after. **Do NOT thin the margin instead**
      (`OS_MARGIN_GIB=30` in `experiments/exp008_qat_eval/preflight_mem.sh` is
      hard-pinned; inviolate rule 7).
- [ ] Before ANY serve of 3.8:
      `bash experiments/exp008_qat_eval/preflight_mem.sh 30` (the on-box Qwen
      figure at `--gpu-memory-utilization 0.25` is ~30 GiB) must return **0**.
- [ ] After the swap, with **both resident servers up** (gemma + the surviving
      qwen): `preflight_mem.sh 0` returns **0** — i.e. the 30 GiB OS margin
      HELD with the steady-state pair running.
- [ ] Gemma MARLIN re-verified after any container churn: the vllm-gemma4 log
      MUST contain `Using 'MARLIN' NvFp4 MoE backend`; `CUTLASS_FP4` = STOP
      (inviolate rule 2).
- [ ] Qwen serve keeps `--gpu-memory-utilization 0.25` unless a preflight-
      verified change is ratified (serve-models.sh header: do not raise
      utilization without re-running preflight with both servers up).

## 3. Validation battery (A/B, same cases both models)

Run each stage against 3.6 (control, current production) and 3.8 (candidate)
under identical prompts/cases. `bench/critic_eval/qwen_ab.py --dry-run` prints
the full plan; `--live` gates on preflight. Results go in the D-0zz table.

### 3a. Skeptic-ladder cases (pass criteria verbatim from `docs/skeptic_ladder.md`)

Battery: `experiments/lit_falsification_battery/cases.jsonl`, via
`orchestrator.novelty_skeptic.attack(..., backend="vllm-qwen")`, real corpus,
`env -u MOCK_LLM`. A step PASSES only if all three hold on the live run:

> 1. **Kill check** — both falsifiable claims (`falsifiable_01`,
>    `falsifiable_02`) come back `refuted`, each with a
>    `contradicting_doc_id` from the skeptic's own retrieved set that a
>    human spot-check agrees is a real contradiction/restatement.
> 2. **No-false-kill check** — the true on-domain survivor
>    (`novel_on_01_quant_lockin`) is NOT `refuted` (`survives_attack`
>    preferred; `inconclusive` acceptable — it fails closed and the
>    consumer treats it as not-corroborated, but log it).
> 3. **Liveness check** — no empty/unparseable completions across the
>    sweep (the token-starvation signature: `finish_reason=length`,
>    `content=None`). One unparseable completion = investigate before
>    passing; systematic unparseable output = FAIL.

"Close" is a failure (inviolate rule 4): one of two falsifiable claims refuted
is a FAIL for the kill check, not a partial pass. Note: the D-044 working
figure `max_tokens=3072` was tuned on 3.6's reasoning channel; if 3.8 starves
at 3072 that is a battery FINDING to report, not a knob to silently retune.

### 3b. finding_promotion multi-vote on fixed historical candidates

`orchestrator/finding_promotion.py` runs its cross-model adversarial
multi-vote on `backend="vllm-qwen"` (default of both the `promote()` kwarg and
the `--backend` CLI flag). Re-run the vote on a FIXED set of historical
candidates (already-adjudicated loop_memory rows — same rows for A and B) and
compare per-skeptic verdicts, quorum attainment, and failure counts
(timeout / schema_mismatch / error are observable and never counted as
refuted). Regression bar: 3.8 must not lose quorum on candidates where 3.6
attains it, and must not flip adjudicated outcomes without a rationale a human
spot-check accepts.

### 3c. Two-voice attacker spot-run

`orchestrator/finding_session.py` pins the discussion stances:
`STANCE_BACKEND = {defender: "vllm-gemma", attacker: "vllm-qwen"}`. Run one
real two-voice session per model on the same finding and spot-check that the
3.8 attacker stays adversarial, parses cleanly, and cites like 3.6.

### 3d. restate_skeptic — VERIFIED at build time: it IS a Qwen role

The P5 spec asked whether `orchestrator/restate_skeptic.py` even runs on Qwen
(suspecting it might use default-Gemma `call_sync`). **Verified by reading the
module 2026-08-14: it is a Qwen role.** `restate_attack()` resolves
`backend=None` from `NARA_SKEPTIC_BACKEND` with default `"vllm-qwen"`
(line ~225) and passes `backend=` explicitly to BOTH of its `call_sync` calls
(canonicalize and judge) — it never falls through to the wrapper's
default-Gemma backend. Same pattern in `orchestrator/novelty_skeptic.py` and
`orchestrator/topicality_skeptic.py`. So the restate hook cases (the four
rediscovery residual-2 cases named in the module docstring) belong in the A/B
battery: run `restate_attack` per case and compare
`restate_verdict`/`restating_doc_id` groundedness across 3.6/3.8.

## 4. D-0zz decision-entry template (ratified at cutover; template only now)

```
## D-0zz — Qwen 3.6 → 3.8-27B pin amendment (YYYY-MM-DD)

**Decision.** Cut the vllm-qwen backend over from qwen3.6-27b-nvfp4-mtp to
qwen3.8-27b-nvfp4-mtp. [If applicable: amend the vLLM image pin
v0.21.0 → vX.Y.Z because 3.8's MTP method/parsers require it — verbatim
new pin here, per inviolate rule 2.]

**Battery table (A = 3.6 control, B = 3.8 candidate):**
| Stage | Criterion (verbatim ref) | A result | B result | Verdict |
| 3a skeptic ladder | kill / no-false-kill / liveness (docs/skeptic_ladder.md §Pass/fail) | | | |
| 3b promotion multi-vote | quorum kept; no unadjudicated flips | | | |
| 3c two-voice attacker | adversarial, parseable, cites (human spot-check) | | | |
| 3d restate hook | grounded restating_doc_id on residual-2 cases | | | |

**Serve-diff.** Exact serve_qwen() flag diff (old vs new: model path,
served-model-name, speculative-config method, parsers, image tag).

**Memory.** preflight_mem.sh 0 with both servers up = PASS at <MemAvailable>;
MARLIN line re-verified on gemma.

**Rollback.** 3.6 weights retained at /mnt/models/qwen3.6-27b-nvfp4-mtp for
>= 30 days post-cutover; revert = restore serve_qwen() flags + rename the
served model back; hardcoded-string inventory in
docs/qwen38_upgrade_checklist.md §5 re-applied in reverse.

**Ratified by:** <human> on <date> (Tier S — cron/serve-models.sh is
human-ratified per the entrenchment tier list).
```

## 5. Rollback plan + hardcoded model-name string inventory

- 3.6 weights are RETAINED at `/mnt/models/qwen3.6-27b-nvfp4-mtp` for
  **≥ 30 days** after cutover. Rollback = revert `serve_qwen()` to the §0
  flags and revert the string sites below; no re-download.
- The backend registry name **`vllm-qwen` does not change** at cutover — it is
  a registry key pointing at `:8001`, so the many `"vllm-qwen"` references
  (skeptics' `NARA_SKEPTIC_BACKEND` default, `finding_promotion` backend
  default, `finding_session.STANCE_BACKEND`, `boundary_probe`) are **safe** and
  need no edit.
- Sites that DO carry the literal model name / weights path (grep
  `qwen3\.6|qwen3.6-27b`, 2026-08-14; production files):

| File:line | String | Action at cutover |
| --- | --- | --- |
| `cron/serve-models.sh:49` | `-v /mnt/models/qwen3.6-27b-nvfp4-mtp:...` | edit (Tier S, human-ratified) |
| `cron/serve-models.sh:51` | `--model /models/qwen3.6-27b-nvfp4-mtp` | edit (Tier S) |
| `cron/serve-models.sh:52` | `--served-model-name qwen3.6-27b-nvfp4-mtp` | edit (Tier S) |
| `agent_wrapper/wrapper.py:99` | `model="qwen3.6-27b-nvfp4-mtp"` (vllm-qwen backend registration) | edit — this is the name the OpenAI-compat client sends; must match `--served-model-name` |
| `docs/skeptic_ladder.md` (step-1 row) | "Qwen NVFP4-MTP on :8001" prose | doc touch-up |
| test files (`tests/test_*`, `ui/backend/tests/*`) referencing `qwen3.6`/`vllm-qwen` | fixtures/assertions | audit after cutover; fixtures asserting the literal model string must be updated in the same commit |

- Memory note (`OLLAMA_MODEL` pin) concerns the demoted `ollama-coder` route
  (D-044), not this backend — unaffected by cutover.
- UI: `ui/sampler/sampler.py` keys metrics as `vllm_qwen` by URL (`:8001`),
  not by model name — unaffected; the dashboard keeps both LLM health panels.
