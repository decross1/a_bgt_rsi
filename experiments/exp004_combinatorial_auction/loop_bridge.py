#!/usr/bin/env python3
"""exp004 — combinatorial-auction → LOOP_V0 bridge.

Generates a topic seed FROM the experiment's results and (optionally)
runs a LOOP_V0 iteration on it via ``orchestrator.nara.run_iteration``,
threading the experimental evidence through the ``experiment_outcome``
iteration_record field (schema/iteration_record.schema.json).

exp004 is the HARDEST SYNTHETIC rung of the sandbox spectrum:
combinatorial auctions over two items with KNOWN optimal solutions. It is
the on-ramp to — but is NOT yet — the semi-synthetic mechanism-DESIGN
tier. The bridged metric is the VCG mechanism's truthful-bid fraction:
VCG is the cross-rung strategyproof anchor, so its truthful fraction is
the rediscovery signal that flows into the literature loop.

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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXP_DIR = Path(__file__).resolve().parent
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"


EXPERIMENT_ID = "exp004_combinatorial_auction"
METRIC_NAME = "vcg_truthful_fraction"


def _vcg_mechanism(summary: dict) -> dict:
    """Pull the VCG per-mechanism entry from summary.json."""
    for m in summary.get("per_mechanism", []):
        if m.get("mechanism") == "vcg":
            return m
    raise SystemExit(
        f"FATAL: no 'vcg' mechanism in {SUMMARY_JSON_PATH} per_mechanism"
    )


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
    """Read summary.json + trials.jsonl and produce the experiment_outcome
    payload that gets threaded into the iteration_record. The bridged value
    is the VCG mechanism's truthful_fraction."""
    if not SUMMARY_JSON_PATH.exists():
        raise SystemExit(
            f"FATAL: {SUMMARY_JSON_PATH} missing — run analyze.py first"
        )
    summary = json.loads(SUMMARY_JSON_PATH.read_text())
    vcg = _vcg_mechanism(summary)
    fraction = float(vcg["truthful_fraction"])
    verdict = vcg.get("verdict")
    trials = _trial_count_from_jsonl()

    outcome: dict = {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": fraction,
        "summary": (
            f"VCG verdict={verdict}. Fraction of per-bundle bids with "
            f"|bid - valuation| <= 5 under VCG: {fraction:.2%}."
        ),
        "results_path": str(SUMMARY_JSON_PATH.relative_to(REPO_ROOT)),
    }
    if trials > 0:
        outcome["trials"] = trials
    return outcome


def build_topic_seed(outcome: dict) -> str:
    """Generate the LOOP_V0 topic seed from the experiment outcome."""
    fraction = outcome["value"]
    return (
        "In single-round sealed-bid COMBINATORIAL auctions over two items "
        "(bids on item A, item B, or the A+B bundle) cleared by a VCG "
        "(Clarke-pivot) mechanism, with LLM bidders drawing independent "
        "private bundle valuations and no priming on auction theory, "
        "bidders converge on bidding approximately their true bundle "
        f"valuations (observed VCG truthful-bid fraction: {fraction:.2%} of "
        "per-bundle bids within |bid − valuation| ≤ 5)."
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

    print("=== exp004 loop_bridge ===")
    print()
    print("Topic seed (combinatorial-auction rung → literature loop):")
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
    bridged = record.get("experiment_outcome")
    if bridged:
        print(f"experiment_outcome bridged: experiment_id="
              f"{bridged.get('experiment_id')!r} "
              f"metric={bridged.get('metric')!r} value={bridged.get('value')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
