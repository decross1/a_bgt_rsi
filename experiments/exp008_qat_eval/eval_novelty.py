#!/usr/bin/env python3
"""exp008 / quality eval — NOVELTY AGREEMENT (the binding-relevant metric).

Measures whether a QAT-quantized arm reproduces the loop's ACTUAL novelty
behavior, not a re-implementation of it. We import the real worker
(`workers.novelty_classify`) and the real prompt/parsing it carries, drive it
over the ground-truth calibration fixtures, and score the arm's tier
agreement, a 4-class confusion matrix, and calibration error vs the
ground-truth novelty scores.

EVAL-ONLY. This script never touches the production pin, the serial spine,
the production calls log, or run_state/. It:
  - stages synthetic neighbors into a SCRATCH iteration cache under this
    experiment's runs/ dir (CACHE_ROOT is redirected at import time, so the
    real worker reads from there instead of run_state/iteration_cache/);
  - routes the model call through a scratch backend pointed at the arm's
    endpoint (e.g. the QAT container on :8002), NEVER the production :8000;
  - logs one row per (arm, fixture) to runs/novelty_<arm>.jsonl.

Greedy decoding (temperature 0), one request at a time.

CLI:
  --arm    NAME              arm label (used in the output filename + rows)
  --config PATH             optional JSON: {"endpoint": "...", "model": "..."}
  --endpoint URL           optional; OpenAI-compat base url for the arm
  --model NAME             optional; served-model-name for the arm
  --limit N                optional; only the first N fixtures (smoke)
  --fixtures-dir PATH      optional; override fixture directory

With NO endpoint (and no config endpoint) the script makes NO live call and
exits after reporting that the arm is offline — safe under MOCK_LLM.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXP_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES_DIR = REPO_ROOT / "experiments" / "fixtures" / "novelty_calibration"
RUNS_DIR = EXP_DIR / "runs"

# The four classes the REAL worker emits.
CLASSES = ("novel", "rediscovery", "nonsense", "unclear")

# Ground-truth fixtures live in a 4-tier novelty taxonomy
# (well_known/incremental/novel/surprising) that is NOT the worker's 4-class
# output space (novel/rediscovery/nonsense/unclear). To compute "exact-tier
# agreement" we project the ground-truth tier into the worker's space. This
# mapping is a documented benchmark decision, not a silent coercion:
#   well_known  -> rediscovery  (a known result in the literature)
#   incremental -> novel        (a real, if modest, new claim)
#   novel       -> novel
#   surprising  -> novel
# No fixture maps to nonsense/unclear (those are degenerate worker outcomes);
# the confusion matrix still spans all four classes so off-target arm outputs
# register on the off-diagonal.
TIER_TO_CLASS = {
    "well_known": "rediscovery",
    "incremental": "novel",
    "novel": "novel",
    "surprising": "novel",
}


def _stage_scratch_cache() -> Path:
    """Redirect the iteration cache to a scratch dir so the real worker reads
    from there instead of run_state/iteration_cache/. Returns the scratch
    root. Eval-only side effect; never writes under run_state/."""
    from orchestrator import iteration_cache

    scratch = Path(tempfile.mkdtemp(prefix="exp008_novelty_cache_"))
    iteration_cache.CACHE_ROOT = scratch
    return scratch


def _register_arm_backend(
    endpoint: str, model: str | None, *, allow_production: bool = False,
    arm: str | None = None,
) -> str:
    """Register an OpenAI-compat scratch backend for the arm's endpoint and
    return its registry name. Reuses the OllamaBackend class (it is a generic
    OpenAI-compat wrapper, same as the vLLM API).

    By default the production :8000 endpoint is REFUSED — a candidate arm must
    never accidentally be production. The ONE legitimate exception is the
    reference ('pin') arm: the benchmark's whole question is "does QAT match
    production", so the reference IS the production model, collected READ-ONLY.
    `allow_production=True` (wired to the `--reference` CLI flag) permits :8000
    for that read-only reference collection. Even then the worker's call log is
    redirected to runs/calls_<arm>.jsonl, so production logs/calls.jsonl is
    never written, and nothing here launches or reconfigures :8000."""
    from agent_wrapper.backends.ollama_openai import OllamaBackend
    from agent_wrapper.wrapper import register_backend

    # The production-read exception is scoped to the reference arm ONLY: a
    # candidate label must never reach :8000 (it would route candidate traffic
    # at production AND mislabel the output as a candidate). Enforce, not just
    # document, that allow_production is paired with --arm pin.
    if allow_production and arm != "pin":
        raise ValueError(
            f"refusing --reference for arm {arm!r}: the production-read "
            "exception is for the reference arm only — use --arm pin."
        )
    if ":8000" in endpoint and not allow_production:
        raise ValueError(
            f"refusing arm endpoint {endpoint!r}: :8000 is the production "
            "endpoint and is off-limits to a candidate arm. To collect the "
            "read-only production REFERENCE arm, pass --reference (and use "
            "--arm pin)."
        )
    name = "exp008-qat-arm"
    register_backend(
        OllamaBackend(
            name=name,
            base_url=endpoint,
            model=model or "qat-eval-model",
            model_version=f"exp008-qat/{model or 'qat-eval-model'}",
        )
    )
    return name


def load_fixtures(fixtures_dir: Path, limit: int | None = None) -> list[dict]:
    """Load calibration fixtures (sorted by filename), skipping the README."""
    out: list[dict] = []
    for p in sorted(fixtures_dir.glob("*.json")):
        out.append(json.loads(p.read_text()))
    if limit is not None:
        out = out[:limit]
    return out


def _synth_neighbor(fixture: dict) -> dict:
    """Turn a fixture's prior_art_summary into one synthetic neighbor so the
    real worker has retrieved evidence to reason over. The neighbor's doc_id
    is stable per fixture."""
    return {
        "doc_id": f"prior::{fixture['id']}",
        "score": 0.5,
        "title": f"prior art for {fixture['id']}",
        "source_layer": "fixture",
        "chunk_text": fixture.get("prior_art_summary", ""),
    }


def _classify_fixture(
    fixture: dict,
    *,
    classifier,
    model: str | None,
    log_path: str | None = None,
) -> dict:
    """Stage neighbors and run the REAL worker on one fixture. `classifier`
    is workers.novelty_classify.novelty_classify (or a test stub with the
    same signature). Returns the worker's result dict.

    NOTE: the worker does not take a `backend` kwarg — it routes through the
    wrapper's DEFAULT_BACKEND. The arm is selected by pointing that default at
    the scratch backend (see run_eval), so the worker's call_sync lands on the
    arm endpoint, never :8000."""
    from orchestrator import iteration_cache

    iter_id = f"exp008-novelty-{fixture['id']}"
    # Mirror the production cache shape: a tool_result wrapping the worker
    # payload under result.neighbors.
    iteration_cache.write_entry(
        iter_id,
        "retrieval",
        {"status": "passed", "result": {"neighbors": [_synth_neighbor(fixture)]}},
    )
    kwargs = {}
    if model is not None:
        kwargs["model"] = model
    # Redirect the real worker's call log into the eval's runs/ dir so a live
    # run NEVER writes to production logs/calls.jsonl (novelty_classify defaults
    # log_path to CALLS_LOG_PATH=logs/calls.jsonl otherwise). EVAL-ONLY isolation.
    if log_path is not None:
        kwargs["log_path"] = log_path
    return classifier(
        fixture["hypothesis_text"],
        iter_id,
        parent_request_id=f"exp008-{fixture['id']}",
        **kwargs,
    )


def _predicted_score(predicted_class: str) -> float:
    """Map a predicted class to a point on the 0-1 novelty axis so we can take
    a calibration error against the ground-truth score. rediscovery is low,
    novel is high; nonsense/unclear sit at the neutral midpoint (the worker is
    declining to place the claim, so we do not credit it either direction)."""
    return {
        "rediscovery": 0.1,
        "novel": 0.75,
        "nonsense": 0.5,
        "unclear": 0.5,
    }.get(predicted_class, 0.5)


def aggregate(rows: list[dict]) -> dict:
    """Compute per-arm metrics from the per-fixture rows.

    Returns:
      n
      agreement_rate           exact-tier agreement (predicted == projected GT)
      confusion                {gt_class: {pred_class: count}} over CLASSES
      calibration_error_mae    mean |predicted_score - ground_truth_score|
      per_fixture              echo of the rows for the report
    """
    n = len(rows)
    confusion = {gt: {pred: 0 for pred in CLASSES} for gt in CLASSES}
    agree = 0
    abs_err = 0.0
    for r in rows:
        gt = r["gt_class"]
        pred = r["predicted_class"]
        if gt in confusion and pred in confusion[gt]:
            confusion[gt][pred] += 1
        if pred == gt:
            agree += 1
        abs_err += abs(r["predicted_score"] - r["ground_truth_score"])
    return {
        "n": n,
        "agreement_rate": (agree / n) if n else 0.0,
        "confusion": confusion,
        "calibration_error_mae": (abs_err / n) if n else 0.0,
        "per_fixture": rows,
    }


def run_eval(
    *,
    arm: str,
    classifier,
    fixtures: list[dict],
    model: str | None,
    runs_dir: Path = RUNS_DIR,
) -> dict:
    """Drive the real worker over the fixtures and write one row per
    (arm, fixture). Returns the aggregate metrics. `classifier` is injected
    so tests can stub the model call without touching the wrapper.

    The arm endpoint is selected by the caller via the wrapper's
    DEFAULT_BACKEND (set in main() before this runs); `model` is the
    served-model-name passed through to the worker."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    out_path = runs_dir / f"novelty_{arm}.jsonl"
    # analyze.py consumes {arm, metric, value} rows; the rich per-fixture rows
    # above carry no `metric` key so analyze.py skips them. We emit the
    # decision-metric rows analyze.py reads to a SEPARATE file (distinct name so
    # novelty and toolcall metric files never collide) — closing the gap where a
    # live run produced rich rows but analyze.py found zero decision metrics.
    metrics_path = runs_dir / f"metrics_novelty_{arm}.jsonl"
    # Eval-local wrapper-call log — keeps real worker calls OUT of production
    # logs/calls.jsonl (the production_log_forbidden invariant in config.yaml).
    calls_log = str(runs_dir / f"calls_{arm}.jsonl")
    rows: list[dict] = []
    with open(out_path, "w") as fh, open(metrics_path, "w") as mfh:
        for fx in fixtures:
            result = _classify_fixture(
                fx, classifier=classifier, model=model, log_path=calls_log
            )
            predicted_class = (result.get("result") or {}).get("class") or "unclear"
            gt_tier = fx["ground_truth_tier"]
            gt_class = TIER_TO_CLASS.get(gt_tier, "unclear")
            gt_score = float(fx["ground_truth_novelty_score"])
            pred_score = _predicted_score(predicted_class)
            calib_err = abs(pred_score - gt_score)
            row = {
                "timestamp": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "arm": arm,
                "fixture_id": fx["id"],
                "ground_truth_tier": gt_tier,
                "gt_class": gt_class,
                "ground_truth_score": gt_score,
                "predicted_class": predicted_class,
                "predicted_score": pred_score,
                "agree": predicted_class == gt_class,
                "calibration_abs_err": calib_err,
                "worker_status": result.get("status"),
                "worker_errors": result.get("errors") or [],
                "wrapper_request_id": result.get("wrapper_request_id"),
            }
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            # analyze.py rows: novelty_agreement is the per-fixture exact-tier
            # hit (mean -> agreement_rate, n -> fixture count); calibration_error
            # is the per-fixture abs error (mean -> calibration_error_mae).
            mfh.write(json.dumps({
                "arm": arm,
                "metric": "novelty_agreement",
                "value": 1.0 if predicted_class == gt_class else 0.0,
                "reference_verdict": gt_class,
                "predicted_verdict": predicted_class,
            }) + "\n")
            mfh.write(json.dumps({
                "arm": arm,
                "metric": "calibration_error",
                "value": calib_err,
            }) + "\n")
    return aggregate(rows)


