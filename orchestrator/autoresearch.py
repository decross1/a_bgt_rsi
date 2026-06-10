#!/usr/bin/env python3
"""autoresearch driver — SINGLE-SHOT, HUMAN-TRIGGERED orchestration.

One invocation composes the existing pieces into exactly ONE experiment →
ONE bridged LOOP_V0 iteration:

    resolve experiment → (optionally run it) → build experiment_outcome
    → (optionally replicate) → (optionally) one run_iteration → return payload

This driver is SINGLE-SHOT and HUMAN-TRIGGERED. It runs the chain ONCE per
call and returns. It honors the CLAUDE.md no-continuous-orchestrator
guardrail: there is NO loop, NO scheduler, NO auto-iterate / keep-going
behavior here. A human (or a human-invoked CLI) triggers each run; the
apparatus does not re-arm itself. To run another iteration, a human invokes
it again.

It reuses, and does NOT reimplement, the existing modules:

  - orchestrator.tier_registry.get_experiment  — resolve + tier-check the
    experiment. The registry reports apparatus capabilities (has_run /
    has_analyze / has_loop_bridge / results_summary) by filesystem inspection
    and does NOT import the experiment module; this driver loads the
    experiment's loop_bridge itself when has_loop_bridge is True.
  - orchestrator.nara.run_iteration            — the LOOP_V0 chain (live only).
  - <experiment>/loop_bridge.build_experiment_outcome — when the experiment
    ships a loop_bridge; otherwise a minimal experiment_outcome dict is
    constructed from the experiment's summary.json
    ({experiment_id, metric, value}).
  - orchestrator (experiments) replication_driver — the cross-rung replicate
    step for the auction experiments.

No new iteration_record fields are introduced: the bridge reuses the existing
`experiment_outcome` (and optional `cross_tier_comparison`) fields that
run_iteration already threads.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# --------------------------------------------------------------------------
# Experiment resolution. orchestrator.tier_registry.get_experiment returns a
# plain dict that reports apparatus capabilities by filesystem inspection
# (experiment_id, tier, dir [repo-relative], has_run, has_analyze,
# has_loop_bridge, results_summary). It does NOT import the experiment module,
# so the build_experiment_outcome callable is loaded here, lazily, only when
# has_loop_bridge is True.
# --------------------------------------------------------------------------
def _exp_dir(exp: dict[str, Any]) -> Path:
    """Absolute dir for an experiment from the registry's repo-relative `dir`."""
    return REPO_ROOT / exp["dir"]


def _load_build_experiment_outcome(exp: dict[str, Any]) -> Callable[[], dict] | None:
    """Load the experiment's loop_bridge.build_experiment_outcome by path.

    Returns None when the experiment ships no loop_bridge."""
    if not exp.get("has_loop_bridge"):
        return None
    bridge_path = _exp_dir(exp) / "loop_bridge.py"
    spec = importlib.util.spec_from_file_location(
        f"{exp['experiment_id']}_loop_bridge", bridge_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "build_experiment_outcome", None)


def _resolve_experiment(tier: str, experiment_id: str) -> dict[str, Any]:
    """Step 1. Resolve the experiment via the tier registry and ASSERT it
    belongs to `tier`."""
    from orchestrator.tier_registry import get_experiment

    exp = get_experiment(experiment_id)
    actual_tier = exp.get("tier")
    assert actual_tier == tier, (
        f"tier mismatch: experiment {experiment_id!r} belongs to tier "
        f"{actual_tier!r}, not requested tier {tier!r}"
    )
    return exp


# --------------------------------------------------------------------------
# experiment_outcome construction.
# --------------------------------------------------------------------------
def _minimal_outcome_from_summary(exp: dict[str, Any]) -> dict:
    """Construct a minimal experiment_outcome from summary.json when the
    experiment has no loop_bridge. {experiment_id, metric, value} are the
    schema-required fields (schema/iteration_record.schema.json)."""
    summary_path = _exp_dir(exp) / "results" / "summary.json"
    if not summary_path.exists():
        raise SystemExit(
            f"FATAL: no loop_bridge and no {summary_path} to bridge from"
        )
    summary = json.loads(summary_path.read_text())
    metric = summary.get("metric")
    value = summary.get("value")
    if metric is None or value is None:
        raise SystemExit(
            f"FATAL: {summary_path} lacks a top-level {{metric, value}} for a "
            "minimal experiment_outcome (and the experiment ships no "
            "loop_bridge.build_experiment_outcome to build a richer one)"
        )
    return {
        "experiment_id": exp["experiment_id"],
        "metric": metric,
        "value": value,
    }


