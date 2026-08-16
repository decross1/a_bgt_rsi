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
>
> **The most recent decision wins** over an older one it supersedes.
> Use `**Superseded by:** D-NNN (YYYY-MM-DD).` at the top of the
> older entry.

---

## Category index

A reading-finder, not authoritative. Each decision lives in its own
section below; the index just collects them by topic so you don't
have to grep.

### Hardware
- D-001 — DGX Spark, single unit

### Models
- D-002 — Orchestrator: Gemma 4 26B-A4B MoE in NVFP4
- D-006 — Defer Qwen 3.6 to Week 2–3 (dual-model routing excluded)

### Stack — serving and runtime
- D-003 — vLLM image pin (superseded by D-019, D-022)
- D-017 — Pin vLLM image **digest**, not just tag
- D-018 — SM12x compatibility gap awareness
- D-019 — MTP enablement (deferred → resolved by D-022)
- D-020 — `FLASHINFER_CUTLASS for NVFP4 GEMM` expectation update
- D-021 — NemoClaw fallback discipline (Day 1)
- D-022 — Re-pin to `vllm/vllm-openai:v0.21.0` (MTP enabled)

### Stack — knowledge base and retrieval
- D-007 — ChromaDB
- D-008 — BGE-M3 over ChromaDB default
- D-023 — Needle-haystack score band update (informational)
- D-027 — Pipeline source: Semantic Scholar → arXiv API (S2 lag)

### Logging and reproducibility
- D-011 — JSONL append-only call log
- D-012 — JSONL field set (14 fields) for `calls.jsonl`
- D-013 — JSONL integrity verifier
- D-014 — `parent_request_id` chain discipline for tool calls
- D-026 — Day-4 jsonl-integrity check amended (per-artifact counts)

### Orchestration architecture
- D-030 — Retire track/tier model; single primary + optional UI session
- D-034 — Path-B selective sub-agent migration via SubAgent primitive; reference-passing as the next architectural fix

### Scope and fallback discipline
- D-004 — Three-tier sandbox spectrum
- D-005 — Apparatus v0 as Week 1 deliverable
- D-009 — OpenSpiel + GRA for synthetic tier
- D-010 — Bandit keep/discard (Google SCORE excluded Phase 1)
- D-015 — Fallbacks: explicit, logged, time-capped
- D-016 — File-boundary discipline for concurrent tracks
- D-018 — Polymarket live trading is Phase 3 (design-only in Phase 1)
- D-029 — ownership.yaml v2: tighten globs, add zones (Day-8 fix)

### Process and gates
- D-024 — (from adversarial review notes)
- D-025 — (from adversarial review notes)
- D-028 — Day-7 result: not published standalone (aggregating into broader publication)

### Findings
- D-028 — Cooperation lock-in vs cooperators is a Gemma 4 model prior

### Pending / unresolved

See "Open decisions (pending)" at the end of this file for items
tracked but not yet locked in.

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

## D-026 — Day-4 jsonl-integrity check re-pinned: arbitrary `≥30 total` → per-artifact record counts

**Date locked.** 2026-05-21, Day-5 startup; human-authorized (decross1).
**Decision.** The `day4_end_of_day_artifacts` jsonl-integrity validation
in `plan.yaml` is amended. The bullet `total entries across day 4 ≥ 30`
(with `fail_signal: total < 30`) is replaced by per-artifact record
counts: `logs/day4_e2e.jsonl` has 2 linked records (matching
`parent_request_id`) and `logs/day4_robust.jsonl` has 2 records per
trial (10 for `--n 5`). The `verify_log_integrity(...) == 0` checks on
both logs are unchanged. Day 4 was logged `partial_pass` on this bullet;
with the amendment the prescribed scope satisfies the check and the
finding `state.notes.day_4_entries_count_finding` is resolved/closed.
**Alternatives.**
- Coerce the Day-4 `partial_pass` to a pass without amending the plan —
  rejected: violates Inviolate Rule 4 (validations are never silently
  coerced); the mismatch was correctly reported, not recoded.
- Leave the plan unchanged and accept the `partial_pass` permanently —
  rejected by the human: the threshold is wrong, not the run, and a
  standing wrong bar mis-signals every future reader of the plan.
- Inflate Day-4 activity (extra trials/chains) to reach 30 — rejected
  as gaming: it would manufacture log records solely to clear a bar,
  not reflect the prescribed Day-4 scope.
- Lower the aggregate to a flat `≥18` — rejected: still arbitrary and
  brittle. The day-4 run-log entry count drifts as post-review fixes
  and merges append entries (now ~13 run-log + 12 call records ≈ 25),
  so any aggregate is unstable.
**Rationale.** The original `≥30` anticipated richer Day-4 activity than
the prescription (`--n 5` trials of 2-record chains plus one e2e chain)
can produce — that scope structurally yields exactly 12 call-log
records. The meaningful invariant is not a headcount but that each log
artifact contains exactly the prescribed, well-formed chains. The
per-artifact counts pin that invariant precisely and do not drift with
unrelated run-log appends. Reported on Day 4 as a finding (run log
`task_id=day4_end_of_day_artifacts`, `status=partial_pass`) rather than
coerced; carried as `state.notes.day_4_entries_count_finding` and
resolved here.
**Operational notes.** Edit applied to `plan.yaml`
`day4_end_of_day_artifacts` validation block with an inline amendment
comment pointing to this decision. `state.notes.day_4_entries_count_finding`
updated to mark the carryover resolved. Day 4 stays in `completed_tasks`;
its run-log entry keeps the original `status=partial_pass` (the run log
is append-only history — the resolution is recorded forward, not by
rewriting the past entry).
**Reversibility.** Easy — `git revert` the plan.yaml hunk restores the
`≥30` bullet. The amendment is scoped to one validation bullet on one
already-complete day and touches no version pin, human-only block, or
hard checkpoint.

---

## D-027 — Day-5 arXiv pipeline source: Semantic Scholar API → arXiv API

**Date locked.** 2026-05-21, Day-5 Block 2; human-authorized (decross1)
via the `day5_block2_pipeline_implementation` escalation.
**Decision.** `pipeline/arxiv_scraper.py` sources papers from the **public
arXiv API** (`export.arxiv.org/api/query`, Atom feed), not the Semantic
Scholar API the plan originally named. The arXiv API has a native `cat:`
category filter and no indexing lag.
**Context.** The plan's `day5_block2_pipeline_implementation` describes
"Source: Semantic Scholar API." The first run with `--since-days 7`
ingested **1 paper** — far below the ≥30 floor. Diagnosis (direct
probes, logged in `run_state/week1.run.jsonl` under
`day5_block2_pipeline_implementation` status=escalated): Semantic Scholar
has no native arXiv-category filter — each category was mapped to a
free-text query — and S2 lags arXiv on `externalIds.ArXiv` population by
weeks. arXiv-ID counts by window: 7d=1, 30d=30, 90d=51. The plan's
7-day window sits entirely inside the S2 indexing-lag dead-zone.
**Alternatives.**
- Widen the S2 window to ~90 days — rejected: a band-aid that redefines
  "recent" and, critically, leaves the daily cron (24-hour window)
  returning ~0 papers/day. Day 5's headline deliverable is a *working
  daily-cron-able* literature feed; the S2 path cannot deliver one.
- Accept the 1-paper run as a documented below-floor partial — rejected:
  leaves Day 5's core deliverable unmet.
- Re-open ML-Intern — rejected: it inherits the same upstream data
  problem, is the wrong shape (autonomous web-app agent, not a cron-able
  scraper), and the router fallback to direct API is already logged
  (D-nil; see run log `day5_block2_ml_intern_router`).
**Rationale.** The success criterion is "a daily-cron-able script pulls
*new* cs.MA / cs.GT / econ.TH abstracts." arXiv is the publisher: its API
returns papers in those exact categories with zero indexing lag, so both
the first-run 7-day window and the cron's 24-hour window work. This is
the only option that makes the deliverable real, and it stays within the
fallback's spirit ("direct API + simple Python — definitely works").
**Fields.** `semantic_scholar_id` and `citation_count` are not provided
by the arXiv API. The per-paper schema keeps both keys (`null` / `0`) so
`pipeline/embed_and_store.py` is unchanged; `citation_count` is ~0 for
brand-new papers regardless. Both can be backfilled later via the
Semantic Scholar `paper/batch` endpoint (POST `ARXIV:<id>` list) if a use
surfaces — tracked as an optional follow-up, not Week-1 scope.
**Operational notes.** `arxiv_scraper.py` rewritten: stdlib `urllib` +
`xml.etree` only (the `requests` dependency and `SEMANTIC_SCHOLAR_API_KEY`
are dropped; the arXiv API needs no key). One category-filtered query
(`cat:A OR cat:B OR ...`), newest-first, paginates until papers fall
outside the window. `tests/test_arxiv_scraper.py` rewritten to mock the
Atom feed (8 unit tests, all pass). CLI (`--categories / --since-days /
--output`) is unchanged, so the plan command and `cron/daily-arxiv.sh`
are unaffected.
**Reversibility.** Moderate. `git revert` restores the S2 scraper — but
that scraper's 1-paper output is the reason for the switch, so a revert
would re-break Day 5. The arXiv-API scraper is self-contained.

---

## D-028 — Day-7 finding + publication disposition: cooperation lock-in is a Gemma 4 prior; result is not published standalone

**Date locked.** 2026-05-24, Day-7 close-out; human-authorized (decross1)
at the publication-review gate.

**Decision (two parts).**

1. **Finding.** The Day-7 LLM-vs-cooperator cooperation lock-in is
   Gemma 4's *prior*, not a measurement artifact. Across a 4-run
   diagnostic ladder — T ∈ {0.0, 0.2, 0.7} with baseline prompt, plus
   T=0.0 with an `exploitation_hint` prompt — the LLM-vs-TFT (and
   LLM-vs-grim_trigger / LLM-vs-all_c / LLM-vs-mirror_llm) cooperation
   rate is 1.000 on every run. The same model in the same runs defects
   88–98% against `all_d` (rates: 0.120 / 0.110 / 0.120 / 0.020), so
   the model IS responsive to opponent data — it just does not defect
   first against a non-defecting opponent. Sampling artifact and
   framing artifact are both ruled out.
2. **Publication disposition.** The Day-7 result is **not published as
   a standalone announcement**. It will be aggregated as one data point
   in a broader publication that combines Day-7 with subsequent
   experiments (additional games, additional models, additional
   opponent classes). The `day7_publication_review` gate is cleared
   under this disposition.

**Alternatives.**

- *Publish the Day-7 result as a standalone post (preliminary tag
  off).* Rejected. One-game / one-model / one-week-of-apparatus is too
  thin a base for a standalone behavioral claim about Gemma 4, even
  with the 4-run robustness diagnostic. The 1.000 vs cooperators is
  a clean signal but is consistent with multiple causal stories
  (training-data prior, RLHF safety prior, prompt-template prior, etc.)
  that the Day-7 experiment alone cannot disambiguate.
- *Hold the result private indefinitely.* Rejected. The finding is
  publishable in aggregate; the apparatus's value is partly that its
  results compound. Permanently sequestering Day-7 would defeat the
  purpose of the daily-cron pipeline that already feeds Week 2+.
- *Coerce the precompute-range safeguard to "expected" so the gate
  auto-clears.* Rejected by Inviolate Rule 4. The safeguard fired
  correctly; the range was amended (notes/day7_expected_range.md
  →[0.60, 1.00]) *after* the 4-run diagnostic established what the
  model actually does, not to make the bar fit.

**Rationale.**

The cooperation lock-in IS the publish-worthy headline, but the
appropriate venue is a paper-shaped artifact that argues from a
broader evidence base than one game over one week. Aggregating Day-7
into a multi-experiment publication:

- gives the finding a fair shot at causal disambiguation (cross-game,
  cross-model, cross-opponent-class evidence narrows the candidate
  stories),
- avoids the trap where the first apparatus result drives the
  apparatus's reputation (Week 1's deliverable is *the apparatus*, per
  D-005 — the findings come later and the first finding shouldn't
  carry undue weight),
- preserves the option to publish a cleaner, stronger version once
  Week 2+ supplies the surrounding data points (e.g., public-goods +
  stag-hunt extensions per the Week-2 seed, second-model replication
  per D-006).

The 4-run diagnostic ladder (Days 7.1 / 7.2 / 7.3 slips) stands on its
own merit as a Phase-1 methodology contribution and is referenced in
the weekly retrospective; it does not require its own publication.

**Operational notes.**

- `state.human_gates_pending` no longer contains
  `day7_publication_review` after this decision lands.
- `journal/day7.md`'s ⚠️ PRELIMINARY banner is replaced by a
  no-publish disposition note pointing here.
- `notes/day7_expected_range.md` gains a Publication-disposition
  appendix pointing here.
- The Day-7 data itself (`logs/exp001.jsonl`, `results/*`,
  `results_7_*`, `experiment.lock`, the cumulative-payoff plots, and
  the quicklook) is retained unmodified — D-028 governs publication,
  not retention.
- Track D may *consume* Day-7 data freely; D-028 only constrains
  external publication.

**Reversibility.** Easy. To reverse the publication disposition,
re-arm the gate (`state.human_gates_pending` += `day7_publication_review`)
and supersede this entry with a D-NNN that explains the new reasoning.
The finding itself (part 1) is harder to reverse — that would require
new data, not a different decision.

---

## D-029 — ownership.yaml v2: tighten docs-root glob, broaden experiments, add four new zones

**Date locked.** 2026-05-24, Day-8 entry; human-authorized (decross1)
in response to the first 4-track concurrent day surfacing latent
ownership-registry bugs.

**Decision.**

`agent/ownership.yaml` advances from `schema_version: 1` to
`schema_version: 2` with the following changes:

1. **Tighten `docs-root` glob** — replace `*.md` with an enumerated
   list of the 10 root-level project markdown files (ARCHITECTURE,
   CLAUDE, current_day, DECISIONS, GLOSSARY, PHASE_1_ROADMAP,
   PROJECT_CONTEXT, README, START_HERE, week2_plan_seed). The original
   `*.md` pattern over-matched because `fnmatch.fnmatch` — the matcher
   in `tools/claims_check.py` — treats `*` as matching `/`. As a result
   53 markdown files under `agent/**`, `human/**`, `notes/**`,
   `experiments/**`, and `infra/**` were silently multi-assigned to
   both `docs-root` and their own zone.
2. **Broaden `experiments` zone** — change
   `experiments/exp001_repeated_pd/strategies*.py` +
   `experiments/exp001_repeated_pd/quicklook.py` to
   `experiments/exp001_repeated_pd/*.py` (catching `llm_agent.py`,
   `dry_run_llm_vs_all_d.py`, `run.py`). Add `experiment.lock`,
   `.gitkeep`, and `results_*/**` (which catches the three Day-7
   slip-rerun output dirs `results_7_1/`, `results_7_2/`, `results_7_3/`).
3. **Add four new zones**:
   - `setup-scripts` — `setup/**` (Track A, non-dispatchable). The
     five one-shot install / serve scripts (`day1_docker_config.sh`,
     `day1_vllm_serve.sh`, `day2_vllm_serve_mtp.sh`, `day3_chroma.sh`,
     `day4_vllm_serve_tools.sh`) were unassigned.
   - `repo-config` — `.env.example`, `.gitignore`, `.worktreeinclude`,
     `plan.yaml`, `requirements.txt` (Track A, non-dispatchable).
   - `tests-fixtures` — `tests/fixtures/**` (Track C, dispatchable).
     Carved out from `tests-shared` (Track B) so the Day-39 critic
     fixture set and the Day-41 calibration scaffolds, both authored
     by Track C, don't collide with Track-B test scaffolds.
   - `docs-tree` — `docs/**` (Track A, dispatchable). Architecture
     diagrams (D-024 / D-025 SVGs) plus `docs/sources/` reference
     notes were unassigned.
   - `journal` — `journal/**` (Track A, dispatchable). The seven
     daily public posts (`journal/day1.md` … `journal/day7.md`) plus
     `journal/index.md` were caught by the old `*.md` over-match and
     became unassigned after the tightening; this new zone gives them
     a proper home.
4. **Extend two existing zones** to cover their auxiliaries:
   - `state-file` gains `run_state/.gitkeep` and
     `run_state/vllm_image.digest`.
   - `tests-shared` gains `tests/needle_in_haystack.py`,
     `tests/example_call.jsonl`, and `tests/.gitkeep`.
5. **Update `conflict_resolution.track_a_primacy`** to include the
   two new non-dispatchable Track-A zones (`setup-scripts`,
   `repo-config`).

After the changes, `tools/claims_check.py --validate-ownership` reports
**0 multi-assigned, 0 unassigned** across all 283 tracked files;
`--weekly-summary` continues to report 0/0/0.

**Alternatives.**

- *Fix `claims_check.py`'s matcher instead of the patterns.* Rejected.
  Replacing `fnmatch.fnmatch` with `pathlib.PurePath.match` (which
  honors `/` boundaries) would solve the over-match but is a behavior
  change to a Week-1 tool that already shipped clean against actual
  Week-1 usage. The pattern-side fix is local to the registry and
  doesn't touch claim-protocol semantics. The matcher can still be
  swapped later if more zones grow `*.ext` patterns.
- *Carry over as a Week-2 polish item.* Rejected. The Week-2 unlock
  attestation in `human/retrospectives/week2.md` cites the
  claim-protocol-clean week (autonomy.md §4.2). The `--weekly-summary`
  check passed clean, but `--validate-ownership` failed loudly, and
  leaving it failed would mean Day 8's verification task was silently
  coerced past inviolate rule 4. Better to fix in Track A on Day 8 —
  exactly the kind of finding the first 4-track concurrent day was
  designed to surface.
- *Coerce the Day-8 verification task to pass `--weekly-summary` only
  and ignore `--validate-ownership`.* Rejected by inviolate rule 4
  (validations are never silently coerced).

**Rationale.**

The registry is the source of truth for `tools/dispatch_coding_agent.py`
(Day-39 deliverable). If the registry's globs over-match or under-cover,
the dispatcher will assign work to the wrong track or refuse to
dispatch work that belongs in a real zone. Day 8 is the right day to
fix this because:

- Day 8 is the first day with 4 concurrent tracks (A/B/C/D) running
  against the registry simultaneously, so any bug surfaces today.
- The Day-39 orchestrator-dispatch deliverable assumes the registry
  is clean; landing a bad registry into that deliverable would make
  every subsequent dispatch quietly mis-routed.
- The Week-2 unlock attestation's alignment-evidence section
  (autonomy.md §4.2) is more credible with a clean
  `--validate-ownership` than with a noted caveat.

**Operational notes.**

- The changelog in `agent/ownership.yaml` records the v1 → v2 bump
  with the same enumeration of changes above.
- `plan.yaml` task `day8_block2_verify_concurrency_infra` (autonomous
  tier) covers the recurring verify step.
- No claim-protocol changes; this is a registry config update only.
  Existing in-flight claims (none at write time) are unaffected.
- `ui_plan_v2.md` was mentioned in some Day-7 EOD notes but does not
  exist as a tracked file in this worktree; the `ui` zone covers only
  `ui_plan.md`. If `ui_plan_v2.md` is later added, the `ui` zone gets
  an additional path in a follow-on D-NNN.
- **2026-05-24 follow-on (same day, pre-merge).** The `experiments`
  zone gained one additional path — `experiments/fixtures/**` —
  to cover Track C's Day-8 fixture deliverable (critic_hypotheses/
  + novelty_calibration/). The original v2 fix did not include this
  glob because the directory did not exist yet at the time of the
  registry audit. Track C's claim entry labeled the zone as
  `experiments` (the natural conceptual fit), and the
  `experiments/fixtures/README.md` explicitly identifies the dir as
  Track C territory. No separate D-NNN entry; recorded here.

**Reversibility.** Easy. `git revert` restores the v1 patterns; the
recorded multi-assignment / unassigned counts return to 53 / 34.
Tools that read the registry (claims_check, the future dispatcher)
fall back to their v1 behavior without further changes.

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
- **Day 7 publication review framing — RESOLVED 2026-05-24 (D-028).**
  Gate cleared under a no-publish-standalone disposition; Day-7 result
  aggregates into a broader future publication. A second
  publication-review gate will be defined when the aggregate
  publication is drafted (Week 2+ scope).

---

## D-030 — Retire track-A/B/C/D + autonomy tiers; adopt single-primary + optional-UI session model; LOOP_V0 is active slice

**Date.** 2026-05-26.

**Decision.** Retire the four-track parallel-execution framework
(`agent/orchestration.md`, `agent/ownership.yaml`,
`agent/collision_protocol.md`, `agent/prompts/track_{a,b,c,d}.md`,
`agent/prompts/dispatched_task.md`), the three-tier autonomy
machinery (`agent/autonomy.md`), the 30/60/90-day phase roadmap
(`PHASE_1_ROADMAP.md`), the live day tracker (`current_day.md`), and
the Week-2 seed plan (`week2_plan_seed.md`). Retire the canonical
`plan.yaml` (4,037 lines) and the per-day / per-track notes in
`notes/`. Move all retired files under `archive/` for reference.

