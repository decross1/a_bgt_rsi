# Decisions log — a_bgt_rsi

> **What this document is.** A flat log of architectural and operational
> decisions, each with: date, decision, alternatives considered, rationale,
> and what would reverse it. The point is not bureaucracy — it's that six
> months from now you (or a future Claude instance) can ask "why did we
> pick X?" and get an answer without re-running the original reasoning.
>
> Decisions are appended in roughly chronological order by when they were
> locked in. The most recent decisions are at the bottom. Each decision has
> an ID for cross-referencing from other docs.

---

## D-001 — Hardware: DGX Spark, single unit

**Date locked.** Pre-Phase 1, before April 2026.
**Decision.** A single NVIDIA DGX Spark unit as the apparatus's runtime.
**Alternatives.**
- Cloud GPU rental (H100/A100 hours).
- AMD Strix Halo (Ryzen AI Max+ 395, 128 GB unified, similar memory).
- Apple M4 Ultra Mac Studio (up to 512 GB unified, >800 GB/s bandwidth).
- Two interconnected DGX Sparks (for 405 B-parameter capability).
**Rationale.** The Spark is the cheapest path to 128 GB unified memory with
full CUDA support, which is what the open-model + multi-tool stack assumes.
Apple has more memory and bandwidth but no CUDA. Strix Halo has no CUDA.
Cloud rental adds latency, cost-per-hour, and data-sovereignty concerns —
the apparatus logs every prompt and seed as a research observation, which
makes cloud usage operationally awkward and creates a hard cost ramp.
Spark pays back vs. cloud within 6–12 months of daily use. Two-Spark
configurations are a Phase 2+ option, not Phase 1.
**Reversibility.** Hard. The cost is sunk. Migration to cloud or Mac would
require a serving-layer rewrite (vLLM → MLX or vLLM-cloud) and an
embedding-layer rebuild.

---

## D-002 — Orchestrator model: Gemma 4 26B-A4B MoE in NVFP4

**Date locked.** April 2026, after Gemma 4 release.
**Decision.** Use `nvidia/Gemma-4-26B-A4B-NVFP4` (NVIDIA's official NVFP4
quantization, attention in BF16) as the orchestrator model on Spark.
**Alternatives.**
- Gemma 4 31B Dense — dense, slower on bandwidth-limited memory.
- Qwen 3.6 27B Dense — better coding (77.2 % SWE-bench vs. ~75 %); dense.
- Llama 4 / DeepSeek variants.
- `bg-digitalservices/Gemma-4-26B-A4B-it-NVFP4` — community quant with
  attention also in FP4.
**Rationale.** MoE wins on the Spark's 273 GB/s memory bandwidth: only
~3.8 B parameters activate per token. The 31B dense variant runs at ~4–7
tok/s (limited by reading all 31 B weights per token at 2 bytes each);
the 26B MoE achieves ~50 tok/s single-stream, ~115 tok/s aggregate at
three concurrent requests. Total parameter count is irrelevant; active
parameter count determines speed.
Independent confirmation: ai-muninn's April 13, 2026 run reports 52 tok/s
single-stream on Spark with vLLM 0.19+ and `--moe-backend marlin`.
NVIDIA's quant leaves self-attention in BF16 by design (modelopt default)
because quantizing attention to 4-bit hurts Gemma 4 accuracy more than
quantizing MLP does. This is a deliberate accuracy/size trade-off; the
NVIDIA checkpoint is correct for production.
**Reversibility.** Easy. Swap to Qwen 3.6 (D-006) or any vLLM-served
model is documented as a single config change.

---

## D-003 — Serving stack: vLLM with `--moe-backend marlin`

**Date locked.** April 2026 with vLLM 0.19 release.
**Decision.** vLLM ≥ 0.19, image `vllm/vllm-openai:gemma4-cu130`, launched
with `--moe-backend marlin` and the FLASHINFER_CUTLASS NVFP4 linear
backend.
**Alternatives.**
- Ollama (Q4_K_M GGUF, gemma4:26b).
- SGLang.
- Custom inference loop.
**Rationale.** vLLM 0.19+ shipped the SM121 NVFP4 fixes broken since
March; Ollama is faster for single-stream but slower for concurrent
batching and weaker on continuous-batching semantics that the loop will
use heavily. vLLM gives an OpenAI-compatible endpoint, which keeps the
wrapper layer thin. SGLang would also work but vLLM has more community
mileage on this exact stack.
**Operational pin.** Image tag `:gemma4-cu130` is NOT a superset of
`:gemma4` (the latter is the dev image and crashes on FP4 GEMM). Capture
the image digest at first boot and pin the digest, not just the tag.
**Reversibility.** Easy at the serving level (any OpenAI-compatible
endpoint can substitute). Hard at the version level — downgrading vLLM
below 0.19 reintroduces the broken NVFP4 path on SM12x.

---

## D-004 — CUDA 13.0 pin, auto-update locked

