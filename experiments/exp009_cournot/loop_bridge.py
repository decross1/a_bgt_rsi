#!/usr/bin/env python3
"""exp009 — Tier-2 → Tier-3 bridge (exp003 shape).

Reads ``results/summary.json`` (written by ``analyze.py``) into the
standard ``experiment_outcome`` payload and (optionally) runs a LOOP_V0
iteration on a topic seed derived from the result, via
``orchestrator.nara.run_iteration``.

This closes the REVERSE path for the surviving literature thesis
iter-2026-06-06-001 (docs/thesis_to_experiment_construction.md worked
example 1): the thesis survived the literature loop unrun; exp009 is
its constructed experimental test, and this bridge threads the verdict
back into the loop. The ``summary`` string carries the Verdict=YES|NO
token that finding_promotion keys on.

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


EXPERIMENT_ID = "exp009_cournot"
METRIC_NAME = "mean_abs_deviation_from_nash_quantity"
SOURCE_ITERATION_ID = "iter-2026-06-06-001"


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
    explicit = summary["arms"]["explicit"]
    absent = summary["arms"]["absent"]
    value = explicit["mean_abs_deviation"]
    if value is None:
        raise SystemExit(
            f"FATAL: explicit arm has no valid trials in {summary_path} — "
            "no metric value to bridge (not coerced)"
        )

    def _f(x):
        return "n/a" if x is None else f"{x:.4f}"

    outcome: dict = {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": value,
        "summary": (
            f"Verdict={verdict}. Cournot duopoly (q*=(a-c)/3b=30): mean "
            f"|q - q*|/q* with explicit few-shot marginal-cost examples = "
            f"{_f(value)} vs {_f(absent['mean_abs_deviation'])} without "
            f"(pre-registered ceiling "
            f"{summary['explicit_deviation_ceiling']}); secondary "
            f"var(explicit) < var(absent): "
            f"{summary['variance_directional_holds']}."
        ),
        "results_path": str(SUMMARY_MD_PATH.relative_to(REPO_ROOT)),
    }
    trials = _trial_count(trials_path)
    if trials > 0:
        outcome["trials"] = trials
    return outcome


def build_topic_seed(outcome: dict) -> str:
    """Generate the LOOP_V0 topic seed from the experiment outcome. The
    topic restates the source thesis with the observed evidence."""
    return (
        "In a symmetric Cournot duopoly with linear demand and constant "
        "marginal cost, LLM agents' convergence to the Nash quantity "
        "q* = (a - c)/(3b) is modulated by few-shot prompting examples "
        "that explicitly define the marginal cost parameter (observed "
        f"mean |q - q*|/q* in the explicit arm: {outcome['value']:.4f}; "
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

    print("=== exp009 loop_bridge ===")
    print()
    print(f"Source thesis: {SOURCE_ITERATION_ID}")
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
