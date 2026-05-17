# a_bgt_rsi — Week 1 research apparatus

Phase 1 / Week 1 (Days 31–37) of the research program. The authoritative
plan is `plan.yaml`. The source human-readable plan is
`week1_days_31-37_plan.md` (not in this repo yet — bring it over if you
need to resolve a discrepancy; the source wins).

## Target environment

- NVIDIA DGX Spark (GB10, ARM64)
- CUDA **13.0** (NOT 13.2 — gibberish on low-bit quants)
- vLLM image `vllm/vllm-openai:gemma4-cu130` (NOT `:gemma4`)
- Gemma 4 26B-A4B-NVFP4 weights at `/mnt/models/gemma-4-26b-a4b-nvfp4`
- BGE-M3 weights at `/mnt/models/bge-m3`

Full version pins in `plan.yaml` "Pre-flight" + Appendix C.

## Quick start (on the Spark)

```bash
git clone git@github.com:decross1/a_bgt_rsi.git
cd a_bgt_rsi
cp .env.example .env  # fill in the 5 credentials
claude                # then ask it to begin day_1 per plan.yaml
```

Claude reads `CLAUDE.md` and `plan.yaml`, then resumes from
`run_state/week1.state.json`. Pre-flight checks run first; Block 1 of
day 1 is human-only — Claude prints the reading + problem set and halts.

## Layout

```
plan.yaml                  # authoritative machine-readable plan
CLAUDE.md                  # operating contract for Claude Code
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