**Date locked.** Day 0 of Spark setup, May 2026.
**Decision.** Pin CUDA 13.0 via `apt-mark hold` on the eight
`cuda-*-13-0` packages; disable `unattended-upgrades`; manual updates only.
**Alternatives.**
- CUDA 13.2 (current). Allow auto-update.
- Stay on CUDA 12.x.
**Rationale.** CUDA 13.2 produces gibberish output on low-bit quantized
models — a documented silent-failure mode flagged in the
validation-pass review and confirmed across multiple community reports.
The Spark ships with 13.0 working; the cost of "drifting" to 13.2 via
auto-update is unrecoverable until a known-good 13.x point release lands.
**Operational caveat.** Two `cuda-*-config-common` packages drifted to
13.2.75-1 on the Spark; characterized as cosmetic (not in runtime path).
Before any first vLLM serve, run `nvcc --version && nvidia-smi | head -3`
and confirm 13.0 in the driver line — if anything shows 13.2 in the
runtime path, back out before serving.
**Reversibility.** Mechanically easy (unhold, upgrade); operationally
gated on a verified-clean CUDA 13.x release.

---

## D-005 — Embedding model: BGE-M3 over ChromaDB default

**Date locked.** Validation-pass review, May 2026.
**Decision.** Use `BAAI/bge-m3` (MIT, ungated, ~1–2 GB) as the embedding
model across all three knowledge-base layers; override ChromaDB's default
`all-MiniLM-L6-v2`.
**Alternatives.**
- ChromaDB default `all-MiniLM-L6-v2`.
- OpenAI `text-embedding-3-large` (API, paid).
- Cohere embed models (API, paid).
- Other open models (e5-mistral, GTE-large, jina-embeddings).
**Rationale.** The ChromaDB default collapses to 0.4–0.6 retrieval
accuracy at 4 K-character chunks — unacceptable for dense math textbooks.
BGE-M3 is the canonical multilingual long-context retrieval model as of
2026 and holds accuracy at 8 K-token chunks (validation: ~0.92 retrieval
score on the Day 3 needle-in-haystack benchmark). MIT license is
preferable to API-gated alternatives; the apparatus runs entirely on local
compute by design, and embedding is high-volume.
**Reversibility.** Easy at the model level (drop-in swap). Reversibility
of the *embedded data* depends on regenerating embeddings — a few hours
of work on the Spark, not blocking.

---

## D-006 — Qwen 3.6 deferred to Week 2–3

**Date locked.** Validation-pass review, May 2026.
**Decision.** Use Gemma 4 26B-A4B MoE alone for Week 1. Introduce Qwen 3.6
27B Dense as a manually-swappable alternative starting Week 2 or 3.
**Alternatives.**
- Use both models from Day 1 with a routing layer.
- Use Qwen 3.6 as primary from Day 1.
**Rationale.** A configuration matrix with two models from Day 1 would
mask Week 1 bugs — when a problem appears, you'd have to disambiguate
"model A behavior" vs. "model B behavior" vs. "harness issue" vs. "vLLM
issue." Single-model in Week 1 gives clean signal. Qwen 3.6 only matters
if Gemma 4's coding quality proves insufficient for autoresearch
modifications, and that hypothesis can't be tested without Week 1's
foundations in place anyway.
**Reversibility.** Trivial. Adding Qwen 3.6 is one model download and one
config change.

---

## D-007 — Synthetic-tier engine: OpenSpiel + Game Reasoning Arena

**Date locked.** Validation-pass review, May 2026.
**Decision.** Use `github.com/SLAMPAI/game_reasoning_arena` (GRA) on top
of OpenSpiel as the synthetic-tier game environment. Day 7's repeated PD
experiment runs on this stack.
**Alternatives.**
- Custom synthetic-tier game engine.
- PettingZoo / Gymnasium.
- Direct OpenSpiel with custom LLM-agent glue.
**Rationale.** GRA already supports a local vLLM backend, has `prisoners_dilemma` and `matching_pennies` built in, and integrates an
agent registry that matches the apparatus's "TFT, grim trigger, all-C,
all-D, mirror-LLM" Day-7 needs. Building a custom engine would consume
1–2 weeks for no research-content gain. The validation pass estimated
the savings at exactly that range.
**Reversibility.** Medium. Switching engines mid-Phase-1 would require
re-implementing the agent strategies; not blocking but not free.

---

## D-008 — NemoClaw alpha discipline, plain-Docker fallback

**Date locked.** Validation-pass review, May 2026; reinforced by ongoing
NemoClaw README operational guidance.
**Decision.** Use NemoClaw as the intended sandbox runtime; cap NemoClaw
onboarding at 90 minutes on Day 1; if onboarding fails, fall back to
security-hardened plain Docker (`seccomp`, `no-new-privileges`,
`cap-drop=ALL`). Re-attempt NemoClaw with fresh eyes at the end of Week
1, not during Week 1.
**Alternatives.**
- Block on NemoClaw onboarding until it works.
- Skip NemoClaw entirely, use plain Docker from the start.
**Rationale.** NemoClaw was announced at GTC 2026 March 16 and is
explicitly "not production-ready" per NVIDIA's own docs. Multiple
operational footguns are documented: direct `openshell self-update`,
`npm update -g openshell`, and `openshell sandbox create` break
NemoClaw's state management and require `nemoclaw onboard` to recover.
For Week 1's threat model (researcher's own code on the researcher's own
box), plain Docker with the hardening above is good enough. NemoClaw's
value proposition is *better* isolation for *agentic* workloads where
worker code might do unexpected things — a Phase 2+ concern when
autoresearch loops run overnight, not Week 1 when every worker is
summarize_paper or play_one_round.
**Reversibility.** Easy by design. Day 6's orchestrator router reads
`state.fallbacks_taken.day1_nemoclaw` and branches accordingly; bringing
NemoClaw up later just flips the router.

