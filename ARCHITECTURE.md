# Architecture — a_bgt_rsi research apparatus

> **What this document is.** The canonical written walkthrough of the
> apparatus. Read alongside `docs/diagrams/architecture_v4.svg` (static
> structure) and `docs/diagrams/intelligence_loop_v4.svg` (the eight-step
> loop). For the intellectual program behind these choices, see
> `docs/sources/research_program_v2.pdf`. For the rationale of each major
> decision, see `DECISIONS.md`. For what to execute today, see `plan.yaml`.
>
> This document supersedes
> `docs/sources/research_apparatus_technical_plan_v1.md` only where the two
> conflict and the conflict has been resolved in `DECISIONS.md`; otherwise
> the source technical plan wins on detail.

---

## 1. The contribution

The apparatus is the research contribution. The findings populate the work
with content; the apparatus is the research object under test. Concretely:
the claim is that a single researcher with a DGX Spark, open models, and a
deliberate loop design can produce findings a competent domain researcher
would endorse — at the productive edge of a real field. The field of
application is game theory, behavioral game theory, and learning in games,
chosen because LLM agents in game-theoretic settings are underexplored, the
experimental-design traditions are clean, and the apparatus can operate
across a synthetic-to-applied spectrum with increasing realism.

The apparatus is not a frontier-lab automation system, not a recursive
self-improvement system, and not a theorem prover. It is a single human's
research workflow amplified by an LLM orchestrator that has access to the
literature, a sandbox of experimental tiers, a small set of bounded tools,
and a memory of what's been tried and assessed before.

---

## 2. Hardware and serving layer

### 2.1 DGX Spark

One NVIDIA DGX Spark unit. GB10 Grace Blackwell Superchip, 128 GB unified
LPDDR5X memory, ~1 petaFLOP FP4 (with sparsity caveat — without sparsity,
~500 TFLOPS), 273 GB/s memory bandwidth, 240 W power supply, 20 ARM cores
(10 × Cortex-X925 + 10 × Cortex-A725), 4 TB SSD, desktop form factor,
$3,999–$4,699 depending on configuration.

The 128 GB unified memory is the **enabling** constraint — it permits a
26–30 B-parameter orchestrator model (~18–29 GB) plus training-experiment
headroom (~30–50 GB) plus vector storage (~3–5 GB) plus runtime overhead
(~5–8 GB) concurrently. The 273 GB/s memory bandwidth is the **binding**
constraint, not capacity. MoE architectures are strongly preferable to dense
models because they activate fewer parameters per token and demand less
bandwidth.

The Spark pays for itself versus cloud rental within 6–12 months of daily
inference and provides full data sovereignty — critical when every prompt,
seed, and model version is recorded as a research observation.

### 2.2 Orchestrator: Gemma 4 26B-A4B MoE in NVFP4

Selected for ~3.8 B active parameters per forward pass (yielding ~50–60
tok/s single-stream on the Spark's bandwidth-constrained memory, ~115 tok/s
aggregate at three concurrent requests), 85.5 % τ2-bench agentic tool use,
89.2 % AIME 2026 math reasoning, native function calling and structured JSON
output, Apache 2.0 license, ~16.5 GB on-disk at NVFP4, 256 K context
window, multimodal text/image/video/audio input. Released April 2026 by
Google DeepMind.

NVIDIA's official NVFP4 quantization is on HuggingFace at
`nvidia/Gemma-4-26B-A4B-NVFP4` and is what this apparatus uses. Note that
"NVFP4" as NVIDIA ships it leaves **self-attention weights in BF16** — only
the MLP and MoE expert weights are actually FP4. This is an intentional
accuracy trade-off in NVIDIA's modelopt toolkit; full uniform FP4 quants
(e.g. `bg-digitalservices/Gemma-4-26B-A4B-it-NVFP4`) exist and quantize
attention too, at a small accuracy cost. The NVIDIA checkpoint is the
correct production choice here.

Qwen 3.6 27B Dense is the documented alternative if coding quality proves
insufficient for autoresearch modifications. This is **not a routing
layer** — it is a manual swap. Start with one model. Swap only if a specific
bottleneck is identified. See `DECISIONS.md` "Dual model routing excluded."

### 2.3 Serving: vLLM

