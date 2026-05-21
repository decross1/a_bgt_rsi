# START HERE — a_bgt_rsi

> **Read this first.** This is the single orientation document for the
> repository. It tells you what the project is, where it stands right
> now, which document answers which question, and the handful of facts
> that must never drift. Everything else is one hop away from the
> document map below.

---

## 1. What this is

`a_bgt_rsi` is **Week 1 (Days 31–37) of Phase 1** of a multi-year
research program. The goal of Week 1 is **"apparatus v0"**: a
self-hosted research loop on a single NVIDIA DGX Spark that, by the end
of Day 7, can run **one synthetic-tier experiment** (repeated
Prisoner's Dilemma against fixed strategies) whose result requires
human review before publication.

The apparatus — not the findings — is the research contribution. Field
of application: game theory, behavioral game theory, learning in games.
Full background is in `PROJECT_CONTEXT.md`; the architecture is in
`ARCHITECTURE.md`.

**Day ladder.** Day 1 hardware + vLLM serving · Day 2 wrapper + JSONL
logging · Day 3 ChromaDB + textbook ingest · Day 4 first tool call ·
Day 5 arXiv pipeline · Day 6 orchestrator + first worker · Day 7
first PD experiment + retrospective.

---

## 2. Where the project stands

_As of 2026-05-21. The live tracker is `current_day.md`; the
authoritative state is `run_state/week1.state.json`._

- **Days 1–4 — complete.** Hardware + vLLM serving (Day 1), Python
  wrapper + JSONL logging (Day 2), ChromaDB + textbook ingest (Day 3),
  Day 3.5 schema amendments, first tool call / function calling
  (Day 4). Decode throughput was weight-bandwidth-bound at ~32 tok/s on
  the v0.20.0 image; resolved via MTP speculative decoding — re-pin to
  `vllm/vllm-openai:v0.21.0` (first release with Gemma 4 MTP, PR
  #41745). Single-stream decode 32 → 69 tok/s (D-022).
- **Day 5 — complete.** arXiv pipeline → ChromaDB. 138 papers
  (cs.MA / cs.GT / econ.TH, 7-day window) ingested into the
  `papers_recent` collection with BGE-M3 embeddings; sub-second
  retrieval. The pipeline source was switched from the Semantic Scholar
  API to the arXiv API (D-027 — S2 lags arXiv-ID indexing by weeks).
  ML-Intern was probed and fell back to a direct-API path within the
  planned 45-min cap. `cron/daily-arxiv.sh` exists but is not yet in
  crontab (Day 6 enables it).
- **Next: Day 6** — OpenClaw orchestrator + first worker.

---

## 3. Document map — which file answers which question

| If you need… | Read |
| --- | --- |
| Orientation, current state (this file) | `START_HERE.md` |
| The operating contract you (Claude Code) must obey | `CLAUDE.md` |
| The canonical task plan — tasks, validations, checkpoints | `plan.yaml` |
| What the human researcher does each day (Block 1, gates) | `HUMAN_PLAN.md` |
| Parallel-execution orchestration (the 3 worktree tracks) | `AGENT_PLAN.md` |
| Full project background and rationale | `PROJECT_CONTEXT.md` |
| How the apparatus is built, architecturally | `ARCHITECTURE.md` |
| Why a decision was made the way it was | `DECISIONS.md` (D-001…D-021) |
| What is being worked on right now | `current_day.md` |
| Execution state / run log | `run_state/week1.state.json`, `run_state/week1.run.jsonl` |
| The telemetry dashboard plan | `ui_plan.md` |

**Audiences differ.** `CLAUDE.md` and the per-track prompts in
`AGENT_PLAN.md` are read by Claude Code sessions. `HUMAN_PLAN.md` is
the researcher's. `plan.yaml` is machine-readable and parsed.
`PROJECT_CONTEXT.md` / `ARCHITECTURE.md` / `DECISIONS.md` are reference.

**Authority.** `plan.yaml` is the **canonical** plan: where any summary
document disagrees with it on task content, `plan.yaml` wins. The
original human-readable source documents (`week1_days_31-37_plan.md`,
`research_program_v2.pdf`, `research_apparatus_technical_plan_v1.md`)
are **not yet committed** to the repo — until they are, `plan.yaml`
plus `CLAUDE.md` are the operative authority. `DECISIONS.md` records
why; the most recent decision wins over an older one it supersedes.

---

## 4. Inviolate version pins

These are verbatim. If the environment does not match, the task
**fails** — it does not best-effort substitute. Full rationale in
`DECISIONS.md`; full list in `plan.yaml` Appendix C.

| Pin | Value | Note |
| --- | --- | --- |
| vLLM image | `vllm/vllm-openai:v0.21.0` | NOT `:gemma4`, `:gemma4-cu130`, or `:v0.20.0`. D-022: v0.21.0 is the first release with PR #41745 (Gemma 4 MTP) and runs MTP speculative decoding. Pin the image **digest**, not just the tag (D-017). |
| OpenShell cluster | `ghcr.io/nvidia/openshell/cluster:0.0.13` | |
| CUDA | `13.0` | NOT 13.2 — produces gibberish on low-bit quants. |
| Embedding model | BGE-M3 (`BAAI/bge-m3`) | NOT ChromaDB's default `all-MiniLM-L6-v2`. |
| vLLM MoE backend | `--moe-backend marlin` | Startup log MUST contain `Using 'MARLIN' NvFp4 MoE backend`. |
| Weights path | `/mnt/models/gemma-4-26b-a4b-nvfp4` | NVFP4, not BF16. |

> **Throughput note.** GB10 is SM12x with no native FP4 compute
> (D-018); vLLM uses the Marlin weight-only FP4 path. The plan's
> expected `FLASHINFER_CUTLASS for NVFP4 GEMM` startup line does not
> appear on this hardware — that is expected, not a failure (D-020).

---

## 5. Inviolate rules (the short version)

The full contract is `CLAUDE.md`; `plan.yaml` Appendix C restates it.
The rules that never bend:

1. **No Block 1.** Every Block 1 task is human-only. Print the reading
   and problem set, set a timer, and HALT. Do not execute, assist,
   summarize, derive, or solve.
2. **Version pins are verbatim** (§4).
3. **Human gates are blocking.** The Day 7 publication review gate is
   the most important — never auto-publish results.
4. **Validations are never silently coerced.** Each check is reported
   independently. "Below band but close" is a failure.
5. **State file is authoritative on resume.**
6. **Hard checkpoints abort the day.** The next day is gated on the
   prior day's success.
7. **Fallbacks are explicit, logged, and time-capped.**
8. **Logging is mandatory** — every agent-executable task appends to
   `run_state/week1.run.jsonl`.
9. **Code-generation is bounded** — the wrapper's budget is ~100 lines.
10. **The retrospective is the human's** — print questions, record
    answers, do not interpret.

---

## 6. How to start a session

Default to **Track A (Main)** unless a launch prompt told you
otherwise. Track A startup:

1. Read this file (`START_HERE.md`).
2. Read `CLAUDE.md` in full.
3. Read `plan.yaml` preamble + Appendix C.
4. Read `AGENT_PLAN.md` — the file-boundary rules and today's row of
   the per-day parallel schedule.
5. Read `run_state/week1.state.json`. Resume at the first incomplete
   task in `current_day`. Earlier days are not re-run.
6. If `human_gates_pending` is non-empty, do NOT proceed past the gate
   until a human explicitly marks it complete.
7. Append every agent-executable task to `run_state/week1.run.jsonl`.

Tracks B and C are side worktrees with their own scoped prompts and
narrower file boundaries — see `AGENT_PLAN.md`.

---

## 7. Out of scope for Week 1

Polymarket API calls (design-only) · autoresearch overnight runs
(Week 2+) · a second model (Qwen 3.6, Week 2–3) · concurrency in
workers (sequential only on Day 6) · a fully autonomous loop · fine-
tuning · Week 2 planning (a separate task — do not begin it after the
Day 7 retrospective).
