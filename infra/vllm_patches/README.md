# vLLM patches

## `gemma4_mtp.py` — RETIRED (kept as a provenance record)

This file was a bind-mount patch for the *preview* vLLM image, whose
bundled `gemma4_mtp.py` had two bugs against a quantized target (see
`DECISIONS.md` D-019). **It is no longer used.**

As of D-022 (2026-05-19) the pinned image is `vllm/vllm-openai:v0.21.0`
— the first vLLM release that includes PR #41745 (Gemma 4 MTP). v0.21.0
ships the merged, fixed `gemma4_mtp.py` itself, so no bind-mount is
needed: `setup/day2_vllm_serve_mtp.sh` launches MTP without it.

The file is kept in-tree only as a provenance record — its header notes
the PR #41745 commit SHA it was taken from.