Adopt a **single primary Claude Code session + an optional concurrent
UI session** model. The UI session is worktree-isolated to
`ui/` + `ui_plan.md`. No other concurrent sessions. No dispatched
sub-agents. The new prompts are `agent/prompts/main.md` and
`agent/prompts/ui_session.md`.

The active build plan is **LOOP_V0** ([`LOOP_V0.md`](LOOP_V0.md)) —
the literature-only slice of the eight-step intelligence loop in
[`docs/diagrams/intelligence_loop_v5.svg`](docs/diagrams/intelligence_loop_v5.svg).
LOOP_V0 chains six steps (seed → hypothesize → retrieve → novelty-classify
→ critique → journal), explicitly omitting the sandbox / experiment
tier work, the continuous loop, the meta-review synthesis, and the
automated Step-8 gate. Each component is a worker (~100–150 LOC);
the loop driver is one file (~150 LOC).

Per-session working notes live at `human/sessions/YYYY-MM-DD.md` and
replace `human/daily_plan.md` (archived).

**Alternatives considered.**

1. **Keep the tier/track system, build LOOP_V0 under Track A only.**
   Rejected: the ceremony costs (per-day startup matrix, claim
   protocol, ownership zones, tier-shift mechanics, phase-boundary
   alignment evidence) outweigh their benefit when only one or two
   sessions actually run. ~10,600 words of governance for a
   ~2,300-LOC product that has not yet run the intelligence loop
   end-to-end. The framework was designed for a future scale that
   hasn't arrived.
2. **Delete the retired files outright.** Rejected: history is
   load-bearing — `DECISIONS.md` cross-references many of these
   docs; `archive/` preserves them as read-only reference without
   keeping them as active rules.
3. **Keep `plan.yaml` as the active plan; only retire the track
   framework.** Rejected: `plan.yaml` is 4,037 lines built around the
   day-by-day / tier-by-tier model. Its task-level detail is now
   stale (Week-1 specific) and the schema embeds `track`, `target_zone`,
   `dispatchable`, and `autonomy_tier*` fields that no longer apply.
   A short `LOOP_V0.md` replacing it is cleaner than editing it down.
4. **Build a different slice first** (e.g., the synthetic-tier
   sandbox: one full experiment with robustness battery). Rejected:
   the diagrams call novelty evaluation the hardest step and the
   loop-memory layer is named as the differentiator from other
   auto-science systems; LOOP_V0's literature-only slice exercises
   both with minimal new substrate.

**Rationale.**

The retired framework was designed to scale parallel work across
multiple human-launched sessions and orchestrator-dispatched
sub-agents, with autonomy tiers gating which classes of work could
proceed without explicit human approval. In practice the project has
been driven by 1–2 sessions per day. The framework's costs (reading,
maintaining, complying with ~10,600 words of governance docs) have
exceeded its benefits (collision avoidance, parallel speedup,
trust-by-evidence trajectory), and the cost is paid every session.

The system diagrams under `docs/diagrams/` describe what the
apparatus is supposed to do; eight days of build have produced the
substrate but not the loop. LOOP_V0 is the smallest slice that
closes the cognitive half of the loop end-to-end, on existing
substrate, with no new sandbox tier required.

The UI session running concurrently is the one form of parallelism
that the new model keeps, because the human has explicitly named
visual observability of the running loop as a precondition for
trusting subsequent autonomy expansions.

**Reversibility.** Fully reversible. All retired files are in
`archive/` and can be restored with `git mv` if the single-session
model proves insufficient. The decision to revert would itself be a
durable signal that parallelism is needed; the framework can be
revived without rewriting.

**What would reverse this.** (1) LOOP_V0 cannot be built within
~6 sessions of focused work, indicating the substrate is more
fragmented than expected and explicit collision avoidance is needed.
(2) The UI session repeatedly produces merge conflicts despite the
worktree boundary, indicating either the boundary is wrong or the
two-session model is undertheorized. (3) An overnight / continuous
loop becomes the immediate next slice after LOOP_V0, at which point
the orchestrator-dispatched sub-agent pattern (currently in
`archive/agent_prompts/dispatched_task.md`) returns from archive as
the right pattern.