OpenAI-compatible endpoint on `localhost:8000`. Pinned image
`vllm/vllm-openai:v0.21.0`, vLLM 0.21.0 — the first release with Gemma 4
MTP speculative decoding (PR #41745; see DECISIONS.md D-022). The `:gemma4` tag
without `-cu130` is the dev image and crashes on FP4 GEMM — do not use it.
Tag naming does not imply one tag is a superset of another; the Day-1 plan
captures the image digest and pins the digest, not just the tag.

Launch flag `--moe-backend marlin` is required. The startup log MUST include
`Using 'MARLIN' NvFp4 MoE backend`. If the log shows `CUTLASS_FP4`, the
backend flag did not take effect; the model will appear to work but will
not reason correctly. This is one of the apparatus's named silent-failure
modes. See `DECISIONS.md` "vLLM MARLIN backend" and "CUDA 13.0 pin."

### 2.4 SM12x compatibility gap (sidebar)

The DGX Spark's Blackwell GPU reports as **SM12x (compute capability 12.1)**,
not SM100 (datacenter Blackwell). This is a real architectural split: SM100
exposes `tcgen05`, TMEM, and 2-SM cooperative MMA; SM12x's tensor-core
programming model is closer to Ampere's `mma.sync`. Kernel libraries that
advertise "Blackwell support" often mean SM100, not SM12x.

What works on the Spark:
- vLLM ≥ 0.19 with the NVFP4 GEMM backends (FLASHINFER_CUTLASS for linear,
  MARLIN for MoE).
- Standard FlashAttention 2 (Ampere-and-later path).
- All of Gemma 4's required ops, via the Marlin path.

What does NOT work:
- FlashAttention 4 (Blackwell-specific, SM100 only).
- FlashMLA's Blackwell backend (SM100 only).
- Any kernel that hard-codes `tcgen05` or TMEM.

This is not a blocker for Week 1. It is a constraint to keep in mind when
later optimizations are proposed — if someone suggests "use FA4 to speed up
attention," that proposal is not portable to the Spark and the suggestion
should be reframed.

---

## 3. The three-tier sandbox

The experimental backbone of the apparatus. A finding that generalizes
across tiers is strong; a finding that succeeds in one and fails in another
is **diagnostic**, not discardable.

### 3.1 Synthetic tier

Classical games with known equilibria — repeated PD, public goods, stag
hunt, Cournot, auctions. Success is cleanly measurable against established
theory. The loop's job here is to rediscover or characterize what's known.
On Week 1 Day 7 this is the only tier in use, with repeated PD vs. five
fixed opponents (TFT, grim trigger, all-C, all-D, mirror-LLM).

Implementation substrate: **OpenSpiel + Game Reasoning Arena**
(`github.com/SLAMPAI/game_reasoning_arena`). Validation-pass adjustment #3
chose this over a custom environment to save 1–2 weeks; GRA already supports
local vLLM as a backend and ships with `prisoners_dilemma` and
`matching_pennies`.

### 3.2 Semi-synthetic tier

Multi-agent LLM societies in designed scenarios. No ground truth, but clear
structure. The research focus here is **mechanism design** — an extension
beyond Research Program v2. The core question: *Can an LLM agent, given a
desired social outcome and a population of self-interested agents, evolve
game mechanisms that outperform known analytical solutions?* This is tested
via a graduated research ladder:

1. **Rung 1 — weeks 1–4 post-hardware.** Single-item auction design.
   Rediscover incentive-compatible mechanisms (Vickrey / Myerson) from
   scratch. Calibration step.
2. **Rung 2 — months 2–3.** Multi-item combinatorial auctions. Evolve
   mechanisms for settings where optimal solutions are computationally
   intractable.
3. **Rung 3 — months 3–5.** Dynamic mechanism design with learning agents.
   Directly connects to Polymarket — prediction markets are
   information-aggregation mechanisms.
4. **Rung 4 — months 5+.** Multi-party mechanism design with incomplete
   information. Governance structures for commons problems.

### 3.3 Applied tier

Polymarket primarily. Live prediction markets with real money, real
adversaries, and objective resolution. Brier Score and Brier Skill Score
against market price are the optimization targets — not raw accuracy.
Design-only in Phase 1; live trading is Phase 2 at the earliest, and gated
on CFTC compliance work (Ed25519 authentication, KYC, trade logging,
position auditing) that the Phase 1 docs flag as a tracked open question.

### 3.4 Cross-tier generalization is the primary value signal

A finding that holds across all three tiers is strong. A finding that
succeeds in one tier and fails in another is **diagnostic** — the gap tells
you something about the difference between clean theory and messy reality.
Cross-tier replication is named explicitly as Step 5 of the intelligence
loop (see §6), and is one of the program's distinguishing methodological
commitments.

---

## 4. The knowledge base

ChromaDB vector store with **BGE-M3 embeddings**. Three layers, all in the
same store, distinguished by collection and metadata.

### 4.1 Why BGE-M3 over the ChromaDB default

ChromaDB's default `all-MiniLM-L6-v2` collapses to 0.4–0.6 retrieval
accuracy at 4 K-character chunks — unacceptable for dense math textbooks.
BGE-M3 (`BAAI/bge-m3`, MIT, ungated) is the canonical multilingual
long-context retrieval model as of 2026 and holds accuracy at 8 K-token
chunks. See `DECISIONS.md` "BGE-M3 over default embedding."

### 4.2 Layer 1 — foundational corpus (static, embedded once during Phase 1)

The textbooks and classical papers from the research program's Track A, B,
and C reading lists. Chunked and embedded as they are read across Days 1–30
(pre-hardware) and 31–60 (post-hardware). By Day 60 the agent has the same
foundational knowledge the researcher does.

Sources include Osborne & Rubinstein, Camerer (Behavioral Game Theory),
Weibull, Hofbauer & Sigmund, Fudenberg & Levine, Cesa-Bianchi & Lugosi, the
AGT book, Hacking (Representing and Intervening), the replication-crisis
papers (Ioannidis 2005, Open Science Collaboration 2015, Camerer et al.
2016/2018), the key LLM-as-agent papers (Horton 2023, Aher et al. 2023,
Park et al. 2023), and the auto-science literature (Sakana, FunSearch,
Coscientist, plus the critical responses).

Why this layer matters: the foundational game-theory literature is almost
entirely pre-arXiv (Nash 1950, von Neumann & Morgenstern 1944, Schelling
1960, Smith & Price 1973, McKelvey & Palfrey 1995, Camerer 2003). An
arXiv-only knowledge base would miss rediscoveries of textbook results —
the exact failure mode the research program names.

### 4.3 Layer 2 — live literature (automated, nightly)

ArXiv nightly scan of `cs.MA`, `cs.GT`, `econ.TH` via the ML-Intern
literature pipeline. Extracts methodology sections, traverses citation
graphs. Semantic Scholar API (200 M+ papers, free, fast) for on-demand deep
search during novelty evaluation — including pre-arXiv literature surfaced
through publisher sites and institutional repositories.

### 4.4 Layer 3 — loop memory (cumulative, grows over time)

Human assessments from Step 6's novelty evaluation feed back into ChromaDB.
When the researcher evaluates a finding as "rediscovery of McKelvey &
Palfrey 1995 QRE," that structured assessment — claim, prior, search
results, post-search assessment, what would change it — gets embedded so
the hypothesis generator doesn't propose the same direction again.

Over months, Layer 3 accumulates what's been tried, what's been found,
what's already known, and what assessments the researcher has made. **This
is the mechanism by which the apparatus gets smarter over time, and the
primary differentiator from systems like Sakana's AI Scientist that have no
cross-run memory.**

**Active vs. passive read (Phase 2).** Layer 3 as described above is a
ChromaDB collection — the hypothesis generator may retrieve from it, but
is not required to read it coherently. The co-scientist's Meta-review
agent synthesizes patterns across runs; this project adds an equivalent
in Phase 2 (the Meta-review synthesis worker, §5.1 and §6 step 1's
Phase 2 addition). Without it, loop memory is a library nobody is
required to read — accumulation without synthesis. With it, "the
apparatus gets smarter over time" is mechanism, not aspiration.

---

## 5. Orchestration, tools, and sandboxing

### 5.1 The harness stack

Pi (Mario Zechner's open-source minimal coding-agent harness, MIT, at
`github.com/badlogic/pi-mono`) is the underlying agent loop. OpenClaw
(Peter Steinberger, January 2026) is built on Pi and provides the
multi-agent orchestration layer (nested sub-agents, isolated tool
permissions per agent, configurable concurrency). NemoClaw (NVIDIA, GTC
March 16 2026, **alpha**) wraps OpenClaw with the OpenShell sandbox,
policy-based egress control, and Spark-aware model routing.

The apparatus's agents run on this stack pointed at the **local Gemma 4
endpoint** — never at any Claude subscription. This local-pointing is what
keeps the Anthropic policy changes from touching the apparatus runtime.

**Compute budgeting (Phase 2).** The orchestrator carries a
per-hypothesis GPU-time budget, deducted as workers run, with early-stop
when the budget is exceeded. This is the project's analog of the
co-scientist's Supervisor (cf. Paper, contribution 1: "asynchronous task
execution framework for flexible compute scaling"). The budget is also
the input to the cost-aware reward function on the keep/discard bandit
(see §6 step 3 and D-010's "Reversibility" entry). Phase 1's
orchestrator has only a memory budget (§7), not a compute budget; Phase
2 adds the time dimension.

**Critic / red-team agent (Phase 2).** The orchestrator dispatches a
critic prompt against each generated hypothesis before any experiment
runs (see §6 step 2). The critic is the same Gemma 4 endpoint with a
red-team system prompt; no second model is required (consistent with
D-012). Implementation is in `workers/critic.py` (Phase 2).

**Meta-review synthesis worker (Phase 2).** A worker that reads the
last N loop-memory entries and emits 3–5 conditioning bullets for the
generator's next prompt (see §6 step 1). Implementation in
`workers/meta_review.py` (Phase 2).

### 5.2 NemoClaw fallback discipline

NemoClaw is alpha and has documented operational footguns: direct
`openshell self-update`, `npm update -g openshell`, and
`openshell sandbox create` break NemoClaw's state management and require
`nemoclaw onboard` to recover. The Week 1 plan accordingly caps NemoClaw
onboarding at 90 minutes on Day 1 and reserves a plain-Docker fallback path
(security-hardened: `seccomp`, `no-new-privileges`, `cap-drop=ALL`) so that
NemoClaw failure does not block apparatus build. See `DECISIONS.md`
"NemoClaw alpha discipline" and "NemoClaw plain-Docker fallback."

### 5.3 The orchestrator's job

The Gemma 4 orchestrator does three things:

1. **Spawn workers** in OpenClaw sub-agents per task type — game
   simulations, literature synthesis, autoresearch experiments, robustness
   sweeps.
2. **Synthesize results** across workers and across knowledge-base layers
   into hypotheses, experiment designs, and novelty assessments.
3. **Log everything** through the wrapper introduced on Day 2 — every
   prompt, every completion, every seed, every model version. Every model
   call is a research observation.

### 5.4 The tool layer

Three tools, each bounded.

**Autoresearch.** Karpathy's canonical
`github.com/karpathy/autoresearch` — one Python file (`train.py`), one
metric, one GPU, 5-minute experiments, bandit keep/discard. Invoked by the
orchestrator when a hypothesis requires training or tuning a model. ~12
experiments per hour, ~100 overnight. Compatible with concurrent
orchestrator inference because training and inference naturally alternate
rather than overlap. Estimated 10–20 % of loop cycles use it; most don't.
Deferred Week-2+ tool; Week 1 only needs the directory present. Note:
NOT `matt-langston/autoresearch`, which is a fork tuned for dual-Spark
bundles and ships configuration assumptions that mismatch a single-Spark
setup. See `DECISIONS.md` "Autoresearch fork correction."

**ML-Intern (literature pipeline).** Built on HuggingFace's smolagents.
Reads arXiv papers, walks citation graphs, queries Semantic Scholar,
embeds into ChromaDB. The reasoning agent uses the Claude API in Phase 1
(~$5–20/month under the old subscription model; with the June 15 policy
change this draws from the Max-20x $200 Agent SDK credit at API list
rates, so the effective budget shrinks meaningfully). Migrate to a local
model in Phase 2+ once local reasoning quality is validated against the
API on the same inputs.

**Robustness battery.** Not a separate tool — a step in the loop
implemented as a scripted sweep. The orchestrator generates N variations
of an experiment configuration (prompt, seed, model version) and runs
them in parallel or sequentially. Results are logged as a sensitivity
matrix alongside the finding. Systematic robustness data is itself
publishable; the program treats it as a first-class output, not as a
validation step.

---

### 5.5 Multi-agent coordination

As of the Week 2 deliverable, the apparatus supports more than the four
named tracks (A/B/C/D) launching simultaneously. The orchestrator may
dispatch additional Claude Code sessions on demand via
`agent_wrapper/dispatch_coding_agent.py` (Day-39 deliverable). Each
dispatched session:

- Runs in its own git worktree (extending the existing `claude
  --worktree` pattern).
- Receives a scoped prompt assembled from
  [`agent/prompts/dispatched_task.md`](agent/prompts/dispatched_task.md)
  plus a task spec describing the target zone, allowed paths, and
  success criteria.
- Obeys the **claim/lock protocol** documented in
  [`agent/collision_protocol.md`](agent/collision_protocol.md): scan
  `run_state/claims.jsonl` for non-expired claims on the target paths;
  if clean, append a claim with 2-hour expiry; release on commit.
- May write only to **dispatchable** zones in
  [`agent/ownership.yaml`](agent/ownership.yaml). Track A's primary
  zones (`orchestrator`, `state-file`, `bench-and-logs`, `chroma-store`)
  are reserved.

The concurrency cap rises with phase boundary, governed by the same
alignment evidence as the autonomy-tier unlock (see
[`agent/autonomy.md`](agent/autonomy.md) §4): Week-1 baseline = 4
concurrent (human launches each); Week-2 unlock = orchestrator
dispatches 1/day; Weeks-3-4 unlock = up to 3 concurrent dispatches;
Phase-2 entry = autonomous dispatches with weekly human attestation.
The Phase-2 aspirational target is ~80% of new code shipped via
dispatched agents.

The dispatch pattern does NOT introduce autonomy beyond what
`agent/autonomy.md` already permits — a dispatched agent inherits its
task's tier (`autonomous`, `soft_gate`, or `hard_gate`) and its
SLA-and-attestation behavior. The dispatcher merely launches; Track A
still merges, after validation.

### 5.6 Phase 2 architecture deltas (cross-reference summary)

Phase 1's intelligence loop (§6) is eight steps with three Phase-2
additions explicitly marked. The full set of Phase-2 deltas spread
across this document:

| Phase 2 element | Location | Becomes operational |
|---|---|---|
| Meta-review synthesis worker | §5.1, §6 step 1 (Phase-2 addition) | Day 40 (W2-02) |
| Critic / red-team agent | §5.1, §6 step 3 (Phase-2 addition) | Day 39 (W2-01) |
| Experiment-outcome feedback edge to loop memory | §6 step 8 (Phase-2 addition) | Day 80 milestone (full Phase-2 loop) |
| Active vs passive read from Layer 3 | §4.4 | Day 40+ (depends on meta-review) |
| Per-hypothesis GPU-time budget | §5.1 (compute budgeting) | Phase 2 milestone |
| Polymarket live trading | §3.3 (gated on CFTC compliance) | Phase 3 entry (Day ~270) |
| Second model (Qwen 3.6) | §2.2 (manual swap, NOT routing) | Day 72 milestone |
| Dispatched coding agents (§5.5) | §5.5 above | Day 39 plumbing; Phase-2+ scale |

For the executable sequencing of these deltas, see
[`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md).

---

## 6. The intelligence loop

The loop runs steps 1–7 autonomously on the DGX Spark and gates on step 8,
which requires human judgment. The autonomy boundary moves up over time as
the apparatus's judgment on specific domains is validated through Step 8
feedback. See `docs/diagrams/intelligence_loop_v5.svg` for the current
visual; the v4 diagram remains in `docs/diagrams/` as the historical
record (per the versioning convention).

The loop has the *eight original steps* — the structural commitment of
the research program. Three additional pieces of machinery surround them,
each labeled with phase and rationale so that no reader mistakes Phase 2
plans for Phase 1 implementation:

- A **Meta-review synthesis** step that runs between Step 1 and Step 2,
  distilling loop memory into conditioning text for the generator. New
  in Phase 2; not present in Phase 1.
- A **Critic / red-team** step that runs between Step 2 and Step 3,
  attempting to falsify the generated hypothesis before spending
  experiment budget on it. New in Phase 2; not present in Phase 1.
- An **experiment → generator feedback edge**, returning the experiment
  outcome (not just the human's novelty assessment) into the knowledge
  base and the next generation cycle, gated by Step 8. New in Phase 2;
  not present in Phase 1.

### The steps

1. **Literature scan.** Query all three knowledge-base layers. Ingest new
   arXiv papers. Surface relevant prior work for the current research
   direction.

   **(Phase 2)** *Meta-review synthesis.* Between scan and hypothesis
   generation, a synthesis worker reads recent loop-memory entries (last N
   journal entries, with N tunable) and distills 3–5 conditioning bullets —
   *what kept winning*, *what kept losing*, *what surprised the human* —
   into the generator's prompt. This is the "active" reading of Layer 3
   that the passive ChromaDB collection alone does not provide. Without
   this, the generator reads loop memory only as nearest-neighbor
   retrieval, missing cross-cutting patterns.

2. **Generate hypothesis.** The orchestrator synthesizes literature and
   accumulated data into a research question or trading thesis. Domain
   knowledge in the knowledge base constrains the hypothesis space — the
   agent should not propose experiments that test things already known.

   **(Phase 2)** *Critic / red-team review.* Before dispatching the
   experiment, a critic prompt attempts to falsify the hypothesis: what's
   the strongest counter-argument? what known result does this contradict?
   is the proposed experiment actually a test of the hypothesis? The
   critic is implemented as a structured prompt pattern on the same model
   (consistent with D-012's single-model Phase 1 stance), not as a second
   model. The critic's output is logged and, if the critic's confidence
   in the falsification exceeds a threshold, the hypothesis is sent back
   to Step 2 with the critic's reasoning appended. Bounded retries (≤ 2)
   per generation cycle to prevent infinite loops.

3. **Run experiment in one tier.** Design and execute the experiment in
   the synthetic, semi-synthetic, or applied tier. If model training is
   needed, invoke autoresearch as a bounded tool. Most experiments are
   game simulations (seconds to minutes) or research synthesis (inference
   only), not training runs.

   **(Phase 2)** *Per-hypothesis compute budget.* The orchestrator
   maintains a GPU-time budget per hypothesis, deducted as the experiment
   runs. Early-stop if exceeded. The budget allocator is the project's
   analog of the co-scientist's Supervisor (cf. Paper, contribution 1).
   The keep/discard bandit's reward function (D-010) normalizes by compute
   consumed — *skill per GPU-hour*, not raw skill.

4. **Robustness battery.** Vary prompt, seed, and model version. Does the
   finding hold?

   **Methodological note.** The robustness battery is *falsification* —
   does *this* hypothesis survive perturbation. It is not *exploration*
   (which hypothesis among many ranks highest). Multi-candidate
   exploration with bandit selection is a separate Phase 2 layer over
   Step 2 (generation), and the bandit acts on already-cleared hypotheses
   (post-Step 8) rather than at this step. This distinction matters
   because the co-scientist's tournament conflates the two.

5. **Cross-tier replication.** Test whether the finding generalizes to
   other tier(s). A finding from the synthetic tier gets tested in
   semi-synthetic. A mechanism-design result gets tested against
   Polymarket dynamics (in Phase 2+; design-only in Phase 1).
   Tier-specific failure is diagnostic signal, not a discard.

6. **Novelty evaluation.** Check all three knowledge-base layers. Surface
   the 5 most similar known results. Classify: novel / rediscovery /
   nonsense / unclear. The hardest step and explicitly named as its own
   sub-research-problem. Automated check surfaces candidates; human makes
   the final call in Step 8.

   **Two requirements on the automated novelty checker:**

   - **(Phase 1 — minimum)** The retrieval pass is anchored to ChromaDB
     BGE-M3 similarity, *plus* a logged human-sample rate (a fixed
     fraction of automated novelty calls get reviewed by the human even
     when the automated call is "novel" — sample rate logged per
     assessment).

   - **(Phase 2)** When a second model lands (D-006: Qwen 3.6 in
     Week 2–3), the *novelty scorer* and the *generator* should be
     different models. Same-model scoring is structurally the
     co-scientist's Elo circularity in miniature (the model surfaces
     similar results from its own embedding/output space).

   - **(Phase 2)** Alongside semantic retrieval, run a *structured-claim
     search*: extract from the candidate finding the claim of form
     "X about Y under conditions Z" and run a structured query for any
     literature that asserts X about Y under Z — even when surface
     wording differs. This addresses the foundational-game-theory blind
     spot: a finding that restates Schelling's focal-point argument in
     different prose may miss BGE-M3's nearest-neighbor cutoff.

7. **Log to research journal.** Record in the structured format: claim,
   prior for novelty, literature search results, post-search assessment,
   what would change the assessment. Every non-trivial loop output gets
   this treatment.

   **Reproducibility requirement (Phase 1, additive).** Every generator
   call's prompt logs a `retrieval_context` field — a list of
   `{doc_id, content_hash, chunk_offset}` for each retrieved chunk that
   entered the prompt. This is the difference between "every model call
   is a research observation" being a slogan and being load-bearing —
   retrieval drifts as the corpus grows, and without pinning the
   retrieved content the generator's input cannot be reconstructed.
   Schema work scheduled as Day 3.5 (`day3_5_block2_retrieval_context_field`).

8. **Human evaluation.** Researcher validates the novelty assessment,
   approves or rejects trades (applied tier), updates the novelty
   evaluation rubric, publishes to the public research journal.
   Assessments feed back into Layer 3 of the knowledge base — closing the
   learning loop.

   **(Phase 2)** *Experiment-outcome feedback edge.* In addition to the
   human's novelty assessment (Phase 1, already in design), the experiment
   outcome itself (cooperation rates, robustness battery matrix,
   cross-tier replication result) is written into an `experiment_outcome`
   entry in Layer 3. The next generation cycle reads this entry via the
   Meta-review synthesis worker. The edge is **gated by Step 8** — outcomes
   only enter loop memory after the human clears them; this preserves
   graduated autonomy.

### Monthly red flags

The program names four diagnostic checks that fire monthly. These are not
loop steps; they are a periodic self-audit.
- Reading without doing? → build
- Doing without thinking? → read
- Am I the bottleneck on evaluating loop outputs? → that's the point — is
  that skill improving?
- Is the loop surfacing things I genuinely didn't know? If no for 30+
  days, something is wrong with the hypothesis generator or experiment
  design.

---

## 6.5 Degradation metrics

The intelligence loop's structural form (generate → experiment → log) is
similar enough to the co-scientist's that the same failure modes can
creep in if not measured. The metrics in this section are designed to
*catch* drift toward those failure modes early; they are not gates, and
Phase 1 only needs to *log* them. Phase 2 sets thresholds once a baseline
is established.

### 6.5.1 Hypotheses-to-experiments ratio

Track the count of hypotheses generated per experiment actually run to
completion (through Step 5 cross-tier replication). The natural drift in
any system with cheap generation and expensive experimentation is for
this ratio to rise. The co-scientist's tournament *is* the limit case:
many hypotheses, no experiments. This project's design pushes the ratio
toward 1:1 via the robustness battery and cross-tier replication, both
of which are themselves expensive. Logging the ratio is essentially free —
counters on existing JSONL events. Threshold-setting is deferred to
Phase 2 (need a baseline first).

### 6.5.2 Model-degradation canary

A fixed prompt with a fixed seed, run every N hours against the live
orchestrator, scored against a stored baseline output. Catches silent
model drift — prompt context too long, retrieval returning irrelevant
results, temperature drift, MoE backend silently flipped. The Day 1
silent-failure-mode safeguards (MARLIN backend check, NvFp4 backend
startup log) catch the gross cases at startup; the canary catches the
slow cases at runtime. Cheap. Phase 2.

### 6.5.3 Hypothesis-input provenance audit

Each generator call records its `retrieval_context` (per §6 step 7
above). The audit is a periodic check that for any logged hypothesis,
the retrieval context can be re-fetched from ChromaDB and verifies
against the stored content hashes. If a hash mismatches, the corpus has
drifted under a prior hypothesis's feet, and any "rediscovery" claim
against that hypothesis is suspect. Phase 2.

### 6.5.4 Researcher calibration log

Pairs the human's pre-experiment expected range (already a Day 7 artifact
for the PD experiment per `plan.yaml` `day7_block2_run_experiment`) with
the post-experiment observed value. Over time, per-person calibration is
itself research data — if the researcher's calibration improves, the
apparatus is teaching the human; if it stays flat, the human is the
bottleneck on what the loop can surface. Implementation: a
`calibration_entry` event in the run-log JSONL. Schema work scheduled as
Day 3.5 (`day3_5_block2_events_schema`).

---

## 7. Compute and cost budget

### Memory allocation (peak concurrent)

| Component | Memory | Notes |
|---|---|---|
| Gemma 4 26B-A4B MoE (orchestrator) | ~17 GB | NVFP4, always loaded during operation |
| Autoresearch training (when active) | ~30–50 GB | Only during experiment runs |
| ChromaDB + 3-layer knowledge base | ~3–5 GB | All three layers |
| NemoClaw + OpenClaw runtime | ~3–5 GB | Sandbox overhead |
| Data pipeline + feeds | ~1–2 GB | WebSocket, APIs |
| KV cache (vLLM) | ~80 GB available | At 16 GB loaded model, ~80 GB free |
| **Peak total** | **~60–90 GB** | Well within 128 GB |

### Cost budget (Year 1)

| Item | Cost | Notes |
|---|---|---|
| DGX Spark | ~$4,000–4,700 | One-time |
| Electricity (~240 W continuous) | ~$25/month | Running 24/7 |
| Claude API (ML-Intern reasoning) | up to ~$200/month from June 15, 2026 | Was ~$5–20/month under old subscription pool; new Max 20x credit is metered at API list and does not roll over |
| Semantic Scholar API | Free | 200 M+ papers |
| Polymarket trading capital | $500–$5,000 | Start small, scale with confidence; Phase 2+ |
| News / data APIs | $0–100/month | Depends on sources |
| **Year 1 total** | **~$5,500–10,500** | Hardware-dominated |

---

## 8. What the apparatus deliberately does NOT do

Carried forward from Research Program v2 and `research_apparatus_technical_plan_v1.md`:

- **Recursive self-improvement.** Out of scope. The apparatus tests a
  structurally different hypothesis.
- **Frontier-lab automation.** Out of scope. The apparatus is a single
  researcher's workflow amplifier.
- **Theorem proving.** Out of scope.
- **Sakana-style auto-paper generation.** Excluded; see `DECISIONS.md`.
- **Google SCORE tree search.** Excluded in Phase 1; possible Phase 2+
  upgrade if the bandit keep/discard proves limiting.
- **Dual-model routing layer.** Excluded as premature optimization.
- **Full autonomy on day one.** Excluded by the graduated-autonomy
  architecture.
- **Same-model novelty grading in Phase 2+.** Once a second model lands
  (Week 2–3 per D-006), the novelty *scorer* must be a different model
  from the *generator*. Phase 1 mitigates the single-model configuration
  with logged human sampling on automated novelty calls (see §6 step 6).
  This is the project's response to the co-scientist's Elo circularity
  (the same model that *generates* also *ranks*, producing a
  self-confirming improvement curve).
- **Auto-publish of experiment outcomes back into the generator without
  the human gate.** Phase 2 adds an experiment → generator feedback edge
  (§6 step 8), but it is gated by Step 8 — experiment outcomes enter
  loop memory *after* the human has cleared them. The edge is for the
  loop to *learn from* outcomes, not to *react to* them autonomously.

---

## 9. First-boot verification checklist

After any rebuild or system restore, before serving inference, verify:

1. `nvcc --version` reports release 13.0. `nvidia-smi | head -3` shows
   CUDA Version 13.0 in the driver line — NOT 13.2.
2. `apt-mark showhold` lists the eight `cuda-*-13-0` packages.
3. `unattended-upgrades` is disabled.
4. Root crontab contains the 30-minute `drop_caches` entry.
5. `docker info` works; if `/etc/docker/daemon.json` is present, it uses
   `default-cgroupns-mode: host` (not `cgroupns: host`).
6. `docker images` shows `vllm/vllm-openai:v0.21.0` AND the digest
   matches the one pinned in `run_state/`.
7. `ls /mnt/models/gemma-4-26b-a4b-nvfp4` shows the NVFP4 weights.
8. `vllm/vllm-openai:v0.21.0 --version` reports 0.21.0.
9. First serve: startup log contains
   `Using NvFp4LinearBackend.FLASHINFER_CUTLASS for NVFP4 GEMM` AND
   `Using 'MARLIN' NvFp4 MoE backend`. If MoE shows `CUTLASS_FP4`, STOP.
10. Single-stream tok/s ≥ 40 (calibration target: ~52, independent
    confirmation).

If any of 1–10 fails, do not proceed to wrapper, knowledge base, or
experiment work. Fix first.