def _build_experiment_outcome(exp: dict[str, Any]) -> dict:
    """Step 3. Prefer the experiment's own loop_bridge.build_experiment_outcome;
    otherwise the minimal-from-summary path."""
    build = _load_build_experiment_outcome(exp)
    if callable(build):
        return build()
    return _minimal_outcome_from_summary(exp)


# --------------------------------------------------------------------------
# Replicate step (the auction experiments share the cross-rung comparison).
# --------------------------------------------------------------------------
def _build_replication(experiment_id: str) -> dict | None:
    """Step 4. Call the matching replication_driver comparison. For the
    auction experiments this is the cross-rung (Vickrey single-item -> exp004
    combinatorial VCG) comparison. Returns None when no comparison applies."""
    from experiments import replication_driver

    if experiment_id in ("exp003_vickrey_rediscovery", "exp004_combinatorial_auction"):
        return replication_driver.build_cross_rung_comparison()
    return None


# --------------------------------------------------------------------------
# Optional experiment (re)run. GUARDED: default run_experiment=False so tests
# and dry-runs NEVER invoke the real model.
# --------------------------------------------------------------------------
def _run_experiment_subprocess(exp: dict[str, Any], runtime: str | None) -> None:
    """Step 2 (run_experiment=True). Subprocess run.py then analyze.py under
    `env -u MOCK_LLM` (real model). Guarded behind an explicit flag."""
    exp_dir = _exp_dir(exp)
    interp = runtime or sys.executable
    for script in ("run.py", "analyze.py"):
        path = exp_dir / script
        if not path.exists():
            raise SystemExit(f"FATAL: {path} missing; cannot run experiment")
        subprocess.run(
            ["env", "-u", "MOCK_LLM", interp, str(path)],
            cwd=str(exp_dir),
            check=True,
        )


