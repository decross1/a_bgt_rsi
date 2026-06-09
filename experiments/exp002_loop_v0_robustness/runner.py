#!/usr/bin/env python3
"""exp002 — robustness battery on LOOP_V0's three Phase-2 topics.

Re-runs Topic 1 / Topic 2 / Topic 3 five times each. Same prompts, same
Gemma backend, expanded Chroma retrieval. Stochastic variance comes from
the chain's default sampling temperatures (0.7 on hypothesize, 0.2 on
critic sub-agent). No seed plumbing; the variance is the natural per-run
noise the apparatus exhibits in production.

Captures per-iteration: novelty class, top_neighbor_id, critic verdict,
contradicting_paper_id, sub-agent status, hypothesis text, wall-clock.
Writes one JSONL row per iteration to `results.jsonl`. `aggregate.py`
turns that into per-topic verdict distributions in `results.md`.

Run via:
    env -u MOCK_LLM ./.venv-chroma/bin/python experiments/exp002_loop_v0_robustness/runner.py

The three topics are the same ones documented in
`human/retrospectives/2026-05-27-session.md` § 1 and tabulated in D-036.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Eval-local wrapper-call log: every real worker call this battery drives lands
# here, NEVER in production logs/calls.jsonl. The IN-CHAIN workers
# (hypothesize/novelty_classify/meta_review) read LOOP_V0_CALLS_LOG at import
# time, so it MUST be set BEFORE importing orchestrator.nara below (which
# imports them). run_iteration's own turns are additionally redirected via the
# log_path= arg at the call site.
CALLS_LOG_PATH = str(Path(__file__).resolve().parent / "runs" / "calls.jsonl")
os.environ["LOOP_V0_CALLS_LOG"] = CALLS_LOG_PATH

from orchestrator.nara import run_iteration  # noqa: E402

EXP_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXP_DIR / "results.jsonl"

TOPICS = [
    {
        "label": "topic_1_open_bayesian_pgg",
        "topic": (
            "In repeated public goods games with noisy contribution observation, "
            "conditional cooperators using a Bayesian belief over others' types "
            "will exhibit faster contribution decay than under perfect observation, "
            "even when expected observation error is mean-zero."
        ),
        "prior_novelty": "unclear",
        "prior_verdict": "restated",
        "diagnostic_role": "open",
    },
    {
        "label": "topic_2_rediscovery_probe",
        "topic": (
            "In symmetric 2x2 coordination games played on a fixed network, "
            "fictitious play with uniform priors converges to the risk-dominant "
            "equilibrium more often than to the payoff-dominant one as the "
            "population grows."
        ),
        "prior_novelty": "rediscovery",
        "prior_verdict": "restated",
        "diagnostic_role": "should-be-rediscovery",
    },
    {
        "label": "topic_3_deliberately_wrong",
        "topic": (
            "In finitely repeated prisoner's dilemmas with common knowledge of "
            "rationality, subgame perfect equilibrium predicts cooperation in the "
            "penultimate round when the stage-game cooperation payoff exceeds twice "
            "the defection payoff."
        ),
        "prior_novelty": "nonsense",
        "prior_verdict": "falsified",
        "diagnostic_role": "should-be-falsified-deliberately-wrong-claim",
    },
]

RUNS_PER_TOPIC = 5


def _extract_verdict_fields(iteration_record: dict) -> dict:
    """Pull the fields we want to compare across runs from an iteration_record."""
    hyp = iteration_record.get("hypothesis") or {}
    nov = iteration_record.get("novelty") or {}
    crit = iteration_record.get("critique") or {}
    return {
        "iteration_id": iteration_record.get("iteration_id"),
        "hypothesis_text": hyp.get("text") or "",
        "candidates_considered": hyp.get("candidates_considered"),
        "novelty_class": nov.get("class"),
        "novelty_top_neighbor_id": nov.get("top_neighbor_id"),
        "critic_verdict": crit.get("verdict"),
        "critic_contradicting_paper_id": crit.get("contradicting_paper_id"),
        "critic_subagent_status": crit.get("subagent_status"),
        "critic_subagent_turns_used": crit.get("subagent_turns_used"),
        "critic_subagent_wall_seconds": crit.get("subagent_wall_seconds"),
        "tool_calls_made": iteration_record.get("tool_calls_made"),
        "wrapper_calls": len(iteration_record.get("wrapper_call_ids") or []),
        "started_at": iteration_record.get("started_at"),
        "ended_at": iteration_record.get("ended_at"),
    }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    Path(CALLS_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    out = open(RESULTS_PATH, "w")
    total = len(TOPICS) * RUNS_PER_TOPIC
    done = 0
    print(f"=== exp002 runner starting at {_utcnow_iso()} ===", flush=True)
    print(f"=== {total} iterations: {len(TOPICS)} topics × {RUNS_PER_TOPIC} runs ===", flush=True)

    for spec in TOPICS:
        label = spec["label"]
        for run_idx in range(1, RUNS_PER_TOPIC + 1):
            done += 1
            print(f"\n[{done}/{total}] {label} run {run_idx}/{RUNS_PER_TOPIC} ...", flush=True)
            t0 = time.perf_counter()
            try:
                # `loop_memory_probe` is the iteration_record schema's enum
                # value for programmatic batch runs — semantic match for
                # this robustness battery (vs. human_cli / human_ui).
                record = run_iteration(
                    topic=spec["topic"],
                    source="loop_memory_probe",
                    log_path=CALLS_LOG_PATH,
                )
                wall_s = time.perf_counter() - t0
                row = {
                    "exp": "exp002",
                    "topic_label": label,
                    "topic_text": spec["topic"],
                    "diagnostic_role": spec["diagnostic_role"],
                    "prior_novelty": spec["prior_novelty"],
                    "prior_verdict": spec["prior_verdict"],
                    "run_idx": run_idx,
                    "wall_s_total": round(wall_s, 2),
                    **_extract_verdict_fields(record),
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                print(f"  → novelty={row['novelty_class']} verdict={row['critic_verdict']} "
                      f"contradicting={row['critic_contradicting_paper_id']} wall={wall_s:.1f}s",
                      flush=True)
            except Exception as exc:
                row = {
                    "exp": "exp002",
                    "topic_label": label,
                    "run_idx": run_idx,
                    "error": f"{type(exc).__name__}: {exc}",
                    "wall_s_total": round(time.perf_counter() - t0, 2),
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                print(f"  → ERROR: {row['error']}", flush=True)

    out.close()
    print(f"\n=== exp002 runner done at {_utcnow_iso()}; wrote {RESULTS_PATH} ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