---

## D-009 — Autoresearch fork: use canonical karpathy/autoresearch

**Date locked.** May 2026 (corrected from earlier reference to a fork).
**Decision.** Clone `github.com/karpathy/autoresearch` (canonical
upstream). Do NOT use `matt-langston/autoresearch`.
**Alternatives.**
- `matt-langston/autoresearch` — a fork tuned for a *dual*-GB10 Spark
  bundle.
**Rationale.** The matt-langston fork carries configuration assumptions
that mismatch a single-Spark setup (the apparatus's hardware reality).
Earlier planning conversations imprecisely pointed at the fork; the
canonical upstream is the correct dependency.
**Operational scope.** Autoresearch is a Week-2+ tool; Week 1 only needs
the directory present. It fires on the ~10–20 % of loop cycles where the
agent identifies a pattern that a specialist model could capture better
than general reasoning.
**Reversibility.** Trivial. `git clone` from the right URL.

---

## D-010 — Google SCORE excluded in Phase 1

**Date locked.** Technical plan v1, April 30, 2026.
**Decision.** Use the bandit keep/discard ratchet planned in Research
Program v2 for autoresearch. Do NOT introduce Google's SCORE UCB-based
tree search in Phase 1.
**Alternatives.**
- Replace bandit with SCORE-style UCB tree search now.
- Use both, route between them.
**Rationale.** (a) The research program already planned a bandit
keep/discard criterion, which is in the same algorithmic family. (b)
SCORE's advantage emerges at thousands of candidates, which the Spark
can't sustain for training-based experiments. (c) For game-simulation
experiments (which evaluate in seconds), the simpler bandit with good
heuristics gets most of the value.
**Reversibility.** Easy. Noted as a Phase 2 upgrade if the greedy
approach proves limiting for mechanism-design search.

---

## D-011 — Sakana AI Scientist excluded

**Date locked.** Technical plan v1, April 30, 2026.
**Decision.** Do not adopt Sakana's AI Scientist paradigm or any
LLM-as-reviewer automation for novelty evaluation. The human-in-the-loop
novelty evaluation rubric is the design.
**Alternatives.**
- Use Sakana / AI Scientist for paper generation and review.
- Use LLM-as-reviewer for partial autonomy on novelty calls.
**Rationale.** The research program already has a superior methodology
for the things Sakana automates (novelty evaluation, paper writing, peer
review). The critical Track-B reading identifies why LLM-as-reviewer is
unreliable — and the 2024–2025 critical-response literature has since
strengthened, not weakened, that case. Novelty evaluation is named as
its own sub-research-problem; automating it away would defeat the
research program's central methodological commitment.
**Reversibility.** Conceptually easy but would change what the project
*is* — not a swap, a different program. Re-evaluate in Phase 4 only if
the meta-scientific synthesis demands it.

---

## D-012 — Dual-model routing layer excluded

**Date locked.** Technical plan v1, April 30, 2026.
**Decision.** No automatic routing layer that dispatches between Gemma 4
and Qwen 3.6. The architecture supports model swaps via single command;
swaps are manual, when a specific bottleneck is identified.
**Alternatives.**
- Build a routing layer now.
- Build one when a second model is introduced (Week 2–3).
**Rationale.** Premature optimization. A routing layer adds complexity
(routing rules, fallback handling, observability per model) before the
problem it solves has been validated. Start with one model. If
autoresearch coding modifications fail too often, manually swap to Qwen
3.6 for *that workload only*. Don't build infrastructure for a problem
that hasn't been validated yet.
**Reversibility.** Easy. Adding a router later is straightforward; the
worker contract (Day 6) is already designed to accept a `model` field on
the task.

---

## D-013 — Pi as the underlying agent harness

**Date locked.** Pre-Week-1 architecture.
**Decision.** Use Pi (`github.com/badlogic/pi-mono`, MIT) as the
underlying coding-agent harness. OpenClaw runs on Pi; the apparatus's
custom workers also use Pi underneath.
**Alternatives.**
- Build the agent loop from scratch on top of vLLM.
- Use Claude Code as the underlying harness (impossible: see D-014).
- Use Codex CLI or Gemini CLI.
**Rationale.** Pi is the minimal coding-agent harness that ships with
the four tools the apparatus actually uses (Read, Write, Edit, Bash) and
supports OpenAI-compatible endpoints (which is what vLLM exposes). It's
the harness OpenClaw is built on, so the upstream architecture matches
the apparatus's structure. MIT license, no vendor lock-in. Pi's "no
hidden context" philosophy aligns with the reproducibility commitment —
every prompt the model sees is exactly what's in the conversation.
**Reversibility.** Medium. The worker contract is harness-agnostic, but
custom skills/extensions are Pi-shaped. A migration would mean rewriting
those.

---

## D-014 — Apparatus runtime points at local Gemma 4, never at Claude

**Date locked.** May 2026 (Anthropic policy April–May 2026).
**Decision.** Pi and OpenClaw point at the *local* Gemma 4 vLLM endpoint
on `localhost:8000`. They never authenticate to a Claude subscription.
Claude Code (first-party Anthropic) authenticates to Max separately and
is used for the apparatus's *bootstrap* work (Day 1–7 setup, debugging)
under human supervision — distinct from the apparatus's runtime.
**Alternatives.**
- Point OpenClaw at the Claude API via the Anthropic-issued Agent SDK
  credit.
- Use Claude Code as the apparatus's runtime orchestrator.
**Rationale.** Three reasons. (1) The apparatus's central claim is that
a single researcher can build and operate a useful research loop on
*open* models with *local* compute. Routing the orchestrator through
Anthropic invalidates that claim. (2) Anthropic's June 15, 2026 policy
caps third-party Agent SDK usage on Max-20x at $200/month of API
list-rate tokens, non-rolling, which would consume the budget
unsustainably for a continuous research loop. (3) Local compute is the
data-sovereignty guarantee — every prompt is a research observation; the
apparatus needs that data to stay local.
**Reversibility.** Conceptually possible but reverses the project's
identity. Not a swap, a different program.

---

## D-015 — Repository name: `a_bgt_rsi` (not `huchi-loop`)

**Date locked.** May 2026, naming retro.
**Decision.** The GitHub repository is `decross1/a_bgt_rsi`.
**Alternatives.**
- `huchi-loop` (earlier placeholder).
- `a_bgt_rsi-private` (with a separate public mirror later).
- Personal naming under derrickcross.com domain.
**Rationale.** The name "huchi-loop" was a placeholder used in some
early planning conversations and predates the formal repo creation.
`a_bgt_rsi` is the canonical name on the GitHub remote. Any doc that
refers to "huchi-loop" is stale and should be updated.
**Reversibility.** GitHub repo rename is trivial. Don't do it without
updating every dependent reference (CI, README, this file).

---

## D-016 — Dual-license deferred to public flip

**Date locked.** May 2026.
**Decision.** Do not stage `LICENSE` (Apache-2.0), `LICENSE-CONTENT`
(CC-BY-4.0), `CITATION.cff`, or polished `README.md` until just before
the repo flips public (Day 7+).
**Alternatives.**
- Add them now.
- Defer indefinitely.
**Rationale.** While the repo is private, license files have no force.
Staging them now invites premature decisions about the exact CC-BY
variant, the citation block formatting, etc. Better to make those
decisions once and correctly, at the moment the public flip is
imminent, with the actual artifact list in hand.
**Reversibility.** Easy; just add the files when ready.

---

## D-017 — Capture vLLM image digest, not just tag

**Date locked.** May 2026, added on review.
**Decision.** Day 1 captures the SHA digest of
`vllm/vllm-openai:gemma4-cu130` at first pull and writes it to
`run_state/`. The inviolate-pin is the digest, not the tag. Day 7's
`experiment.lock` also records it.
**Alternatives.**
- Pin the tag only.
- Build a custom vLLM image and pin its hash.
**Rationale.** Container tags are mutable. The community has flagged
that `:gemma4` and `:gemma4-cu130` are different images with different
vLLM versions and that tag naming does not imply one is a superset of
the other. A future tag rebuild against a regressed vLLM would silently
change apparatus behavior. The digest pin defends against that.
**Reversibility.** Trivial. Update the pin to a new digest after
verifying the new image's startup logs.

---

## D-018 — SM12x kernel-compatibility constraint acknowledged

**Date locked.** May 2026, added on review.
**Decision.** The apparatus does NOT depend on any kernel that requires
SM100 (datacenter Blackwell) features — `tcgen05`, TMEM, 2-SM cooperative
MMA, FlashAttention 4, FlashMLA's SM100 backend. The Spark reports as
SM12x (compute capability 12.1) and is architecturally distinct from
SM100 despite both being "Blackwell."
**Alternatives.**
- Plan around SM100-only kernels and accept they won't work on the Spark.
**Rationale.** The Spark's SM12x is its own ISA in Blackwell. vLLM 0.19+
patched its NVFP4 paths to work on SM12x; not all libraries have. If a
future optimization proposal cites "FlashAttention 4 makes this 2x
faster," that proposal is non-portable to the Spark and needs reframing.
**Reversibility.** Not applicable — this is a hardware constraint, not
a chosen direction.

---

## D-019 — MTP speculative decoding enabled (Gemma 4 + official drafter)

**Date locked.** 2026-05-18, after the post-2026-05-05 MTP research
review; human-approved. Resolves the "MTP support" open decision.
**Decision.** Enable MTP (Multi-Token Prediction) speculative decoding on
the vLLM Gemma 4 stack, using the official Google drafter
`google/gemma-4-26B-A4B-it-assistant` (~870 MB BF16) paired with the
`nvidia/Gemma-4-26B-A4B-NVFP4` IT target. The Day-1 launch adds
`--speculative-config '{"method":"mtp","model":".../gemma-4-26b-a4b-it-assistant","num_speculative_tokens":4}'`.
**Alternatives.**
- No MTP — NVFP4 baseline, ~52 tok/s single-stream.
- FP8 + MTP — ~108 tok/s, faster, but re-pins the whole model stack.
- GGUF / Ollama — rejected: no MTP path, no concurrency, slower.
**Rationale.** MTP is a ~1.84× single-stream speedup on GB10 with zero
quality loss (the target verifies every accepted token), validated by
community benchmarks. NVFP4 (not FP8) is retained because an FP8 swap
would re-derive every MARLIN / startup-log / image-tag pin for a ~12 %
delta that changes no per-day budget. The drafter MUST pair with the IT
target — pairing with a base target is a 38 % slowdown.
**Operational caveats.** The preview vLLM image's bundled `gemma4_mtp.py`
has two bugs on quantized targets (`intermediate_size` read from the
wrong config layer; `quant_config` wrongly propagated to the BF16
drafter); the head of vLLM PR #41745 fixes both. Until the image is
rebuilt, bind-mount the patched file (`infra/vllm_patches/gemma4_mtp.py`).
The Day-1 tok/s band is updated to 80–130 with MTP γ=4; the hard floor
stays 40.
**Reversibility.** Easy — drop the `--speculative-config` flag and the
drafter mount to fall back to the NVFP4 baseline.
**Plan impact.** `plan.yaml` updated 2026-05-18 (6 edits: weights size
note, drafter pinned, `day1_block2_vllm_serve` launch + validation, tok/s
band, Appendix C, `infra/bookmarks.txt`).

**2026-05-18 update — DEFERRED, not abandoned.** Day-1 execution found
the then-pinned image (`:gemma4-cu130`, vLLM 0.19.1.dev6) could not run
MTP: it predates merged vLLM PR #41745 (9 files of MTP support, not just
`gemma4_mtp.py`) and crashed in `SpeculativeConfig` on the unrecognized
`gemma4_assistant` drafter. Per human decision, MTP is deferred to
Week 2+ — get the baseline product working first. The `plan.yaml` task
#6/#7 MTP edits were reverted (tok/s band back to [50,110]). The drafter
weights and `infra/vllm_patches/gemma4_mtp.py` remain staged. Whether
the re-pinned v0.20.0 image (D-020) ships PR #41745 is untested; MTP
re-evaluation is re-tracked under "Open decisions" below.