# --------------------------------------------------------------------------
# The driver.
# --------------------------------------------------------------------------
def run_autoresearch(
    tier: str,
    experiment_id: str,
    *,
    reuse_results: bool = True,
    run_experiment: bool = False,
    n: int | None = None,
    replicate: bool = False,
    live: bool = False,
    runtime: str | None = None,
    source: str = "human_cli",
) -> dict:
    """Run ONE autoresearch pass — SINGLE-SHOT, HUMAN-TRIGGERED.

    Composes existing pieces into a single experiment → single bridged
    LOOP_V0 iteration and returns. There is NO loop and NO scheduling: this
    honors the CLAUDE.md no-continuous-orchestrator guardrail. One call = one
    experiment + (at most) one bridged iteration. To iterate again, a human
    invokes this again.

    Steps (executed once, in order):
      1. resolve the experiment via the tier registry; ASSERT it belongs to
         `tier`.
      2. if run_experiment: subprocess run.py then analyze.py under
         `env -u MOCK_LLM` (real model; guarded — default False so tests and
         dry-runs never invoke the model). if reuse_results: skip, use the
         already-committed results.
      3. build the experiment_outcome via the experiment's
         loop_bridge.build_experiment_outcome when present, else a minimal
         {experiment_id, metric, value} dict from summary.json.
      4. if replicate: call the matching replication_driver comparison
         (cross-rung for the auction experiments) and record it.
      5. if live: run_iteration(topic=<seed from outcome>, source="human_cli",
         experiment_outcome=outcome[, cross_tier_comparison]). else (dry-run):
         return the payload WITHOUT calling run_iteration.

    Returns: {tier, experiment_id, experiment_outcome,
              cross_tier_comparison (optional), iteration_id (when live),
              dry_run: bool}.
    """
    # UI observability: announce this autoresearch pass as the active run.
    # set_run_id stamps every wrapper call in this pass; active_run.json is
    # the single 'what is running now' file the UI polls. Cleared in finally
    # so both the dry-run early-return and the live path leave no stale state.
    from agent_wrapper.wrapper import get_run_id, set_run_id
    from orchestrator import active_run

    run_id = f"autoresearch_{experiment_id}_{uuid.uuid4().hex[:8]}"
    # Restore the PRIOR run_id on exit (not None) so an in-process parent
    # run — the coordinator's run_experiment action — keeps its own call
    # attribution (same nesting fix as nara.run_iteration, 2026-06-10).
    _prev_run_id = get_run_id()
    set_run_id(run_id)
    active_run.write_active_run(
        run_id, "autoresearch", f"autoresearch {experiment_id}")
    try:
        # Step 1 — resolve + tier-check.
        exp = _resolve_experiment(tier, experiment_id)

        # Step 2 — optionally (re)run the experiment. Guarded.
        if run_experiment and not reuse_results:
            _run_experiment_subprocess(exp, runtime)

        # Step 3 — build the experiment_outcome.
        outcome = _build_experiment_outcome(exp)
        if n is not None:
            # `n` is an advisory trial count surfaced into the bridged outcome;
            # it does not re-run anything (single-shot). Only set when the bridge
            # didn't already carry a trial count.
            outcome.setdefault("trials", n)

        # Step 4 — optional replication comparison.
        comparison = _build_replication(experiment_id) if replicate else None

        payload: dict[str, Any] = {
            "tier": tier,
            "experiment_id": experiment_id,
            "experiment_outcome": outcome,
            "dry_run": not live,
        }
        if comparison is not None:
            payload["cross_tier_comparison"] = comparison

        # Step 5 — dry-run returns the payload WITHOUT touching the model; live
        # threads it through exactly ONE run_iteration.
        if not live:
            return payload

        # Lazy import — run_iteration pulls in vLLM + chromadb.
        from orchestrator.nara import run_iteration

        topic = _topic_seed(outcome, comparison)
        kwargs: dict[str, Any] = {"experiment_outcome": outcome}
        if comparison is not None:
            kwargs["cross_tier_comparison"] = comparison
        record = run_iteration(topic=topic, source=source, **kwargs)
        payload["iteration_id"] = record.get("iteration_id")
        return payload
    finally:
        active_run.clear_active_run()
        set_run_id(_prev_run_id)


def _topic_seed(outcome: dict, comparison: dict | None) -> str:
    """Seed sentence for the LOOP_V0 chain, derived from the bridged outcome.

    Kept minimal and self-contained: a one-sentence hypothesis carrying the
    experiment id, metric, and value. (The richer per-experiment seeds live
    in each loop_bridge; this driver does not need to reimplement them.)"""
    return (
        f"Experiment {outcome['experiment_id']} reports "
        f"{outcome['metric']} = {outcome['value']}. Evaluate this finding "
        "against the literature: is it novel, and does it survive critique?"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "SINGLE-SHOT, human-triggered autoresearch driver. One invocation "
            "= one experiment + one bridged LOOP_V0 iteration. Honors the "
            "no-continuous-orchestrator guardrail (no loop/scheduler)."
        )
    )
    p.add_argument("--tier", required=True,
                   help="the tier the experiment must belong to (asserted)")
    p.add_argument("--experiment", required=True,
                   help="experiment id, e.g. exp004_combinatorial_auction")
    p.add_argument("--run", action="store_true", default=False,
                   help="(re)run the experiment via run.py+analyze.py under "
                        "env -u MOCK_LLM (real model). Default: reuse results.")
    p.add_argument("--n", type=int, default=None,
                   help="advisory trial count surfaced into the outcome")
    p.add_argument("--replicate", action="store_true", default=False,
                   help="also build the cross-rung replication comparison")
    p.add_argument("--live", action="store_true", default=False,
                   help="run the LOOP_V0 iteration (needs env -u MOCK_LLM + a "
                        "live backend). Default: dry-run, no model call.")
    args = p.parse_args(argv)

    payload = run_autoresearch(
        args.tier,
        args.experiment,
        reuse_results=not args.run,
        run_experiment=args.run,
        n=args.n,
        replicate=args.replicate,
        live=args.live,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
