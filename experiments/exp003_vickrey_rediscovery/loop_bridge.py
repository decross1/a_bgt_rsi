#!/usr/bin/env python3
"""exp003 — Tier-2 → Tier-3 bridge.

Generates a topic seed FROM the experiment's results and (optionally)
runs a LOOP_V0 iteration on it via ``orchestrator.nara.run_iteration``,
threading the cross-tier evidence through the new
``experiment_outcome`` iteration_record field (schema/iteration_record
.schema.json).

This is the Slice-1 contract: Tier-2 evidence flows into the Tier-3
literature loop, so novelty + critic engage with the experimental
finding alongside the literature.

Two modes:

  --dry-run (default)   : prints the topic + experiment_outcome payload
                           that would be threaded, makes NO LLM call.
                           Safe in MOCK_LLM environments.

  --live                : runs the full chain via run_iteration.
                           Requires `env -u MOCK_LLM` + a live vLLM
                           backend (Gemma).

The dry-run mode is the default so this can be exercised in tests +
smoke checks without the ~30s + GPU cost of a real LOOP_V0 iteration.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXP_DIR = Path(__file__).resolve().parent
SUMMARY_PATH = EXP_DIR / "results" / "summary.md"
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"


EXPERIMENT_ID = "exp003_vickrey_rediscovery"
METRIC_NAME = "truthful_bid_fraction"


def _verdict_from_summary(text: str) -> str | None:
    """Pull the YES/NO verdict line from the summary.md analyze.py wrote."""
    for line in text.splitlines():
        if line.startswith("**Verdict: "):
            # "**Verdict: YES** — ..."  or  "**Verdict: NO** — ..."
            tail = line[len("**Verdict: "):]
            return tail.split("**", 1)[0].strip()
    return None


def _truthful_fraction_from_summary(text: str) -> float | None:
    """Pull the eps=5 truthful fraction (a float in [0, 1]) from summary.md."""
    needle = "Truthful fraction at eps=5.0: "
    for line in text.splitlines():
        if needle in line:
            # "- Truthful fraction at eps=5.0: 42/50 (84.0%)"
            tail = line.split(needle, 1)[1]
            pct = tail.split("(", 1)[1].rstrip().rstrip(")")
            return float(pct.rstrip("%")) / 100.0
    return None


def _trial_count_from_jsonl() -> int:
    if not TRIALS_PATH.exists():
        return 0
    n = 0
    with open(TRIALS_PATH) as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def build_experiment_outcome() -> dict:
    """Read summary.md + trials.jsonl and produce the experiment_outcome
    payload that gets threaded into the iteration_record."""
    if not SUMMARY_PATH.exists():
        raise SystemExit(f"FATAL: {SUMMARY_PATH} missing — run analyze.py first")
    summary_text = SUMMARY_PATH.read_text()
    verdict = _verdict_from_summary(summary_text)
    fraction = _truthful_fraction_from_summary(summary_text)
    if fraction is None:
        raise SystemExit(
            f"FATAL: could not parse truthful fraction from {SUMMARY_PATH}"
        )
    trials = _trial_count_from_jsonl()

    outcome: dict = {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": fraction,
        "summary": (
            f"Verdict={verdict}. Fraction of trials with mean |bid - "
            f"valuation| <= 5: {fraction:.2%}."
        ),
        "results_path": str(SUMMARY_PATH.relative_to(REPO_ROOT)),
    }
    if trials > 0:
        outcome["trials"] = trials
    return outcome


def build_topic_seed(outcome: dict) -> str:
    """Generate the LOOP_V0 topic seed from the experiment outcome. The
    topic is a hypothesis-shaped sentence in Tier-2 vocabulary."""
    fraction = outcome["value"]
    return (
        "In repeated single-round sealed-bid second-price auctions with "
        "four LLM bidders drawing independent private valuations from "
        "U[0, 100] and no priming on auction theory, bidders converge on "
        "submitting bids approximately equal to their private valuations "
        f"(observed truthful-bid fraction: {fraction:.2%} of trials "
        "had mean |bid − valuation| ≤ 5)."
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

    print("=== exp003 loop_bridge ===")
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
    record = run_iteration(
        topic=topic,
        source="human_cli",
        experiment_outcome=outcome,
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
