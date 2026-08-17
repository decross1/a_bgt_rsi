#!/usr/bin/env python3
"""exp011 — Tier-2 → Tier-3 bridge (exp003 contract).

Reads ``results/summary.json`` (written by ``analyze.py``) into the
standard ``experiment_outcome`` payload and (optionally) runs a LOOP_V0
iteration on a topic seed derived from the tested claim
(cl-iter-2026-07-15-001), via ``orchestrator.nara.run_iteration``.

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


EXPERIMENT_ID = "exp011_matching_reconstruction"
METRIC_NAME = "median_kendall_tau_at_termination"
SOURCE_CLAIM_ID = "cl-iter-2026-07-15-001"
CLAIM_TEXT = (
    "An adversary can reconstruct the preference rankings of a specific "
    "agent by observing the deviation in the resulting stable matching "
    "when a small, targeted subset of agent preferences is perturbed."
)


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
            f"FATAL: no valid trials behind {summary_path} — no metric "
            "value to bridge (not coerced)"
        )
    r1 = summary["rules"]["rule1_median_tau"]
    r2 = summary["rules"]["rule2_trial_floor"]
    attribution = summary.get("attribution") or {}
    summary_line = (
        f"Verdict={verdict}. Stable marriage n=12, man-proposing GS, "
        f"budget Q<=44, <=2 perturbed lists/query: median scored Kendall "
        f"tau at attack termination = {value:.4f} (rule 1 needs >= "
        f"{r1['threshold']}); {r2['observed_fraction']:.0%} of trials "
        f"reached tau >= {r2['tau_floor']} (rule 2 needs >= "
        f"{r2['required_fraction']:.0%})."
    )
    if verdict == "NO":
        summary_line += f" Attribution: {attribution.get('case')}."
    summary_line += " No random-perturbation control arm was run."
    return {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": value,
        "summary": summary_line,
        "results_path": str(SUMMARY_MD_PATH.relative_to(REPO_ROOT)),
        "trials": _trial_count(trials_path),
        "effect_confirmed": bool(summary["effect_confirmed"]),
    }


def build_topic_seed(outcome: dict) -> str:
    """LOOP_V0 topic seed: the tested claim text plus the observed
    evidence, in Tier-2 vocabulary."""
    return (
        f"{CLAIM_TEXT} Tested in a stable-marriage market (n=12 per side, "
        "deterministic man-proposing Gale-Shapley, uniform-random "
        "profiles) under a two-mode targeted-perturbation attack with at "
        "most 2 perturbed preference lists per query and at most 44 "
        "queries (observed median scored Kendall tau at attack "
        f"termination: {outcome['value']:.4f}; {outcome['summary']})"
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

    print("=== exp011 loop_bridge ===")
    print()
    print(f"Source claim: {SOURCE_CLAIM_ID}")
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
