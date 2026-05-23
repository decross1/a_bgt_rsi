# Current day — day_6: OpenClaw orchestrator + first worker

_Active-day tracker. Authoritative plan: `plan.yaml`. State:
`run_state/week1.state.json`. Run log: `run_state/week1.run.jsonl`._

**Day goal:** Orchestrator spawns one worker (NemoClaw sandbox if up,
plain-Docker / multiprocessing otherwise); the worker calls Gemma 4
via the wrapper; a structured `worker_output` returns; the full
round-trip is captured as a JSONL chain linked by `parent_request_id`.

**Status as of 2026-05-23: ✅ Day 6 COMPLETE.** Sequential 5/5 +
malformed 5/5; multiprocessing fallback taken (NemoClaw never
installed on Day 1); 4-level causal chain reconstructed by
`inspect_run`. All Block 2 + Block 3 tasks done; end-of-day artifacts
committed; arXiv cron enabled at 03:00. `current_day` advances to
`day_7` on the next session's resume — day_7 Block 1 is human-only
(HALT).

## Headline outcomes

- **Worker contract — 3/3 checks.** `schema/worker_contract.schema.json`
  (Track-B Day-3 draft, human-accepted on Day 6) validates as Draft
  2020-12 with `worker_input.required = [task_id, task_type, payload,
  parent_request_id]` and `worker_output.required = [task_id, status,
  result, errors, jsonl_log_path]`. Hard checkpoint cleared.
- **Router → multiprocessing fallback.** `nemoclaw status` returned
  "command not found"; router selected
  `day6_block2_orchestrator_with_fallback`. Logged as
  `state.fallbacks_taken.day6_orchestrator_isolation = "multiprocessing"`.
  Sandbox isolation deferred to Week 2 (CLAUDE.md inviolate rule 7).
- **Orchestrator + worker built.** `orchestrator/openclaw_runner.py`
  (Python `multiprocessing.get_context("fork")`, 60 s wall-clock
  timeout, terminate+kill on hang, no-orphan discipline) +
  `workers/summarize_paper.py` (ChromaDB `papers_recent` lookup +
  `agent_wrapper.call_sync` at `temperature=0`). One smoke-test task
  end-to-end: 98-word summary, 3 linked orchestrator entries + 1
  wrapper entry parent-linked across files.
- **Robustness mini — 3/3 checks (hard checkpoint).** 5/5 sequential
  workers passed (per-task 2.6–3.7 s, total wall-clock ~15 s); 5/5
  malformed inputs rejected cleanly (no exceptions, no hangs);
  `ps`-checked: 0 orphan worker processes pre and post. Metric logged
  as `day6_orchestrator_5_of_5 = 5`.
- **`inspect_run` — 1/1 check.** Full 4-level chain reconstructed for
  `task_id = seq-1` (orchestrator_dispatch → worker_invocation →
  wrapper_call → orchestrator_receipt) with matching IDs from the two
  JSONL files. Scoped run (`--no-discover`) prints the chain warning-free.
- **arXiv cron enabled at 03:00.** `cron/daily-arxiv.sh` was authored
  on Day 5 (present, executable, not in crontab); Day 6 enables it.

## Block 1 — Foundations (human-only, NO AI)

> HALT. Reading: Cesa-Bianchi & Lugosi, *Prediction, Learning, and
> Games*, Ch. 1 §1.5 – end + §2.1–2.3 (multiplicative weights).
> Problem set: implement Multiplicative Weights from scratch on paper;
> prove the regret bound (Phase-1 keystone problem).

| Task | Type | Status |
|------|------|--------|
| `day6_block1_reading` | human-only, blocking | ✅ passed — human attestation (decross1) 2026-05-23 |
| `day6_block1_problemset` | human-only | ✅ passed — human attestation (decross1) 2026-05-23 |

## Block 2 — Build (agent-executable, with router)

| Task | Status |
|------|--------|
| `day6_block2_worker_contract` (hard) | ✅ 3/3 schema checks |
| `day6_block2_orchestrator_router` | ✅ probe FAILED → branched to fallback |
| `day6_block2_orchestrator_with_fallback` | ✅ multiprocessing runner + worker; smoke test passed |
| `day6_block2_robustness_mini` (hard) | ✅ 5/5 sequential + 5/5 malformed + 0 orphans |
| `day6_block2_inspect_run_cli` | ✅ 4-level chain prints with matching IDs |

`day6_block2_orchestrator_with_nemoclaw` was skipped (router branched
to the fallback before any attempt).

## Block 3 / end of day

| Task | Type | Status |
|------|------|--------|
| `day6_block3_reading` | human-only, blocking | ✅ passed — human attestation (decross1) 2026-05-23 (Horton 2023 "Homo Silicus") |
| `day6_block3_journal` | human-assisted | ✅ stub at `journal/day6.md`; prose + publication is the human's |
| `day6_ambient` | human-only | ✅ passed — human attestation (decross1) 2026-05-23 |
| `day6_end_of_day_artifacts` | agent-executable | ✅ passed — runner + worker + logs + journal committed; cron enabled; Day 7 pre-staged |

## Side-track status

- **Track C `day6-quicklook`** — branch `worktree-day6-quicklook`
  holds commit `5785bc4 track-c day6: quicklook analysis`. Consumer
  is Day 7 (`exp001_repeated_pd/quicklook.py`); has NOT printed
  `TRACK C COMPLETE`, so per CLAUDE.md it is not merged today. Will
  re-audit on Day 7.

## Decisions / findings

- **NemoClaw → multiprocessing (expected).** `state.fallbacks_taken.day1_nemoclaw`
  documented that NemoClaw was never installed; the Day-6 router
  faithfully reproduced that choice. No new decision — just the
  scheduled second-order consequence of Day 1.
- **Worker contract authored ahead-of-time by Track B (Day 3).** The
  Day-6 hard checkpoint accepted the Track-B draft after human
  attestation; the agent only validated. Field lists matched the
  plan exactly; saved one ~20-minute task.
- **`openai==2.37.0` installed into `.venv-chroma`.** The Day-6 worker
  needs both `chromadb` and `openai`. Human-approved (recommended
  option). `.venv` and `.venv-chroma` remain two separate venvs by
  design; only `.venv-chroma` now bridges both, matching the
  established cron pattern.
- **Pre-stage divergence (cosmetic).** Plan literally names
  `experiments/exp001_repeated_pd/strategies_stubs.py`; the actual
  file is `experiments/exp001_repeated_pd/strategies.py` (full
  implementation, not a stub). Better than required; left as-is to
  avoid churn.

## Carried into Day 7

- `experiments/exp001_repeated_pd/strategies.py` — four fixed
  agents (mirror/latch/constant_c/constant_d) ready.
- OpenSpiel cloned at `clones/open_spiel/`; `chat_game.py` human-
  skimmed (decross1 attestation, 2026-05-23).
- Day-7 publication review gate is the most important of the week —
  `human_gates_pending = ["day7_publication_review"]` to be re-armed
  on Day 7 entry. Do NOT auto-publish.
