#!/usr/bin/env python3
"""exp006 — Tier-2/semi-synthetic → Tier-3 bridge.

Generates a topic seed FROM the mechanism-DESIGN experiment's results and
(optionally) runs a LOOP_V0 iteration on it via
``orchestrator.nara.run_iteration``, threading the cross-tier evidence
through the ``experiment_outcome`` iteration_record field
(schema/iteration_record.schema.json).

This is the same Slice-1 contract as exp003's loop_bridge, applied to the
semi-synthetic mechanism-DESIGN tier: the LLM-as-designer evidence flows
into the Tier-3 literature loop so novelty + critic engage with the
experimental finding alongside the literature.

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
# production logs/calls.jsonl. In-chain workers (hypothesize/novelty_classify/
# meta_review) read LOOP_V0_CALLS_LOG at import time, so set it now (module
# load), BEFORE the lazy `from orchestrator.nara import run_iteration` in main()
# — that routes every worker call eval-local. run_iteration's own turns are
# additionally redirected via the log_path= arg at the call site.
CALLS_LOG_PATH = str(EXP_DIR / "runs" / "calls.jsonl")
os.environ["LOOP_V0_CALLS_LOG"] = CALLS_LOG_PATH


EXPERIMENT_ID = "exp006_mechanism_design"
METRIC_NAME = "designer_mean_efficiency"


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
    payload that gets threaded into the iteration_record."""
    if not SUMMARY_JSON_PATH.exists():
        raise SystemExit(
            f"FATAL: {SUMMARY_JSON_PATH} missing — run analyze.py first"
        )
    summary = json.loads(SUMMARY_JSON_PATH.read_text())
    verdict = summary.get("verdict")
    mean_eff = summary.get("designer_mean_efficiency")
    feasibility_rate = summary.get("feasibility_rate")
    if mean_eff is None:
        raise SystemExit(
            f"FATAL: could not read designer_mean_efficiency from {SUMMARY_JSON_PATH}"
        )
    trials = _trial_count_from_jsonl()

    try:
        results_path = str(SUMMARY_MD_PATH.relative_to(REPO_ROOT))
    except ValueError:
        results_path = str(SUMMARY_MD_PATH)

    outcome: dict = {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": float(mean_eff),
        "summary": (
            f"Verdict={verdict}. Mean allocative efficiency of LLM-designed "
            f"mechanisms (scored vs the VCG benchmark): {float(mean_eff):.2%}"
            + (f"; feasibility_rate {feasibility_rate:.2%}."
               if feasibility_rate is not None else ".")
        ),
        "results_path": results_path,
    }
    if trials > 0:
        outcome["trials"] = trials
    return outcome


def build_topic_seed(outcome: dict) -> str:
    """Generate the LOOP_V0 topic seed from the experiment outcome. The
    topic is a hypothesis-shaped sentence in semi-synthetic-tier vocabulary."""
    mean_eff = outcome["value"]
    return (
        "When an LLM is asked to act as a mechanism designer for a "
        "combinatorial auction over two items — choosing both the allocation "
        "and the payments for a truthfully reported bid profile, with no "
        "priming on VCG or auction theory — its self-authored mechanisms "
        "achieve allocative efficiency approaching the welfare-maximizing "
        f"optimum (observed mean allocative efficiency: {mean_eff:.2%} of "
        "optimal welfare, scored against the VCG benchmark)."
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

    print("=== exp006 loop_bridge ===")
    print()
    print("Topic seed (semi-synthetic → Tier-3):")
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
