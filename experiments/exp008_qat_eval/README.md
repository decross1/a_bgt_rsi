# exp008_qat_eval — QAT-checkpoint novelty-evaluation benchmark

**EVAL-ONLY.** This experiment measures whether a Q4-QAT build of Gemma 4
26B-A4B reproduces the production NVFP4 model's novelty-tier judgements. It is a
benchmark, not a migration. It **never** swaps the production pin, touches the
serial spine, or writes to production logs.

## Objective

The production apparatus runs Gemma 4 26B-A4B as NVFP4 via vLLM (`:8000`).
Quantization-aware-trained (QAT) Q4 checkpoints exist that *might* be cheaper to
serve. Before anyone considers such a swap, we need evidence that a QAT build
gives the **same novelty-tier decisions** as production on a held set of
hypotheses. This benchmark produces that evidence — directionally.

## The three arms

| Arm | Role | Model | Engine | Endpoint |
|-----|------|-------|--------|----------|
| A | control (READ-ONLY) | `nvidia/Gemma-4-26B-A4B-NVFP4` | vLLM | `:8000` production |
| B | candidate | `google/gemma-4-26B-A4B-it-qat-q4_0-gguf` | llama.cpp | `:8002` scratch |
| C | candidate (optional) | `google/gemma-4-26B-A4B-it-qat-q4_0-unquantized` | vLLM | `:8002` scratch |

Arm A is the reference: the question is "does QAT change behavior *vs
production*", so we compare candidates against A, not against fixture ground
truth. Arm A is called **read-only** — the benchmark hits the already-running
production server and never launches or reconfigures it.

## How to run

### 1. Build / harness check (now, under MOCK_LLM)

The harness and config validate offline with the default `MOCK_LLM=1` shell:

```bash
./.venv-chroma/bin/python -m pytest tests/test_exp008_config.py -q -p no:cacheprovider
```

Inspect the scratch launch args without executing anything:

```bash
bash experiments/exp008_qat_eval/serve_qat.sh up B --dry-run
bash experiments/exp008_qat_eval/serve_qat.sh up C --dry-run
bash experiments/exp008_qat_eval/serve_qat.sh down --dry-run
```

### 2. Live run (human-attended, on :8002)

The live quality run is human-attended. Fill the `PLACEHOLDER_*` revision and
content-hash fields in `config.yaml` from the resolved checkpoint first, then:

```bash
# scratch container on :8002 ONLY — never production :8000
bash experiments/exp008_qat_eval/serve_qat.sh up B          # or: up C
# ... run the eval driver (greedy, one request at a time) ...
bash experiments/exp008_qat_eval/serve_qat.sh down
```

All eval calls log to `experiments/exp008_qat_eval/runs/*.jsonl`. They are
**never** written to `logs/calls.jsonl`.

## Metric and pre-registered threshold

- **Primary:** `tier_agreement_rate` — fraction of fixtures where a candidate's
  novelty tier matches arm A's tier.
- **Materiality:** a candidate is flagged *materially different* only if its
  tier-disagreement with A **exceeds the within-control seed-perturbation
  variance** (measured by reseeded probe runs of A) by a fixed margin. See
  `config.yaml: materiality`. This is pre-registered so a near-miss cannot be
  recoded into a pass.

## Honest limitations

These are real and bound what any result can claim:

1. **Engine confound on arm B.** Arm B is llama.cpp; arm A is vLLM. A delta
   between B and A mixes the QAT-quantization effect with the engine effect and
   they cannot be separated from B alone. Arm C (vLLM) exists to partly
   disentangle this, but only if the unquantized QAT weights are available.
2. **Small fixture N.** Only ~10 fixtures. With N=10 a single tier flip is 0.10
   of the set, so resolution is coarse. **Every result here is DIRECTIONAL, not
   proof** — a signal to investigate on a larger set, never a deployment call.
3. **Latency is non-comparable and non-decision.** Cross-engine latency
   (llama.cpp vs vLLM) is apples-to-oranges; it is recorded for context only and
   is explicitly excluded from any pass/fail or materiality judgement.
4. **No drop-in swap exists.** There is no vLLM-native 26B-A4B QAT checkpoint, so
   even the most favorable hypothesis (H1: QAT matches NVFP4) is **not** a
   drop-in production swap — it would still require an engine change. This
   benchmark informs that question; it does not resolve it.

## Safety boundary

- Arm A endpoint `:8000` is read-only and never launched/reconfigured here.
- `serve_qat.sh` binds `:8002` only, uses a distinct container name
  (`qat-eval-scratch`), and references neither the production image/container nor
  the MARLIN/MTP launch args.
- Eval output isolated to `runs/`; production `logs/calls.jsonl` is never written.