**2026-05-19 update — ENABLED (see D-022).** The re-pinned v0.20.0
image was tested and found NOT to ship PR #41745 (no `gemma4_mtp.py`,
no `Gemma4MTPModel` registry entry). Re-pinning to v0.21.0 — the first
vLLM release that includes #41745 — enabled MTP cleanly: single-stream
decode 32.21 → 69.44 tok/s, and the day_2 50-call sweep now passes all
5 checks. The deferral is closed.

---

## D-020 — vLLM image re-pinned: `:gemma4-cu130` → `:v0.20.0`

**Date locked.** 2026-05-18, Day-1 execution; human-authorized.
**Decision.** The inviolate vLLM image pin moves from
`vllm/vllm-openai:gemma4-cu130` to `vllm/vllm-openai:v0.20.0` — digest
`sha256:04563c302537a91aa49ebdfbceda96111c5712275999b7e8804fa598f0b5641d`,
vLLM 0.20.0, torch 2.11.0+cu130. Supersedes the image tag named in D-003.
**Alternatives.**
- Keep `:gemma4-cu130` — rejected: it cannot serve the checkpoint.
- Patch vLLM 0.19.1.dev6 inside the image — rejected: open-ended, fragile.
**Rationale.** `:gemma4-cu130` shipped vLLM `0.19.1.dev6`, whose
`gemma4.py` weight loader has no parameter for the per-expert NVFP4
`input_scale` tensors the `nvidia/Gemma-4-26B-A4B-NVFP4` checkpoint
ships — `KeyError: layers.0.experts.0.down_proj.input_scale` at engine
start. The checkpoint's own model card specifies `vllm/vllm-openai:v0.20.0`.
v0.20.0 serves it cleanly (MARLIN MoE backend confirmed; curl round-trip
returned `ok` in 1.45 s). `:gemma4-cu130` was a stale preview tag that
predated the published checkpoint — exactly the moving-tag risk D-017
flagged.
**Operational notes.** v0.20.0 also needs `--max-num-batched-tokens 8192`
(Gemma 4 is multimodal; vLLM force-disables chunked MM input, so the
batch-token budget must exceed `max_tokens_per_mm_item`=2496). The GB10
has no native FP4 compute (SM12x — D-018); vLLM uses the Marlin
weight-only FP4 path, so the plan's expected `FLASHINFER_CUTLASS for
NVFP4 GEMM` log line does not appear — `day1_block2_vllm_serve`
validation check #2 needs correcting to match.
**Reversibility.** Easy — re-pin to a new digest after verifying its
startup logs (per D-017).

---

## D-021 — Day-1 decode throughput is memory-bandwidth-bound on GB10

**Date locked.** 2026-05-18, Day-1 follow-up investigation + the E1
clock experiment (`notes/day1-bench-debug.md`).
**Decision.** Settled by investigation and the E1 experiment:
1. `scripts/bench_tokens_per_sec.py` is corrected to measure *true*
   decode rate — streaming, first/last-token timestamps, TTFT split,
   warmup discard, `/metrics` cross-check. The prior version reported
   end-to-end throughput mislabelled as "decode tok/s".
2. Single-stream decode (~32.4 tok/s) is **memory-bandwidth-bound** —
   bound by reading the model weights from unified LPDDR5X every token.
   It is not compute/clock-bound, not thermally limited, and not gated
   by KV-cache traffic.
3. The 32-vs-~52 gap is a tuning target in the *memory path*, not a GPU
   clock or power-profile issue. The Day-1 baseline number stands
   (human decision, run log 06:15Z).
**Alternatives considered.** (a) "Compute-bound, lift the clock" —
tested as E1 and **rejected**: see Evidence. (b) Accept 32 tok/s as a
structural ceiling — rejected: E6/E7 are open memory-path levers.
**Evidence.** E1 experiment (2026-05-18): locking the GPU clock
(`nvidia-smi -lgc 3003`) raised it from 2411→~2560 MHz under load and
power from 28→38 W, but decode tok/s did **not** change (32.4→32.46).
A ~6 % clock rise yielding 0 % throughput rules out a compute/clock
bound — the 96 % SM utilisation seen earlier was warps stalled on
memory, not saturating arithmetic (SM util does not distinguish the
two). The E2 context-length sweep showed decode nearly flat (32.3 @
256-ctx → 31.6 @ 2816-ctx), so KV-cache traffic is not the bottleneck
either — the per-token cost is the weight read (BF16 dense + 4-bit MoE
experts). On GB10 (SM12x, no native FP4 — D-018) vLLM runs the Marlin
weight-only FP4 path; achieved effective bandwidth sits well below the
273 GB/s nominal.
**Implication.** Clock and power-profile levers are dead (E1 FAIL). The
throughput levers are **E7** (MTP / speculative decoding — reads the
weights once per K tokens, the right lever for a weight-bandwidth-bound
decode) and **E6** (a faster FP4 MoE kernel with a better memory-access
pattern). Experiment plan in `notes/day1-bench-debug.md`.
**Supersedes.** The D-002 calibration (~50–52 tok/s) is qualitatively
consistent (memory-bound) but its specific number does not transfer to
this checkpoint + vLLM 0.20.0 + Marlin FP4; treat ~32 tok/s as the
measured GB10 baseline pending E6/E7.
**Reversibility.** N/A — a measurement correction and a hardware
finding, not a chosen direction.

---

## D-022 — vLLM image re-pinned `:v0.20.0` → `:v0.21.0`; MTP enabled

**Date locked.** 2026-05-19, Day-2 throughput resolution; human-attested
(decross1).
**Decision.** The inviolate vLLM image pin moves from
`vllm/vllm-openai:v0.20.0` to `vllm/vllm-openai:v0.21.0` — digest
`sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9`,
vLLM 0.21.0, torch 2.11.0+cu130. MTP (Multi-Token Prediction)
speculative decoding is enabled on the Gemma 4 stack via
`--speculative-config '{"method":"mtp","model":".../gemma-4-26b-a4b-it-assistant","num_speculative_tokens":4}'`
paired with the staged official drafter. Supersedes the tag pinned in
D-020; resolves the MTP deferral in D-019.
**Alternatives.**
- Keep `:v0.20.0`, accept ~32 tok/s — rejected: the day_2 50-call
  sweep hard checkpoint requires aggregate ≥ 40 tok/s.
- Re-derive the 40 floor down to the GB10 structural baseline (R1) —
  rejected by the human in favor of meeting the floor.
- n-gram speculative decoding within v0.20.0 — rejected: workload-
  dependent, near-zero input/output overlap on the day_2 sweep
  prompts, would not reliably clear 40.
**Rationale.** Day-2's 50-call sweep failed check #3 (aggregate 29.75
tok/s vs the 40 floor). D-021 established decode is weight-bandwidth-
bound on GB10; the lever that clears the floor is speculative decoding,
which reads the target weights once per K tokens. Empirical image
introspection found `vllm/vllm-openai:v0.20.0` ships no `gemma4_mtp.py`
and no `Gemma4MTPModel` registry entry — PR #41745 (Gemma4 MTP, merged
2026-05-06 @ 27e0057) first appears in the **v0.21.0** release, which
bundles the merged fix (no `infra/vllm_patches/gemma4_mtp.py` bind-mount
needed). Measured: single-stream decode 32.21 → 69.44 tok/s (2.16×);
50-call sweep aggregate 29.75 → 56.09; all 5 sweep checks pass;
determinism intact (speculative decoding is lossless — the target
verifies every token). A DGX Spark community benchmark reached ~108
tok/s single-stream with the same config.
**Operational notes.** v0.21.0 keeps `--moe-backend marlin` (startup
log confirmed `Using 'MARLIN' NvFp4 MoE backend`), CUDA 13.0, torch
2.11.0+cu130, and the NVFP4 weights path — only the vLLM version moved.
The drafter MUST pair with the IT target (D-019; base target = 38%
slowdown). `--max-model-len` is set to 32768 (down from the 262144
default) to free unified memory for the drafter and stop host swapping
(folds in the E5 right-sizing). `infra/vllm_patches/gemma4_mtp.py` is
retired — kept in-tree only as a provenance record. The `day1_block2_*`
task bodies in `plan.yaml` retain `:v0.20.0` as the historical record
of what Day 1 ran. Launch script: `setup/day2_vllm_serve_mtp.sh`.
**Reversibility.** Easy — drop `--speculative-config` and the drafter
mount to fall back to the NVFP4 baseline; re-pin to a new digest after
verifying startup logs (per D-017).

---

## D-023 — Day-3 needle benchmark accepted at 0.72; the 0.85 score bar is mis-calibrated to the scaffold

**Date locked.** 2026-05-19, Day-3 needle-benchmark gate; human-attested
(decross1).
**Decision.** `day3_block2_needle_haystack` is accepted as passing and
day_3 advances to Block 3. The benchmark scored top-1 retrieval
**0.7221** at the plan-default 96-token chunk size: validation check 1
(top-1 is the needle) and check 3 (score ≥ 0.70 floor) pass; check 2
(score ≥ 0.85 "proceed" band) fails. The human cleared the
`day3_needle_score_gate` on the evidence below; check 2's 0.85 bar is
recorded as **mis-calibrated to the Track B scaffold's haystack design**,
not as a retrieval-layer defect.
**Alternatives.**
- Hold at the gate until the benchmark clears 0.85 — rejected: no chunk
  size clears both rank-1 and 0.85 (see below), so the bar is
  unreachable for this haystack; holding would block on an artifact.
- Shrink `--chunk-tokens` until score ≥ 0.85 — rejected as gaming: it
  would not reflect production retrieval (textbook chunks are ~70 words).
- Fix the scaffold's haystack first (varied filler, needle-dominated
  unit) then re-run — deferred: optional cleanup, not gating; can be
  done by Track B later without blocking Day 4.
**Rationale.** A chunk-size sweep (16/32/64/96/128/256 tokens) plus a
paraphrase query characterised the score: the needle is retrieved at
**rank 1 at every realistic chunk size (32–256) and under a paraphrase
query** (genuine semantic recall, no lexical reliance). Score is cleanly
dilution-bound — 0.83 → 0.77 → 0.72 as chunks grow — exactly as
needle-share-of-chunk predicts; a retrieval defect would show wrong
chunks or random scores. The best passing size (ct=32) peaks at 0.83,
still < 0.85; the only finer size (ct=16) fails rank-1 at 0.34 — an HNSW
approximate-search pathology caused by 500 byte-identical filler chunks
(a synthetic-data artifact; real corpora have no such duplicates). No
chunk size clears both rank-1 and 0.85. The plan's "~0.92 expected"
assumed a needle-dominated retrieval unit the scaffold never produces.
The retrieval layer itself — ChromaDB + BGE-M3, cosine space — is sound
and validated.
**Operational notes.** Needle collection verified: `embedding_function:
BGE-M3`, `hnsw.space: cosine`, weights `/mnt/models/bge-m3`. Artifacts:
`bench/day3_needle.json` (official run), `notes/day3-needle-characterization.md`
(the sweep). The Track B scaffold `tests/needle_in_haystack.py` had its
real-client branch wired by Track A on Day 3 (HttpClient :8001, BGE-M3,
cosine). A future cleanup — varied filler instead of one repeated
sentence — would make the benchmark well-posed; tracked as an open item.
**Reversibility.** Easy — the gate decision is a judgement on one
metric; if Day-4+ retrieval underperforms, revisit the embedding/chunking
layer. The 0.85 bar can be re-derived against a fixed scaffold.

---

## D-024 — Architecture v5 diagrams adopted from adversarial review

**Date locked.** 2026-05-20
**Decision.** Adopt `docs/diagrams/architecture_v5.svg` and
`docs/diagrams/intelligence_loop_v5.svg` as the canonical diagrams. The
v4 diagrams are kept in `docs/diagrams/` per the versioning convention
(`docs/diagrams/README.md`).

**v5 changes (loop diagram).**
- Critic / red-team node inserted between Step 2 (generate) and Step 3
  (experiment); retry edge bounded at ≤ 2 cycles. Phase 2.
- Meta-review synthesis node inserted between Step 1 (literature scan)
  and Step 2 (generate). Phase 2.
- Experiment-outcome → loop-memory feedback edge added, gated by Step 8
  (human review). Phase 2.
- Step 6 (novelty evaluation) annotated with Phase 1 human-sampling
  requirement and Phase 2 generator-scorer separation + structured-
  claim search.
- Step 7 (log) annotated with `retrieval_context` reproducibility field
  (schema work scheduled as Day 3.5).
- Step 3 (experiment) annotated with per-hypothesis compute budget
  (Phase 2).
- Step 4 (robustness battery) annotated to clarify falsification ≠
  exploration.
- Degradation-metrics callout added on the right side
  (hypothesis:experiment ratio, model canary, retrieval-context audit,
  researcher calibration log).

**v5 changes (architecture diagram).**
- Orchestrator block expanded with Phase-2 annotation: compute budget,
  cost-aware bandit reward, critic + meta-review worker dispatch.
- `retrieval_context` reproducibility annotation under experiment logs.
- Phase-2 experiment-outcome feedback edge annotated (drawn fully in
  the loop diagram).

**Alternatives.**
- Leave v4 unchanged; capture additions in prose only. Rejected: the
  diagrams are referenced by both `ARCHITECTURE.md` and
  `PROJECT_CONTEXT.md` and are the first read for any new contributor;
  insights that don't make it onto the diagrams effectively don't
  exist.
- Redesign from scratch (v5 as full redraw). Rejected: the v5 deltas
  are additive and clearly labeled Phase 2; a full redraw would lose
  the clean separation between Phase 1 (in flight) and Phase 2
  (planned).

**Rationale.** The 2026-05-19 adversarial review (see
`notes/research/2026-05-19-adversarial-review/1_adversarial_review_memo.md`)
identified seven structural critiques of the Google AI co-scientist
that hold against this project's intended Phase 2 architecture. The v5
diagrams make the Phase 2 additions visible without redesigning Phase 1
elements that have already shipped or are mid-implementation.
v4 is preserved as a baseline showing the pre-review architecture.

**Operational notes.** `ARCHITECTURE.md` §6 reference updated to point
at `intelligence_loop_v5.svg`. `PROJECT_CONTEXT.md` and `START_HERE.md`
will be updated as a follow-up; the v4 SVGs remain present so existing
references do not break.

**Reversibility.** Trivial. Revert the `ARCHITECTURE.md` reference and
the `docs/diagrams/README.md` "current" pointer to v4. v5 files can be
moved to `docs/diagrams/retired/`.

---

## D-025 — ARCHITECTURE.md patches from adversarial review

**Date locked.** 2026-05-20
**Decision.** Apply the patches in
`notes/research/2026-05-19-adversarial-review/3a_architecture_md_patches.md`
to `ARCHITECTURE.md`: replace §6 with the labeled-Phase-1/Phase-2
version, insert §6.5 "Degradation metrics," add the active-vs-passive
paragraph to §4.4, add the compute-budgeting / critic / meta-review
paragraphs to §5.1, and add the two negative-scope bullets to §8.

Schedule the three additive run-log schema changes (P1
`human_intervention` event, P2 `retrieval_context` field on call records,
P3 `calibration_entry` event) as **Day 3.5** in `plan.yaml`, since they
amend Day-2 schema work that has already shipped. Day 3.5 is the
retroactive-amendment slot per the user's instruction that "amendments
to day 1, 2, or 3 go in as a new day 3.5."

**Alternatives.**
- Apply only the §6 changes and defer the rest. Rejected: §6.5
  degradation metrics and the §4.4 active-vs-passive paragraph are
  inseparable from the §6 Phase-2 additions (the meta-review worker
  closes the active-read gap in §4.4; the degradation metrics ride on
  the new annotations on steps 3/7/8).
- Don't apply; carry insights in supplementary memos only. Rejected for
  the same reason as the diagram patches — insights that aren't in the
  canonical architecture document effectively don't exist for any
  future reader.
- Treat P1/P2/P3 as Week-2 proposals and not touch Week 1 at all.
  Rejected by user direction: Day 3.5 captures the retroactive
  amendments to Days 1–3 cleanly, and P2's `retrieval_context` field
  is load-bearing on the project's reproducibility commitment which
  needs to be in place before Day 4 tool-call work hardens.

**Rationale.** Same source as D-024 — the architecture document is the
canonical written walkthrough of the apparatus; if Phase 2 additions
are not in it, they don't exist for any future reader. The Day 3.5
schema-work entries make the additive run-log changes traceable on the
same Week-1 cadence as the other days, and respect the inviolate rule
that version pins, human-only blocks, and hard checkpoints do not
change.

**Operational notes.** Six patches in
`3a_architecture_md_patches.md`; patch 6 was already folded into
patch 1, so five patches landed (1: §6 replacement; 2: §6.5 insert;
3: §5.1 additions; 4: §8 negative-scope bullets; 5: §4.4 active-vs-
passive paragraph). Day 3.5 added to `plan.yaml` with three
agent-executable tasks
(`day3_5_block2_retrieval_context_field`,
 `day3_5_block2_events_schema`,
 `day3_5_block2_wrapper_retrieval_passthrough`) and one human-only
prose task (`day3_5_block3_claudemd_prose`) — CLAUDE.md edits remain
the human's prerogative per the operating contract.

**Reversibility.** Easy. `git revert` the integration commit. The Day
3.5 plan.yaml entries are additive; they can be deleted without
affecting Days 1–7. The schema changes (when Day 3.5 executes) are
additive and nullable — older logs without the new field remain
valid.

---

## Open decisions (pending)

These are tracked but not yet locked in. Move to the main list with an ID
when locked.

- **MTP enablement — RESOLVED 2026-05-19 (D-022).** v0.20.0 was found
  not to ship PR #41745; re-pinned to v0.21.0 and enabled Gemma 4 MTP
  speculative decoding (single-stream decode 32 → 69 tok/s). Qwen 3.6
  MTP remains a Week 2–3 item, tied to introducing that model (D-006).
- **Decode throughput floor / band re-derivation (R1).** The
  `day1_block2_bench` hard floor of 40 and band [50,110] came from the
  D-002 ~52 tok/s calibration, which D-021 shows does not transfer to
  GB10 + vLLM 0.20.0 + Marlin FP4. Re-derive from the measured GB10
  memory-bandwidth baseline (~32 tok/s, pending E6/E7), or from the
  apparatus's actual latency budget; flag the plan validation for
  correction. Tracked with the E2–E8 experiment plan in
  `notes/day1-bench-debug.md`.
- **General architecture re-scope.** Whether v4 architecture and
  technical plan v1 remain sensible given releases between their
  authoring dates and now. Tracked in PROJECT_CONTEXT §6.
- **ML-Intern local migration timing.** At what point Gemma 4 (or Qwen
  3.6, if introduced) meets the reasoning-quality bar to replace the
  Claude API in the ML-Intern pipeline. Tracked in
  `research_apparatus_technical_plan_v1.md` §10, open question 4.
- **CFTC compliance scope.** Ed25519, KYC, trade logging, position
  auditing for Polymarket live trading. Phase 2 infrastructure; landscape
  to be monitored during Phase 1.
- **Cross-tier replication methodology.** What counts as "the same
  finding" across tiers with different evaluation frameworks. Develops
  through experience; track candidate definitions as Phase 1 surfaces
  cross-tier candidates.
- **Day 7 publication review framing.** What information the human
  reviews before clearing the publication gate; what gets surfaced
  automatically vs. on request. Tracked in `plan.yaml` and `CLAUDE.md`.
