# Project Context — a_bgt_rsi

> **What this document is.** The single canonical orientation document for the
> `a_bgt_rsi` repository. A future researcher or Claude instance opening this
> repo cold should read this first, then `ARCHITECTURE.md`, then `DECISIONS.md`,
> then `plan.yaml`. Source planning documents (`docs/sources/research_program_v2.pdf`,
> `docs/sources/week1_days_31-37_plan.md`, `docs/sources/research_apparatus_technical_plan_v1.md`)
> win where this summary conflicts with them.

---

## 1. Project purpose

**Researcher.** Derrick Cross (GitHub `decross1`, ORCID on file, business email
`derrick@derrickcross.com`, operating as a sole proprietorship under his legal
name — no DBA).

**Central question.** Can a well-designed at-home research loop, run by an
independent researcher with modest hardware, produce findings at the
productive edge of a research field — not via recursive self-improvement of
models, but by amplifying a single human's ability to explore, evaluate, and
contribute?

**The apparatus is the contribution.** The claim under test is whether the
research loop itself — built, operated, and evaluated by one person on a DGX
Spark with open models — produces findings a competent domain researcher would
endorse. The findings populate the work with content; the apparatus is the
actual research object.

**Primary field of application.** Game theory, behavioral game theory, and
learning in games — chosen because LLM agents in game-theoretic settings are
underexplored, have clean experimental-design traditions, and let the loop
operate across a synthetic-to-applied spectrum.

**Sandbox spectrum — three tiers, all in use.**
- **Synthetic.** Classical games with known equilibria (repeated PD, public
  goods, stag hunt, Cournot, auctions). Loop's job: rediscover or characterize
  what's known. Success cleanly measurable.
- **Semi-synthetic.** Multi-agent LLM societies in designed scenarios; no
  ground truth but clear structure. Mechanism-design ladder lives here (see
  `ARCHITECTURE.md` §3).
- **Applied.** Polymarket primarily; possibly other prediction markets or
  open-source-contribution environments over time. Design-only in Phase 1;
  live deployment is Phase 3.

**Program arc — 2 to 5 years; Phase 1 is the 90-day alignment phase.**

| Phase | Duration | Milestone |
|---|---|---|
| 1 — Alignment | 90 days | Foundations laid, apparatus v0 running, first synthetic-tier experiments, public preprint |
| 2 — Loop v1 | months 4–9 | Autoresearch loop across synthetic + semi-synthetic tiers; first real findings; 1–2 workshop papers |
| 3 — Applied deployment | months 10–18 | Polymarket live; multi-tier findings; conference submission |
| 4 — Meta-scientific synthesis | months 19–36 | Main paper / thesis-equivalent artifact |
| 5 — Extension | months 37–60 | Second program or deepening |

---

## 2. Architecture at a glance

Full detail in `ARCHITECTURE.md`. Canonical diagrams in `docs/diagrams/`.
One-paragraph summary:

A self-hosted research loop running on a single NVIDIA DGX Spark. The
orchestrator (Gemma 4 26B-A4B MoE in NVFP4, served by vLLM on
`localhost:8000`) runs inside a NemoClaw/OpenShell sandbox (with a
plain-Docker fallback). The orchestrator dispatches experiments across the
three sandbox tiers via OpenClaw multi-agent orchestration on top of the Pi
harness. ChromaDB with BGE-M3 embeddings holds three knowledge layers — a
foundational corpus (game-theory textbooks), live literature (arXiv
cs.MA/cs.GT/econ.TH ingested nightly via Semantic Scholar), and loop memory
(human assessments fed back). Tools include autoresearch (bounded, bandit
keep/discard), ML-Intern (literature pipeline), and a robustness battery
(prompt/seed/model variation). The intelligence loop is eight steps;
steps 1–7 are autonomous, step 8 is human evaluation. The autonomy boundary
moves up over time as the apparatus's judgment on specific domains is
validated.

---

## 3. Key principles

- **Graduated autonomy.** The 26B scale has real capability limits the system
  design must respect. Full autonomy is not a day-one goal. Day 7's experiment
  produces a result that REQUIRES human review before publication.
- **The apparatus is the contribution**, not the findings.
- **Robustness as a first-class concern.** LLM agent behavior is prompt-,
  seed-, and model-version-sensitive in ways classical experimental economics
  is not. Every finding gets a robustness battery. Systematic robustness data
  is itself potentially publishable.
- **Reproducibility is load-bearing.** Every model call is a research
  observation. All data, code, prompts, seeds, model versions, hardware specs
  recorded. Determinism (T=0, and T=1 with fixed seed) is verified explicitly.