**Supersedes.** D-005 (graduated autonomy, in spirit — the tier
mechanism is retired but the underlying instinct, "human in the loop
until specific evidence permits less," remains). Does not supersede
the inviolate-rules portion of `CLAUDE.md`, which is preserved
verbatim in the rewrite.

---

## D-031 — NemoClaw: install feasible, deferred today (sudo-blocked autonomous session)

**Date locked.** 2026-05-26 (LOOP_V0 Part 1, primary session).

**Decision.** Do not run NemoClaw install in today's autonomous
primary session. Keep `NemoClawRuntime` as a `NotImplementedError`
stub in `orchestrator/runtime.py`. The substrate-swappable design
(D-030) holds: when NemoClaw is installed in a future session (by
the human, or interactively), implementing `NemoClawRuntime` is
mechanical and Nara does not change.

**Amendment (2026-06-09, human-authorized decross1) — the "mechanical
NemoClawRuntime swap" is FALSIFIED.** β is **not** a drop-in
`NemoClawRuntime`-as-dispatch-subclass swap. The 2026-06-09 de-risk proved
nara-sandbox is genuinely isolated (no apparatus deps), so β is a real **port**:
an **OpenClaw agent bundle** (`agent/nemoclaw_nara/`) driving a **host-side tool
plane** (`orchestrator/tool_plane.py`) around the unchanged host spine;
`PyRuntime` stays the host default. **Empirically confirmed** the same day — the
write-capable seam ran end-to-end: a sandbox-originated `run_loop_iteration` drove
a full host iteration (`iter-2026-06-09-003`, `seed.source="nemoclaw_agent"`).
This amends D-008's alpha framing and the D-030/D-031 "mechanical swap" language;
`LOOP_V0.md:229` corrected to match.

**Investigation summary** (≈10 min of the 90-min cap):

Status of NemoClaw as of 2026-05-26 (vs. Day-1's D-008 state in
March 2026):

- Now installable via a public installer:
  `curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash`
  Bootstrap clones `github.com/NVIDIA/NemoClaw` and runs
  `scripts/install.sh` from the checkout.
- DGX Spark is officially supported (`spark-install.md` in repo:
  "DGX Spark needs no platform-specific pre-setup as Docker is
  pre-installed"). Per-repo `setup-spark.sh` exists.
- Repo still marked "Alpha" in `CLAUDE.md` ("Interfaces may change
  without notice"), but the install path is no longer the ad-hoc
  state described in March 2026.

Prerequisites on this host (all met):

- Docker 29.2.1 (D-022 vLLM image already running).
- Node.js 22.22.2 (≥ 20 required).
- `NVIDIA_API_KEY` set in env.
- 3.4 TB free on `/dev/nvme0n1p2`.
- User in `docker` and `sudo` groups; Docker accessible without sudo.
- GPU + CUDA 13.0 driver (`nvidia-smi` reports 580.142).

The blocker: the installer needs sudo to run
`nvidia-ctk cdi generate` for NVIDIA Container Device Interface
spec generation (per `scripts/install.sh` line 1850). The host
requires a sudo password (not passwordless). An autonomous Claude
Code session cannot type the password. The installer would prompt
and halt.

Other sudo-using paths in the installer (docker install, docker
systemd enable, docker group add) are no-ops on this host because
Docker is already installed, active, and the user is already in
the `docker` group.

**Alternatives.**

1. Push through with `NEMOCLAW_NON_INTERACTIVE_SUDO_MODE=prompt` —
   doesn't help; still requires interactive password.
2. Skip the nvidia-cdi step — installer warns and continues per
   `scripts/install.sh:1862` ("Could not obtain sudo credentials
   for NVIDIA CDI device spec generation"), but downstream behavior
   when CDI is unset is undocumented and may break GPU access from
   sandboxed agents.
3. Pre-authorize passwordless sudo for the install duration —
   security-meaningful change to the host; out of scope for a doc
   reorg + scaffolding session.
4. The human runs the installer directly outside an autonomous
   session — straightforward; works in any future working session.

**Rationale.** Today's session has scope beyond NemoClaw (Runtime
abstraction, tool registry, schemas, Nara hello-world, end-to-end
smoke). Spending the remaining ~80 minutes of the cap on sudo
workarounds risks zero-output day. The substrate-swappable design
means we do not lose architectural value by deferring: when
NemoClaw is later installed, swapping is a one-line change to the
`runtime=` argument in `nara.run_iteration()`.

**Reversibility.** Trivial. To revive NemoClaw integration in a
future session:

1. Human runs `curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash`
   in a normal terminal (typing the sudo password when prompted).
2. Implement `NemoClawRuntime.dispatch_tool` to shell out to
   `nemoclaw run` or call the NemoClaw CLI's blueprint API.
3. Swap `runtime=PyRuntime()` → `runtime=NemoClawRuntime()` in CLI
   default; PyRuntime stays as fallback.

**What would reverse the deferral.** (1) The human installs
NemoClaw outside the session — the implementation is ~150 LOC
when prereqs are met. (2) Passwordless sudo is enabled in a way
the user is comfortable with. (3) The user explicitly requests an
attended-but-paused install session where they type the sudo
password mid-run.

**Supersedes.** D-008 (NemoClaw alpha discipline, plain-Docker
fallback) — partially. D-008's "re-attempt with fresh eyes at the
end of Week 1" intention is honored; the deferral reason has
shifted from "alpha and breaks" to "installable but needs sudo
interaction we don't have in this session."

**UPDATE 2026-05-26 ~03:00 UTC — install completed (attended).** The
user ran the install in a real terminal with the sudo password
available. Outcome:

- `nemoclaw v0.1.0` CLI installed (`/home/decross1/.npm-global/bin/nemoclaw`,
  symlinked to a wrapper at `/home/decross1/.local/bin/nemoclaw`).
- Sandbox `nara-sandbox` built and running
  (`openshell-nara-sandbox-763df558-...`).
- OpenClaw v2026.5.18 baked into the sandbox image (Dockerfile steps
  22-23). Gateway listening at http://127.0.0.1:18789, /health
  returns `{ok:true, status:live}`.
- Inference: vllm-local provider, model `gemma-4-26b-a4b`, routed
  through NemoClaw's egress proxy at `10.200.0.1:3128`. Sandbox-side
  status reports "Inference (vllm backend): healthy".
- Resource profile: gamer (25% CPU / 25% RAM).
- GPU passthrough verified (3 GPU proofs passed: nvidia-smi, /proc
  comm write, `cuInit(0)` via libcuda).
- Dispatch path verified: `nemoclaw nara-sandbox exec --no-tty -- echo
  "hello"` returns cleanly.

**Two artifacts to note (non-blocking):**

1. **Container Docker healthcheck reports "unhealthy"** even though
   the gateway is fine. The in-container `curl 127.0.0.1:18789/health`
   fails for an internal network-namespace reason, but the gateway is
   reachable from the host and responding. Cosmetic.

2. **`openshell sandbox connect nara-sandbox` hangs** without a TTY
   (same root cause that blocked autonomous install). This affected
   the wizard's step 7/8 ("Setting up OpenClaw inside sandbox") and
   reported a non-zero exit, but OpenClaw was already baked into the
   image at build time, so nothing material was missing. The CLI's
   `exec --no-tty` and the gateway API are the practical dispatch
   paths and both work.

**NemoClawRuntime.dispatch_tool — implementation DEFERRED.** Nara is
currently a Python orchestrator on the host that calls Python worker
functions in-process. Shelling out to the sandbox via `nemoclaw
exec` (or speaking to the gateway API) for every tool call would
add network/serialization overhead for no benefit at LOOP_V0's
current shape. NemoClawRuntime earns its keep when **Phase-2
dispatched coding agents** become real (Nara dispatches a coding
sub-agent to write a new worker → that sub-agent runs as an OpenClaw
session in the sandbox). PyRuntime remains the default and only
working runtime for LOOP_V0 hello-world iterations.

D-031 is now **partially resolved**: install side done, runtime
integration deferred to Phase-2 use cases.

---

## D-032 — Install full `agent_system` skill set into `.agents/` (diverges from BOUNDARY.md)

**Date locked.** 2026-05-26 (LOOP_V0 Part 1, primary session).

**Decision.** Install all 24 skills + 4 agent profiles from
`agent_system` into `a_bgt_rsi/.agents/` as symlinks, with no
runtime-safe filter. This includes the dev-only skills
(`code-review`, `experiment`, `health`, `investigate`,
`plan-research`, `repro-check`, `ship`, `context-save`,
`context-restore`, `orchestrate`, `harvest`, `narrate`,
`decision-log`, `propose`, `review-proposal`, `slip-ladder`,
`auto-experiment`, `spawn-contract`, `brain-recall`) that
`agent_system/BOUNDARY.md` recommends NOT installing into a
project's runtime.

**Alternatives.**

1. Install only the 5 runtime-safe core skills (`resume-state`,
   `gate-check`, `validate`, `run-log`, `fallback`). Honors
   BOUNDARY.md strictly. Considered and rejected.
2. Install all skills but mark them dev-time-only in this project
   (Nara sees only runtime-safe at runtime). Adds a new layer.
3. The chosen path: install everything, document the divergence.

**Rationale.**

The user explicitly chose "full skill set, symlinked" with awareness
that this diverges from BOUNDARY.md. Three reasons it makes sense
for *this* project:

1. **Nara is a research orchestrator, not a customer-facing
   runtime.** BOUNDARY.md's rule is shaped for production agent
   systems where dev-only skills (code-review, ship) would be
   inappropriate when an agent acts on behalf of a user. Nara
   acts on behalf of one researcher (the framework's author),
   and the dev/runtime line is less sharp here than in a
   product context.

2. **Some "dev-only" skills are valuable for research workflows.**
   `experiment`, `repro-check`, `auto-experiment`, `decision-log`
   speak directly to what Nara needs to do well. The
   `runtime-safe` label was set in 2026-05; a fresh look might
   reclassify some of them.

3. **Reversibility is trivial.** If a dev-only skill turns out to
   create problems (e.g., Nara invoking `ship` autonomously), the
   per-skill symlink can be removed from `.agents/skills/` without
   touching the framework.

**What `agent_system/BOUNDARY.md` actually says.** Two skill
classes, by frontmatter:

- **Runtime-safe core (Layer A, `runtime-safe: true`)** — five
  execution-discipline skills. Designed to be embedded in a
  runtime agent.
- **Dev-only (Layers B/C, `runtime-safe: false`)** — research
  vertical + orchestration/meta. "Must never be loaded into any
  project's runtime agent."

This project consciously diverges from the second rule.

**Reversibility.** Per-skill: `rm a_bgt_rsi/.agents/skills/<skill_name>`.
Wholesale revert to runtime-safe only:
`agent_system/install.sh --uninstall && agent_system/install.sh --target-path a_bgt_rsi/.agents/skills --filter runtime-safe`.

**What would reverse the divergence.** (1) A dev-only skill causes
Nara to take an action the human did not want (e.g., autonomously
shipping code, opening PRs). (2) Re-thinking the dev/runtime line
in `agent_system/BOUNDARY.md` and reclassifying some skills as
runtime-safe. (3) The project crosses a maturity threshold where
"this is a research workflow tool, not a product runtime" no longer
holds — at which point honoring BOUNDARY.md becomes important.

**Documented at:** `.agents/README.md` and `agent/README.md`.

---

## D-033 — Exclude Qwen 3.6 entirely; the apparatus stays single-model on Gemma 4

**Date locked.** 2026-05-26.

**Decision.** Drop Qwen 3.6 27B Dense as a planned second model.
The apparatus runs single-model on Gemma 4 26B-A4B-NVFP4 indefinitely.
Per-user direction: keep the machine clean — one orchestrator model,
one embedding model, one substrate. No Qwen weights are pulled, no
`/mnt/models/qwen-*` directories are created, no Qwen-related docker
images are added.

**Alternatives.**

1. Pull Qwen weights now per the prior D-006 plan (Week 2-3 swap).
   Rejected: not needed for LOOP_V0 or Part 2; adds ~30-50 GB and
   substrate complexity (a second served model, routing decisions,
   per-model metric tracking).
2. Leave Qwen "deferred" per the prior plan. Rejected: deferring
   indefinitely is functionally exclusion; calling it that
   honestly tells future-me what to expect.
3. The chosen path: explicit exclusion, with a documented reopen
   condition.

**Rationale.**

- **No Qwen on disk.** `/mnt/models/` has only `bge-m3`,
  `gemma-4-26b-a4b-nvfp4` (active), and the unused
  `gemma-4-26b-a4b-it-assistant` (also being removed). Qwen was
  planned but never installed.
- **The Phase-2 reason for a second model was Elo circularity in
  novelty scoring** (ARCHITECTURE.md §6 step 6: same-model novelty
  grading lets the model surface results from its own embedding /
  output space). The Phase-1 mitigation — logged human-sample rate
  on automated novelty calls — is sufficient when the human is in
  the loop for every iteration, which is LOOP_V0's design.
- **Single-substrate simplifies operations.** One served model means
  one vLLM container, one config, one set of perf measurements, one
  fail-mode-canary, one model-version stamp on every record. The
  Phase-1 design (D-012, D-007) explicitly excluded the dual-model
  routing layer for similar reasons; D-033 extends that posture to
  "no second model at all."
- **Reversibility is preserved.** If a specific bottleneck emerges
  later (Gemma 4 demonstrably fails some class of task that an
  alternative model handles), the swap pattern is a vLLM container
  restart with different weights — minutes of work, not weeks.
  Starting from a clean "no second model" baseline and adding one
  if needed is cheaper than maintaining a "second model is planned
  but not built" hypothetical.

**What this DOES NOT change.**

- Gemma 4 26B-A4B-NVFP4 remains the inviolate-pinned orchestrator
  (CLAUDE.md rule 2 unchanged).
- The Elo-circularity risk on novelty scoring remains real (see
  ARCHITECTURE.md §6 step 6); the Phase-1 mitigation (logged human
  sample rate) becomes the *durable* mitigation, not a temporary
  one until a second model lands.
- D-006 (defer Qwen 3.6 to Week 2-3) is superseded by this entry.
- D-012 (dual-model routing excluded) is reinforced, not changed.

**What would reverse this.** (1) Gemma 4 demonstrably fails a
specific, narrow task class — measured against a known benchmark,
reproducibly, with the failure attributable to model quality rather
than prompt or retrieval. (2) A novelty-evaluation second-opinion
need that human sampling cannot cover — e.g., overnight autoresearch
loops where the human cannot review every call. (3) Compute budget
expands such that running two served models concurrently is no
longer a cost trade-off.

**`gemma-4-26b-a4b-it-assistant` is RETAINED** (832 MB at
`/mnt/models/`). It is *not* unused — the running vLLM container
loads it as the **MTP speculative-decoding draft model** per D-022's
launch args (`--speculative-config '{"method":"mtp","model":
"/models/gemma-4-26b-a4b-it-assistant","num_speculative_tokens":4}'`).
Removing it breaks vLLM on next restart and gives up the ~52 tok/s
single-stream baseline (D-022's whole point). It is referenced by
`setup/day2_vllm_serve_mtp.sh` and `setup/day4_vllm_serve_tools.sh`.

*Process note.* An earlier draft of this decision claimed
it-assistant was unused and removed it; that removal was reverted
~10 minutes later when the dependency was discovered. The lesson:
"check what running containers actually mount before removing
anything under `/mnt/models/`."

**Supersedes.** D-006 (Defer Qwen 3.6 to Week 2-3). D-006 stays in
the log as history; D-033 is the active position.

---

## D-034 — Path-B selective sub-agent migration; reference-passing is the next architectural fix

**Date locked.** 2026-05-26.

**Decision.** LOOP_V0 workers migrate from Path A (one-shot Nara
tool_call) to Path B (bounded multi-turn sub-agent) **selectively,
per worker, when a concrete failure mode justifies it** — not chain-
wide. The mechanism is `orchestrator/subagent.py`, which exposes
`run_subagent(name, *, system_prompt, user_prompt,
expected_output_schema, tools, tool_dispatch, budget,
parent_request_id, ...) → SubAgentResult` (additional keyword-only
args for `log_path` and `model`; see source for the full signature)
with hard caps on turns / wall-seconds / tokens and JSON-schema
validation on output. Workers keep an **identical input/output
contract** across paths so callers don't change when a worker
migrates.

Currently migrated: `workers/critic_loop_v0` (default budget 6 turns
/ 90s; optional `query_chroma` tool; observability fields
`subagent_turns_used`, `subagent_wall_seconds`, `subagent_status`).
Still on Path A: `hypothesize`, `retrieve_literature`,
`novelty_classify`, `journal_writer`.

**Companion decision: reference-passing is the next architectural
priority.** Even with the Gemma inline-tool-call fallback parser
(`agent_wrapper/gemma_tool_parse.py`, 20 unit tests including the
real iter-010 leak sample), the LOOP_V0 chain truncates at the
`max_tokens=1024` cap because Nara copies the full `neighbors` array
through every downstream tool_call's args. The fix: workers fetch
heavy payloads by `iteration_id` from `run_state/iteration_cache/
<iteration_id>/` instead of receiving them in args. Downstream tool
schemas accept `iteration_id` (required) plus only the new fields
each step computes. Nara's prompt is rewritten to forbid re-emitting
captured payloads. `journal_writer` gathers everything from cache at
the end. See [`LOOP_V0.md`](LOOP_V0.md) §"Reference-passing".

**Alternatives considered.**

- *Wholesale sub-agent migration of all five workers.* Rejected:
  over-engineering for the cheap steps. One-shot calls are correct
  for `hypothesize` (single-turn generation), `retrieve_literature`
  (deterministic tool wrapper), `journal_writer` (deterministic
  serializer). Multi-turn would only add latency and token cost
  without changing output quality.
- *Forked Claude Code worktrees as workers.* Rejected for LOOP_V0:
  the substrate-swappable runtime keeps the option open for later,
  but in-process sub-agents are the right primitive for the
  literature-only slice. The cost ceiling, observability, and
  determinism trade-offs all favor in-process.
- *Raise max_tokens above 1024 instead of reference-passing.*
  Rejected: addresses symptom, not cause. Long inline tool_call
  emissions are parser-fragile regardless of cap, and re-emitting
  captured state through args is duplicate-state by construction.
  Reference-passing fixes both the truncation and the fragility at
  once.
- *Migrate off OpenAI tool_calls entirely (custom message protocol).*
  Deferred. The Gemma parser bridges today's stochastic format
  mismatch; a protocol change would compound the migration risk
  while LOOP_V0 is mid-build. Revisit if vLLM upgrade or runtime
  swap (NemoClawRuntime) makes the parser unnecessary.

**Rationale.**

- *Selective migration preserves the per-worker contract.* Outer
  callers (Nara, downstream workers) are agnostic to whether a worker
  is Path A or Path B. Migration is local; rollback is local.
- *SubAgent is runtime-agnostic.* The wrapper call inside
  `run_subagent` goes through PyRuntime today; a future
  NemoClawRuntime swap is mechanical.
- *Reference-passing is the load-bearing prerequisite for real
  iterations.* Without it, the chain truncates probabilistically on
  any iteration whose retrieved neighbors are non-trivial. With it,
  the chain becomes deterministic at the substrate level — Gemma's
  format-choice stochasticity stops mattering at scale.
- *The Path-B primitive unblocks fan-in/fan-out.* Future Nara →
  multiple sub-agents (e.g., three critics from different angles) →
  merged result depends on having `run_subagent` as a primitive.
  Building it now for one worker is the cheapest path to that
  future shape.

**What would reverse this.**

- A worker stays on Path A unless multi-turn reasoning is justified
  by a concrete failure mode observed on real iterations. If
  `critic_loop_v0` is consistently single-turn in practice, the
  migration is reverted and the SubAgent primitive is reserved for
  workers that actually need it.
- If reference-passing turns out to introduce more state-management
  complexity than it removes — e.g., cache lifecycle bugs, race
  conditions across UI polling, schema drift between cache files and
  iteration_record — the alternative is back to direct args with a
  raised token cap and tighter neighbor-payload trimming at the
  `retrieve_literature` boundary (return summaries, not full
  chunk_text, for downstream steps).

**Cross-refs.** D-030 (single-primary session model — Path B
sub-agents are in-process, not concurrent sessions). LOOP_V0.md
§"Path B" + §"Reference-passing". The Gemma parser is documented in
`agent_wrapper/gemma_tool_parse.py` module docstring; the chain
re-prompt mechanism is in `orchestrator/nara.py`.


## D-035 — Multi-backend wrapper substrate; Qwen3.6-27B + Anthropic API onboarded; supersedes D-033

**Date locked.** 2026-05-26.

**Supersedes.** [D-033](#d-033--exclude-qwen-36-entirely-the-apparatus-stays-single-model-on-gemma-4) — the single-model commitment to Gemma 4 is replaced by a tiered, multi-backend apparatus. D-033's same-model novelty mitigation framing is also reconsidered: the Google Co-Scientist paper finding that running the critic on a different model is a load-bearing insight (not a nice-to-have) is the empirical reason to admit a second and third model.

**Decision.** The wrapper becomes backend-pluggable. `agent_wrapper.backends`
exposes a `Backend` protocol; three backends register at module load:

- **`vllm-gemma`** — the existing vllm-served Gemma 4 26B-A4B-NVFP4 path.
  Default. Reads `wrapper._sync_client` / `wrapper._async_client` lazily
  at call time so the ~30 existing `patch.object(W, "_sync_client", …)`
  mocks across the test suite continue to work unchanged.
- **`ollama-coder`** — Qwen3.6-27B dense (Apache 2.0) on Ollama's
  OpenAI-compatible endpoint at `:11434/v1`. Pulled today at Q4_K_M
  (17 GB on disk, ID `a50eda8ed977`). Picked over Qwen3-Coder-30B-A3B
  (MoE), Codestral 25.01 (non-commercial license + 42% SWE-bench vs
  Qwen's 77.2%), and DeepSeek-R1-Distill-Qwen-32B (no published
  SWE-bench Verified). Caveat: the 77.2% number uses Qwen's own bash +
  file-edit scaffold; third-party reproductions are limited as of
  2026-04-23. Coder tier.
- **`anthropic`** — Claude API (default `claude-opus-4-7`) with prompt
  caching on the system message and tool definitions. Anthropic SDK
  0.104.1 installed into `.venv-chroma`. Planner tier — invoked
  selectively for hard / complex orchestration, never as the
  per-iteration default (the apparatus stays self-hosted by default).

The substrate is **additive**: every existing call site defaults to
`vllm-gemma`, no behavior change. Backend selection is opt-in via a
`backend=` kwarg on `call_sync` / `call_async` / `call_with_tools`
(wrapper), `run_subagent` (sub-agent primitive), and `run_iteration`
(Nara). The `calls.jsonl` schema's `host_metadata` is relaxed to allow
heterogeneous per-backend shapes (existing fields remain valid; new
`backend` discriminator added as optional).

**Routing model (today vs deferred).**

- **Today**: declarative — callers (workers, sub-agent dispatchers,
  Nara) opt into a backend at the call site. No automatic routing.
  Coder workloads pass `backend="ollama-coder"`; planning workloads
  pass `backend="anthropic"`.
- **Deferred to follow-up slices** (still under the D-035 umbrella):
  (1) optional `default_model` / `model_tier` field on each tool spec
  so the runtime can route mechanically rather than each call site
  hardcoding the brain; (2) a complexity-calculator stub with a
  threshold-based escalation hook to the planner tier; (3) per-iteration
  override (a "this iteration is hard, use SOTA" flag). These are the
  obvious next surfaces but are explicitly out of today's scope per
  the "for now just onboard and set up" framing.

**Verification.**

- **Unit / translation tests** — 76 tests across the wrapper + backend
  registry + Anthropic translation + critic + worker + orchestrator
  paths all pass. New: `tests/test_backend_registry.py` (8 tests),
  `tests/test_anthropic_backend.py` (15 tests). Pre-existing
  `tests/test_dispatch_coding_agent.py` failures (18 errors) are
  D-030 fallout from archived `agent/ownership.yaml` — unrelated to
  this work.
- **Live smoke — ollama-coder** — blocked. The vllm-gemma4 container
  is holding ~110 GiB of 128 GiB unified memory; Qwen3.6-27B at
  Q4_K_M requires ~36 GiB at inference time; Ollama returns 500
  `model requires more system memory (36.0 GiB) than is available
  (12.2 GiB)`. Substrate is verified by the round-trip (correct
  request shape on the wire); cohabitation requires either a smaller
  Qwen quant, a vllm right-sizing pass, or a scheduled stop/start
  pattern. Tracked as the next-but-one follow-up.
- **Live smoke — anthropic** — blocked on `400 invalid_request_error
  — credit balance is too low`. Request shape correct; live verify
  gated on credit top-up.

**Alternatives considered.**

- *Defer multi-backend until critic-on-different-model is the
  bottleneck.* Rejected: the reference-passing refactor (D-034) and
  the multi-backend substrate both touch `wrapper.py`, `subagent.py`,
  `nara.py`. Laying the substrate first lets reference-passing land on
  a backend-aware foundation, and avoids cracking open the same files
  twice.
- *Adopt an LLM-as-router from day one.* Rejected: premature without
  evidence the static per-tool tier is wrong. Hook is in place for
  later (complexity-calculator stub is the deferred follow-up).
- *Graduate Nara itself to Claude Opus every turn.* Rejected for now:
  the apparatus design pillar is self-hosted by default; SOTA is the
  ceiling, not the floor. The substrate permits the graduation later
  with a one-line change (`run_iteration(..., backend="anthropic")`),
  but the default stays vllm-gemma.
- *Re-pull `qwen3.6:35b` to match the pre-D-033 setup.* Rejected:
  Qwen3.6-27B's SWE-bench Verified (77.2% per Qwen's blog) and
  Terminal-Bench 2.0 (59.3%) are well ahead of the older 35B sibling
  for coding-tier workloads, and the smaller footprint helps with the
  co-residency RAM problem (which is the binding constraint anyway).

**Why this is not a rollback of D-033.** D-033's commitment was to
the apparatus staying single-model on Gemma 4 *for novelty scoring* —
the same-model novelty-classify worker stays Gemma. What D-035 admits
is that *other* roles (critic, planner) benefit from a different
model. The novelty-classify worker remains on Gemma per D-033's
mitigation framing (logged human sampling per ARCHITECTURE.md §6 step
6). The critic is the worker most likely to flip first, per the
Co-Scientist insight.

**Pointers.**

- `agent_wrapper/backends/{__init__,base,vllm_openai,ollama_openai,anthropic}.py`
- `schema/calls.jsonl.schema.json` — `host_metadata` relaxed
- `tests/test_backend_registry.py`, `tests/test_anthropic_backend.py`
- Research that picked Qwen3.6-27B over the alternatives: in-session
  general-purpose agent report, 2026-05-26.


## D-036 — Critic-flip (Co-Scientist insight) empirically tested on three topics — no observed benefit on this evidence; binding constraint is upstream

**Date locked.** 2026-05-27.

**Refines.** [D-035](#d-035--multi-backend-wrapper-substrate-qwen36-27b--anthropic-api-onboarded-supersedes-d-033) — the multi-backend substrate stays as-is; the specific *application* of routing the critic to a non-Gemma backend was tested and falsified for this round.

**Decision.** Do not permanently route `workers/critic_loop_v0`'s sub-agent to a non-Gemma backend on the current evidence. The infrastructure (env-driven `CRITIC_BACKEND`, `vllm-qwen` registered, SubAgent's `reasoning_content` fallback, UI divergence-chip) all stays — it works and is available the moment empirical evidence justifies turning it on. But for these three topics, on this retrieval, the Co-Scientist insight produced *no* divergent verdicts. The binding constraint is upstream of the critic.

**The test.**

Pre-committed rule (from `human/sessions/2026-05-27.md`'s Phase-3 plan):
> *flip-critic-if: Critic returns 'survives' on Topic 2 (rediscovery probe) without surfacing KMR/Young or equivalent risk-dominance literature, OR returns 'survives' on Topic 3 (the deliberately wrong claim). Either failure alone is enough — both is dispositive.*
> *keep-critic-if: Critic correctly flags Topic 2 as rediscovery with at least one named citation to the risk-dominance literature, AND falsifies Topic 3 with the backward-induction/unraveling argument spelled out.*

Procedure: ran each topic twice — once with Gemma critic (Phase 2 baseline), once with `CRITIC_BACKEND=vllm-qwen` (Qwen3.6-27B NVFP4-MTP on :8001).

**Findings.**

| Topic | Gemma critic | Qwen critic | Same verdict? |
|---|---|---|---|
| 1 — open / Bayesian PGG (iter-004 vs iter-009) | `novel/survives` | `novel/survives`, 59.3 s, 2 turns | yes — identical conclusion, slightly more specific rationale on Qwen ("doesn't address conditional cooperation, Bayesian belief updating under noisy observations") |
| 2 — rediscovery probe (iter-002 vs iter-007) | `novel/survives`, 4.1 s | `novel/survives`, 52.6 s, 2 turns | yes — identical conclusion, Qwen named Osborne & Rubinstein explicitly |
| 3 — deliberately-wrong PD claim (iter-003 vs iter-008) | `rediscovery/survives` (Gemma critic; novelty also `rediscovery`) | substrate failed: `schema_mismatch` → critic_loop_v0 fallback `survives` — but **novelty classified `nonsense` AND Nara's summary engaged with backward induction explicitly**. The chain caught the deliberate wrongness; the critic step didn't get to. | inconclusive at the critic step; chain-as-a-whole correct |

**Cost observed.** Qwen critic ran 12–30× slower (Gemma 2–4 s, Qwen 50–60 s) and produced a `schema_mismatch` substrate failure on 1/3 runs even with the `reasoning_content` fallback in place (intermittent Qwen reasoning-placement variance).

**Diagnosis of why both critics agreed.** Both critics follow the same contract: *"Do NOT invoke knowledge from outside the retrieved set."* In all three topics, the retrieved set was Osborne & Rubinstein foundational chunks that don't cover the specialized claims at hand. Both critics correctly reported "the retrieved literature does not contain results that would falsify this." That's the *correct* behavior given the contract — not "marking own homework". The Co-Scientist insight assumed the critic was the bottleneck; for this evidence, it isn't.

**Binding constraints actually surfaced.**

- **Retrieval gap** (Topic 2). KMR 1993 / Young 1993 / Ellison 1993 / Blume 1995 are not in Chroma's foundational layer. A coordination-games-on-networks topic that asks about risk dominance can't get a rediscovery verdict when the rediscovery literature isn't retrievable. **Fix: Track B retrieval expansion** (the next slice).
- **Hypothesize selection bias** (Topic 1). The worker generated three candidates; candidate #2 contained the exact asymmetric-updating mechanism the user was probing for ("inflating the posterior probability of 'defector' types"). The worker selected candidate #1 — the most generic restatement. **Fix: prompt tightening to prefer mechanism-engaged candidates over linguistic restatements.**
- **Hypothesize claim sanitization** (Topic 3). The deliberately-wrong claim was rewritten before the critic ever saw it (verb flipped, inequality flipped). **Fix: an `as-stated` mode that bypasses the rewrite when the user signals "test this claim verbatim".**

**Reopen conditions.** D-036 falsifies critic-flip *on the current evidence*. The flip reopens cleanly if/when:

1. **Retrieval cooperates AND hypothesize preserves the claim AND the critic still parrots / fails to push back.** That's the actual "marks own homework" failure mode the Co-Scientist insight targets. It hasn't been observed.
2. **A workload arises where the critic's contract has to invoke outside knowledge.** Today the contract is "only retrieved literature"; if we widen it (e.g., let the critic call `query_chroma` more aggressively or invoke a broader knowledge base), a different-model critic might surface different judgments.
3. **The hypothesize and retrieval fixes (Track B + prompt tightening) land, three more iterations run, AND a critic-marks-own-homework pattern emerges in the cleaner data.**

**What stays in the apparatus.**

- `vllm-qwen` backend registration in `agent_wrapper/wrapper.py`.
- `CRITIC_BACKEND` env var read in `workers/critic_loop_v0.py`.
- `SubAgent` `reasoning_content` fallback for Qwen-class reasoning models (`orchestrator/subagent.py`).
- UI divergence chip wiring (sky-accented subagent chip in `ActiveIterationPanel`).
- The `vllm-qwen` container itself (port 8001) — keep running. Coder-tier workloads (Phase 2+) will use it; substrate is ready.

**What does NOT change.**

- D-035's multi-backend substrate stands. The infrastructure was the right investment regardless of this specific Co-Scientist application.
- The novelty classifier's same-model risk (per ARCHITECTURE.md §6 step 6) is unchanged. D-033's human-sampling mitigation remains the durable mitigation for novelty scoring.
- Anthropic backend stays wired; can be used for the planner tier when actually-hard planning shows up.

**Pointers.**

- `human/sessions/2026-05-27.md` § Phase-2 / Phase-3 (when written) — full session-level narrative.
- `journal/iterations/{012..020}.md` — the iteration journals on disk.
- `memory/loop_memory.jsonl` — structured iteration_records; gitignored.
- `iter-2026-05-27-002` / `-003` / `-004` (Gemma critic) and `-007` / `-008` / `-009` (Qwen critic) — the comparison pairs.

**Process note.** This entry is itself an example of what research_program_v2 § "Public research journal as primary data" asks for: a *negative* result honestly documented. The Co-Scientist insight wasn't wrong in principle; it just isn't the failure mode this slice surfaced. Falsifying it cheaply ($0, ~3 hours of work) before building elaborate planner-tier infrastructure around it is the apparatus working as designed.

## D-037 — Authorize Dynamic Workflows; amend D-030's single-session constraint

**Date locked.** 2026-06-05.

**Amends.** D-030 — the single-primary operating model is amended, not revoked.

**correction:** Local constraints written for previous-generation tooling must not rate-limit newer shipped Claude Code capabilities. When a managed, bounded, observable primitive ships that handles the failure modes an old prohibition guarded against, amend the prohibition rather than letting it cap the new capability.

**Decision.** Dynamic Workflows (the `Workflow` primitive shipped 2026-05-28 with Opus 4.8) are **permitted** and are the **default vehicle** for parallelizable build / audit / research work in the primary session. D-030's "no dispatched coding agents / no multi-worktree matrices" ban is amended: it still governs *manual* parallel human/Claude sessions (the retired track-A/B/C/D machinery); it does **not** govern the Workflow primitive.

**Why D-030 doesn't apply to Workflows.** D-030 reacted to pre-2026-05 tooling — hand-rolled multi-worktree day-matrices with claim-and-lock coordination that produced merge chaos and stale-HEAD forks. Dynamic Workflows removes the conditions that motivated the ban:

- **Bounded.** Runtime caps a run at 16 concurrent / 1000 total agents; no runaway fan-out.
- **Observable.** `/workflows` shows live per-agent progress + token cost.
- **Context-isolated.** The orchestration script (not Claude's context) holds the loop and intermediate state; the parent only sees the synthesized result.
- **Resumable.** Same script + same args replays cached agent results.

**The guardrails that DO stay** (codified in `CLAUDE.md` §"Dynamic Workflow discipline"): inviolate rules inherit to every subagent; **parallel limbs / serial spine** (build agents create disjoint new files; a single serial integrator owns `orchestrator/nara.py` + `orchestrator/tool_registry.py` + `schema/iteration_record.schema.json`); spawn-contract per build agent; single human-authority commit gate after `code-review` + full suite + real smoke; workflow phases log to `run_state/week1.run.jsonl`. These preserve the SDLC discipline D-030 was really protecting — without forbidding concurrency.

**Reversibility.** High. Toggle workflows off in `/config`; revert to serial primary-session builds. No data migration. The discipline subsection and this entry document the boundary so re-tightening is a one-edit change.

**What does NOT change.** The single concurrent UI-session rule; the bounded-codegen budget (~100 lines per component, now enforced per-agent); MOCK_LLM discipline; human gates blocking; version pins; the prohibition on continuous-running orchestrators and live Polymarket trading.

**First application.** Loop v1 build (full v5 loop: steps 1.5 / 2.5 / 5 / 8) — a Build (parallel) → Integrate (serial) → Verify workflow. See `human/sessions/2026-06-05.md` and `.claude/plans/elegant-bouncing-gem.md`.

## D-038 — ML-Intern uses Semantic Scholar for topic-based foundational backfill, scoped distinctly from D-027

**Date locked.** 2026-06-05, LOOP_V0 Slice-2 wiring; serial-integrator spine work.

**Decision.** The Slice-2 `ml_intern` worker (`workers/ml_intern.py`) queries the **Semantic Scholar Graph API** for topic-relevant papers, embeds their abstracts with BGE-M3, and stores them in a dedicated `ml_intern_fetched` Chroma collection (`source_layer: "live_ml_intern"`). It fires deterministically, orchestrator-driven, at most once per iteration when `retrieve_literature` signals escalation (weak signal AND narrow foundational coverage), after which retrieval re-runs against the now-registered collection.

**Why this does NOT reopen D-027.** D-027 rejected Semantic Scholar for the **daily-recent arXiv pull** because S2 lags new arXiv-ID indexing by weeks — the 7-day window sat entirely inside S2's indexing dead-zone. That failure mode is specific to recency-windowed retrieval keyed on freshly-published arXiv IDs. ML-Intern does the **opposite** job: topic-based, all-time relevance search where S2's broad corpus and citation graph are the right source, and indexing lag is irrelevant (the relevant foundational/canon papers are years old and fully indexed). The two uses are complementary, not contradictory: arXiv API for the recent pipeline (D-027 stands), S2 for topic backfill (this entry).

**Containment.** ML-Intern writes only to `ml_intern_fetched`, kept separate from the human-curated `papers_recent` and foundational collections so an automated, unreviewed pull never pollutes them. The worker never raises (inviolate rule 7); any error / 0-stored leaves the original weak retrieval and the chain proceeds.

**Reversibility.** High. Unregister `ml_intern_fetched` from `orchestrator/chroma_query.py:COLLECTIONS` and remove the orchestrator-driven block in `orchestrator/nara.py`; no data migration (the collection is git-ignored Chroma state). The schema enum widening is additive and backwards-compatible.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## D-039 — Gemma 4 QAT evaluated vs the NVFP4 pin — SHELVED

**Status.** Ratified 2026-06-09 (human-authorized decross1). Disposition: **SHELVE the exp008 live run.**

**Disposition (2026-06-09) — SHELVE.** No interpretable or deployable result is reachable here: (1) Google ships no vLLM-native W4A16 QAT for 26B-A4B, so even a win yields no production swap — the NVFP4 pin stands (inviolate rule 2); (2) arm C OOM-froze the box and the new memory guard now mechanically refuses it; (3) arm B carries an uninterpretable llama.cpp-vs-vLLM engine confound (arm C was the only disambiguator); (4) N≈10 is directional only. **Revisit** only on a dedicated-GPU box, with production paused behind the guard, or if a vLLM-native W4A16 path ships. The `experiments/exp008_qat_eval/` harness is preserved as-is; nothing in production serving is touched.

**Date drafted.** 2026-06-08. Single-serial-integrator wiring of the `experiments/exp008_qat_eval/` benchmark harness (eval-only, no production swap).

**Trigger.** Gemma 4 QAT (quantization-aware training) is a quant variant of the *exact* model the orchestrator already runs (Gemma 4 26B-A4B). On GB10 the binding throughput constraint is memory bandwidth — fixed silicon (D-021). Bandwidth is not a lever we can pull, so the only thing a quant change can buy is **quality**, and quality is what determines whether the orchestrator's own judgments (novelty scoring, tool-calling, robustness) are trustworthy. QAT promises near-BF16 quality at 4-bit footprint, so it is worth measuring against the current NVFP4 pin — strictly as evaluation, not as a deployment.

**Design.** Three arms, eval-only, **NO production swap**:
- **Arm A** — the production NVFP4 pin as-is (`/mnt/models/gemma-4-26b-a4b-nvfp4`, `vllm/vllm-openai:v0.21.0`, Marlin MoE), the baseline.
- **Arm B** — Gemma 4 QAT as a llama.cpp GGUF quant.
- **Arm C** — Gemma 4 QAT unquantized under vLLM.

All arms are served on a **scratch container, port `:8002` only** (`serve_qat.sh`); the production `:8000` endpoint, image, config, and launch args are never touched. Eval calls log to `experiments/exp008_qat_eval/runs/*.jsonl`, never to production `logs/calls.jsonl`. Greedy decoding (temperature 0), one request at a time, for all quality runs. Eval surfaces: tool-calling, robustness, novelty.

**Planning-confirmed blocker.** Google ships **no vLLM-native W4A16 QAT** for the 26B-A4B variant — the MoE 4-bit path carries quality loss and only GGUF + unquantized weights exist. So even Arm B/C "winning" the eval does **not** yield a drop-in production swap: H1 (adopt QAT) is gated on a serving path that does not exist today. This experiment measures the quality ceiling; it cannot, by itself, authorize a swap.

**Tensions.** CLAUDE.md inviolate rule 2 (version pins are verbatim — the NVFP4 weights path + vLLM image + Marlin MoE backend); D-017/D-022 (the MTP-enabling image pin); D-018 (SM12.1 build constraints). This entry does not touch any of them — the harness is a scratch-port benchmark, and the pin stands.

**Reversibility.** The *experiment* is trivial and fully reversible (a scratch container + eval-scratch JSONL under `experiments/exp008_qat_eval/`; nothing in the serial spine, schema, agent_wrapper, workers, run_state, or production serving is touched). A *production swap*, by contrast, is **not** trivially reversible and is explicitly out of scope here — it would require its own decision once a real W4A16 serving path exists and the eval favors QAT.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

## D-040 — Unattended Nara autonomy contract (effective at β; amends the continuous-orchestrator guardrail)

**Status.** RATIFIED 2026-06-08 by the human (this entry added to `DECISIONS.md`
and the `CLAUDE.md` out-of-scope guardrail amended to point here). The contract
takes effect **only at β** — it grants no operative autonomy until Nara is
packaged as the always-on OpenClaw agent; until then the continuous-orchestrator
guardrail stands unchanged. The MAY/MUST-NOT boundary below is the agreed
contract for that unattended Nara.

**Date drafted.** 2026-06-08. Formalized from the autonomy contract in
`human/sessions/2026-06-08.md` (lines 14–20) and the α→β→γ build path (line 12).

**Amends (on ratification).** The `CLAUDE.md` out-of-scope guardrail
"Continuous-running orchestrator — not yet; LOOP_V0 is single-shot,
human-triggered iterations." This contract is the instrument that lifts that
guardrail — but **only at β, only when the human ratifies, and only within the
bounds below.** The guardrail stays fully in force until then; the α coordinator
brain shipped 2026-06-08 deliberately stayed host-side, non-continuous, opt-in,
default dry-run precisely so it landed under the *current* (un-amended) rules.

**Context.** β packages Nara as an always-on OpenClaw **agent** in the
`nara-sandbox` NemoClaw runtime — NOT a worker-runtime swap. The 2026-06-08
probe finding established that the sandbox is genuinely isolated (our repo/venv
are not in it; Python 3.13 vs host 3.12; the model is reachable only via
OpenClaw's provider routing), so NemoClaw runs OpenClaw agents, not our
in-process Python workers. β therefore = "package Nara as the OpenClaw agent,"
which is what makes a *continuous* Nara a real proposition and is why the
guardrail amendment is needed now and not earlier. (See the D-031/D-008 update
also pending from 2026-06-08.)

**Decision.** When ratified, unattended (scheduled, always-on) Nara operates
under the following bounded contract. Nara essentially **inherits the
human-session operating discipline** — every inviolate rule in `CLAUDE.md`
binds Nara exactly as it binds a primary session.

### Unattended Nara MAY:

1. **Plan** — on a schedule, assess whole-system health and in-flight
   experiments (reading the 2026-06-06 instrumentation:
   `active_run` / `worker_activity` / `surfaced_findings` — Nara's "eyes"),
   generate hypotheses, and plan the day.
2. **Run experiments / loop iterations** — execute LOOP_V0 iterations and
   experiment runs within its constraints.
3. **Spawn agents** — critic / review / analysis sub-agents (and coding agents
   under the same discipline) to do bounded work.
4. **Build new tools and improve the system within constraints** — additive,
   bounded work consistent with the bounded-codegen rule (inviolate rule 8).
5. **Do LIMITED commit/push** — only behind the verify gate (tests green +
   `code-review` + a real smoke). Default destination is a `nara/auto/*`
   branch. **Merges to `main` remain human.**
6. **Bubble up proposals** — surface applied/trade IDEAS and proposals through
   the messaging channels (the bubble-up mechanism), for the human to act on.

### Unattended Nara MUST NOT:

1. **Execute live trades.** Live trading is human-only (consistent with the
   Polymarket design-only guardrail / D-018). Trade IDEAS may be bubbled up;
   execution may not.
2. **Widen its own or its sub-agents' permissions beyond a granted preset.**
   Permission presets are the constrained-autonomy mechanism (this is the seam
   γ builds on); Nara may not self-escalate or grant a sub-agent more than a
   subset of its own granted preset.
3. **Bypass the verify gate.** No commit/push without tests-green + the review
   + smoke gate; no degraded/silent path around it (inviolate rule 7).
4. **Touch inviolate pins or guardrails.** Version pins (inviolate rule 2),
   human gates (rule 3), validations-never-coerced (rule 4), mandatory logging
   (rule 6), and the remaining out-of-scope guardrails stand. Nara does not
   edit `CLAUDE.md` / `DECISIONS.md` or the inviolate-rule set itself.

**Alternatives considered.**

1. **Keep the hard continuous-orchestrator ban; never go always-on.** Rejected:
   it forecloses the user's central β→γ vision (Nara as a secure, always-on
   OpenClaw agent) without retiring the *real* protection — which is the
   discipline, not the single-shot triggering. The α slice already showed the
   apparatus's discipline can be enforced mechanically (the constrained action
   menu + `validate_plan`), so "continuous" need not mean "unbounded."
2. **Go always-on with no formal contract (implicit trust).** Rejected: it
   violates the apparatus's whole premise. Autonomy without a written,
   ratified MAY/MUST-NOT boundary is exactly what the guardrail exists to
   prevent.
3. **The chosen path: a written, human-ratified, preset-bounded contract that
   amends the guardrail at β and inherits every inviolate rule.**

**Rationale.** The continuous-orchestrator guardrail was written for a
single-shot LOOP_V0 with no constrained-action enforcement and no isolated
runtime. β changes both conditions: (a) the α coordinator's
`coordinator_actions.validate_plan` proved a planner can be held to a fixed,
budgeted action menu where off-menu / over-budget / bad-arg plans are *rejected,
never executed* (verified independently 2026-06-08); and (b) NemoClaw provides
a genuinely isolated sandbox with permission presets as the autonomy lever. With
those in place, "continuous" is no longer synonymous with "unbounded," so the
guardrail can be *amended* (not revoked) to permit a disciplined always-on Nara —
in the same spirit as D-037 amending D-030 for Dynamic Workflows: when a bounded,
observable mechanism handles the failure modes an old prohibition guarded
against, amend the prohibition rather than let it cap the capability.

**What does NOT change.** Live-trade prohibition (human-only); version pins;
human gates blocking; validations never coerced; mandatory run-logging; the
single-model constraint (D-033); MOCK_LLM discipline. `main` merges stay human.
Nara cannot amend its own contract.

**Reversibility.** High by design. The amendment is one paragraph in
`CLAUDE.md`; revert it and Nara returns to single-shot, human-triggered
operation. The permission presets are the throttle — tighten or revoke a preset
to narrow Nara's authority without code changes. No data migration.

**Dependencies / sequencing.** Blocked on **β** (Nara packaged as the always-on
OpenClaw agent in `nara-sandbox`). γ (permission-scoped NemoClaw sub-agents,
`docs/specs/gamma_permission_scoped_subagents.md`) builds on this contract's
preset mechanism. The pending D-031/D-008 update (sandbox-isolation finding) is
a companion to this entry.

**Ratification gate (HUMAN-ONLY).** To put this in force the human must, in one
attended action: (1) paste this entry into `DECISIONS.md` as D-040, and
(2) amend the `CLAUDE.md` out-of-scope continuous-orchestrator guardrail to point
at D-040. Until both are done, this contract is inert and the guardrail stands
unamended.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

## D-041 — β is gated on a validated independent novelty skeptic + the memory guard

**Status.** Ratified 2026-06-09 (human-authorized decross1). Extends D-035
(Co-Scientist: a different-model critic is load-bearing). Supersedes the RESERVED
placeholder.

**Decision.** Before the unattended loop (β / the D-040 autonomy switch) may be
armed, a novelty/critique verdict must be checked by a **skeptic step separate from
the generator**, and the **free-memory pre-flight guard**
(`experiments/exp008_qat_eval/preflight_mem.sh`) must gate every model launch.
Single-model self-scoring (Gemma grading Gemma) is mitigated today only by human
sampling; β removes the human, so the skeptic is a hard β prerequisite, not a nicety.

**Skeptic route — priority ladder (use the highest available; each tier states its
independence guarantee honestly, inviolate rule 4):**

1. **Qwen** (on-box `:8001`, behind the memory guard) — the preferred standing
   skeptic: a genuinely *different model* from Gemma, so it does not share the
   generator's blind spots (true independence). **Gated on a separate quality
   validation first:** the empty-content issue was token starvation (fixed —
   `max_tokens` ≥ 3072), but Qwen must PASS a stand-alone skeptic back-test
   (schema-valid, genuinely-skeptical verdicts on a labelled set) before it is
   trusted as the standing skeptic. "It returns JSON" is not "it is a quality skeptic."
2. **Gemma 4 with a critic-specific skill-set + persona** (a distinct critic prompt
   on the host model) — the operational fallback when Qwen is unavailable.
   **CAVEAT — does NOT clear the strict independence bar:** it shares weights with
   the generator, so it shares blind spots; it is a prompt/persona-level skeptic,
   not a model-independent one. Better than no skeptic, but β armed on tier-2 ALONE
   is a weaker guarantee — tier-1 (validated Qwen) or tier-3 must back the full gate.
3. **Claude** (Opus — and/or a lighter tier; "fable" per the human's note, model TBC)
   via the **Claude Agent SDK on the max-plan subscription** — only if needed (local
   skeptics disagree or are down). Narrow, explicit exception to D-014: the apparatus
   *main reasoning loop* still never authenticates to Claude (D-013/D-014 intact);
   only the bounded **critic-only** step may, via the Agent SDK + max plan (NOT
   metered API credits). Annotate D-014 when this tier is first wired.

`gemma-persona` is NOT a substitute for a different-model skeptic — it is tier-2 with
the caveat above; the strict independence the gate wants is tier-1/tier-3.

**Reversibility.** Reversible — the route is config (`workers/novelty_skeptic.py`
backend selection); the durable rule is the gate (β needs a validated skeptic + the
memory guard) and this priority ladder.

**Open item (human, when tier-3 is reached).** Confirm the exact Claude model for
"fable", and that the Agent-SDK / max-plan path is the intended auth (not API credits).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

## D-042 — orchestrate / experiment / repro-check / plan-research are intentionally REFERENCED-ONLY (harvest re-flags resolved)

**Date locked.** 2026-06-09. Agent-governance harness cycle; serial-integrator wiring under the human's 2026-06-09 attestation.

**Relates to.** [D-037](#d-037--authorize-dynamic-workflows-amend-d-030s-single-session-constraint) — Dynamic Workflows + the verify gate are the substitution this entry records.

**Decision.** The four framework skills `orchestrate`, `experiment`, `repro-check`, and `plan-research` are, in this apparatus, **intentionally referenced-only** — their function is met by the **Dynamic-Workflow + verify-gate substitution** (D-037), not by invoking the skills as named procedures. `orchestrate`'s role-decomposition / parallel-execution job is carried by the `Workflow` primitive under the §"Dynamic Workflow discipline"; `experiment` / `repro-check` are carried by the run log + `DECISIONS.md` + per-experiment harness dirs (the project deliberately keeps no separate `experiments.md` ledger); `plan-research` is carried by the daily `human/sessions/` working note + the staged plan. Harvest passes should **stop re-flagging** these as gaps/frictions: the divergence is a ratified design choice, recorded here so the harvest watermark has a durable reference instead of re-surfacing it each cycle.

**Verified harvest mapping** (against `agent_system/memory/feedback.jsonl`, this cycle): `orchestrate` -> **H002** (confirmed L23/L24, friction L33 under H005), **H005**, **H007** (confirmed L42); `experiment` -> **H002** (friction L21, the "allow the run log to be the experiment ledger" finding); `repro-check` -> **H002** (confirmed L22) and **H003** (friction L29, the real-vs-mock check); `plan-research` -> **not harvest-flagged** (zero `feedback.jsonl` hits — listed here for completeness, not because a finding exists). This entry dispositions those findings as *won't-fix-by-design* on the consumer side; they may still inform framework-side skill edits, which is the framework's call, not the apparatus's.

**Why referenced-only, not adopted.** Adopting the skills as literal procedures would duplicate machinery the apparatus already has in a more discipline-bound form: the Workflow primitive is bounded/observable/resumable (D-037) where `orchestrate`'s hand-rolled worktree matrices were the very thing D-030 retired; a separate `experiments.md` is a parallel store the project rejected in favor of the single append-only run log; `plan-research`'s artifacts already live in the session note. The skills remain *symlinked and available* (`.agents/skills/`) for ad-hoc dev-time use; they are simply not load-bearing in the apparatus's standing loop.

**Reversibility.** High. This is a documentation/disposition decision — it changes no code and no run state. Reverse it by deleting this entry and letting harvest re-flag; or adopt any one skill literally by wiring it into the loop. No data migration.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

## D-043 — run-log schema bump: `agent` (required) + `skill_used` (optional); inviolate rule 6 amended

**Date locked.** 2026-06-09. Agent-governance harness cycle; HUMAN-ATTESTED amendment of an inviolate rule (rule 6 is inviolate -> required the human's explicit 2026-06-09 sign-off, per P-008's human-review routing).

**Amends.** Inviolate rule 6 in [`CLAUDE.md`](CLAUDE.md). The canonical run-log entry shape gains two fields; the rest of rule 6 (append-only, mandatory-per-task, state-transitions-as-first-class-entries) is unchanged.

**Decision.** `run_state/week1.run.jsonl` rows now carry `{timestamp, task_id, agent, status, observable_actual, observable_expected, duration_ms, skill_used?}`. `agent` is **required** — the entity that ran the step (`nara`, `claude-code-main`, `human:<id>`, or `workflow:<wf_id>/<role>` for a Dynamic-Workflow limb). `skill_used` is **optional**, present only when the row is a framework-skill invocation (e.g. `validate`, `fallback`). The 7-field shape is a **minimum, not a ceiling** (consistent with the project's organically-extended `status` vocabulary). **Existing rows are not rewritten** — append-only stands; pre-bump rows are canonicalized at read time (`week1.run.jsonl` -> `nara`) per the framework projector.

**Why now.** A 2026-06-09 skill-alignment review found the consumer run log had `agent` populated **0/1004** and the **12 Dynamic-Workflow rows anonymous** (all `agent:null`, `week1.run.jsonl` L886-981): you could see *that* a workflow ran, not *which* limb did what or *where* a step failed. D-037 rule 5 already asks for per-agent start+finish entries; this closes the attribution gap **before** D-040's unattended-Nara autonomy makes anonymous limbs un-reconstructible. It also restores the framework's `harvest -> propose -> rule` loop, which anonymous-by-task-id logs break.

**Provenance / links.** Mirrors framework rule **FR-003** (`agent_system/memory/brain/rules.md:24`, source decision 2026-05-27) and framework commit **`2690b5b`** ("S24a: run-log schema gains `agent` + `skill_used`; agent and skill projected", 2026-05-27). **Reconciles framework proposal P-008** (`agent_system/memory/brain/proposals.jsonl`, opened 2026-06-09, routed to human-review because it edits an inviolate consumer rule) — ratifying this entry is the consumer-side adoption P-008 requested; P-008 may be marked resolved on the framework side.

**What does NOT change.** Append-only (no row is ever edited or deleted to add `agent`); the per-task logging mandate; version pins; human gates; validations-never-coerced; MOCK_LLM discipline. The framework side already shipped (`run-log` SKILL.md requires `agent`, FR-003 codifies it, the projector reads it at ingest); this is the consumer catching up.

**Reversibility.** High. Drop the two fields from rule 6 and the writers stop emitting them; the read-time canonicalizer already tolerates rows that lack `agent` (it injects the per-file default), so historical rows need no migration either way.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

## D-044 — D-041 skeptic ladder step 1 VALIDATED: vllm-qwen is the standing independent skeptic; attack() seam shipped (default off)

**Date locked.** 2026-06-09 (evening session). Executes the D-041 ladder; human-directed
("ship Qwen or whatever is the right skeptic this session — priority order Qwen →
Gemma-persona → Claude/Agent-SDK").

**Decision.** The independent-skeptic mechanism ships as
`orchestrator/novelty_skeptic.attack(hypothesis_text, iteration_id=None, backend=None)`:
its OWN retrieval (`query_top_k`, default curated collections — closes the
iteration-068 shared-neighbor blind spot), REFUTE-framed prompt, fail-closed parsing
(every failure path → `inconclusive`, never `survives_attack`). The critic hook
(`workers/critic_loop_v0._maybe_run_skeptic`) fires only on a final `survives` with a
clean gate, behind env `NARA_SKEPTIC` (default **off** until β); `refuted`/`inconclusive`
demote the verdict to `undecidable` with full observability
(`skeptic_verdict`, `verdict_overridden_from`).

**Backend.** Default resolves from `NARA_SKEPTIC_BACKEND`, default **`vllm-qwen`**
(`qwen3.6-27b-nvfp4-mtp` on `:8001`, max_tokens 3072 per the token-starvation
diagnosis). The D-041 stand-alone back-test PASSED 3/3 on the labelled battery subset:
falsifiable_01 (finite-PD cooperate-to-end) **refuted** citing
`osborne_rubinstein-chunk-850` (backward induction); falsifiable_02 (TFT dominant)
**refuted** citing `chunk-831` (strict dominance); novel_on_01 (true on-domain novel)
**survives_attack** with a correct no-prior-art rationale. Run-log entry
`skeptic_ladder_step1_live_test`.

**Alternatives.** (a) `ollama-coder` (the D-035 default) — DEMOTED: requires the
unset-by-default `OLLAMA_MODEL` env pin (fails closed as a silent-looking
`inconclusive`), and pages a SECOND qwen copy into the 121 GB unified pool alongside
the resident vllm-qwen container (observed thrash: 15-min hang). Still selectable
explicitly. (b) Gemma-4 adversarial persona (ladder step 2) — built and tested
(`GEMMA_ADVERSARY_PERSONA`, backend `vllm-gemma`), NOT validated live; remains the
operational fallback if vllm-qwen is down. (c) Claude via Agent SDK (step 3) —
design-only in `docs/skeptic_ladder.md` (~$0.04–0.055/attack, ≥3,600 attacks under the
$200 Max plan); wiring it is the D-014/ToS human decision, not taken.

**Reversibility.** Env-gated and additive; unset `NARA_SKEPTIC` to remove from the
pipe entirely. The D-041 β arming condition "validated independent skeptic" is now MET
at ladder step 1; the memory-guard prerequisite stands unchanged.

---

## D-045 — Literature-pipe refinement landed: embedding anchors FALSIFIED as off-domain separators; R0 LLM-topicality gate + two-axis novelty + critic hardening; bar honestly NOT met, residuals characterized

**Date locked.** 2026-06-09 (evening session; workflow `wf_3fc91fc6-0de` + serial
integration). References P-009 ("calibrate a discriminative gate against a varied set,
not a single instance") and the iteration-068 external review.

**The negative result (the load-bearing finding).** Both corpus-derived semantic-anchor
variants were falsified as off-domain separators on a 22-case labelled set + ~45
historical hypotheses, by the procedural rule declared BEFORE calibration: global
foundational-centroid cosine separation gap **−0.079**, per-collection max-cosine
**−0.075** (required: ≥ +0.05). Mechanism: a genuinely novel on-domain hypothesis is far
from the existing corpus BY DEFINITION of novelty — the same place a
vocabulary-camouflaged off-domain hypothesis sits. Distance-to-known-content structurally
conflates the two. `ANCHOR_LOW`/`ANCHOR_BORDERLINE`/`SPREAD_MAX` ship as None (rules
R3/R4/R5 inert); `run_state/domain_anchor.json` + `calibrate_anchor.py` remain as the
measurement apparatus.

**What shipped instead (single rule-7 revision cycle).** R0: an explicit LLM topicality
judgment (`orchestrator/topicality.py`, condemns ONLY on literal "off", fail-open to
None), wired at both nara relevance sites and the battery; the two-axis novelty rubric
(`novelty_axes` = phenomenon × substrate × predicted_direction, deterministic legacy-class
mapping, `docs/novelty_two_axis_rubric.md` pre-registered); critic hardening (`undecidable`
fails closed everywhere: schema_mismatch/timeout fallbacks, coverage-adequacy bar,
low-confidence override, the nara placeholder, the skeptic demotion — raw verdicts kept in
`verdict_overridden_from`); corpus de-drift (default retrieval = foundational +
papers_recent; `ml_intern_fetched` opt-in via the escalation path, D-038 preserved);
targeted ingest of 8 LLM-agent GT papers closing the 068 corpus gap.

**Battery outcome (bar NOT met — reported, not coerced; revision cap reached).**
Locked bar ≥0.80 acc ∧ recall 1.0 ∧ 0 ungated: **FAILED** at 0.636 / 0.875 / 1.
Versus the morning baseline (0.50 / 0.0 / recurring bug): R0 caught 7/8 off-domain
(all camouflaged + drift probes); every gated case tempered end-to-end
(`unclear`/`undecidable`); the survives→skeptic→survives path passed on a true novel
(canary_on_03). **Live-pipe proof:** the original FASE bug class now resolves honestly
(iter-2026-06-09-007: R0, unclear/undecidable, low_confidence=true) and the 068 p-beauty
re-run moved to **rediscovery/restated** with axes {known, unstudied_llm, matches} —
exactly the review's predicted correction.

**Residuals (named, for the next session — no further tuning this session):**
1. Domain-BOUNDARY claims (LLM-behavior with GT framing, fase_off_01) pass topicality —
   needs a finer domain definition or a skeptic-side off-domain attack, not threshold
   tuning. The one remaining ungated novel/survives.
2. Restatement recognition on plain-language phrasings still weak (4 rediscoveries →
   survives/undecidable); the named escalation is routing restatement through the Qwen
   skeptic (D-044 infrastructure is in place).
3. The critic still retreats to `undecidable` on 2/3 corpus-silent novels despite the
   STEP-3 instruction (prompt adherence is stochastic; promotion-path starvation risk).
4. `predicted_direction=deviates` over-assignment inflates `novel` via the
   known+deviates→novel mapping (falsifiable_01/02, pbeauty battery phrasing).
5. R0 over-gates ~3 on-domain cases incl. nonsense rows (epistemically harmless but
   costs battery accuracy).

**Reversibility.** All additive: R0 fail-open, anchor rules inert, overrides carry
provenance, schema changes additive. The battery + calibration artifacts under
`experiments/lit_falsification_battery/runs/` are the regression baseline.

## D-046 — Human write-back contract blessed: UI POSTs exec blessed CLIs; defer-to-dev-session queue + startup triage step

**Date locked.** 2026-06-10 (screenshot-review session; ratified by the human at
planning time).

**Decision.** The UI's deferred "B4 write-back" ships against a blessed CLI contract
(`docs/human_writeback_contract.md`): `ui/backend` POST endpoints exec the CLIs as
**argv arrays, no shell** — `gate_cli` for gate verdicts (enum frozen
valid|invalid|needs_revision), NEW `finding_session --set-status` one-shot for quick
finding dispositions (validated|rejected|in_review; validated/rejected route
`gate_cli.append_feedback` against the finding's source iteration exactly as
`end_session` does), NEW `todo_cli ack` for bubble acks (`memory/coordinator_acks.jsonl`,
the join key `ui/backend/human_todo.py` already reads), and NEW `todo_cli defer` —
a **defer-to-dev-session** disposition appending
`{ref_id, kind, note, status:"open", attested_by, deferred_at}` to
`memory/dev_session_queue.jsonl` (append-only; `close` appends a closing row; readers
fold by ref_id, last status wins). Writes from the UI stamp `human:ui`. CLI validation
is the gate: out-of-enum exits nonzero, writes nothing, stderr surfaced verbatim.
CLAUDE.md "How to start a primary session" gains one step: run
`todo_cli list-deferred` and triage open deferrals into the session plan.
`stale_active_run` / `state_gate` direct resolution stays a primary-session human
action — defer-only from the UI.

**Alternatives rejected.** (a) UI writes `memory/*` files directly — breaks the
single-writer discipline every ledger relies on; (b) a separate primary-owned API
service — a second server to run/version for no added safety over exec-ing the same
CLIs; (c) reusing `run_state/attestations.jsonl` — that is retired track-era machinery
(soft-gate SLA log), and overloading it would resurrect retired semantics.

**Reversibility.** Endpoints are additive; the queue file is append-only; removing the
blessing reverts the UI to copy-paste rendering with no data migration.

## D-048 — Test-pollution purge (one logged surgical cleanup) + the autouse no-live-artifacts guard

**Date locked.** 2026-06-10 (ratified by the human at planning time as an explicit
exception to append-only discipline).

**The finding.** Def-time-bound default paths let the test suite write LIVE apparatus
files for days: 23 synthetic "RuntimeError: boom" coordinator cycles (rendered as failed
dispatches on the dashboard), **3,930 of 4,819** `logs/calls.jsonl` rows with
`model:"fake-model"` (82% of the canonical call log), and 88 same-day worker_activity
rows. A second vector: `orchestrator/topicality.py` makes a REAL model call when
MOCK_LLM is unset — and MOCK_LLM is set in the human's interactive shell but NOT in
non-interactive shells, so test runs silently hit the live Gemma server and stamped
rows with a stale fixture run_id.

**Decision.** (a) One surgical purge with `.pre_purge_2026-06-10` backups kept beside
each file: coordinator_cycles 140→117 (−23 boom rows), calls.jsonl 4,819→879 (−3,930
fake-model − 10 test-context topicality rows), worker_activity 1,251→1,163 (−88; lands
exactly on the session-start baseline, confirming the dropped rows were all same-day
test artifacts), and — found by the same-day adversarial review AFTER the new
`subagent_start/finish` events shipped — week1.run.jsonl 1,402→1,192 (−210 fixture
sub-agent rows: `subagent:"t"`, `run_id:null`, written live by `tests/test_subagent.py`
through the new `runtime.append_run_log` before the guard covered it). Malformed lines
are never dropped. (b) The leak is closed structurally: all writer defaults now resolve
at CALL time (worker_activity, coordinator_cycle_log, coordinator bubbles, nara's
calls-log sentinel) and `tests/conftest.py` gains an AUTOUSE `_no_live_artifacts`
fixture redirecting every such default to tmp_path — including `runtime.RUN_LOG_PATH`
and the D-046 ledgers — the invariant is "a full pytest run adds ZERO rows to
run_state/, logs/, memory/".
(c) Operating rule: pytest runs are invoked with explicit `MOCK_LLM=1` (the inverse
discipline of `env -u MOCK_LLM` for real runs — do not rely on the shell default).
Stray finished-run redirects deleted (`run_state/battery_run*.log`,
`coordinator_cycle_evening.log`; battery artifacts live in
`experiments/lit_falsification_battery/runs/`); live server stdout (`tool_plane.out`,
`ui_backend.out`) stays in place (open fds) and is now gitignored along with the
registry dir and purge backups.

**Alternatives rejected.** Keeping the rows and rendering around them (UI ×N grouping)
— leaves failure triage and call-log forensics poisoned forever and the "canonical call
log" 82% synthetic. Append-only discipline is for research observations; these rows
were never observations.

**Reversibility.** Full: the `.pre_purge_2026-06-10` backups are byte-complete copies.

## D-047 — Multi-run active-run registry (per-run files + foreground mirror)

**Date locked.** 2026-06-10 (ratified at planning; built by Dynamic Workflow
`wf_27141574-2c6` limb R in an isolated worktree; serially integrated).

**Decision.** `orchestrator/active_run.py` becomes a multi-run registry: every live run
writes its own `run_state/active_runs/<safe(run_id)>.json` (schema-validated, atomic
write tmp + os.replace, deleted on completion) carrying `heartbeat_at`, refreshed on
every update — consumers treat a stale heartbeat as a possibly-dead run. Ownership is
keyed by a module-level ContextVar holding the run_id, so `write_active_run` /
`update_active_run` / `clear_active_run` keep their exact signatures and the ~10 call
sites are untouched. `run_state/active_run.json` stays as the foreground mirror (most
recent writer; the UI keeps polling just that file) with **only-owner-clears**: an
update never rewrites a mirror owned by a different run_id, and a context-keyed clear
deletes the mirror only when it owns it; legacy no-context clears remove the mirror
plus its per-run twin. Resolves loop-iteration / coordinator / battery runs clobbering
each other's live state (the screenshot-review "BUSY (unregistered)" / single-slot
failure mode). Registry path follows the mirror's parent when a test relocates only
ACTIVE_RUN_PATH ("the registry lives beside the mirror" invariant).

**Integration note (honest record).** The limb's worktree rewrite regressed the `kind`
surface to 4 kinds — dropping `coordinator` from both `_KINDS` and the schema enum
(present at HEAD since the Slice-Alpha coordinator landed). Caught by the existing
join-contract test at integration (`test_update_active_run_each_coordinator_step_is_
schema_valid`); restored before merge. Full suite 1068 green after integration.

**Alternatives.** (1) Thread run handles through every call site — rejected: ~12-file
churn for no safety gain. (2) Replace the mirror outright with the registry — rejected:
breaks the live UI contract mid-flight.

**Reversibility.** Delete RUNS_DIR + the contextvar; mirror behavior reverts to the
single-slot helper.

## D-049 — β-interim bounded autonomy: the coordinator may run unattended cycles ONLY under the pause/ledger/sentinel bounds (RATIFIED + ARMED 2026-06-18)

**Date drafted.** 2026-06-10 (Session 3). **Status: RATIFIED + ARMED 2026-06-18**
(see the ratification note at the end of this entry). The
continuous-orchestrator guardrail (CLAUDE.md out-of-scope) stood unchanged until the
human ratified this entry; D-040's unattended contract activates at β proper.

**Proposed decision.** Until β (Nara packaged in the sandbox), a bounded HOST-side
interim is permitted: scheduled coordinator cycles via `cron/run-coordinator.sh`,
gated by ALL of — (1) the ratification sentinel `run_state/d049_ratified` exists
(the human creates it to ratify; deleting it un-ratifies); (2) the kill switch
`run_state/pause_coordinator` does not exist (creating it halts every cycle,
checked before any LLM call — never bypassed, even supervised); (3) the daily
executed-cycle ledger `run_state/coordinator_budget.jsonl` stays within
`COORDINATOR_DAILY_CAP` (default 18 units/day ≈ 3 full cycles; dry-runs uncharged);
(4) the memory preflight (`preflight_mem_guard`, 30 GiB OS margin hard-pinned)
passes; (5) cycles run with `NARA_SKEPTIC=1` (the D-044-validated Qwen skeptic in
the critic seam). The action menu stays the validated constrained space (v2: +
`run_experiment` — committed-results bridge by default, real re-runs only with
explicit `run_real`; + `forecast_markets` — exp007 paper sweep, design-only, zero
trading surface). Supervised soaks (`tools/coordinator_soak.sh --i-am-supervising`,
human watching) may bypass ONLY the sentinel, never the pause file or ledger.

**To ratify:** `touch run_state/d049_ratified` and add the crontab line in
`cron/run-coordinator.sh`'s footer. **Reversibility:** delete the sentinel and/or
crontab line; create the pause file for an immediate halt.

**Alternatives rejected.** Unbounded host-side daemon (violates the guardrail's
intent); waiting for full β (forfeits months of bounded daily research throughput
the apparatus is now instrumented to run safely and the UI can observe).

**Ratified + ARMED 2026-06-18** by the human (derrick), explicit sign-off. The serial
integrator created the sentinel `run_state/d049_ratified` and installed the crontab
line `0 9,15 * * * /home/decross1/projects/a_bgt_rsi/cron/run-coordinator.sh` (morning
+ afternoon cycles), per the `cron/run-coordinator.sh` footer. The bounded host-side
interim is now LIVE: each firing runs only while ALL gates hold — sentinel present, no
`run_state/pause_coordinator` kill-switch (checked before any LLM call, never
bypassed), within `COORDINATOR_DAILY_CAP`, mem preflight passes, `NARA_SKEPTIC=1`.
First real cycle fires at the next 09:00/15:00. **Halt:** `touch
run_state/pause_coordinator` (immediate). **Un-arm:** `rm run_state/d049_ratified`
and/or remove the crontab line. The continuous-orchestrator out-of-scope guardrail
(CLAUDE.md) is hereby relaxed to exactly this bounded interim; the full-β D-040
contract still activates only at β.

## D-050 — D-045 residuals 1+2: independent topicality attack (R0b) + restatement skeptic at the critic, both env-gated dark

**Date.** 2026-06-10 (session 2, workflow `wf_d4e96978-59a` limbs b2/b3/b4 +
serial integration). Extends D-044 (vllm-qwen standing skeptic) and D-045
(residuals named, no further threshold tuning).

**Decision.** Two additive, fail-open seams, each behind its own env gate and
OFF by default until the pre-registered battery decision run judges them:

1. **Residual 1 — `NARA_TOPICALITY_SKEPTIC=1`**: `orchestrator/topicality.py
   check()` escalates a non-"off" primary verdict to
   `orchestrator/topicality_skeptic.attack_topicality()` — an independent
   vllm-qwen REFUTE-framed domain attack (fail-open `None`, only literal
   "off" condemns). Skeptic-only condemnation returns the new value
   `"off_independent"`; `workers/retrieval_relevance.py` gates it as R0 with
   `rule_fired="R0b"` and a reason naming the independent judge. Targets the
   domain-BOUNDARY class (fase_off_01) that passes primary R0.
2. **Residual 2 — `NARA_RESTATE_SKEPTIC=1`**: `workers/critic_loop_v0.py`
   gains `_maybe_run_restate_skeptic` (mirrors the D-044 hook: lazy import,
   crash-recorded-never-fatal) in the passed-branch BEFORE the novelty
   skeptic: `orchestrator/restate_skeptic.restate_attack()` canonicalizes the
   hypothesis, does fresh retrieval plus the cached novelty top-neighbor
   union, and judges restatement under the two-axis transfer rule. A
   "restated" attack verdict demotes survives→restated carrying
   `verdict_overridden_from` + `restate_verdict` (schema parity added beside
   D-044's `skeptic_verdict`). Targets the 4 plain-language rediscovery cases.

Battery (`experiments/lit_falsification_battery/battery.py`) carries the new
per-case provenance fields (additive, default None) so the decision run is
auditable per case; `cases_residual12_smoke.jsonl` is a 9-row byte-identical
dev-smoke subset (informational only, never the decision run).

**Pre-registered decision rule (locked BEFORE the real run; baseline =
`runs/battery_20260609T212352Z.json`, run with `NARA_SKEPTIC=1` + both new
gates on, judged on ONE full-22 run).** PASS iff ALL: (1) fase_off_01 reaches
low-confidence-gated, not ungated novel/survives; gate recall 8/8, 0 ungated
off-domain. (2) ≥3 of {redisc_on_01, redisc_on_03, canary_on_01, canary_on_02}
reach critic "restated" with non-null contradicting_paper_id; neither
redisc_on_01 nor redisc_on_03 stays "survives". (3) No regression:
canary_on_03 stays novel+survives+ungated; redisc_on_02 stays restated; the 7
baseline-gated off-domain cases stay gated; novel_on_01/novel_on_03 stay
novel; the on-domain low-confidence set does not grow beyond the baseline
three. (4) verdict_accuracy ≥ 0.70 (baseline 0.636). Explicitly
pre-registered: the locked D-045 bar (0.80/1.0/0) is expected to STILL fail
its accuracy leg — residuals 3–5 are out of scope; the battery exit code may
be 1 and is judged by THIS rule, not `all_pass` (inviolate rule 4). On FAIL:
unset the env gates (byte-identical revert), report honestly; at most one
rule-7 revision cycle on prompt text only, then one re-run.

**Reversibility.** Both seams fail-open and env-gated dark; schema/battery
changes additive; revert = unset two env vars.

**DECISION RUN VERDICT (2026-06-10 18:23Z, `battery_20260610T182342Z`, real,
31 min): the pre-registered rule FAILED — gates STAY DARK.** Per criterion:
**C1 PASS** (residual-1 target met: fase_off_01 → `off_independent`/R0b,
low-confidence-gated; gate recall 8/8; 0 ungated off-domain). **C2 FAIL**
(restated-with-citation 0/4 — see defect (b); redisc_on_01 DID flip
survives→restated via the hook and canary_on_02/redisc_on_02 reached
restated at the base critic, but no flip carried a citation;
redisc_on_03's restate judge honestly returned `not_restated`).
**C3 FAIL** (on-domain low-confidence set grew 3 → 7). **C4 FAIL**
(verdict_accuracy 0.6818 < the 0.70 floor; baseline 0.6364 — improved,
insufficient). As pre-registered, the locked 0.80 bar also failed.

Two named defects, for the single remaining revision cycle:
(a) **Topicality-attack domain definition too narrow** — the skeptic
condemned 4 ON-domain plain-language classics (ultimatum, hawk-dove,
quantal lock-in, folk theorem) alongside the 1 correct boundary case;
this is D-045 residual-5's over-gating harm amplified, and it caused most
of C3+C4 and one C2 miss. Fix lives in the attack prompt's ON-side
instruction (plain-language canonical GT = ON). (b) **Restate-hook wiring
bug** — the flip records `restate_verdict`/`verdict_overridden_from` but
drops the judge's restating doc id, leaving `contradicting_paper_id` null
on a "restated" verdict (inconsistent with the critic's own output
contract; C2 reads that field). This is a code defect fix, distinct from
the prompt-revision allowance. Status: the one rule-7 prompt-revision
cycle + single re-run remain AVAILABLE and deliberately not spent
in-session (2-3h budget reached); both seams remain dark until that
re-run passes this same rule.

**REVISION CYCLE + RE-RUN EXECUTED (2026-06-13, `battery_20260613T043130Z`,
real, 22 cases): the pre-registered rule FAILED AGAIN — gates STAY DARK.
The one rule-7 revision allowance is now SPENT; residuals 1+2 close as NOT
MET.** Per criterion: **C1 PASS** (residual-1 holds: fase_off_01 →
off_independent/R0b, gated; gate recall 8/8; 0 ungated off-domain).
**C2 FAIL** (restated-with-citation **2/4**, need ≥3, AND redisc_on_03 stayed
`survives`). **C3 FAIL** (over-gating RELOCATED — see below; on-domain
low-confidence set grew 3→5). **C4 FAIL** (verdict_accuracy **0.6591** <
0.70 floor; baseline 0.6364; the 06-10 run was 0.6818 — within the real
run-to-run stochasticity of this design). The locked D-045 0.80 bar also
failed, as pre-registered.

Two fixes were applied this cycle, and the diagnosis of defect (b) was
CORRECTED by instrumentation:
- **(a) Topicality ON-side prompt broadened** (`orchestrator/topicality_skeptic.py`
  `_SYSTEM`): plain-language canonical / behavioral / evolutionary game
  theory (Nash, QRE, level-k, folk theorem, reciprocity, bargaining, ESS)
  is now explicitly ON regardless of AI framing or evidence type, while the
  OFF discriminator (systems / ML-infra / single-model uncertainty metrics
  like semantic entropy) stays sharp. **It worked for the named classics**:
  ultimatum (canary_on_01), hawk-dove (canary_on_02), folk theorem
  (redisc_on_02) are now `topicality=on`, no longer R0b-gated. **But the
  independent topicality skeptic RELOCATED its over-condemnation** to two
  *novel* on-domain cases — novel_on_01 (quantal lock-in) and novel_on_03
  (level-k × quantal bridge) — which it still returns `off_independent` on
  (R0b-gated → unclear/undecidable), even though the prompt names QRE/level-k
  as ON. This confirms **D-045 residual-5 (over-gating) as STRUCTURAL**: the
  adversarial REFUTE-framed topicality skeptic is too aggressive to be
  net-positive on accuracy at this design — prompt text moves *which*
  on-domain cases it condemns, not *whether* it over-condemns.
- **(b) was MISDIAGNOSED on 2026-06-10 — it is NOT a critic wiring bug.**
  Instrumentation proved `workers/critic_loop_v0.py` correctly carries the
  restating citation (the flip sets `contradicting_paper_id` to the restate
  skeptic's verified doc_id and returns it intact). The real defect was a
  **battery REPORTING bug**: `CaseScore` / `score_case` / the `per_case` dict
  never copied `contradicting_paper_id` through from `CaseObservation`, so the
  C2 criterion ("restated WITH non-null contradicting_paper_id") was reading a
  field that was structurally always-`None`. Fixed (3-line passthrough +
  regression test `test_new_observation_fields...` extended). **Consequence:
  the 06-10 "restated-with-citation 0/4" was partly a measurement artifact** —
  redisc_on_01 DID carry `osborne_rubinstein-chunk-979` and was silently
  dropped. With the harness fixed, the restate mechanism demonstrably delivers
  **2/4 with citations** (redisc_on_01, canary_on_02); the limiter is the
  skeptic's own `not_restated` judgments on redisc_on_03 and canary_on_01, not
  lost wiring.

**Disposition.** Env gates `NARA_TOPICALITY_SKEPTIC` / `NARA_RESTATE_SKEPTIC`
stay OFF by default → runtime behavior is byte-identical to the no-seam
apparatus (the reversibility property). The **battery reporting fix STAYS
live** (it is measurement correctness, test-pinned, not part of the dark
seam — reverting it would re-break C2 observability for any future run). The
topicality prompt change STAYS in the now-dark seam (strictly better domain
definition, inert while the gate is off; retained as the seam's current
state, NOT blessed for activation). No further revision cycle is available
under this pre-registration. Reopening residuals 1+2 (or the over-gating
question) requires a NEW decision — the natural next question is whether an
*independent adversarial* topicality skeptic is the right instrument at all,
given it over-condemns on-domain novelty in both runs (D-045 residual-5).

## D-051 — MCP submit+poll seam at the β tool plane (ticket store composed with the D-047 registry)

**Date.** 2026-06-10 (session 2, workflow `wf_d4e96978-59a` limb b1 + serial
integration). Implements the direction recorded in the 2026-06-10 morning
note; closes the T2 known gap (OpenClaw MCP client 15s timeout vs the
~74–479s synchronous `run_loop_iteration`).

**Decision.** Two new tools beside the unchanged pair at
`orchestrator/tool_plane.py` — `submit_loop_iteration` (returns a
`mcpsub-…` ticket run_id in milliseconds) and `poll_run` (honest reads
only) — backed by NEW `orchestrator/submitted_run.py`: an atomic ticket
store under `run_state/tool_plane_submits/`, a single daemon executor
thread per submit (latch + the existing one-at-a-time guard; no queue, no
scheduler, no cancellation), thread body `set_current_agent("nemoclaw_agent")`
→ `write_active_run(ticket_id, "ad_hoc", …)` → run-log accepted-event →
`run_iteration(topic, source="nemoclaw_agent")` → ticket finished/failed +
terminal event → `finally` clear/reset/release. `poll_run` reports
running/finished/failed/unknown from the ticket + registry +
`active_iteration.json` (mtime as freshness; 900s informational stale flag;
pid-mismatch reconciles a dead-server orphan ticket honestly). The sandbox
can poll ONLY this seam's tickets — host iterations and experiment runs are
not pollable (containment). Sync `run_loop_iteration` stays byte-compatible
(T2 evidence + curl smokes unaffected); the D-040/continuous-running
guardrail is intact: submit is still single-shot, human/agent-triggered, one
in flight.

**Verification.** 14 hermetic seam tests + plane-level endpoint tests; suite
1158 green at integration; real-smoke decision rule per the recon design
(submit <2s; poll converges; verdict fields equal the `loop_memory.jsonl`
record; a sandbox MCP drive completes without the 15s timeout) — pending the
next GPU-idle window, see the session note.

**Reversibility.** New module + additive plane endpoints; the sync path is
unchanged (its in-flight refusal predicate gains `thread_live()`, refusing
strictly more, never less); removing the two tools restores the exact T2
surface.

**Review residuals (2026-06-10 two-reviewer gate, accepted as documented).**
(a) pid-reuse: a restarted server that coincidentally inherits the dead
writer's pid would report an orphan ticket "running" — astronomically
unlikely under Linux pid_max; accepted as a residual of the pid-based
design. (b) The busy refusal's `in_flight` field names the INNERMOST live
run (during most of a submitted run that is the nested `iter-…` doc, not
the mcpsub ticket) — honest, by design. (c) Single-process assumption
(in-process latch) documented in the module + runbook.

**REAL-SMOKE VERIFICATION (2026-06-13, host-side): the three host-driveable
clauses PASS.** Tool plane :8077 restarted on current code (`/health` now
lists all four tools incl. `submit_loop_iteration` + `poll_run`). Drove
`submit_loop_iteration` with an in-domain topic (QRE vs Nash in repeated
public goods): **submit returned in 9ms** (`mcpsub-20260613T023330Z-b3de`,
clause: <2s ✓). **Poll converged** running→finished over ~2m21s
(submitted 02:33:30Z → finished 02:35:51Z), with the honest intermediate
reads exercised (registry kind/heartbeat, `active_iteration` steps[] board
walking meta_review→hypothesize→…→journal_writer, a dynamic redteam→failed
chip, `stale:false`) ✓. **Verdict fields equal the `loop_memory.jsonl`
record** (iter-2026-06-13-001: novelty `novel`, critic `survives`,
low_confidence false, journal 075) ✓. Run-log carries `nemoclaw_agent`
`tool_plane_submit_accepted`/`tool_plane_submit_finished` events bracketing
the 40-row chain. **Remaining clause — sandbox MCP drive (no 15s timeout) —
NOT run**: it is the runbook's stretch/out-of-scope path (sandbox egress +
gRPC/h2), deferred to a sandbox-coordinated window. The seam is proven at
the host boundary; the end-to-end sandbox proof is the one open item.

## D-052 — Independent *adversarial* topicality skeptic (R0b): is it the right instrument? — isolated boundary probe + pre-registered rule

**Date.** 2026-06-13 (session 4). Reopens the over-gating question D-050's
disposition named as needing a NEW decision ("whether an independent adversarial
topicality skeptic is the right instrument at all, given it over-condemns
on-domain novelty in both runs"). Supersedes the residual-1 thread of D-050;
extends D-045 residual-5 (over-gating). **Orthogonal to β:** D-041 gates β on the
independent *NOVELTY* skeptic (D-044, validated vllm-qwen) + the memory guard —
NOT on this topicality skeptic, a dark-by-default add-on. Retiring or neutering
R0b touches no β arming condition.

**Evidence (two real battery runs + baseline).** R0b runs only when the primary
Gemma judge does NOT condemn, so its entire marginal effect is the
`off_independent` cases. Across runs it gates exactly ONE off-domain camouflage
case (`fase_off_01_semantic_entropy`) — its only consistent win — and cannot do
so without condemning genuinely-novel on-domain claims: 06-10 over-gated
`novel_on_01` (lost both verdict axes) + `canary_on_01`; 06-13 (ON-side prompt
broadened, the D-050 cycle) FIXED the plain classics but RELOCATED the harm onto
`novel_on_01` AND `novel_on_03` (both genuinely novel, both lost both axes) and
accuracy fell 0.6818→0.6591. Aggregate accuracy is noise-dominated (±2 axes of
44); the per-case firing pattern is the signal and it is consistent. Diagnosis
(D-045 residual-5, confirmed structural): the adversarial REFUTE framing
conflates "novel on-domain" with "camouflaged off-domain" because both sit far
from canonical GT — the falsified-embedding-anchor failure recurring at the
LLM-judge level. Prompt text moves WHICH novel cases die, not WHETHER.

**Decision space.**
- **A. Retire R0b** — keep the seam byte-identical but permanently dark; rely on
  the primary R0 (Gemma) + downstream critic/novelty + the human reading the
  journal.
- **B. Positive-identification reframe** — condemn ONLY on positive ID of an
  off-domain subject, not on failure-to-defend-in-domain. Dark until a
  full-battery A/B blesses it.
- **C. Advisory (non-gating) flag** — surface the independent judge's dissent to
  the record / journal / UI but NEVER set `low_confidence` / never temper the
  verdict (over-gating harm → zero; the one signal preserved). Behind a new
  `NARA_TOPICALITY_ADVISORY`.
- **D. Abstain-by-default** variant of B.

**Method — isolated boundary probe (the smallest experiment).** The topicality
judgment is an isolated function, so instrument variants are compared by calling
the judges directly on the labeled cases — NO retrieval / novelty / critic chain.
Key property: a variant that condemns ZERO on-domain case *in isolation* cannot
over-gate in the battery (the gate cannot fire when the judge says on/unsure),
and catching the primary's misses is directly observable — so the isolation
result is a valid hard gate on promotion.
`experiments/topicality_instrument/boundary_probe.py` runs FOUR variants over all
22 cases, N=3 repeats, temp 0.0: `primary-gemma` (`topicality._primary_check`),
`adversarial-qwen` (current `attack_topicality`), `positive-id-qwen` (B prompt,
harness-owned), `neutral-qwen` (primary prompt on vllm-qwen — isolates
framing-vs-backend). Boundary set: MUST-CATCH = the 8 `domain:off` cases;
MUST-NOT-CONDEMN = the 12 genuine `domain:on` cases (novel/redisc/canary ×3,
pbeauty, falsifiable ×2); `nonsense_01/02` informational.

**Phase-1 pre-registered rule (locked BEFORE the run).** A variant QUALIFIES for
a Phase-2 full-battery A/B iff, over N=3 repeats, ALL: (1) **marginal catch** —
it labels `off` every off-domain case `primary-gemma` does NOT (if the primary
already catches all 8, this clause is vacuous → no marginal value → outcome A);
(2) **zero over-gating** — it labels `off` ZERO must-not-condemn case; (3)
**stable** — every boundary label identical across all 3 repeats. Branch: NO
variant qualifies (expected) → **A + C** (A only if clause-1 is vacuous); a qwen
variant qualifies → PAUSE for Phase-2 (a second pre-registered decision + ~70-min
battery; the blessed prompt enters `_SYSTEM` only on a Phase-2 PASS).

**Phase-2 sketch (only if a variant qualifies).** Paired battery: arm0
`NARA_TOPICALITY_SKEPTIC=0` vs armV (variant on). PASS iff fase_off_01 stays
gated (recall 8/8, 0 ungated off) AND zero `domain:on` case un-gated in arm0
becomes low-confidence in armV AND `verdict_accuracy(armV) >=
verdict_accuracy(arm0)` (paired baseline). FAIL → byte-identical revert → A+C.

**Reversibility.** All arms env-gated and dark / fail-open; the advisory (C) is a
new orthogonal `NARA_TOPICALITY_ADVISORY`, additive record field, no schema edit,
no verdict effect. Revert = unset env vars.

**DECISION RUN VERDICT (2026-06-14, isolated probe `probe_20260614T035332Z`,
real, 22 cases × 4 variants × 3 repeats): NO independent variant qualifies →
outcome A + C (retire R0b as a gate; demote the independent dissent to a
non-gating advisory).** Per the pre-registered Phase-1 rule:

- **primary-gemma catches 7/8 off-domain**; it MISSES only
  `fase_off_01_semantic_entropy` — that one camouflage case is R0b's entire
  possible marginal job.
- **adversarial-qwen (current R0b): DISQUALIFIED.** Catches `fase_off_01`
  (clause 1 ✓) but over-gates THREE genuine novel on-domain cases —
  `novel_on_01`, `novel_on_02`, `novel_on_03`, all labelled `off` (clause 2 ✗).
  The structural over-gating is reproduced a third time.
- **positive-id-qwen (candidate B): DISQUALIFIED, but diagnostic.** Over-gates
  ZERO on-domain cases (clause 2 ✓ — the reframe PROVES the adversarial *framing*
  is the over-gating cause) but MISSES `fase_off_01` and the other GT-vocab
  camouflage (clause 1 ✗ — a positive-ID judge cannot name an off-domain subject
  when the claim is dressed in game-theory vocabulary).
- **neutral-qwen (control): DISQUALIFIED** — over-gates `novel_on_02` and is
  unstable/unmeasurable on `fase_off_01`.

**The instrument question is answered: an independent adversarial topicality
skeptic is the WRONG GATE.** The probe isolates WHY: catching the one camouflage
case the primary misses (`fase_off_01`) is INSEPARABLE from over-condemning
genuine novelty — the only judge that catches it (adversarial) is the one that
over-gates; the only clean judge (positive-ID) is blind to it. Novelty and
GT-vocab camouflage look the same to an independent judge — the falsified-anchor
failure (D-045) at the LLM-judge level, now confirmed a THIRD time.

**Outcome A — retire R0b as a gate.** `NARA_TOPICALITY_SKEPTIC` stays permanently
dark (the seam kept byte-identical for reversibility, not ripped out). Supersedes
the residual-1 thread of D-050.

**Outcome C — advisory (non-gating).** The lesson lands exactly here: the
independent topicality dissent belongs as a HUMAN-FACING HINT, not an
auto-suppressing gate. Behind a new `NARA_TOPICALITY_ADVISORY` (dark by default,
fail-open): when the primary passes, the existing adversarial `attack_topicality`
(the only judge carrying the marginal `fase_off_01` signal) is consulted and its
dissent rides as the additive `relevance.topicality_advisory` field — surfaced to
the record / journal / UI but NEVER setting `low_confidence` or tempering any
verdict (over-gating harm → zero). It is labelled the known-over-flagging
adversarial signal so a `novel`-case false hint is discounted by the human.
Additive field, no schema edit; logged for the UI in `docs/DATA_SHAPES.md`.

**NEW RESIDUAL (out of D-052 scope, recorded for a future decision).** The
PRIMARY R0 judge (Gemma, always-on) ITSELF over-gates
`novel_on_02_critic_flip_model` (domain:on, stable `off`) — primary-layer
over-gating that retiring R0b does not touch. The over-gating problem is not
fully solved by this decision; the primary neutral judge carries some of it.

**Reversibility.** `NARA_TOPICALITY_SKEPTIC` dark; the C advisory is a new
orthogonal `NARA_TOPICALITY_ADVISORY`, additive non-gating field, fail-open;
revert = unset env vars.

## D-053 — Over-gating vs promotion-starvation: demote BOTH the primary R0 topicality gate AND the adversarial promotion vote to non-gating advisories (option C, env-gated dark) — the human/cockpit is the calibration the automatic vote could not be

**Date.** 2026-06-15 (session 5). Disposes the NEW RESIDUAL D-052 logged (the
PRIMARY R0 Gemma judge over-gates `novel_on_02`) AND the S3 "skeptic refutes 3/3
— calibration question" by applying the **D-052 pattern (option C)** one layer up
*and* one layer down: an inseparable adversarial call should not be a binary gate;
it should ride as a human-facing advisory and let the human (via the `/todo`
cockpit) be the calibration. Extends D-052 / D-045 residual-5 (over-gating).
**Orthogonal to β:** D-041 gates β on the independent *NOVELTY* skeptic (D-044) +
the memory guard — NOT on R0 topicality nor on the finding-promotion vote; both
demotions here are env-gated dark add-ons that touch no β arming condition.

**Evidence (read-only investigation, primary re-verified — see
[`docs/overgating_promotion_analysis.md`](docs/overgating_promotion_analysis.md)).**
The `overgating-understand` Dynamic Workflow (3 parallel maps → design →
adversarial critique) found two conflated problems, with the load-bearing
production numbers **independently re-counted by the primary** (not the workflow's
word):

- **Problem A (R0 over-gating).** The primary R0 judge over-gates the on-domain
  novel case `novel_on_02` and misses off-domain `fase_off_01` — mirror cells a
  hypothesis-text-only judge cannot separate (confirmed a 4th time). BUT: across
  `memory/loop_memory.jsonl` (**59** iterations) the R0 `novel→unclear` downgrade
  fired **0** times. **R0 over-gating is NOT why the cockpit is empty.**
- **Problem B (the actual cargo starvation).** `memory/surfaced_findings.jsonl`
  is **ABSENT** (0 cargo). From `memory/promotion_near_misses.jsonl` (**174**):
  **65** capped by `max_candidates` (44 at =3, 21 at =4); **10** "refuted by
  adversarial vote" (9 at 3/3, 1 at 2/2); **0** R0/low-confidence rejections. The
  **adversarial promotion vote** (`orchestrator/finding_promotion.py:234-307`,
  survive-iff-minority-refute at `:297`) refuting **3/3** is the real binding
  constraint — structurally the **same independent-skeptic-refute pattern D-052
  just retired at the relevance gate**, now at the promotion stage. Even a perfect
  R0 produces zero cargo.

**Decision (option C, both layers).** Demote BOTH over-gating layers to
non-gating advisories, env-gated DARK by default, fully reversible (the D-052
pattern):

- **Layer 1 — primary R0 topicality.** Behind `NARA_R0_ADVISORY` (dark by
  default, fail-open): the R0 `"off"`→`relevance.low_confidence` path is demoted
  to an additive advisory record field, never setting `low_confidence` / never
  downgrading novelty. Dissolves Problem A by refusing to let an inseparable call
  gate anything; residual over-gating handled by logged human sampling.
- **Layer 2 — adversarial promotion vote.** Behind `NARA_PROMOTION_VOTE_ADVISORY`
  (dark by default, fail-open): the survive-iff-minority-refute vote is demoted to
  an advisory annotation that does NOT block promotion. `NARA_PROMOTION_MAX_CANDIDATES`
  raises/removes the `max_candidates` cap for the cost-bounded local run. Together
  these are the binding cargo lever the analysis identified.

**Cargo experiment (pre-registered).** Re-run promotion with the vote demoted to
advisory and the candidate cap lifted; **PASS = ≥1 finding reaches
`memory/surfaced_findings.jsonl`**. A zero result answers the S3 calibration
question honestly (genuine novelty absence vs over-gating) rather than leaving it
masked by a 3/3 auto-refute.

**Why the human/cockpit, not a better vote.** The adversarial vote refuting 3/3
on every candidate is the same inseparability D-052 isolated at the relevance
gate: an independent skeptic cannot separate genuine novelty from camouflage, so
as a *gate* it strangles cargo. Demoted to advisory, that same dissent becomes
cockpit cargo — the human reading `/todo` IS the calibration the automatic vote
could not be. This gives the `/todo` cockpit its first real human-in-the-loop
material.

**Reversibility.** Env flags only, fully reversible: `NARA_R0_ADVISORY`,
`NARA_PROMOTION_VOTE_ADVISORY`, `NARA_PROMOTION_MAX_CANDIDATES` — all dark by
default, fail-open, additive record fields, no schema edit. Revert = unset env
vars.

## D-054 — Tutor card: affirm the verdict-fence, route the accept/deny steer to the two-voice pane, and correct the D-044 mis-citation

**Date.** 2026-06-17 (session 6). Disposes the human's `/todo` tutor-card
design questions (grounded by the 2026-06-17 cockpit design probe). The tutor
card today is a stub that echoes the finding title verbatim; the human asked it
to give an overview, pros/cons, and "a recommendation of what accepting/denying
would do," plus a dynamic probing chat.

**Finding (cockpit design probe — read-only, file:line evidence).** The tutor's
fence note cites "D-044 independence," but D-044 is the vllm-qwen
standing-skeptic decision (the interrogator must not be the authoring model).
The REAL source of the tutor verdict-fence is the 2026-06-14 session note PART 2
("Tutor FENCED from the verdict") + inviolate rule 4 (the verdict is the
human's) + D-053 (the human is the calibration). The fence protects the
pre-verdict calibration capture (ARCH §6.5.4): the human predicts + rates
confidence BLIND, then the verdict unlocks; a tutor recommendation would corrupt
that signal. Mapping the human's three asks against the fence: an
outcome/blocker overview is fence-safe; pros/cons is safe only as a neutral
*unweighted* enumeration; an explicit accept/deny recommendation is a verdict in
all but name — fence-crossing, and cannot be worded around.

**Decision.**
1. **Affirm the verdict-fence.** The tutor stays fenced. It MAY render: a
   neutral overview/mechanics of the finding + blocker; the *mechanical* "what
   each outcome writes" (factual, not a steer); a neutral *unweighted* pros/cons
   enumeration; and a Qwen-backed **no-verdict** probing chat. It MUST NOT render
   an accept/deny recommendation, weight the pros/cons, or write any disposition.
2. **Route the steer to the two-voice pane.** Accept/deny adversarial decision
   support lives in the two-voice pane (defender Gemma / attacker Qwen), which is
   built to feed the verdict by design — NOT in the verdict-fenced tutor.
3. **Tutor backend = vllm-qwen, not the authoring Gemma** — preserves
   teach ≠ author (the same independence rationale as the two-voice
   defender/attacker split, and consistent with D-044's interrogator rule).
4. **Correct the mis-citation** in `TutorPanel.tsx`: cite the real fence source
   (2026-06-14 note PART 2 + rule 4 + D-053); reserve the D-044 reference for the
   interrogator-independence context where it actually applies.

**Scope of the build.** Tutor = richer static overview + live probing chat.
PRIMARY builds the orchestrator tutor engine + a per-turn chat CLI seam (P1–P3,
see [`human/sessions/2026-06-17.md`](human/sessions/2026-06-17.md)); the UI
session wires the frontend + `ui/backend` seam (U1–U5 in that note).

**Fence enforcement (by construction, not convention).** The tutor session is
built with NO `end_session` verdict path — structurally it cannot write a
disposition (no `loop_feedback` / `surfaced_findings.status` write), so the
fence holds even if the UI wiring is wrong. Reversible: the tutor seam is an
additive new path; removing it restores the current stub.

**Ratified 2026-06-18** by the human (derrick), explicit sign-off. The verdict-fence
stands; the accept/deny steer stays in the two-voice pane.

## D-055 — `calibration_entry` overloaded: the cockpit pre-verdict capture coexists with the post-experiment calibration under one event_type, disambiguated by `phase` (integrator call — ratify or redirect)

**Date.** 2026-06-17 (session 6, P4 autonomous build). **Surfaced by the P4
calibration-writer workflow, NOT silently resolved.** The cockpit's pre-verdict
calibration capture (free-text prediction + confidence ∈ [0,1], ARCH §6.5.4)
needed a durable writer, but `schema/events.jsonl.schema.json` already owns
`event_type: 'calibration_entry'` for a DIFFERENT artifact — the post-experiment
metric-range calibration (`experiment_id` / `metric_name` /
`pre_experiment_expected_range` / `post_experiment_observed` / `within_range` /
`human_attestation`). Same event_type literal, two distinct research artifacts at
different lifecycle stages.

**Integrator decision (option a — coexist).** Keep the single event_type
`calibration_entry`; disambiguate with a new `phase` const: the post-experiment
member carries no `phase`, the cockpit's pre-verdict member carries
`phase: 'pre_verdict'`. Both coexist as `oneOf` members in one
`run_state/events.jsonl` (`oneOf` integrity holds — disjoint required-sets +
`additionalProperties:false` mean no row matches two branches). **Rationale:** the
UI already references `calibration_entry` (`ui/frontend/src/types/todo.ts`) and
ARCH §6.5.4 mints the name; option (a) is the lower-churn, additive reconciliation
(a third `oneOf` branch — the existing two members are untouched). **Rejected
option (b):** split the pre-verdict capture into its own event_type — cleaner
one-shape-per-event_type, but it diverges from the UI's existing expectation and
ARCH's naming.

**What landed (P4, commit pending).** `orchestrator/calibration_cli.py` (blessed
writer-of-record mirroring `gate_cli.py`; argv `calibration --ref-id --prediction
--confidence --by` matching the cockpit stub verbatim; confidence ∈ [0,1]
REJECTED-not-clamped per rule 4; append-only to `run_state/events.jsonl` per rule
6); `schema/calibration_pre_verdict.schema.json` (the focused single-shape schema
the writer self-validates against); the additive `pre_verdict` branch in the spine
`schema/events.jsonl.schema.json` (this integrator edit) + its test.

**Status: integrator default — ratify or redirect.** This is a modeling call the
human may override. To redirect to option (b): rename the const in the writer row
+ the two schemas + this entry — small and reversible. No consumer reads
`calibration_entry` out of `events.jsonl` yet, so nothing breaks either way today.

**Ratified 2026-06-18** by the human (derrick), explicit sign-off. The overload
stands: `calibration_entry` + `phase` discriminator, NOT split into a distinct
event_type.

## D-056 — Runtime skill-signals stream: adversarially reviewed, ADOPT-WITH-RECONCILIATIONS; implementation gated

**Date.** 2026-06-18. A framework-side handoff asked the a_bgt_rsi runtime to emit a
per-event `run_state/skill_signals.jsonl` skill-friction stream (the `source="runtime"`
half of the framework's drift-detection `detected` lane; the framework owns ingest,
read-only). The handoff was adversarially reviewed (Dynamic Workflow, 4 reviewers +
synthesis). **Verdict: ADOPT-WITH-RECONCILIATIONS.** The firewall *behavior* (apparatus
writes its own file, framework reads one-way, no brain access) is clean and consistent
with D-014; the apparatus-side contract is
[`docs/skill_signals_contract.md`](docs/skill_signals_contract.md).

**Two hard inviolations pushed back on:**
1. **Trigger (a) imported the framework's run-log enum** (`started|passed|…`) and
   treated a status outside it as "friction." a_bgt_rsi's run-log status is
   open-vocabulary (rule 6 "minimum, not a ceiling"; 25+ live values incl. the
   handoff's own example `recovered`); adopting it would coerce status into a closed
   set (rule 4) and turn normal logging into a friction firehose. **Reframed:** a
   non-framework-enum status is the EXPECTED norm and is NOT friction; emit (a) only on
   genuine run-log-skill misfit, or drop (a) and keep the clean (b) GAP / (c) MISUSE.
2. **The firewall citation pointed at the framework's `BOUNDARY.md`**, which a_bgt_rsi
   lacks and **consciously diverges from (D-032)**. Re-sourced to D-014 + CLAUDE.md
   Dynamic-Workflow-discipline rule 3; all framework-artifact names stripped from the
   apparatus's obligation text.

**Two reconciled collisions:**
3. The "swallow write errors silently" instruction vs rule 7 — guarded: swallow only the
   side-channel, never mask the mandatory run-log write (rule 6), run-log-first, leave a
   logged breadcrumb on emit failure.
4. The new `run_state/` writer was missing from the **D-048** `_no_live_artifacts`
   conftest guard — `emit_skill_signal` must resolve `SKILL_SIGNALS_PATH` from a
   module-global and the autouse fixture must redirect it to `tmp_path`, or it reopens
   the ~210-row leak D-048 closed.

**Decision.** Adopt the stream **on the apparatus's terms** per
`docs/skill_signals_contract.md` (cites D-014, not `BOUNDARY.md`; reframed trigger;
swallow guard; in-repo skill-name constant; D-048 wiring). The handoff's acceptance
criterion "framework ingest parses the file" is framework-side and is dropped from
apparatus acceptance. **Implementation is GATED** behind the human's go: a single small
`emit_skill_signal` one-append helper (rule 8) + the conftest extension; (b)/(c) may ship
first. Follows the D-046 precedent — the apparatus is the single merge/commit authority
and owns whether it takes on a cross-boundary obligation.

## D-057 — GB10 unified-memory budget: trim Gemma util 0.40→0.30 so both vLLM servers co-reside under the 30 GiB OS margin (margin HELD, not lowered)

**Date.** 2026-06-28. **Context.** The D-049 coordinator runway refused every cycle
2026-06-26 → 06-27 on `preflight_mem` (`MemAvailable=22GiB < need(0)+margin(30)=30GiB`).
Root cause: restoring `vllm-qwen` (2026-06-25) plus the orphaned, unhealthy
`openshell-nara-sandbox` pushed the GB10 unified pool (121.7 GiB) under the OS margin.
The two NVFP4 27B-class servers pin the pool via `--gpu-memory-utilization`: gemma 0.40
(~49 GiB) + qwen 0.25 (~30 GiB) ≈ 79 GiB. Weights are ~18.6–18.9 GiB EACH
(near-incompressible per vLLM startup profiles); the only real slack is KV cache.

**Diagnosis.** gemma@0.40 carried **26 GiB / 21.87× KV headroom** — wildly oversized for
the apparatus's single-stream orchestration. qwen@0.25 has only **6.87 GiB KV slack**
(its weights dominate its budget), so it is not the lever.

**Decision.** Trim **GEMMA 0.40 → 0.30** (now 12 GiB KV / 10.1× concurrency for 32k —
ample); leave **QWEN at 0.25**. Result: **MemAvailable ~35 GiB with BOTH resident**;
`preflight_mem.sh 0` PASSES. Captured the exact production launch for both servers in
[`cron/serve-models.sh`](cron/serve-models.sh) (closes the un-scripted `docker run` gap;
both containers `--restart unless-stopped`). Stopped the orphaned `openshell-nara-sandbox`
(idle since the D-051 probe; ~1 GiB).

**Inviolate.** The 30 GiB OS margin was **HELD, not lowered** (inviolate rule 7; the
2026-06-08 arm-C freeze disproved a thin margin). Gemma re-verified on **MARLIN** MoE
(inviolate rule 2): `Using 'MARLIN' NvFp4 MoE backend`.

**Reversibility.** Re-raise via a `cron/serve-models.sh` util edit + re-run `preflight_mem.sh`;
never raise utilization without confirming the margin still clears with both servers up.

**Structural note.** This single box cannot run both 27B servers with generous KV on each
*and* the 30 GiB margin — the trim is the standing accommodation. Deeper options
(on-demand qwen load per cycle; a second box) are deferred; named so they are not lost.

## D-058 — P4 v0: ship the dedup-keystone topic miner (`mine_paper_gap`); single cosine τ_dup demoted, lexical Jaccard load-bearing

**Date.** 2026-06-30. **Context.** The closed-loop-autonomy keystone — let the apparatus
propose its own research topics instead of waiting on a human `spawn_topic` — designed in
[`docs/p4_topic_autogen_design.md`](docs/p4_topic_autogen_design.md) (10-agent design
workflow + adversarial judge). The near-dup pathology is LIVE: the un-starved cron promotes
near-identical hypotheses into the cockpit every 12h (25 items, heavy 5×/3× clusters).

**Decision.** Ship **v0 = the dedup keystone + a non-generative selector** (owner Q1). The
honest headline (from the design panel): the keystone is a **dedup** problem, not LLM
generation — gap-*ranking* is near-random at the current corpus size and the "independent Qwen
screen" is inert at the topic seam. A real **BGE-M3 falsifier on the 21 live backlog claims**
proved a single cosine τ_dup **cannot** separate reworded near-dups from distinct findings
(lowest intra-cluster 0.875 < highest cross-distinct 0.938). So:
- **Lexical Jaccard is the load-bearing dedup layer**; cosine τ_dup is a HIGH (0.97)
  near-identical-only filter, a tunable constant — NOT the gate (agent Q3, grounded by the
  falsifier).
- Topics are **extracted arXiv titles, never Gemma generations** → defuses the same-model
  echo; topic-gen **SELECTS, never scores novelty** — the downstream Qwen skeptic + the loop's
  `novelty_classify` stay the novelty authority (agent Q4).
- On-domain cap **inert/smoke-only** (`ANCHOR_MIN=None`; in-domain anchor measured 0.505–0.607,
  no off-domain examples — corpus is pre-filtered upstream) (agent Q5/Q6).
- **No Qwen at the topic seam** in v0 (agent Q7). **Ledger-only `paper_gap` provenance**, NO
  `seed.source` schema enum edit (owner Q2; `_run_loop_iteration` hardcodes `source="coordinator"`).

**What shipped (ecf5408).** `workers/mine_paper_gap.py` (7-layer `_dedup`) + 8 tests; a budgeted
`mine_paper_gap` coordinator action (cost 1); the graft-4 `_topic_suggestions` origin-tag fix
(mined rows surface as a non-preferred source, not masquerading as human follow-ups).
Verified: full suite 1314 green; real `env -u MOCK_LLM` smoke mined 20 live papers in 31s with
no false-positive drops; the falsifier-oracle test collapses the live near-dup cluster to 1.

**Scope / reversibility.** v0 stops FUTURE near-dups at the TOPIC seam; the existing 25 cockpit
near-dups still need human triage (or a future dedup-at-promotion pass). Fully reversible —
remove one menu entry; constants are env/module-tunable. **v1 deferred** (owner Q2): thread a
real `source="paper_gap"` through `run_iteration` + `journal_writer` (a spine edit) in the next
couple of sessions. Implements the design doc's Decisions(2026-06-30).

## D-059 — Evidence ladder L0–L5; surfacing bar = L4+; supersedes D-053's advisory flip

**Date.** 2026-08-14. **Context.** The 06-25 `NARA_PROMOTION_VOTE_ADVISORY=1` flip (D-053)
was designed to un-starve promotion and let the human calibrate. Measured outcome after 50
days: **all 31 surfaced findings carry `adversarial.survived=false` (3/3 refuted), 16 carry
`redteam.verdict=fatal_flaw`, and zero were ever human-dispositioned** — the cockpit became
a queue of unanimously-refuted candidates, the human disengaged, and the backlog gap then
starved the planner into a 20-cycle no-op fixed point (2026-08-05 → 08-14). `_passes_threshold`
reads 3 of ~15 available signals and consults neither negative one.

**Decision.** A single **evidence ladder** replaces both the binary gate and the non-gating
advisory: L0 asserted · L1 literature-consistent (relevance ok + novelty + critique survives
+ redteam ≠ fatal_flaw) · L2 synthetic-tier experiment (trials ≥ 30) · L3 robustness/replication
· **L4 adversarial-survived (vote `survived=true` AND redteam `proceed` — the two previously
ignored signals ARE the L3→L4 gate)** · L5 human-validated. **Only L4+ surfaces to the
cockpit.** Surfacing is a bar, not a quota: zero-survivor weeks report a count, never a coerced
promotion. Rung derivation is pure code (rule 4: missing signal ≠ pass). The
`NARA_PROMOTION_VOTE_ADVISORY` env branch is retired; the vote writes `evidence_level_changed`
events instead of gating a binary surface.

**Alternatives.** (a) Keep the advisory + hand-triage the 31 — rejected: the owner's measured
behavior (n=0 dispositions) is the falsifier; (b) re-harden the vote as a binary gate —
rejected: reproduces the pre-D-053 starvation with no gradation. **Reversibility.** Ladder
thresholds are module constants; surfacing bar is one constant; existing ledgers untouched
(demotions are append-only overlay events, D-060).

## D-060 — Idea ledger + MAP-Elites acceptance as the apparatus's memory; deep-wiki shape rejected; LLM judge gated behind a pre-registered calibration

**Date.** 2026-08-14. **Context.** Measured duplication pathology: 8–10× lexical restatement
clusters (May), seed-level rediscovery incl. re-deriving a retrieved paper 5 iterations
running (Jul–Aug; 18 distinct seeds across 40 iterations). Root cause is bookkeeping, not
retrieval: nothing records idea status (open / in-progress / killed-with-reason) and nothing
injects it into topic selection or generation. gbrain is process telemetry and firewalled from
the runtime (D-014) — the memory must be a runtime artifact.

**Decision.** (1) **`memory/idea_ledger.jsonl`** — append-only events (`cluster_created`,
`member_added`, `evidence_level_changed`, `cluster_killed`, `cluster_reopened`,
`niche_seeded`, `agenda_item_*`); cluster state = deterministic reduction; existing ledgers
never rewritten. (2) **Clusters = niches; MAP-Elites elite rule**: a candidate entering a
populated cluster must differ from or beat the elite; prefilter = the D-058 lexical/cosine
layers; the **LLM equivalence-or-better judge activates only if it passes a pre-registered
calibration** against the known restatement clusters (precision ≥ .90, recall ≥ .80,
false-equivalence ≤ 10%, symmetry ≤ 10%, flip ≤ 15% — each checked independently, never
coerced; fail → prefilter-only stands, judge logs advisory). (3) **Programmatic kill reasons**
(from run records — never LLM prose) + evidence-keyed reopening conditions; **paper niches
pre-closed** (rediscovery must articulate a delta); **mandatory adopt-or-reject** of matched
failure records at generation time. (4) Deterministic three-section **`ideas.md`** projection
(live / graveyard / agenda-with-provenance) consumed by topic selection + hypothesize
conditioning; **agenda-first topics** (arxiv picks become agenda candidates).

**Alternatives.** Karpathy-style LLM-compiled wiki — **rejected on measured grounds** at this
corpus scale (~100 structured rows): LLM-compiled context measured net-negative in 5/8
settings (arXiv:2602.11988); summary-poisoning/self-citation reports; memory agents barely
beat bare LLMs on invalidation (Memora/FAMA, arXiv:2604.20006); free-prose failure
reflections 0/121 correct vs 86% programmatic (arXiv:2605.29463); mandatory-consultation
typed negative memory outperforms (arXiv:2606.21024); MAP-Elites/IDEAAgent lineage grounds
the acceptance rule (arXiv:2607.22375). A wiki-shaped synthesis layer stays a candidate for
the EXTERNAL literature corpus (Phase 2, frontier-synthesized, after S2 search is healthy).
**Reversibility.** The ledger is an overlay; deleting it restores today's behavior. The judge
seam is injected and defaults to prefilter-only.

## D-062 — Task-packet micro-orgs (stage-(ii) of the D-046 authorize-fix path) + entrenchment tiers ratified

**Date.** 2026-08-15. **Context.** LOOP_V1 P4: the orchestrator (and primary session)
can spawn bounded engineering micro-orgs, with mechanical enforcement FIRST (the PoE
teardown's two loudest lessons: its merge robot never merged once — the gate wasn't
installed — and its only real-money budget was silently unmeasured).

**Decision.** (1) Work unit = a **task packet** (`schema/task_packet.schema.json`;
a field the dispatcher doesn't mechanically read is documentation, not control).
(2) **`orchestrator/packet_dispatcher.py`**: attempt incremented BEFORE invoke;
ack decided by the dispatcher (acceptance test re-run + `tools/premerge_check.sh`),
never the agent; red-first (must_fail_before); done requires a COMMITTED branch;
secrets stripped from the agent env; NEVER merges. Ledger `run_state/packets.jsonl`
(machine-enforced control; `spawn.jsonl` stays a discipline). Human overrides →
`run_state/overrides.jsonl` via `orchestrator/override_log.py` (human-only actors).
(3) **Entrenchment tiers ratified by the owner (G4, 2026-08-15, overrides.jsonl)**:
Tier P (workers/tools/tests/docs/bench/experiments) merges on green + framework
code-review; Tier S (spine, schema/, version pins, promotion-bar constants,
CLAUDE.md, DECISIONS.md, cron/serve-models.sh, run_state semantics) additionally
requires logged human ratification. Full pipeline: `docs/packet_sdlc.md`.

**Evidence.** Real e2e 2026-08-14/15: PKT-EXAMPLE done on attempt 1, premerge green,
primary merged `--no-ff` (cc2b542); the first run caught the relative-venv worktree
trap and digest-only ledger opacity (both fixed + documented). **Reversibility.**
The dispatcher is dev-time, primary-invoked; coordinator-runtime dispatch is
explicitly deferred (D-014 line, its own future gated decision).

## D-061 — Frontier critic tier: Claude Max + Codex as falsifiers-only inside the promotion funnel (executes D-041 step 3; supersedes-in-part D-012's no-routing posture for this seam)

**Date.** 2026-08-15 (G1 cleared + G5 ratified by owner; overrides.jsonl). **Context.**
The owner pays Claude Max + ChatGPT subscriptions; the LOOP_V1 design routes them as an
adversarial early screen while local pinned models remain the PI. D-041's skeptic ladder
already named Claude as its design-only step 3; D-033's "second model excluded" was
superseded in live practice by D-035/D-044 (this entry also ratifies the CLAUDE.md
bullet fix recording that).

**Decision.** (1) **Roles are opposed and fixed**: Claude = methods reviewer, Codex =
novelty reviewer (env-overridable); disagreement cross-runs once, persistent
disagreement -> inconclusive + escalation row. (2) **Falsifier-only**: verdicts are
vetoes/annotations — attention filters. A veto cannot contaminate reproducibility
(survivors' evidence stays local+pinned); frontier NEVER generates, never writes
loop_memory or the brain (annotate-only firewall, D-014-adjacent). (3) **Seam**:
env-gated `NARA_FRONTIER_SCREEN` veto stage in `finding_promotion` between the cheap
gate and the Qwen vote; fail-open on outage (a frontier outage never blocks the local
loop); plus the weekly agenda-synthesis cron (proposals land `status: proposed`, inert
until accepted). (4) **Every call ledgered** in `run_state/frontier_calls.jsonl` —
this doubles as the frontier-vs-local calibration dataset. (5) **Routing rule** (from
the 2026-08 restructure review): a call a reader needs to reproduce a finding runs
local/pinned; everything else is rentable. (6) `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`
are stripped from every spawned CLI env (test-pinned) — subscription auth only, never
silent metered billing.

**Evidence.** First real screen 2026-08-15: both vendors independently vetoed
`iter-2026-08-04-001` with cited critiques (methods: tautological FOC, concurring with
the June Qwen redteam fatal_flaw; novelty: von Wangenheim prior) — first calibration
datapoint = frontier/local agreement. **Reversibility.** `rm run_state/frontier_tos_ratified`
darkens every frontier path (CLI + cron refuse, test-pinned); the promotion stage is
env-gated off by default.

## D-063 — Always-on Nara: hourly cadence + event-driven daemon (executes D-040's β clause; owner-ratified)

**Date.** 2026-08-15 (ratification row `D063_ratify_always_on` in
`run_state/overrides.jsonl`). **Context.** The continuous-orchestrator guardrail
was written pre-β with D-040 as its sunset clause. β shipped 06-18; on 08-15 the
loop proved itself autonomous twice in production (un-blind clean iteration at
09:00Z; agenda-first cycle at 15:00Z), and the safety inventory the June zombie
demanded now exists: stall detector + red loop_alert, container watchdog cron,
budget ledger, keyed near-misses, pause-file kill switch, and the L4+ surfacing
bar (volume cannot flood the human — it accumulates on ladder rungs).

**Decision.** (1) **Stage 1 (immediate):** coordinator cron `0 9,15` → hourly
`0 * * * *`; `DAILY_BUDGET_CAP` 18 → 60 (24 cycles × ~2.5 avg cost ≈ ~50 min
GPU/day; env-overridable unchanged). (2) **Stage 2:** resident
`orchestrator/nara_daemon.py` under systemd --user (Restart=always): wakes on
EVENTS (agenda additions, mined papers, lab-channel delegations, packet
completions) with a heartbeat floor + idle backoff; every pass runs the SAME
gate ladder as cron/run-coordinator.sh (flock, pause, D-049 sentinel,
preflight, budget). Cron stays as belt-and-braces until the daemon shows a
clean week, then retires by a follow-up note. (3) **Stage 3:** lab-channel
messages wake the daemon; Nara posts cycle results to the channel.
CLAUDE.md guardrail bullet amended accordingly (Tier S, ratified herein).

**Reversibility.** `run_state/pause_coordinator` halts everything instantly;
crontab line reverts to `0 9,15`; cap reverts via `COORDINATOR_DAILY_CAP`;
the daemon is `systemctl --user stop/disable nara-daemon`.

## D-064 — Critique-refine cycle: 5 bounded rounds of frontier feedback → Nara revision → re-screen, before a kill

**Date.** 2026-08-15 (owner-specified mechanism, same session as D-063).
**Context.** The frontier screen kills efficiently (F1: 3 of 8 open clusters on
cited prior work), but a veto carries *improvement information* — "here is the
prior art / here is the missing control" — that was being discarded with the
idea. The owner's framing: reviewers vet AND advise, Nara refines, critique
repeats, "maybe we limit this to 5 times before an IDEA gets killed."

**Decision.** `workers/refine_cycle.py`: for a vetoed/pre-kill cluster, collect
BOTH frontier reviewers' reasoning + closest_prior_work as improvement
feedback, revise the claim through the hypothesize-retry pattern, re-screen,
and repeat — **hard cap MAX_REFINE_ROUNDS=5** (out-of-band values RAISE, never
clamp). Each round appends an additive `cluster_refined` ledger event
{round, feedback_digest, refined_claim}; exhaustion appends `cluster_killed`
coded `paper_prior_exists` (final novelty veto cited concrete prior) else
`adversarial_refuted`, carrying the refinement history. A pass STOPS the cycle
and — only when the cluster's stored `reopening_condition.evidence_kind` is
`articulated_delta` — reopens it; any other required kind reports
`reopen_skipped` rather than forging evidence (rule 4). Refinement **never
auto-promotes**: a survivor re-enters at its honest rung and still owes its
rung's test.

**Alternatives.** Unbounded refinement (rejected: an idea that needs six
rewrites to survive a reviewer is the reviewer's point); kill-on-first-veto
(status quo ante — discards the actionable half of the critique).
**Reversibility.** The worker is opt-in (CLI/coordinator action); the ledger
events are additive; deleting them restores the pre-D-064 reduction exactly.
Coordinator `refine_idea` action wiring is deliberately deferred to the
integrator (not built in the same pass as the mechanism).

## D-065 — Adversarial debate replaces the single-shot skeptic exchange (dark); skeptic provenance is recorded

**Date.** 2026-08-15 (owner-ratified params: `run_state/overrides.jsonl`
`D065_debate_params_ratified`). **Context.** Reading a critic record, the owner
asked for "a real back and forth… like a real research debate" and "can we tag
what model ran this". Verification found a hole: `novelty_skeptic.attack()` (and
`restate_skeptic`) RETURN `backend`/`model`, but `critic_loop_v0` kept only the
verdict string — so every recorded `skeptic_verdict` was **untagged**, making the
D-041/D-044 independence claim (Qwen challenges Gemma) unverifiable from the
record. The exchange was also single-shot: one attack, one verdict, no rebuttal.

**Decision.** (A) **Provenance is carried through** on BOTH skeptic paths:
`critique.skeptic_backend/skeptic_model/skeptic_wall_seconds` and
`restate_backend/restate_model/restate_wall_seconds` (additive schema; no
invented turn counts — `attack()` is one `call_sync`, so no `turns_used` is
fabricated). (B) **`workers/debate.py`**: bounded multi-turn debate — challenger
(vllm-qwen) attacks, defender (vllm-gemma) must rebut specifically or CONCEDE,
repeat; **MAX_DEBATE_ROUNDS = 4** (owner-ratified). Stop criteria: defender
concedes → `refuted`; explicit challenger concession → `survives_debate` (the
ONLY route in); challenger repeats a substantively identical objection
(lexical Jaccard ≥ 0.8) → **`converged` → `inconclusive`** (owner-ratified:
converged is NEUTRAL, never survival); cap reached → `inconclusive`. Every turn
is stored with its own backend/model tag. **Dark by default**: requires
`NARA_SKEPTIC=1` AND `NARA_DEBATE=1`; unset = today's behavior byte-identical.
The debate does its OWN retrieval (evidence=None from the critic) so the
challenger never inherits the critic's neighbor set — preserving exactly the
shared-blind-spot break D-041 exists for.

**Reversibility.** Unset `NARA_DEBATE`; the provenance fields are additive and
harmless. **Known downstream note:** with debate armed, the battery's
`skeptic_verdict` column reads `survives_debate` where it read `survives_attack`
(no code compares that literal; flagged, not silently normalized).

## D-066 — Nara plans improvements to the apparatus itself: telemetry evidence → frontier debate → red-first packet → Qwen builder (dark)

**Date.** 2026-08-16. **Context.** The owner asked for "the orchestrator to go
through a debate loop with frontier intelligence to plan an improvement on the
system itself, something small, and this then gets broken down enough into a
development task that can be shipped to qwen or an organization of developers".
Every prior loop pointed outward at research; the apparatus had no seam for
changing itself, so its own repeating operational failures (the D-063 daemon
log, cycle repeats, near-miss floods) accumulated with nowhere to go but the
owner's attention.

**Decision.** `orchestrator/self_improve.py` — a bounded planner, not an agent:

1. **Evidence is telemetry, not ambition.** `gather_evidence()` is pure reads
   over the run log, health signals, loop alert, coordinator cycles (including
   repeat detection), near-misses and the daemon log. A source that cannot be
   read lands in an explicit `unavailable` list — a missing signal is reported,
   never treated as a clean one (rule 4). A proposal must name the live signal
   it answers.
2. **Both frontier falsifiers must AFFIRM.** `review()` runs the D-061 pair as
   opposed jobs (feasibility / risk-scope). Only an affirmative `pass`
   proceeds; a veto **or an inconclusive** sends the proposal to `revise()` and
   round again, capped at **MAX_IMPROVE_ROUNDS = 3** (the cap raises rather
   than clamping). Exhaustion emits nothing and returns the full transcript.
3. **Red-first is PROVEN, not asserted.** `emit_packet()` writes the acceptance
   test and then RUNS it; only **rc 1** (a real failure) allows the packet.
   A passing test, a collection error, or any other rc refuses the emission —
   a test that was never red cannot certify the fix that follows.
4. **Tier P only.** Every file the packet touches is checked against
   `TIER_P_PREFIXES` (workers/ tools/ tests/ docs/ bench/ experiments/). A
   Tier-S path (the spine, `schema/`, version pins, `CLAUDE.md`,
   `DECISIONS.md`, `cron/serve-models.sh`, run_state semantics) is **refused**,
   not escalated — self-modification stops at the entrenchment line D-062 drew.
5. **The exit is the existing SDLC, not a new one.** The packet + queue row
   are the D-062 artifacts, so the work leaves through the dispatcher (Qwen
   builder, file scope, attempt cap), `tools/premerge_check.sh` and the full
   suite, and the primary session remains the single merge authority.
6. **Dark by default.** The coordinator action `improve_system` (cost 4) is in
   `DARK_ACTIONS`, keyed to `NARA_SELF_IMPROVE`. Unset, it is absent from the
   planner menu — the planner cannot choose what it cannot see — and the
   handler refuses it a second time, so a hallucinated action name cannot spend
   a frontier call. The refusal is returned and recorded, never a silent noop.

**Reversibility.** Unset `NARA_SELF_IMPROVE` and the action disappears from the
menu; nothing else in the cycle changes. Emitted packets are ordinary D-062
packets and are killed the ordinary way.

## D-067 — The lab channel gains an attributable participant registry; Oracle enters as observer-only mission steward

**Date.** 2026-08-16. **Context.** Another session ("Oracle") was ratified by the
owner as mission steward for the broader locally-grounded personal
research/build laboratory, observing `a_bgt_rsi` but never editing it — its
proposals were to flow "through Nara and the existing gates". Its first message
reached the channel relayed as an ordinary `human` turn, so the exchange was
**unattributable in the transcript** (the owner and the steward were the same
row kind), and Nara's reply exposed two real defects: it restated a stale "31
surfaced findings / 8 pending gate verdicts" carried forward from the transcript
tail rather than re-read from the live sections, and it **invented** a handoff
path (write the proposal into `ideas.md`; human verdict before the authorize-fix
queue) instead of naming the seams that exist.

**Decision.** (A) **Participant registry.** `orchestrator/lab_channel.py` gains
`_PARTICIPANTS = ("human", "oracle")` and `turn(..., author=)` / `turn --as`;
the author is stored as the transcript row `kind`, so who addressed the lab is
recorded, not inferred. Default stays `"human"` (every existing caller
byte-identical); an unregistered author RAISES rather than being coerced to
`human` — an unattributable row is worse than no row (rule 4). **Identity is
not capability:** the registry grants a name and nothing else. The module's
disposition fence binds every participant equally, the UI's turn endpoint does
NOT accept an author (the owner's surface cannot impersonate the steward), and
the steward reaches the lab only through the same blessed CLI.
(B) **Context precedence + seam honesty** are now explicit in both voice
prompts: the live pack sections (`ideas.md`, `planner_state`, `loop_alert`) are
AUTHORITATIVE and the transcript tail is HISTORY that may carry superseded
counts; the improvement path is stated in its real ORDER (improvement
delegation → authorize-fix queue row → red-first task packet → dispatcher/Qwen
builder → premerge + full suite, primary merges → D-062 tiers decide autonomy),
research delegation is named as a different seam, and the required evidence is
a named live telemetry signal plus an acceptance test that fails today.
(C) **The exchange is on the dashboard**: the Channel surface renders `oracle`
as a named voice — deliberately the brightest NEUTRAL rather than an apparatus
hue (every remaining hue window is flanked by two status hues, and a wrong read
there would be a status read) — plus a `steward` filter whose exchange is the
steward's turn and the reply the CLI writes directly after it (adjacency, never
inferred from prose).

**Verification.** Both defects were re-tested live against Gemma through the new
path: the second reply corrected itself against `planner_state` ("the transcript
tail mentions 8, the authoritative planner_state lists 1") and, after the prompt
fix, restated the ordered path with the real artifacts and explicitly refused
the step it could not verify. **Reversibility.** Drop `"oracle"` from
`_PARTICIPANTS` — historical rows keep their recorded kind and render under the
neutral fallback voice; no ledger is rewritten.

## D-068 — Frontier vendor invocation is pinned in-repo, not inherited from the machine-global CLI config

**Date.** 2026-08-16. **Context.** The first live D-066 run showed every
`risk_scope_reviewer` call returning "frontier invoke error: nonzero". The
cause was outside the repo: `~/.codex/config.toml` pins `model = "gpt-5.6"` and
`model_reasoning_effort = "max"`, and both began returning HTTP 400 ("not
supported when using Codex with a ChatGPT account"). Ledger evidence in
`run_state/frontier_calls.jsonl`: **32 consecutive clean codex calls, last OK
2026-08-15T19:30:02Z, then every call nonzero.** For roughly six hours every
D-061 consumer — the F1 screens, the D-064 refine cycle, the D-066 debate —
silently ran on a **one-reviewer panel** while still reporting an "opposed
jobs" review. The second reviewer's failure surfaced only as `inconclusive`,
which reads like a reviewer's judgment, not an outage.

**Decision.** `agent_wrapper/frontier_cli.py` pins the codex invocation:
`CODEX_MODEL = "gpt-5.5"` and `CODEX_REASONING_EFFORT = "high"`, passed
explicitly as `-m` / `-c model_reasoning_effort=...` and overridable by
`FRONTIER_CODEX_MODEL` / `FRONTIER_CODEX_EFFORT`. The apparatus states what it
runs on rather than inheriting a machine-global file it does not version — the
same reason the vLLM image and CUDA versions are pinned verbatim. The owner's
`~/.codex/config.toml` is left untouched (it serves other projects, and the
entitlement may return). Verified live: exit 0 with a returned reply. The
command shape is test-pinned.

**Standing lesson (not yet built).** A degraded frontier vendor is currently
indistinguishable from a hesitant reviewer. Frontier-vendor health belongs in
the loop-alert surface; until it is there, a panel can go half-dark for hours
without anything noticing. Filed as open work in the 2026-08-16 session note.

## D-069 — The frontier CLI seam gets a repo-owned CODEX_HOME (amends D-068 the same day)

**Date.** 2026-08-16. **Context.** Hours after D-068 pinned the codex model
in-repo, codex broke again — this time in ~35ms with
`Error loading config.toml: invalid type: string "fast", expected struct
AgentRoleToml in 'agents'`. The machine-global `~/.codex/config.toml` had been
rewritten **mid-session** (mtime 02:04:47Z, during a live review round): an
`[agents]` table appeared above two keys that had been top-level, and the
installed CLI could not parse the result. D-068 pinned WHAT model we ask for;
it did not stop us from reading a mutable file we neither own nor version.

**Decision.** `agent_wrapper/frontier_cli.py` spawns codex with
`CODEX_HOME` pointed at `run_state/codex_home/` (gitignored): a two-line
`config.toml` carrying `CODEX_MODEL` / `CODEX_REASONING_EFFORT`, plus a
**symlink** to `~/.codex/auth.json`. The credential is borrowed, never copied
— a copied token is a token that outlives its rotation. The config is
rewritten on every call, so a stale home can never outvote the module's pin.
If the credential is absent the seam leaves `CODEX_HOME` unset and lets the
call fail with the real error rather than manufacturing a home directory.
Verified live: exit 0 through the isolated home while the global config was
still unparseable.

**The owner's `~/.codex/config.toml` was deliberately NOT repaired.** It is
shared with other projects, it changed while this session was running, and the
`[agents]` block is not ours — editing it could stomp a concurrent edit. It is
still broken for any codex invocation that does not set `CODEX_HOME`, and that
is the owner's call to make.

**Companion detector.** `loop_health.detect_frontier_vendor_down()` fires when
a vendor's last `FRONTIER_DOWN_STREAK = 3` calls all exit nonzero, and
`emit_health_signals` now runs it every cycle. Rows without an integer
`exit_code` are unknown and are scored as neither success nor failure; fewer
than a streak's worth of judgeable rows yields no signal, because too little
evidence is not health. This is the thing that would have caught D-068 six
hours earlier: a dead vendor surfaces one layer up as `inconclusive`, which
is indistinguishable from a reviewer declining to commit.

## D-070 — Reasoning-backend token caps are sized from the measured tail, not from the non-reasoning persona; ml_intern's wall cap is made able to spend its own retry schedule

**Date.** 2026-08-16. **Context.** The 04:00Z cycle raised
`loop_alert.level=amber` with two signals, `ml_intern_zero_papers` and
`qwen_degraded_empty_content`. Both detectors were right, and each pointed at
a *self-inconsistent constant* rather than at an outage.

**(A) Qwen token starvation.** `3072` was fixed on 2026-06-09 as the figure
that stopped Qwen starving at 512/2048. Measured against the call ledger on
2026-08-16 — 651 real Qwen calls — the p90 output for the independent-skeptic
sites sat **AT** that cap; 43 calls hit it and 31 returned EMPTY content. The
cap had become the thing it was introduced to fix. Raised to **6144** at every
reasoning-backend skeptic site (`novelty_skeptic` worker + orchestrator,
`topicality_skeptic`, `debate`, and the promotion-vote subagent), sized against
the served 16k window with ~2k prompts. vLLM rejects rather than clamps, so the
figure is sized, not guessed. For the promotion vote `max_tokens_total` moves
with the per-turn figure (8000 → 16000): at the default a 6144 turn leaves under
one further turn, spending the repair-retry `max_turns=4` exists for.

**What it cost, precisely (the claim was checked, then corrected).** The first
reading — "~4% of promotion votes were lost" — was **wrong**, and the vote
records say so: all 31 recorded votes carry `qwen_failures=0`. That site has a
repair-retry which absorbs a truncated turn, so what truncation cost there was
*turns*: 12.5 calls per vote, ~4.2 per skeptic against a `max_turns` of 4 — the
panel was running at the edge of its own turn budget. The verdicts genuinely
lost were at the **single-call** sites, which have no repair turn: `attack`
(4 of 48), `topicality_probe` (3 of 132), `topicality_attack` (1 of 96). Those
degrade to inconclusive, which is honest but is a verdict the apparatus paid
for and did not get.

**(B) ml_intern could not spend its own retry budget.** `_BACKOFF_SCHEDULE =
(5, 15, 30, 60)` against `wall_cap_s = 90.0`: after 5+15+30 = 50s the next
backoff would exceed the cap, so the fourth retry was **structurally
unreachable** — the worker advertised four retries and could take three. S2
throttles its search endpoint in bursts that outlast 50s (the 04:00Z cycle
429'd four times running while the 18:00, 19:00, 22:00 and 02:00 cycles
recovered after one or two). The cap is now derived —
`sum(_BACKOFF_SCHEDULE) + 70` — and a test pins the *relationship*, not the
number: change the schedule and the cap must follow. Still a hard cap (rule 7),
now an honest one. **The S2 key is fine** — verified live: keyed request 200,
deliberately-bad key 403, anonymous 429.

**Verification.** Both fixed paths were exercised live, not merely reasoned
about: a real Qwen skeptic call returned a verdict using 1690 of 6144 tokens
(28% headroom, non-empty content), and a real `ml_intern` fetch returned
`status=passed`, 6 papers fetched / 3 stored.

## D-071 — The bounded debate is ARMED (executes D-065's adoption gate on measured evidence)

**Date.** 2026-08-16. **Context.** D-065 shipped `workers/debate.py` dark and
required a comparison against the single-shot skeptic "before adopting". The
comparison had never been run: across 128 iterations, **0** carried a debate
transcript, and `NARA_DEBATE` appeared in no cron script, no unit file, and no
environment. Meanwhile the owner, looking at the ideation surfaces, observed
that nothing shows a back-and-forth — correctly, because none existed.

**The comparison** (`bench/debate_eval/adoption_20260816.json`): three claims,
each run through BOTH paths in the same session, challenger vllm-qwen
(qwen3.6-27b-nvfp4-mtp) vs defender vllm-gemma (gemma-4-26b-a4b).

| claim | single-shot | debate | stop | cost |
| --- | --- | --- | --- | --- |
| liquid-democracy centrality inflation | `survives_attack` (96s) | `inconclusive` | round_cap | 428s |
| finite PD cooperation | `refuted` (58s) | `refuted` | defender_conceded | 86s |
| centrality-weighted peer selection | `survives_attack` (91s) | **`refuted`** | defender_conceded (r3) | 469s |

**Decision: arm it** (`NARA_DEBATE=1` in `cron/run-coordinator.sh` and
`systemd/nara-daemon.service`). The evidence:

1. **It never rubber-stamped.** In 2 of 3 cases the debate was strictly more
   conservative than the single shot.
2. **It caught a real over-certification.** On the third claim the single-shot
   skeptic returned `survives_attack`; three debate rounds ended with the
   DEFENDER conceding — "the provided evidence does not contain a direct
   comparison between centrality-weighted peer selection and uniform sortition
   regarding representativeness under partial participation". A `survives`
   verdict the apparatus would have banked was wrong, and only the exchange
   exposed it.
3. **The disagreement is substantive, not stylistic.** The challenger's round-3
   objection was that the defender *misattributed a claim to Doc 5* — a
   citation check the single shot has no mechanism to perform.
4. **Cost is bounded and correctly shaped**: 86s when the claim is plainly bad
   (fast concession), 428–469s when it is contested. The expensive cases are
   exactly the ones the single shot got wrong.

**Reversibility.** Unset `NARA_DEBATE` in both places; the single-shot path is
untouched and returns byte-identically. **Note for the record:** the
single-shot skeptic remains the fallback whenever the debate errors, and
`survives_debate` still requires an explicit challenger concession (D-065) —
arming changes which exchange runs, not what counts as survival.
