# a_bgt_rsi — Phase 1 research apparatus

Phase 1 (Days 1–90) of a multi-year research program. The repo
currently covers Week 1 (Days 31–37) in executable detail; the rest of
Phase 1 is mapped in [`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md).

**New here? Start with [`START_HERE.md`](START_HERE.md)** — the single
orientation document. From there, the doc map at
[`START_HERE.md`](START_HERE.md) §3 tells you which file to read for
which question.

`plan.yaml` is the canonical machine-readable plan. The operating
contract for Claude Code is [`CLAUDE.md`](CLAUDE.md). The agent
autonomy framework is [`agent/autonomy.md`](agent/autonomy.md). The
original source planning documents (`week1_days_31-37_plan.md` and the
others referenced under `docs/sources/`) are **not yet committed** to
the repo — until they are, `plan.yaml` plus `CLAUDE.md` are the
operative authority.

## Target environment

- NVIDIA DGX Spark (GB10, ARM64)
- CUDA **13.0** (NOT 13.2 — gibberish on low-bit quants)
- vLLM image `vllm/vllm-openai:v0.21.0` (NOT `:gemma4`)
- Gemma 4 26B-A4B-NVFP4 weights at `/mnt/models/gemma-4-26b-a4b-nvfp4`
- BGE-M3 weights at `/mnt/models/bge-m3`

Full canonical version-pin table in
[`ARCHITECTURE.md`](ARCHITECTURE.md) §2.

## Documentation layout

The docs are split by audience. Top-level files are shared (everyone
reads); `human/` is for the researcher; `agent/` is for Claude Code
sessions; `plan.yaml` is the machine-readable canonical plan.

| Where | Audience | Use it for |
| --- | --- | --- |
| [`START_HERE.md`](START_HERE.md) | Everyone | Orientation, current state, document map |
| [`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md) | Everyone | The 30/60/90-day arc + slip mechanism |
| [`GLOSSARY.md`](GLOSSARY.md) | Everyone | Stable terminology |
| `plan.yaml` | Claude Code (machine) | Canonical task definitions, validations, autonomy tiers |
| [`CLAUDE.md`](CLAUDE.md) | Claude Code (Track A) | Operating contract: inviolate rules, parallel-track rules |
| [`human/daily_plan.md`](human/daily_plan.md) | The researcher | Daily blockers, manual touchpoints, human gates |
| [`human/learning_track.md`](human/learning_track.md) | The researcher | Phase 1 reading + problem-set syllabus (parallel rail) |
| [`agent/autonomy.md`](agent/autonomy.md) | Claude Code | Three-tier autonomy framework + SLAs + alignment evidence |
| [`agent/orchestration.md`](agent/orchestration.md) | Researcher + Claude Code | Parallel-execution orchestration: which worktree, when, how to merge |
| [`agent/ownership.yaml`](agent/ownership.yaml) | Claude Code | Machine-readable file-ownership registry |
| [`agent/collision_protocol.md`](agent/collision_protocol.md) | Claude Code | Claim/lock protocol for concurrent agents |

Day-by-day, the researcher reads [`human/daily_plan.md`](human/daily_plan.md)
for what's on their plate and [`agent/orchestration.md`](agent/orchestration.md)
for which terminals to open. Each Claude Code session reads
[`CLAUDE.md`](CLAUDE.md) (Track A) or its per-track prompt
([`agent/prompts/`](agent/prompts/)) then resumes from
`run_state/week1.state.json`.

## Quick start (on the Spark)

```bash
git clone git@github.com:decross1/a_bgt_rsi.git
cd a_bgt_rsi
cp .env.example .env  # fill in the 5 credentials

# One-time parallel-execution setup (see agent/orchestration.md):
# .gitignore already ignores .claude/worktrees/; .worktreeinclude is
# committed and copies .env into new worktrees. Verify with:
claude --worktree smoke-test   # then `exit` inside the session

# Begin Day 1 (Track A only; Day 1 has no side tracks):
env -u MOCK_LLM claude    # then ask it to begin day_1 per plan.yaml
```

Claude reads [`CLAUDE.md`](CLAUDE.md), [`agent/autonomy.md`](agent/autonomy.md),
[`agent/ownership.yaml`](agent/ownership.yaml), and `plan.yaml`, then
resumes from `run_state/week1.state.json`. Pre-flight checks run
first; Block 1 of day 1 is human-only — Claude prints the reading +
problem set and halts. From Day 2 onward, open multiple terminals per
[`agent/orchestration.md`](agent/orchestration.md)'s per-day schedule.

## Layout

```
START_HERE.md              # orientation + document map — read this first
PHASE_1_ROADMAP.md         # 30/60/90-day plan + slip mechanism
GLOSSARY.md                # terminology reference
PROJECT_CONTEXT.md         # long-form background
ARCHITECTURE.md            # technical architecture walkthrough
DECISIONS.md               # decision log
plan.yaml                  # canonical machine-readable task plan
CLAUDE.md                  # operating contract for Claude Code
current_day.md             # active-day progress tracker
ui_plan.md                 # UI / observability layer plan
.env.example               # required credentials

human/                     # researcher-facing documentation
  daily_plan.md
  learning_track.md
  reading_list.md
  days_01_30_recap.md
  retrospectives/

agent/                     # agent-facing documentation
  autonomy.md
  orchestration.md
  ownership.yaml
  collision_protocol.md
  prompts/                 # per-track launch prompts

run_state/                 # state file + run log (JSONL); soft/hard-gate +
                           # claims append-only logs

agent_wrapper/             # thin wrapper around vLLM OpenAI client
schema/                    # JSON Schemas: call log, worker contract, tools
tests/                     # validation scripts referenced per-day
logs/                      # JSONL call/orchestrator/experiment logs
bench/                     # micro-benchmarks (tokens/sec, retrieval)
infra/                     # bookmarks, seccomp, docker daemon, cron
ingest/                    # textbook PDF → ChromaDB
pipeline/                  # arXiv scraper + embed-and-store
cron/                      # nightly arxiv pipeline
orchestrator/              # OpenClaw runner (+ multiprocessing fallback)
workers/                   # summarize_paper, etc.
tools/                     # mock_payoffs, inspect_run, gate_sla_check, claims_check
experiments/exp001_repeated_pd/   # day 7 experiment + results/plots/analysis
scripts/                   # bench, chroma init, semantic scholar test, lock writer
notes/                     # per-day debugging / decision notes
journal/                   # daily public-post index
setup/                     # per-day setup shell scripts
docs/diagrams/             # canonical SVG architecture diagrams
docs/sources/              # original source planning docs (not yet committed)

books/                     # gitignored — PDFs
clones/                    # gitignored — third-party repos
chroma_db/                 # gitignored — embeddings (manifest.json IS tracked)
```

## Rules (concise)

1. Block 1 (foundations) is **human-only** but **does not gate Block 2**
   in `plan.yaml` (decoupled per [`agent/autonomy.md`](agent/autonomy.md)
   §7). The human reads in parallel; the agent proceeds.
2. Version pins are inviolate — canonical table in
   [`ARCHITECTURE.md`](ARCHITECTURE.md) §2.
3. Day 7 publication is human-gated and never auto-clears.
4. Validations are never silently coerced into passes.
5. Hard-gates abort the day on failure; soft-gates flag and continue.
6. The state file is authoritative on resume.

Full restatement in [`CLAUDE.md`](CLAUDE.md). The autonomy framework
(`autonomous` / `soft_gate` / `hard_gate` tiers, SLAs, alignment
evidence) is in [`agent/autonomy.md`](agent/autonomy.md).
