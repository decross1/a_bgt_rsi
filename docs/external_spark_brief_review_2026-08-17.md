# External DGX-Spark eval brief — verification + reconciliation (2026-08-17)

The owner supplied an external "Model Evaluation — Dev Session Handover
Brief" (Qwen3.8-27B vs incumbents, Ling-3.0-flash contingent). Its checkable
claims were adversarially verified (`wf_20eeb2f5`, 5 agents, primary
sources). This note records what held, what broke, what it changes for us.
It does NOT adopt the brief's decision framework — see §3.

## 1. Verification results on the brief's load-bearing claims

**DSpark drafter — real, but the brief's serve path is impossible.**
`RadixArk/Qwen3.8-27B-DSpark` exists (SGLang company's HF org, 2026-08-14;
5 layers, 2.72 GB, block_size 7, one BF16 drafter for all quants). BUT: no
released vLLM can load it — the checkpoint's `DSparkDraftModel`+`qwen3`
shape is force-routed to the DeepSeek-V4 path on every release incl.
v0.27.1; the fix (vLLM PR #52197) is OPEN as of today. The brief's
`{"method":"dspark"}` vLLM config cannot work. Working engine today =
**SGLang** (`--speculative-algorithm DSPARK`). The drafter repo has **no
license file** (tag "other") — local-use terms formally unverifiable.
Real third-party Spark numbers exist (NVIDIA forum, SGLang + NVFP4):
**34–38 tok/s vs ~27 baseline**, peak 46.7 — far below the writeup's 75,
different config; acceptance 3.3–4.9 math/code but 1.25–2.8 prose.

**The community writeup — real, named author, credibility moderate-high.**
Two GitHub repos by 0xBakeer (Khaled Bakeer), created 2026-08-16, pinned
`vllm/vllm-openai:v0.27.1-aarch64`, runnable MIT harness. Every number in
the brief appears verbatim in their RESULTS.md (two pairing mislabels: the
98.7→68.7 acceptance pair and the KV-capacity pair mix tables/configs).
Both of the brief's §5.4 inconsistencies mostly resolve from the repo's own
data (k=14: first ~5 draft positions accept at ~1.0 so tokens/pass rises as
rate falls; "1.6× from quantization alone" = two levers — quant 1.26–1.46×
and k/budget +21% — mislabeled as one). Caveats: 1–2 runs/cell, no error
bars, synthetic edit-optimistic workload, self-flagged limitations.

**The SM121 env var (brief's open Q2): `VLLM_MARLIN_USE_ATOMIC_ADD=1`** —
per the 4-bit repo's NOTES.md, fixes a Marlin kernel race on SM121 that
yields silently incorrect output; asserted as externally documented, no
in-repo A/B proof. Secondary: `VLLM_USE_FLASHINFER_MOE_FP4=0` (CUTLASS FP4
insurance). **Production follow-up for US (§4).**

**Licenses/checkpoints (brief's Q1/Q3/Q4 closed).** `Qwen/Qwen3.8-27B`
LICENSE is verbatim Apache 2.0, zero regional language — the restriction
talk belongs to the 2.4T Max's custom license (conflation). unsloth NVFP4:
vision tower IS included (333 visual keys) + MTP shard, but format is
**compressed-tensors mixed-precision, NOT modelopt** — the slower SM120
path this lab already migrated away from; calibration undisclosed. The
AutoRound repo is an anonymous individual, not Intel. The brief **omits
Inferact/Qwen3.8-27B-NVFP4** — still the official vLLM recipe's named
artifact, and the Inferact HF org is verified with vLLM leads (Woosuk Kwon,
Simon Mo) as members: our G6 choice has *better* provenance than anything
in the brief's table.

**Eval-stack claims.** v0.27.1 aarch64 artifacts exist but all release
images are cu129; official SM121/GB10 support rides the cu130-nightly track
only (SM121 build-target PR still open). VL+spec-decode coexistence is
engineered-in for `Qwen3_5ForConditionalGeneration` with a field report on
SM121 — but no temp-0 correctness validation exists. Prefix caching on
hybrid (GDN) models: silently off by default (debug-level log), override
honored, and the correctness evidence is **negative** — #43559 (~20%
accuracy drop with caching+MTP), #47194 (tool-call leakage, caching+MTP),
#51198/#51250 (silent 0%-hit no-ops), fixes unmerged. #51812 confirmed
first-contained in v0.27.2rc0, not v0.27.1 (matches our D-072 record); the
garbage-class decode-misclassification bugs remain open in 0.27.x. The
"parser-name trap" is defused: `qwen3_coder` and `qwen3_xml` are aliases of
the same class in 0.27.x.

**Contingents.** Ling-3.0-flash facts confirmed (MIT; 124.4B/5.5B-active
base + 3.1B MTP = 127.5B shipped — the 5.1B figure is non-embedding active;
AA index 38, #1/63; ~4.2× verbosity) with one staleness: llama.cpp PR
#26608 MERGED upstream 2026-08-17 — GGUF support is now upstream. Muse
Glimmer confirmed but NOT text-only (multimodal, ~1.8B vision encoder);
science parity-to-worse vs Qwen3.6 confirmed from Meta's own table.
Memory-wall rejects hold (DeepSeek's is quant-dependent: 167 GB is FP8).

## 2. Where the brief is stale against this lab's own record (same day)

- "Incumbent decode t/s NOT ON RECORD" — false since this morning: 23.6
  tok/s (3.6-NVFP4+MTP, eval runtime), 16.6 avg-gen (3.8-NVFP4, prod pin),
  ~8 (FP8 arms, MTP off), plus Gemma's D-022 69.4.
- Its Phase-0/2 capability plan ignores the D-072 matched-FP8 results: the
  kill-pair split (3.6-FP8 fails, 3.8-FP8 passes), both NVFP4 artifacts
  passing the full D-044 battery at cap 12288, and the tool-probe results.
- Its checkpoint table misses the artifact we already qualified (Inferact).

## 3. Frame conflict — why this lab does not run the brief as written

The brief decides "single resident model; roles and co-residency out of
scope; production pin disposable." This lab's ratified architecture is the
opposite: two co-resident models with FIXED roles (G5/D-061 — Gemma PI,
Qwen skeptic), role fit IS the question, pins are verbatim. The brief's
gates (≥30 t/s generation-heavy, wall-clock per solved task) describe the
**dev-agent/residency** use case from `docs/qwen38_role_setups.md` — a
legitimate but separate track — not the skeptic seat D-072 just qualified.
Under its G2, 3.8-NVFP4 on our pinned stack (16.6 t/s) would "fail" a gate
that our skeptic workload does not have.

## 4. What we adopt / follow up (recommendation, owner to ratify)

1. **Adopt the brief's instruments** into the D-0zz battery and any future
   window: generation-heavy vs edit-heavy decode fixtures; wall-clock per
   solved task as the verbosity-honest metric; prefill curves; temp-0
   output-equivalence check for prefix caching.
2. **Production follow-up (small, this week): the SM121 Marlin race.**
   Establish whether the race behind `VLLM_MARLIN_USE_ATOMIC_ADD` exists in
   v0.21.0's Marlin kernels — production Gemma runs MARLIN NvFp4 MoE on
   SM121 every day. Gemma's clean battery history argues against gross
   corruption; a rare race is the #51812 class of silent risk. Verify
   upstream, then decide with the owner whether to set the var (env-only,
   reversible) or document non-applicability.
3. **Prefix caching**: production Qwen has it OFF — keep it off (negative
   upstream evidence). Note on our Window B arms: the fork build defaulted
   it ON; impact assessed LOW (MTP was off — the negative evidence is
   caching+MTP — and battery prompts are unique, so hits ≈ 0), recorded
   here rather than silently.
4. **Dev-agent serving option (new, gated, separate track):** SGLang +
   DSpark on NVFP4 is the one verified path to 34–38+ tok/s on this
   hardware today. It is a NEW engine dependency with an unlicensed drafter
   — its own decision entry if pursued. On vLLM, the trigger is PR #52197
   merging + a stable release containing it (watch item, alongside v0.27.2
   for #51812).
5. **Ling-3.0-flash**: no trigger — our gates did not fail. File as a
   watch-class scorecard only.
