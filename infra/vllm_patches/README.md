# vLLM patches

Files here are bind-mounted over the stock `vllm/vllm-openai:v0.20.0`
image at container launch (see `day1_block2_vllm_serve` in `plan.yaml`).

## `gemma4_mtp.py` — REQUIRED, NOT YET STAGED

The MTP (Multi-Token Prediction) speculative-decoding path needs a
patched `gemma4_mtp.py`. The preview image's bundled copy has two bugs
that break MTP against a **quantized** target:

1. `intermediate_size` is read from the top-level config instead of
   `text_config` (4096 vs 8192) — the drafter MLP is built half-size
   and weight load fails.
2. `quant_config` is propagated to the drafter's `Linear` layers — the
   target's `modelopt_fp4` quant_config gets applied to the drafter,
   which ships unquantized BF16 weights → packing mismatch.

Both fixes are at the head of vLLM PR #41745.

**To stage this file (do this before running `day1_block2_vllm_serve`):**

1. Fetch `vllm/model_executor/models/gemma4_mtp.py` from the head of
   <https://github.com/vllm-project/vllm/pull/41745>.
2. Save it here as `infra/vllm_patches/gemma4_mtp.py`.
3. Add a header comment recording the exact PR commit SHA it was taken
   from, e.g. `# from vllm-project/vllm PR #41745 @ <SHA>`.
4. Commit it.

Until then the bind-mount in the launch command will fail — MTP cannot
be exercised without it.