def _resolve_endpoint(args) -> tuple[str | None, str | None]:
    """Resolve (endpoint, model) from --endpoint/--model and/or --config."""
    endpoint = args.endpoint
    model = args.model
    if args.config:
        cfg = json.loads(Path(args.config).read_text())
        endpoint = endpoint or cfg.get("endpoint")
        model = model or cfg.get("model")
    return endpoint, model


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="exp008 novelty-agreement eval")
    ap.add_argument("--arm", required=True, help="arm label")
    ap.add_argument("--config", help="JSON config with endpoint/model")
    ap.add_argument("--endpoint", help="OpenAI-compat base url for the arm")
    ap.add_argument("--model", help="served-model-name for the arm")
    ap.add_argument("--limit", type=int, help="only first N fixtures (smoke)")
    ap.add_argument("--fixtures-dir", help="override fixture directory")
    ap.add_argument(
        "--reference", action="store_true",
        help="permit the READ-ONLY production :8000 endpoint to collect the "
             "reference ('pin') arm. Use with --arm pin. Without this flag "
             ":8000 is refused (candidate-arm guardrail).",
    )
    args = ap.parse_args(argv)

    fixtures_dir = Path(args.fixtures_dir) if args.fixtures_dir else FIXTURES_DIR
    fixtures = load_fixtures(fixtures_dir, limit=args.limit)

    endpoint, model = _resolve_endpoint(args)
    if not endpoint:
        print(
            json.dumps(
                {
                    "arm": args.arm,
                    "status": "offline",
                    "note": (
                        "no endpoint given; no live call made. Pass --endpoint "
                        "or --config with an endpoint to run the arm."
                    ),
                    "n_fixtures": len(fixtures),
                }
            )
        )
        return 0

    _stage_scratch_cache()
    backend = _register_arm_backend(
        endpoint, model, allow_production=args.reference, arm=args.arm
    )
    # Point the wrapper's default backend at the scratch arm so the real
    # worker's call_sync lands on the arm endpoint (never :8000). Eval-only.
    from agent_wrapper import wrapper as _wrapper

    _wrapper.DEFAULT_BACKEND = backend
    from workers.novelty_classify import novelty_classify

    metrics = run_eval(
        arm=args.arm,
        classifier=novelty_classify,
        fixtures=fixtures,
        model=model,
    )
    print(
        json.dumps(
            {
                "arm": args.arm,
                "endpoint": endpoint,
                "agreement_rate": metrics["agreement_rate"],
                "calibration_error_mae": metrics["calibration_error_mae"],
                "n": metrics["n"],
                "confusion": metrics["confusion"],
                "out": str(RUNS_DIR / f"novelty_{args.arm}.jsonl"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