- **Literature search is part of the finding, not after it.** Before treating
  a loop output as novel, search the literature corpus. This closes the gap
  that sinks naive auto-science systems (they rediscover known results).
- **Brier Score / Brier Skill Score against market price** are the correct
  optimization targets for the prediction-market work (Phase 2+), not raw
  accuracy.
- **Honest technical assessment over validation.** Accurate evaluation of
  what works in practice vs. what sounds plausible — not encouragement.
- **Revise aggressively.** A plan that survives Phase 1 unchanged was not
  honest about what would be learned.

---

## 4. Phase 1 / Week 1 plan — days 31 to 37 of the program

Week 1 = "apparatus v0." By end of Day 7, the apparatus can run ONE
synthetic-tier experiment (repeated Prisoner's Dilemma vs. fixed strategies)
that requires human review before publication.

**Daily rhythm — preserved verbatim from the program.**
- **Block 1 — Foundations.** 90 min, NO AI, pen and paper. Game-theory
  reading plus problem sets. Human-only and inviolate.
- **Block 2 — Build.** 2 hr, agent-executable. Apparatus work.
- **Block 3 — Read + write.** 60 min. One paper or chapter, then a 200–500
  word public journal post.
- **Ambient — listening.** 1 hr, passive.
- 30-min slack between Block 2 and Block 3.

**Day ladder.**

| Day | Deliverable |
|---|---|
| 1 | Hardware online, vLLM serving Gemma 4, tokens/sec recorded |
| 2 | Python wrapper around vLLM; every call writes schema-valid JSONL; determinism verified |
| 3 | ChromaDB + BGE-M3; Osborne & Rubinstein textbook ingested; needle-in-haystack retrieval benchmark |
| 4 | First tool call (function calling on a mock tool); robustness rate measured |
| 5 | arXiv pipeline into ChromaDB (cs.MA/cs.GT/econ.TH); ≥50 papers ingested first run |
| 6 | OpenClaw orchestrator + first worker; full round-trip logged |
| 7 | First synthetic-tier experiment (repeated PD vs TFT, grim trigger, all-C, all-D, mirror-LLM); HUMAN-REVIEW GATE before publication |

The authoritative machine-readable version of this is `plan.yaml` (or
equivalently `agent_plan_week1.md` in `docs/sources/` — same content). 83
tasks: 32 human-only, 28 agent-executable, 12 agent-assisted, 11
human-assisted. 12 hard checkpoints. Days 1, 5, 6 carry try-then-fallback
branches. The operating contract for the executing agent is in `CLAUDE.md`.

**Five validation-pass adjustments baked into Week 1.** Each is logged in
`DECISIONS.md` with the rationale.
1. BGE-M3 as embedding model (not ChromaDB default `all-MiniLM-L6-v2`).
2. Defer Qwen 3.6 to Week 2–3 (avoid configuration matrix).
3. OpenSpiel + Game Reasoning Arena for the synthetic tier (not a custom
   env; saves 1–2 weeks).
4. Pin CUDA 13.0, disable auto-update (CUDA 13.2 produces gibberish on
   low-bit quantized models).
5. NemoClaw alpha discipline — official playbook, plain-Docker fallback
   ready.

---

## 5. Critical operational facts

### Version pins (inviolate)
- **vLLM image:** `vllm/vllm-openai:gemma4-cu130` — NOT `:gemma4` (dev,
  crashes on FP4 GEMM). Tag-naming does NOT imply one is a superset of the
  other; capture the image digest at first boot and pin the digest, not just
  the tag — the tag is a moving target.
- **vLLM version:** ≥ 0.19 (April 2026). The 0.19 release shipped the SM121
  NVFP4 fixes that had been broken since March 2026.
- **CUDA:** 13.0 — NOT 13.2 (gibberish on low-bit quants).
- **Embedding:** BGE-M3 — NOT all-MiniLM-L6-v2.
- **vLLM MoE backend:** `--moe-backend marlin`; startup log MUST show
  `Using 'MARLIN' NvFp4 MoE backend`. If it shows `CUTLASS_FP4`, the flag did
  not take effect — STOP (silent failure: model "works" but does not reason).
- **Weights path:** `/mnt/models/gemma-4-26b-a4b-nvfp4` (NVFP4, not BF16).
- **OpenShell cluster image:** `ghcr.io/nvidia/openshell/cluster:0.0.13`.

### Repository URLs (corrected)
The source planning docs were imprecise in places; these are correct.

| Component | URL |
|---|---|
| Gemma 4 weights | HuggingFace `nvidia/Gemma-4-26B-A4B-NVFP4` (NVIDIA's official NVFP4 quantization, attention in BF16 by design) |
| BGE-M3 | HuggingFace `BAAI/bge-m3` (MIT, ungated) |
| autoresearch | **Canonical upstream** `github.com/karpathy/autoresearch` — NOT `matt-langston/autoresearch`, which is a fork tuned for a *dual*-GB10 bundle and carries assumptions that mismatch a single-Spark setup. Deferred Week-2+ tool; Week 1 only needs the directory present. |
| Game Reasoning Arena | `github.com/SLAMPAI/game_reasoning_arena` (underscores, owner SLAMPAI). Day 7 experiment substrate. Supports local vLLM and has `prisoners_dilemma` / `matching_pennies` built in. |
| DGX Spark playbooks | `github.com/NVIDIA/dgx-spark-playbooks` |
| NemoClaw | `github.com/NVIDIA/NemoClaw` (alpha, "not production-ready") |
| Pi (underlying harness) | `github.com/badlogic/pi-mono` (MIT). Acquired by Earendil April 8, 2026; remains MIT-core. |

### Anthropic policy snapshot (mid-May 2026)
Affects tooling, not the apparatus runtime.

- **April 4, 2026.** Anthropic blocked subscription auth for third-party
  agents (Pi, OpenClaw, etc.).
- **May 13–14, 2026.** Reinstated, but third-party / programmatic usage now
  draws from a separate, fixed, non-rollover monthly "Agent SDK credit":
  Pro $20 / Max 5x $100 / **Max 20x $200** / Team $100 per seat / Enterprise
  $200 per seat, billed at standard API list rates. Effective
  **June 15, 2026** for Agent SDK / `claude -p` usage on subscription plans.
- **Why third-party agents cost more.** Anthropic's first-party tools
  (Claude Code, Cowork) maximize prompt-cache hit rates. Third-party Agent
  SDK clients bypass that, so every call processes context from scratch.
  Practical effect: a third-party agent will hit the credit cap faster than
  raw token math suggests.
- **Implication for this apparatus.** The apparatus's agents (Pi/OpenClaw)
  point at LOCAL Gemma 4, so Anthropic policy does not touch the apparatus
  runtime. Claude Code (first-party) on Max continues to draw from normal
  interactive limits — unaffected. After June 15, the Day 5 ML-Intern path
  (which uses the Claude API for reasoning) needs a budget review; the Max
  20x $200 credit, metered at API list, will not stretch as far as it would
  under the old subscription pool.

### Hard disciplines (do not erode)
- Block 1 (foundations) is human-only. No AI assistance, ever. This is the
  architecture, not a preference.
- Day 7 publication is human-gated. The agent runs the experiment and HALTS
  before any publication step.
- Validations are never silently coerced into passes.
- Hard checkpoints abort the day on failure rather than degrading forward.
- Fallbacks are explicit, logged, and time-capped.

### Hardware compatibility gap to be aware of
The DGX Spark's Blackwell GPU reports as **SM12x (compute capability 12.1)**,
not SM100 (datacenter Blackwell). Some performance kernels that advertise
"Blackwell support" only target SM100. FlashAttention 4, FlashMLA's SM100
backend, and tcgen05-using kernels won't run on the Spark. vLLM with NVFP4
works because vLLM 0.19+ has SM12x patches. See `ARCHITECTURE.md` §2.4 for
the full picture. Not a blocker for Week 1; flagged so it doesn't surprise
anyone later.

---

## 6. Current state (as of last update)

> Update this section as state changes. The date stamp on each block is the
> source of truth for staleness.

### Identity and accounts — all under `derrick@derrickcross.com` (May 2026)
- ORCID created.
- Domain `derrickcross.com` registered (Cloudflare Registrar); Cloudflare
  Email Routing live, `derrick@derrickcross.com` forwards to Gmail.
- GitHub `decross1` — profile polished, Profile README live, ORCID linked.
- GitHub PAT generated (repo + read:org scopes).
- HuggingFace account + read-scope token; Gemma 4 + BGE-M3 access confirmed.
- NVIDIA `build.nvidia.com` key generated.
- Semantic Scholar API key — **application submitted** (affiliation:
  Independent Researcher; URL: github.com/decross1; "Public Free/Nonprofit").
  Awaiting 24–48 hr approval; check `derrick@derrickcross.com` inbox.
- Claude Max subscription — opened under the business account; Claude Code
  hooked to the repo.

### Repository (May 2026)
- `a_bgt_rsi` created on GitHub `decross1`, **private**, README + Python
  `.gitignore` initialized. (The name `huchi-loop` was a placeholder used in
  some earlier planning conversations; the actual repo is `a_bgt_rsi`.)
- Cloned onto the Spark; git identity set (Derrick Cross /
  `derrick@derrickcross.com`); `.env` gitignored.
- **Deferred** to before the eventual public flip (Day 7+): dual-license
  files (`LICENSE` Apache-2.0, `LICENSE-CONTENT` CC-BY-4.0), `CITATION.cff`,
  polished README. Not needed while private.

### DGX Spark — Day 1 setup, in progress (May 2026)
- Spark online, wired interface `enP7s7`, IP `10.0.0.73` (DHCP — set a
  router reservation to MAC `4c:bb:47:2e:7e:eb`), hostname `spark-7eeb`,
  user `decross1`.
- Headless: passwordless SSH from the Windows desktop working. KVM decision:
  Spark stays headless, NOT on the CKL-622DP-4 KVM; access via SSH.
- CUDA verified 13.0 (`nvcc` reports release 13.0, V13.0.88). Eight
  `cuda-*-13-0` packages held via `apt-mark hold`. Two `*-config-common`
  packages drifted to 13.2.75-1 but are cosmetic (not in runtime path) —
  noted, not a blocker. **Recommended re-verification step before first vLLM
  serve:** run `nvcc --version && nvidia-smi | head -3` and confirm 13.0
  everywhere, including the libcuda / driver lines.
- `unattended-upgrades` disabled.
- Root cron set: `drop_caches` every 30 min (anti-slowdown mitigation).
- `/etc/docker/daemon.json` set to `{"default-cgroupns-mode": "host"}` —
  **RESOLVED 2026-05-18.** The first attempt used the invalid key
  `cgroupns` and dockerd refused to start; corrected to the valid
  `default-cgroupns-mode` key via `setup/day1_docker_config.sh`. Docker
  daemon is up; the 30-min `drop_caches` cron is in root's crontab.

### Immediate next steps (updated 2026-05-18 — Day 1 Block 2 in progress)
Pre-flight + Block 1 are complete; Block 2 tasks #3–#5 (hardware verify,
firmware/`nvidia-smi`, docker config) are done. The four pre-flight repos
are cloned and the three models are staged at `/mnt/models/`. Remaining
for Day 1:
1. Add `decross1` to the `docker` group (`sudo usermod -aG docker
   decross1`) and restart the Claude Code session so the executing agent
   gets un-sudoed docker access.
2. Stage `infra/vllm_patches/gemma4_mtp.py` from the head of vLLM
   PR #41745 (the MTP bugfix — see D-019).
3. Pull `vllm/vllm-openai:gemma4-cu130`; **capture the image digest**
   (D-017) and pin it in `run_state/`.
4. Launch vLLM with `--moe-backend marlin` plus the MTP
   `--speculative-config`; VERIFY the MARLIN and `method='mtp'` startup
   log lines.
5. Curl test; tokens/sec micro-bench. With MTP γ=4 the expected band is
   80–130 tok/s (calibration ~96); hard floor remains 40 (see D-019).
6. Day 1 hard checkpoint: vLLM serving + MARLIN confirmed + bench ≥ 40.

### Open scoping items
- General architecture re-scope: confirm v4 architecture and technical plan
  v1 are still sensible given releases since they were written.

_(MTP support — previously listed here — was resolved 2026-05-18; see
DECISIONS.md D-019.)_

---

## 7. How to work with this researcher

- Thinks in systems; prefers to ideate full architecture before
  implementation details.
- Strong preference for visual artifacts (SVG diagrams, architecture
  visualizations) during design discussions.
- Values honest technical assessment over validation — wants accurate
  evaluation, not encouragement.
- Engages in interactive, iterative scoping where the scope evolves through
  conversation.
- For Anthropic product facts, current releases, and anything time-sensitive:
  verify by search rather than relying on training data.

---

## 8. Where to look next

| If you want to know… | Read… |
|---|---|
| What the apparatus is, architecturally | `ARCHITECTURE.md` + `docs/diagrams/` |
| Why a decision was made the way it was | `DECISIONS.md` |
| What to execute on the Spark today | `plan.yaml` and the operating contract in `CLAUDE.md` |
| The intellectual program behind the apparatus | `docs/sources/research_program_v2.pdf` |
| The technical companion to the program | `docs/sources/research_apparatus_technical_plan_v1.md` |
| The expanded machine-readable week-1 plan | `docs/sources/agent_plan_week1.md` |
| The visualizations from design sessions | `docs/diagrams/architecture_v4.svg` and `docs/diagrams/intelligence_loop_v4.svg` |
