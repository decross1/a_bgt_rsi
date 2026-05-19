# a_bgt_rsi — Week 1 research apparatus

Phase 1 / Week 1 (Days 31–37) of the research program.

**New here? Start with `START_HERE.md`** — the single orientation
document — then `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `DECISIONS.md`,
and `plan.yaml`.

`plan.yaml` is the canonical machine-readable plan; the operating
contract for Claude Code is `CLAUDE.md`. The original source planning
documents (`week1_days_31-37_plan.md` and the others referenced under
`docs/sources/`) are **not yet committed** to the repo — until they
are, `plan.yaml` plus `CLAUDE.md` are the operative authority.

## Target environment

- NVIDIA DGX Spark (GB10, ARM64)
- CUDA **13.0** (NOT 13.2 — gibberish on low-bit quants)
- vLLM image `vllm/vllm-openai:v0.20.0` (NOT `:gemma4`)
- Gemma 4 26B-A4B-NVFP4 weights at `/mnt/models/gemma-4-26b-a4b-nvfp4`
- BGE-M3 weights at `/mnt/models/bge-m3`

Full version pins in `START_HERE.md` §4 and `plan.yaml` Appendix C.

## Documentation layout

Five documents define how Week 1 runs. They have different audiences;
know which one to read for which question.

| Document | Audience | Use it for |
| --- | --- | --- |
| `START_HERE.md` | Everyone | Orientation, current state, document map, version pins |
| `plan.yaml` | Claude Code (machine) | Canonical task definitions, validations, hard checkpoints, state schema |
| `HUMAN_PLAN.md` | The researcher | Daily blockers, Block 1 readings, manual touchpoints inside Block 2, human gates, end-of-day attestations |
| `AGENT_PLAN.md` | Researcher + Claude Code | Parallel-execution orchestration: which worktree runs which task on which day, per-track system prompts, merge protocol |
| `CLAUDE.md` | Claude Code (Track A) | Operating contract: inviolate rules, parallel-track rules, what's out of scope |

Day-by-day, the researcher reads `HUMAN_PLAN.md` for what's on their
plate and `AGENT_PLAN.md` for which terminals to open. Each Claude Code
session reads `CLAUDE.md` (Track A) or its per-track prompt (Tracks B
and C), then resumes from `run_state/week1.state.json`. `plan.yaml` is
canonical for task content; see `START_HERE.md` §3 for the full
document map and authority rules.

## Quick start (on the Spark)

```bash
git clone git@github.com:decross1/a_bgt_rsi.git
cd a_bgt_rsi
cp .env.example .env  # fill in the 5 credentials

# One-time parallel-execution setup (see AGENT_PLAN.md):
# .gitignore already ignores .claude/worktrees/; .worktreeinclude is
# committed and copies .env into new worktrees. Verify with:
claude --worktree smoke-test   # then `exit` inside the session

# Begin Day 1 (Track A only; Day 1 has no side tracks):
claude                # then ask it to begin day_1 per plan.yaml
```

Claude reads `START_HERE.md`, `CLAUDE.md`, and `plan.yaml`, then
resumes from `run_state/week1.state.json`. Pre-flight checks run first;
Block 1 of day 1 is human-only — Claude prints the reading + problem
set and halts. From Day 2 onward, open multiple terminals per
`AGENT_PLAN.md`'s per-day schedule (Track A in one, Tracks B and/or C
in others).

## Layout

```
START_HERE.md              # orientation + document map — read this first
PROJECT_CONTEXT.md         # full project background
ARCHITECTURE.md            # apparatus architecture walkthrough
DECISIONS.md               # architectural/operational decision log
plan.yaml                  # canonical machine-readable task plan
CLAUDE.md                  # operating contract for Claude Code
HUMAN_PLAN.md              # the researcher's daily blocker list
AGENT_PLAN.md              # parallel-execution orchestration plan
current_day.md             # active-day progress tracker
.env.example               # required credentials

run_state/                 # state file + run log (JSONL)
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
tools/                     # mock_payoffs, inspect_run CLI
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

1. Block 1 (foundations) is **human-only**. Claude prints, halts, does not assist.
2. Version pins in `plan.yaml` are inviolate.
3. Day 7 publication is human-gated.
4. Validations are never silently coerced into passes.
5. Hard checkpoints abort the day.
6. The state file is authoritative on resume.

Full restatement in `CLAUDE.md` and `plan.yaml` Appendix C.
