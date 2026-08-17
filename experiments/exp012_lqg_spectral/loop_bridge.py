#!/usr/bin/env python3
"""exp012 — Tier-2 → Tier-3 bridge (exp003 shape).

Reads ``results/summary.json`` (written by ``analyze.py``) into the
standard ``experiment_outcome`` payload and (optionally) runs a LOOP_V0
iteration on a topic seed derived from the claim under test
(cl-iter-2026-08-15-002: spectral-radius threshold for bounded-rationality
slowdown), via ``orchestrator.nara.run_iteration``. The ``summary``
string carries the Verdict=YES|NO token that finding_promotion keys on
AND the prereg's binding scope-limit note VERBATIM — the scope limit
must reach the ledger events (LOCKED requirement).

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


EXPERIMENT_ID = "exp012_lqg_spectral"
METRIC_NAME = "slowdown_breakpoint_rho_eff"
SOURCE_ITERATION_ID = "cl-iter-2026-08-15-002"


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
    payload that gets threaded into the iteration_record. value is the
    fitted rho* on YES and -1.0 on NO (LOCKED — never a fabricated
    threshold; the raw fit stays in summary.json)."""
    if not summary_path.exists():
        raise SystemExit(f"FATAL: {summary_path} missing — run analyze.py first")
    summary = json.loads(summary_path.read_text())
    verdict = summary["verdict"]
    value = summary["value"]
    if value is None:
        raise SystemExit(
            f"FATAL: no metric value in {summary_path} — the LOCKED rule "
            "always emits fitted rho* or -1.0 (not coerced)")
    fit = summary.get("fit") or {}
    raw_star = fit.get("rho_star")

    def _f(x, spec=".4f"):
        try:
            return format(float(x), spec)
        except (TypeError, ValueError):
            return "n/a"

    return {
        "experiment_id": EXPERIMENT_ID,
        "metric": METRIC_NAME,
        "value": value,
        "summary": (
            f"Verdict={verdict}. Quantized-belief contraction surrogate "
            f"(30 seeds x 7 rho_eff x 2 arms, Delta=0.05, t_max=20000): "
            f"{METRIC_NAME} = {_f(value)} (raw fitted rho* = {_f(raw_star, '.3f')}, "
            f"dBIC = {_f(fit.get('delta_bic'), '.2f')}, slope above = "
            f"{_f(fit.get('slope_above'), '.2f')}). "
            f"{summary['verdict_reason']} "
            f"Scope limit (binding, verbatim): {summary['scope_limit']}"
        ),
        "results_path": str(SUMMARY_MD_PATH.relative_to(REPO_ROOT)),
        "trials": _trial_count(trials_path),
        "effect_confirmed": bool(summary["effect_confirmed"]),
    }


def build_topic_seed(outcome: dict) -> str:
    """Generate the LOOP_V0 topic seed from the experiment outcome. The
    topic restates the source claim (cl-iter-2026-08-15-002) with the
    observed evidence and the surrogate scope."""
    return (
        "Bounded rationality, modeled as a constraint on the precision of "
        "belief updating, slows the convergence rate of "
        "communication-control strategies in partially nested LQG games "
        "specifically when the spectral radius of the information "
        "structure's adjacency matrix exceeds a critical threshold "
        "(tested on a linear belief-best-response contraction surrogate "
        "with a quantization-only bounded arm, Delta=0.05, over "
        f"rho_eff in [0.21, 0.84]; {outcome['summary']})"
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

    print("=== exp012 loop_bridge ===")
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
