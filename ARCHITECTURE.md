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
`vllm/vllm-openai:v0.20.0`, vLLM version ≥ 0.19 (the April 2026 release
that shipped SM121 NVFP4 fixes broken since March). The `:gemma4` tag
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

## 6. The intelligence loop

Eight steps. Steps 1–7 run autonomously on the DGX Spark. Step 8 requires
human judgment. The autonomy boundary moves up over time as the
apparatus's judgment on specific domains is validated through Step 8
feedback. See `docs/diagrams/intelligence_loop_v4.svg` for the visual.

1. **Literature scan.** Query all three knowledge-base layers. Ingest new
   arXiv papers. Surface relevant prior work for the current research
   direction.
2. **Generate hypothesis.** The orchestrator synthesizes literature and
   accumulated data into a research question or trading thesis. Domain
   knowledge in the knowledge base constrains the hypothesis space — the
   agent should not propose experiments that test things already known.
3. **Run experiment in one tier.** Design and execute the experiment in
   the synthetic, semi-synthetic, or applied tier. If model training is
   needed, invoke autoresearch as a bounded tool. Most experiments are
   game simulations (seconds to minutes) or research synthesis (inference
   only), not training runs.
4. **Robustness battery.** Vary prompt, seed, and model version. Does the
   finding hold?
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
7. **Log to research journal.** Record in the structured format: claim,
   prior for novelty, literature search results, post-search assessment,
   what would change the assessment. Every non-trivial loop output gets
   this treatment.
8. **Human evaluation.** Researcher validates the novelty assessment,
   approves or rejects trades (applied tier), updates the novelty
   evaluation rubric, publishes to the public research journal.
   Assessments feed back into Layer 3 of the knowledge base — closing the
   learning loop.

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
6. `docker images` shows `vllm/vllm-openai:v0.20.0` AND the digest
   matches the one pinned in `run_state/`.
7. `ls /mnt/models/gemma-4-26b-a4b-nvfp4` shows the NVFP4 weights.
8. `vllm/vllm-openai:v0.20.0 --version` reports ≥ 0.19.
9. First serve: startup log contains
   `Using NvFp4LinearBackend.FLASHINFER_CUTLASS for NVFP4 GEMM` AND
   `Using 'MARLIN' NvFp4 MoE backend`. If MoE shows `CUTLASS_FP4`, STOP.
10. Single-stream tok/s ≥ 40 (calibration target: ~52, independent
    confirmation).

If any of 1–10 fails, do not proceed to wrapper, knowledge base, or
experiment work. Fix first.
