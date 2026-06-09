#!/usr/bin/env python3
"""exp001 — Tier-2 → Tier-3 bridge (copies exp003's shape).

Reads the narrative-vs-list analysis (results/summary.md, written by
analyze.py) into the standard ``experiment_outcome`` payload and
(optionally) threads it through one LOOP_V0 iteration via
``orchestrator.nara.run_iteration``. This closes the reverse path for
the cheapest literature survivor (iter-2026-05-27-001): a thesis the
loop only "believed" because no neighbor refuted it gets an actual
experimental verdict bridged back in.

Two modes:

  --dry-run (default)   : prints the topic + experiment_outcome payload,
                           makes NO LLM call. Safe under MOCK_LLM.
  --live                : runs the full chain via run_iteration.
                           Requires `env -u MOCK_LLM` + live vLLM.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXP_DIR = Path(__file__).resolve().parent
SUMMARY_PATH = EXP_DIR / "results" / "summary.md"
NARRATIVE_SUMMARY_JSON = EXP_DIR / "results" / "narrative" / "summary.json"
LIST_SUMMARY_JSON = EXP_DIR / "results" / "list" / "summary.json"
# Eval-local wrapper-call log: --live worker calls land here, NEVER in
# production logs/calls.jsonl. In-chain workers read LOOP_V0_CALLS_LOG at
# import time, so set it now (module load), BEFORE the lazy
# `from orchestrator.nara import run_iteration` in main().
CALLS_LOG_PATH = str(EXP_DIR / "runs" / "calls.jsonl")
os.environ["LOOP_V0_CALLS_LOG"] = CALLS_LOG_PATH

EXPERIMENT_ID = "exp001_repeated_pd"
METRIC_NAME = "narrative_minus_list_cooperation"

_VERDICT_RE = re.compile(r"Verdict=(YES|NO)")


def _parse_summary(text: str) -> dict:
    """Pull verdict + the three machine lines analyze.py writes."""
    m = _VERDICT_RE.search(text)
    if not m:
        raise SystemExit(
            f"FATAL: no Verdict=YES|NO token in {SUMMARY_PATH} — rerun analyze.py")
    out: dict = {"verdict": m.group(1)}
    needles = {
        "narrative_rate": "- coop_rate(narrative): ",
        "list_rate": "- coop_rate(list): ",
        "delta": "- delta(narrative - list): ",
    }
    for line in text.splitlines():
        for key, needle in needles.items():
            if line.startswith(needle):
                out[key] = float(line[len(needle):].strip())
    missing = [k for k in needles if k not in out]
    if missing:
        raise SystemExit(
            f"FATAL: could not parse {missing} from {SUMMARY_PATH}")
    return out


def _total_rounds() -> int:
    n = 0
    for path in (NARRATIVE_SUMMARY_JSON, LIST_SUMMARY_JSON):
        if path.exists():
            with open(path) as fh:
                n += int(json.load(fh).get("total_rounds") or 0)
    return n


def build_experiment_outcome() -> dict:
    """Read summary.md (+ arm summary.json) into the experiment_outcome
    payload threaded into the iteration_record."""
    if not SUMMARY_PATH.exists():
        raise SystemExit(f"FATAL: {SUMMARY_PATH} missing — run analyze.py first")
    parsed = _parse_summary(SUMMARY_PATH.read_text())
    try:
        results_path = str(SUMMARY_PATH.relative_to(REPO_ROOT))
    except ValueError:
        results_path = str(SUMMARY_PATH)
    outcome: dict = {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": parsed["delta"],
        "summary": (
            f"Verdict={parsed['verdict']}. Narrative-history cooperation "
            f"{parsed['narrative_rate']:.2%} vs list-history "
            f"{parsed['list_rate']:.2%} (delta {parsed['delta']:+.2%}; "
            "pre-registered threshold +10 points absolute)."
        ),
        "results_path": results_path,
    }
    trials = _total_rounds()
    if trials > 0:
        outcome["trials"] = trials
    return outcome


def build_topic_seed(outcome: dict) -> str:
    """LOOP_V0 topic seed from the outcome — a hypothesis-shaped sentence."""
    return (
        "In repeated Prisoner's Dilemma play against fixed and mirror "
        "opponents, presenting the interaction history to an LLM agent as "
        "a cohesive narrative rather than a structured list shifts its "
        f"cooperation rate by {outcome['value']:+.2%} (absolute, narrative "
        "minus list) under otherwise identical rules and payoffs."
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

    print("=== exp001 loop_bridge ===")
    print()
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
