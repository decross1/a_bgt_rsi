# a_bgt_rsi — self-hosted research apparatus

A self-hosted research apparatus on a single NVIDIA DGX Spark.
Amplifies one researcher's work in game theory, behavioral game
theory, and learning in games. The apparatus — not any particular
finding — is the research contribution.

The canonical specification is the system diagrams under
[`docs/diagrams/`](docs/diagrams/) (`architecture_v5.svg`,
`intelligence_loop_v5.svg`); their prose elaboration is
[`ARCHITECTURE.md`](ARCHITECTURE.md).

**New here? Start with [`START_HERE.md`](START_HERE.md)** — the single
orientation document.

## Target environment

- NVIDIA DGX Spark (GB10, ARM64)
- CUDA **13.0** (NOT 13.2 — gibberish on low-bit quants)
- vLLM image `vllm/vllm-openai:v0.21.0` (NOT `:gemma4`)
- Gemma 4 26B-A4B-NVFP4 weights at `/mnt/models/gemma-4-26b-a4b-nvfp4`
- BGE-M3 weights at `/mnt/models/bge-m3`

Full canonical version-pin table in
[`ARCHITECTURE.md`](ARCHITECTURE.md) §2.

## Documentation layout

| Where | Audience | Use it for |
| --- | --- | --- |
| [`START_HERE.md`](START_HERE.md) | Everyone | Orientation, current state, document map |
| [`LOOP_V0.md`](LOOP_V0.md) | Everyone | The active build slice |
| [`GLOSSARY.md`](GLOSSARY.md) | Everyone | Stable terminology |
| [`CLAUDE.md`](CLAUDE.md) | Claude Code | Operating contract for sessions |
| [`agent/prompts/main.md`](agent/prompts/main.md) | Claude Code | Primary-session prompt |
| [`agent/prompts/ui_session.md`](agent/prompts/ui_session.md) | Claude Code | Concurrent UI-session prompt |
| [`human/sessions/`](human/sessions/) | The researcher + agent | Per-session working notes (one file per day) |
| [`human/learning_track.md`](human/learning_track.md) | The researcher | Reading + problem-set rail |
| [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) | Everyone | Long-form program background |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Everyone | Technical architecture walkthrough |
| [`DECISIONS.md`](DECISIONS.md) | Everyone | Decision log |

A previous parallel-execution framework (Track A/B/C/D, autonomy tiers,
phase roadmap, day tracker, `plan.yaml`) was retired on 2026-05-26
(see [`DECISIONS.md`](DECISIONS.md) D-030). Those documents are
preserved under [`archive/`](archive/) for historical reference; they
are not active rules.

## Quick start

```bash
git clone git@github.com:decross1/a_bgt_rsi.git
cd a_bgt_rsi
cp .env.example .env  # fill in credentials

# Primary session (the one you'll use most of the time):
env -u MOCK_LLM claude

# Optional concurrent UI session (separate terminal):
env -u MOCK_LLM claude --worktree ui-session
```

The primary session reads [`CLAUDE.md`](CLAUDE.md) →
[`START_HERE.md`](START_HERE.md) → [`LOOP_V0.md`](LOOP_V0.md) → the
most recent `human/sessions/YYYY-MM-DD.md`. The UI session reads
[`agent/prompts/ui_session.md`](agent/prompts/ui_session.md) and
writes only to `ui/` + `ui_plan.md`.

## Layout

```
START_HERE.md              # orientation + document map — read this first
CLAUDE.md                  # operating contract for Claude Code
LOOP_V0.md                 # active build slice
GLOSSARY.md                # terminology reference
PROJECT_CONTEXT.md         # long-form background
ARCHITECTURE.md            # technical architecture walkthrough
DECISIONS.md               # decision log
ui_plan.md                 # UI / observability layer plan
.env.example               # required credentials

human/
  sessions/                # per-session working notes (active)
  learning_track.md        # reading + problem-set rail
  reading_list.md
  days_01_30_recap.md
  retrospectives/

agent/
  prompts/
    main.md                # primary-session prompt
    ui_session.md          # concurrent UI-session prompt

archive/                   # retired track/tier framework (reference only)

run_state/                 # state file + run log (JSONL)
agent_wrapper/             # thin wrapper around vLLM OpenAI client
orchestrator/              # OpenClaw runner (multiprocessing fallback)
workers/                   # summarize_paper, play_pd_match, …
pipeline/                  # arXiv scraper + embed-and-store
ingest/                    # textbook PDF → ChromaDB
schema/                    # JSON Schemas
tests/                     # validation scripts
logs/                      # JSONL call/orchestrator/experiment logs
bench/                     # micro-benchmarks
infra/                     # bookmarks, seccomp, docker daemon, cron
cron/                      # nightly arxiv pipeline
tools/                     # mock_payoffs, inspect_run, claims_check, …
scripts/                   # bench, chroma init, lock writer
experiments/exp001_repeated_pd/  # Day 7 experiment + results/plots/analysis
notes/research/            # research material
journal/                   # daily research-journal entries
setup/                     # per-day setup shell scripts
docs/diagrams/             # canonical SVG architecture diagrams
docs/sources/              # original source planning docs (not yet committed)
ui/                        # observability React/FastAPI stack

books/                     # gitignored — PDFs
clones/                    # gitignored — third-party repos
chroma_db/                 # gitignored — embeddings (manifest.json IS tracked)
```

## Inviolate rules (concise)

1. Block 1 (foundations) is **human-only**. The agent does not
   execute, assist, or summarize Block 1 problem sets.
2. Version pins are verbatim — canonical table in
   [`ARCHITECTURE.md`](ARCHITECTURE.md) §2.
3. Human gates are blocking — the agent halts and prints the gate
   notice; clears only on explicit human attestation.
4. Validations are never silently coerced into passes.
5. The state file is authoritative on resume.
6. Logging is mandatory: every executable task appends a row to
   `run_state/week1.run.jsonl`.
7. Fallbacks are explicit, logged, and time-capped.
8. Code-generation is bounded — resist abstraction.
9. The retrospective and research-journal prose are the human's.
10. `MOCK_LLM` discipline — strip the env var for real runs.

Full restatement in [`CLAUDE.md`](CLAUDE.md).
