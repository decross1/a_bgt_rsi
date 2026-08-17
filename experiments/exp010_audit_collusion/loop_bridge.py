#!/usr/bin/env python3
"""exp010 — Tier-2 → Tier-3 bridge (exp003 shape).

Reads ``results/summary.json`` (written by ``analyze.py``) into the
standard ``experiment_outcome`` payload and (optionally) runs a LOOP_V0
iteration on a topic seed derived from the claim under test
(cl-iter-2026-07-13-001: audit cadence predictability → synchronized
collusion timing), via ``orchestrator.nara.run_iteration``. The
``summary`` string carries the Verdict=YES|NO token that
finding_promotion keys on.

Two modes:

  --dry-run (default)   : prints the topic + experiment_outcome payload
                           that would be threaded, makes NO LLM call.
                           Safe in MOCK_LLM environments.

  --live                : runs the full chain via run_iteration.
                           Requires `env -u MOCK_LLM` + a live vLLM
                           backend (Gemma).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXP_DIR = Path(__file__).resolve().parent
SUMMARY_MD_PATH = EXP_DIR / "results" / "summary.md"
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"
# Eval-local wrapper-call log: --live worker calls land here, NEVER in
# production logs/calls.jsonl. In-chain workers read LOOP_V0_CALLS_LOG at
# import time, so set it now (module load), BEFORE the lazy
# `from orchestrator.nara import run_iteration` in main(). Mirrors exp003.
CALLS_LOG_PATH = str(EXP_DIR / "runs" / "calls.jsonl")
os.environ["LOOP_V0_CALLS_LOG"] = CALLS_LOG_PATH


EXPERIMENT_ID = "exp010_audit_collusion"
METRIC_NAME = "collusion_rate_gap_periodic_minus_random"
SOURCE_ITERATION_ID = "cl-iter-2026-07-13-001"


def _trial_count(trials_path: Path) -> int:
    if not trials_path.exists():
        return 0
    n = 0
    with open(trials_path) as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def build_experiment_outcome(
    summary_path: Path = SUMMARY_JSON_PATH,
    trials_path: Path = TRIALS_PATH,
) -> dict:
    """Read summary.json + trials.jsonl and produce the experiment_outcome
    payload that gets threaded into the iteration_record."""
    if not summary_path.exists():
        raise SystemExit(f"FATAL: {summary_path} missing — run analyze.py first")
    summary = json.loads(summary_path.read_text())
    verdict = summary["verdict"]
    value = summary["value"]
    if value is None:
        raise SystemExit(
            f"FATAL: no median collusion-rate gap in {summary_path} — "
            "no metric value to bridge (not coerced)")
    rule2 = summary["rule2"]
    q1 = summary["q1_adjudication"]

    def _f(x):
        return "n/a" if x is None else f"{x:.4f}"

    return {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": value,
        "summary": (
            f"Verdict={verdict}. Q-learning audit game (T=5000, audit rate "
            f"1/8): median collusion_rate gap PERIODIC−RANDOM = {_f(value)} "
            f"(LOCKED bar 0.05, MWU p<0.01); mechanism-gate mean PERIODIC "
            f"timing_gap = {_f(rule2['mean_timing_gap'])} (LOCKED bar 0.10, "
            f"Wilcoxon p<0.01). {summary['verdict_reason']} "
            f"Q1 (any monitoring reduces collusion): {q1['label']}."
        ),
        "results_path": str(SUMMARY_MD_PATH.relative_to(REPO_ROOT)),
        "trials": _trial_count(trials_path),
        "effect_confirmed": bool(summary["effect_confirmed"]),
    }


def build_topic_seed(outcome: dict) -> str:
    """Generate the LOOP_V0 topic seed from the experiment outcome. The
    topic restates the source claim (cl-iter-2026-07-13-001) with the
    observed evidence."""
    return (
        "Periodic audits increase collusion rates in non-equilibrium "
        "markets because the predictability of the audit cadence allows "
        "agents to synchronize deviations during high-probability "
        "oversight gaps (independent tabular Q-learners in a repeated "
        "fined pricing game; observed median collusion-rate gap PERIODIC "
        f"− RANDOM at equal audit frequency 1/8: {outcome['value']:+.4f}; "
        f"{outcome['summary']})"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="print the payload + topic, make no LLM call (default)")
    p.add_argument("--live", dest="dry_run", action="store_false",
                   help="actually call run_iteration with the payload")
    args = p.parse_args(argv)

    outcome = build_experiment_outcome()
    topic = build_topic_seed(outcome)

    print("=== exp010 loop_bridge ===")
    print()
    print(f"Source claim: {SOURCE_ITERATION_ID}")
    print("Topic seed (Tier-2 → Tier-3):")
    print(f"  {topic}")
    print()
    print("experiment_outcome payload:")
    print(json.dumps(outcome, indent=2))
    print()

    if args.dry_run:
        print("[dry-run] not calling run_iteration. Pass --live to run.")
        return 0

    # Lazy import — run_iteration pulls in vLLM + chromadb dependencies.
    from orchestrator.nara import run_iteration

    print("=== running LOOP_V0 iteration with experiment_outcome ===")
    Path(CALLS_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    record = run_iteration(
        topic=topic,
        source="human_cli",
        experiment_outcome=outcome,
        log_path=CALLS_LOG_PATH,
    )
    print()
    print(f"iteration_id: {record.get('iteration_id')}")
    print(f"journal_entry_path: {record.get('journal_entry_path')}")
    novelty = record.get("novelty") or {}
    critique = record.get("critique") or {}
    print(f"novelty_class: {novelty.get('class')!r}")
    print(f"critic_verdict: {critique.get('verdict')!r}")
    print(f"contradicting_paper_id: {critique.get('contradicting_paper_id')!r}")
    bridged = record.get("experiment_outcome")
    if bridged:
        print(f"experiment_outcome bridged: experiment_id="
              f"{bridged.get('experiment_id')!r} "
              f"metric={bridged.get('metric')!r} value={bridged.get('value')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
