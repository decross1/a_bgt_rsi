#!/usr/bin/env python3
# DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).
"""exp007 — applied-tier → Tier-3 bridge.

Generates a topic seed FROM the experiment's results and (optionally)
runs a LOOP_V0 iteration on it via ``orchestrator.nara.run_iteration``,
threading the cross-tier evidence through the ``experiment_outcome``
iteration_record field (schema/iteration_record.schema.json).

This mirrors the exp003 loop_bridge contract: experiment evidence flows
into the Tier-3 literature loop so novelty + critic engage with the
experimental finding alongside the literature. The metric threaded here
is the Brier Skill Score (forecasting skill vs the market price) — a
paper-forecasting result, NOT trading P&L.

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
SUMMARY_PATH = EXP_DIR / "results" / "summary.json"
FORECASTS_PATH = EXP_DIR / "results" / "forecasts.jsonl"


EXPERIMENT_ID = "exp007_polymarket"
METRIC_NAME = "brier_skill_score"


def _forecast_count_from_jsonl() -> int:
    if not FORECASTS_PATH.exists():
        return 0
    n = 0
    with open(FORECASTS_PATH) as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def build_experiment_outcome() -> dict:
    """Read summary.json and produce the experiment_outcome payload that
    gets threaded into the iteration_record."""
    if not SUMMARY_PATH.exists():
        raise SystemExit(f"FATAL: {SUMMARY_PATH} missing — run analyze.py first")
    summary = json.loads(SUMMARY_PATH.read_text())
    verdict = summary.get("verdict")
    bss = summary.get("bss")
    n = summary.get("n")
    if bss is None:
        raise SystemExit(f"FATAL: could not read bss from {SUMMARY_PATH}")

    outcome: dict = {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": bss,
        "summary": (
            f"Verdict={verdict}. Brier Skill Score of LLM forecasts vs the "
            f"market-implied probability over {n} resolved markets: {bss:.4f} "
            "(forecasting skill, not trading P&L)."
        ),
        "results_path": str(SUMMARY_PATH.relative_to(REPO_ROOT)),
    }
    forecasts = _forecast_count_from_jsonl()
    if forecasts > 0:
        outcome["trials"] = forecasts
    return outcome


def build_topic_seed(outcome: dict) -> str:
    """Generate the LOOP_V0 topic seed from the experiment outcome."""
    bss = outcome["value"]
    return (
        "When an LLM with no market-price priming is asked for a calibrated "
        "YES probability on resolved real-world binary prediction-market "
        "questions, its forecasts achieve a Brier Skill Score of "
        f"{bss:.4f} relative to the contemporaneous market-implied "
        "probability (a paper-forecasting measure of skill vs the market, "
        "not trading performance)."
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

    print("=== exp007 loop_bridge ===")
    print()
    print("Topic seed (applied → Tier-3):")
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
