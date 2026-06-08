#!/usr/bin/env python3
# EVAL-ONLY benchmark. Reads runs/*.jsonl ONLY. NEVER production logs/calls.jsonl.
"""exp008 — aggregate the QAT-vs-pin eval and emit a pre-registered verdict.

Reads every ``experiments/exp008_qat_eval/runs/*.jsonl`` (written by the eval
harnesses), aggregates a per-arm comparison table over four DECISION metrics:

  - novelty_agreement     (higher is better; agreement with the held reference)
  - calibration_error     (lower is better)
  - tool_call_adherence   (higher is better; share of well-formed tool calls)
  - robustness            (modal share + score variance from eval_robustness.py)

plus per-metric CONFUSION MATRICES (predicted-vs-reference verdict tallies
carried in the per-row payloads), and then applies the PRE-REGISTERED
materiality threshold from ``config.yaml`` to emit ONE verdict:

  - H0           : no material difference -> the production pin is vindicated.
  - H1           : QAT is materially better AND tool-call adherence holds
                   (does not regress past the floor) -> the gate opens.
  - INSUFFICIENT : small-N or a missing arm -> cannot decide either way.

The materiality threshold is PRE-REGISTERED in ``config.yaml`` and applied
mechanically here — it is never tuned to the result after the fact (CLAUDE.md
inviolate rule 4: validations are never silently coerced). If ``config.yaml``
is absent, a documented default (``_DEFAULT_CONFIG``) is used and the fact is
recorded in the output.

TERTIARY metrics — tokens/sec and memory footprint — are recorded if present
but are EXPLICITLY labeled non-comparable and NON-DECISION: arms run on a
scratch container with a different launch profile than production, so a tok/s
or memory delta MUST NOT move the verdict. They are reported for context only.

This module never calls a model, never hits the network, and never touches the
production endpoint or its logs. Pure file aggregation.

Run:
    ./.venv-chroma/bin/python experiments/exp008_qat_eval/analyze.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

EXP_DIR = Path(__file__).resolve().parent
RUNS_DIR = EXP_DIR / "runs"
CONFIG_PATH = EXP_DIR / "config.yaml"
RESULTS_MD_PATH = EXP_DIR / "RESULTS.md"
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"

# Reference arm: the verdict is read as QAT relative to this arm.
PIN_ARM = "pin"
QAT_ARM = "qat"

# Decision metrics and their polarity. "higher" = larger is better.
DECISION_METRICS = {
    "novelty_agreement": "higher",
    "calibration_error": "lower",
    "tool_call_adherence": "higher",
}

# Tertiary metrics: recorded but NEVER decision-bearing.
TERTIARY_METRICS = ("tok_per_s", "memory_gb")

# Pre-registered fallback if config.yaml is absent. The real pre-registration
# lives in config.yaml; this mirrors it so the analyzer is self-contained and
# deterministically testable offline.
_DEFAULT_CONFIG = {
    "materiality": {
        # A per-metric delta below this magnitude is "not material".
        "novelty_agreement": 0.05,
        "calibration_error": 0.02,
        "tool_call_adherence": 0.05,
    },
    # Tool-call adherence floor: H1 requires QAT adherence at or above this.
    "tool_call_adherence_floor": 0.90,
    # Minimum scored items per arm per metric to be decision-eligible.
    "min_sample": 10,
    # Robustness guard: modal share below this is "wobbly" (informational).
    "robustness_modal_share_min": 0.80,
}


# The threshold keys this analyzer's verdict logic actually reads. A config.yaml
# is only the decision source if it supplies these; otherwise the documented
# default thresholds drive the verdict and we say so (no silent coercion —
# CLAUDE.md inviolate rule 4).
_REQUIRED_MATERIALITY_KEYS = tuple(DECISION_METRICS.keys())
_REQUIRED_TOP_KEYS = ("tool_call_adherence_floor", "min_sample")


def _load_config() -> tuple[dict, str]:
    """Load the pre-registered config.

    Returns ``(config, source)`` where ``source`` is one of:
      - "config.yaml"        : config.yaml supplied all required threshold keys.
      - "default"            : config.yaml absent (or yaml unavailable).
      - "default (config.yaml present but lacks this analyzer's threshold keys)"
                             : config.yaml exists but does NOT carry the keys
                               THIS analyzer reads, so the documented default
                               thresholds drive the verdict. Reported honestly
                               rather than mislabeling the default as config.

    Whichever required keys the config does NOT supply are back-filled from the
    default so the verdict logic never KeyErrors; the source string records
    when that back-fill happened.
    """
    if not CONFIG_PATH.exists():
        return (_DEFAULT_CONFIG, "default")
    try:
        import yaml
    except ImportError:
        return (_DEFAULT_CONFIG, "default")
    with open(CONFIG_PATH) as fh:
        cfg = yaml.safe_load(fh) or {}
    if not isinstance(cfg, dict):
        return (_DEFAULT_CONFIG, "default")

    materiality = cfg.get("materiality", {}) if isinstance(cfg.get("materiality"), dict) else {}
    has_all = (
        all(k in materiality for k in _REQUIRED_MATERIALITY_KEYS)
        and all(k in cfg for k in _REQUIRED_TOP_KEYS)
    )

    # Back-fill any missing required keys from the default so verdict logic is
    # safe; provenance is reported via the source string.
    merged = {**_DEFAULT_CONFIG, **cfg}
    merged["materiality"] = {**_DEFAULT_CONFIG["materiality"], **materiality}

    if has_all:
        return (merged, "config.yaml")
    return (
        merged,
        "default (config.yaml present but lacks this analyzer's threshold keys)",
    )


def _load_rows() -> list[dict]:
    """Read every runs/*.jsonl row. Tolerates blank lines; skips bad JSON."""
    if not RUNS_DIR.exists():
        return []
    rows: list[dict] = []
    for path in sorted(RUNS_DIR.glob("*.jsonl")):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def _aggregate_arm(rows: list[dict]) -> dict:
    """Aggregate one arm's rows into the per-arm table entry.

    Quality rows are expected to be either:
      - {kind: "summary", arm, metric: "robustness", mean_modal_share, ...}
        (from eval_robustness.py), or
      - {arm, metric: <decision metric>, value, [reference_verdict],
        [predicted_verdict]} quality rows from the quality harness.
    Tertiary rows carry {arm, metric: <tertiary>, value}. We average values
    per metric and tally the n per decision metric.
    """
    decision: dict[str, list[float]] = defaultdict(list)
    tertiary: dict[str, list[float]] = defaultdict(list)
    confusion: dict[str, Counter] = defaultdict(Counter)
    robustness = None

    for r in rows:
        metric = r.get("metric")
        if metric == "robustness" and r.get("kind") == "summary":
            robustness = {
                "mean_modal_share": r.get("mean_modal_share"),
                "max_score_variance": r.get("max_score_variance"),
                "n_hypotheses": r.get("n_hypotheses"),
            }
            continue
        if r.get("kind") == "detail":
            continue  # robustness detail rows are audit-only
        if metric in DECISION_METRICS:
            if isinstance(r.get("value"), (int, float)):
                decision[metric].append(float(r["value"]))
            ref = r.get("reference_verdict")
            pred = r.get("predicted_verdict")
            if ref is not None and pred is not None:
                confusion[metric][(str(ref), str(pred))] += 1
        elif metric in TERTIARY_METRICS:
            if isinstance(r.get("value"), (int, float)):
                tertiary[metric].append(float(r["value"]))

    entry = {
        "decision_metrics": {
            m: {"mean": mean(v), "n": len(v)} for m, v in decision.items()
        },
        "tertiary_metrics": {
            m: {"mean": mean(v), "n": len(v),
                "non_decision": True,
                "note": "non-comparable across launch profiles; NOT a decision input"}
            for m, v in tertiary.items()
        },
        "confusion": {
            m: {f"{ref}->{pred}": c for (ref, pred), c in counter.items()}
            for m, counter in confusion.items()
        },
        "robustness": robustness,
    }
    return entry


def _metric_delta(qat_mean: float, pin_mean: float, polarity: str) -> float:
    """Signed improvement of QAT over pin (positive = QAT better)."""
    if polarity == "higher":
        return qat_mean - pin_mean
    return pin_mean - qat_mean  # lower is better -> improvement is pin - qat


def decide_verdict(arms: dict, config: dict) -> dict:
    """Apply the pre-registered threshold to emit H0 / H1 / INSUFFICIENT.

    Returns ``{verdict, reasons, per_metric}`` where per_metric records the
    signed QAT-over-pin delta and whether it cleared the materiality threshold.
    """
    reasons: list[str] = []

    # Missing arm -> cannot compare.
    if PIN_ARM not in arms or QAT_ARM not in arms:
        missing = [a for a in (PIN_ARM, QAT_ARM) if a not in arms]
        return {
            "verdict": "INSUFFICIENT",
            "reasons": [f"missing arm(s): {', '.join(missing)}"],
            "per_metric": {},
        }

    pin = arms[PIN_ARM]["decision_metrics"]
    qat = arms[QAT_ARM]["decision_metrics"]
    min_sample = config["min_sample"]
    materiality = config["materiality"]

    # Sample-size gate: every decision metric needs enough scored items on BOTH
    # arms, or we cannot decide.
    per_metric: dict[str, dict] = {}
    insufficient_metrics: list[str] = []
    for m in DECISION_METRICS:
        pin_m = pin.get(m)
        qat_m = qat.get(m)
        if pin_m is None or qat_m is None:
            insufficient_metrics.append(f"{m} (missing on an arm)")
            continue
        if pin_m["n"] < min_sample or qat_m["n"] < min_sample:
            insufficient_metrics.append(
                f"{m} (n={min(pin_m['n'], qat_m['n'])}<{min_sample})"
            )

    if insufficient_metrics:
        return {
            "verdict": "INSUFFICIENT",
            "reasons": ["small-N or missing metric: " + "; ".join(insufficient_metrics)],
            "per_metric": {},
        }

    # Compute signed deltas and materiality per decision metric.
    any_material_better = False
    any_material_worse = False
    for m, polarity in DECISION_METRICS.items():
        delta = _metric_delta(qat[m]["mean"], pin[m]["mean"], polarity)
        thresh = materiality[m]
        material = abs(delta) >= thresh
        per_metric[m] = {
            "qat_mean": qat[m]["mean"],
            "pin_mean": pin[m]["mean"],
            "delta_qat_over_pin": delta,
            "threshold": thresh,
            "material": material,
            "direction": "qat_better" if delta > 0 else ("qat_worse" if delta < 0 else "tie"),
        }
        if material and delta > 0:
            any_material_better = True
        if material and delta < 0:
            any_material_worse = True

    # Tool-call adherence floor (a hard guard for H1).
    floor = config["tool_call_adherence_floor"]
    qat_adherence = qat["tool_call_adherence"]["mean"]
    adherence_holds = qat_adherence >= floor

    # Verdict logic.
    if not any_material_better and not any_material_worse:
        verdict = "H0"
        reasons.append("no decision metric cleared its materiality threshold")
    elif any_material_better and not any_material_worse and adherence_holds:
        verdict = "H1"
        reasons.append("QAT materially better on at least one metric with no "
                       "material regression")
        reasons.append(f"tool-call adherence holds: {qat_adherence:.3f} >= floor {floor}")
    else:
        # Materially better somewhere but adherence fails the floor, or there is
        # a material regression -> the pin is not displaced.
        verdict = "H0"
        if any_material_better and not adherence_holds:
            reasons.append(f"QAT gains exist but tool-call adherence "
                           f"{qat_adherence:.3f} < floor {floor} -> gate stays closed")
        if any_material_worse:
            reasons.append("QAT materially regresses on at least one metric -> "
                           "pin not displaced")

    return {"verdict": verdict, "reasons": reasons, "per_metric": per_metric}


def analyze(rows: list[dict], config: dict, config_source: bool | str) -> dict:
    """Full aggregation + verdict. Pure; returns the summary dict.

    ``config_source`` is the provenance string from ``_load_config`` (e.g.
    "config.yaml" / "default" / "default (config.yaml present but ...)"). A bool
    is also accepted for back-compat (True == used the default).
    """
    if isinstance(config_source, bool):
        config_source = "default" if config_source else "config.yaml"
    used_default = not config_source.startswith("config.yaml")
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        arm = r.get("arm")
        if arm:
            by_arm[arm].append(r)

    arms = {arm: _aggregate_arm(arm_rows) for arm, arm_rows in by_arm.items()}
    decision = decide_verdict(arms, config)

    return {
        "verdict": decision["verdict"],
        "reasons": decision["reasons"],
        "per_metric": decision["per_metric"],
        "arms": arms,
        "config": {
            "source": config_source,
            "used_default": used_default,
            "materiality": config["materiality"],
            "tool_call_adherence_floor": config["tool_call_adherence_floor"],
            "min_sample": config["min_sample"],
            "robustness_modal_share_min": config["robustness_modal_share_min"],
        },
        "tertiary_disclaimer": (
            "tok/s and memory are recorded for context only; they are "
            "non-comparable across launch profiles and are NOT decision inputs."
        ),
    }


def _render_md(summary: dict) -> str:
    arms = summary["arms"]
    lines = [
        "# exp008 — QAT-vs-pin eval results",
        "",
        "EVAL-ONLY benchmark. The production pin was never swapped; all eval "
        "calls ran against the scratch container (:8002) and logged to "
        "`runs/*.jsonl`, never the production `logs/calls.jsonl`.",
        "",
        f"**Verdict: {summary['verdict']}**",
        "",
    ]
    for r in summary["reasons"]:
        lines.append(f"- {r}")
    lines += ["", "## Decision metrics (QAT over pin)", ""]
    if summary["per_metric"]:
        lines.append("| metric | pin | qat | delta (qat-pin) | threshold | material |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for m, d in summary["per_metric"].items():
            lines.append(
                f"| {m} | {d['pin_mean']:.4f} | {d['qat_mean']:.4f} | "
                f"{d['delta_qat_over_pin']:+.4f} | {d['threshold']} | "
                f"{'yes' if d['material'] else 'no'} |"
            )
    else:
        lines.append("_no decision-eligible metrics (see reasons above)_")

    lines += ["", "## Per-arm robustness (modal verdict stability)", ""]
    for arm, entry in sorted(arms.items()):
        rb = entry.get("robustness")
        if rb:
            lines.append(f"- **{arm}**: mean modal share {rb['mean_modal_share']:.3f}, "
                         f"max score variance {rb['max_score_variance']:.4f} "
                         f"({rb['n_hypotheses']} hypotheses)")
        else:
            lines.append(f"- **{arm}**: no robustness sweep present")

    lines += ["", "## Confusion matrices (reference -> predicted)", ""]
    for arm, entry in sorted(arms.items()):
        conf = entry.get("confusion") or {}
        if not conf:
            continue
        lines.append(f"### arm: {arm}")
        for metric, cells in conf.items():
            cell_str = ", ".join(f"{k}: {v}" for k, v in sorted(cells.items()))
            lines.append(f"- {metric}: {cell_str}")
        lines.append("")

    lines += ["## Tertiary metrics (NON-DECISION)", "",
              summary["tertiary_disclaimer"], ""]
    for arm, entry in sorted(arms.items()):
        tert = entry.get("tertiary_metrics") or {}
        if not tert:
            continue
        parts = ", ".join(f"{m}={d['mean']:.2f}" for m, d in tert.items())
        lines.append(f"- **{arm}** (non-comparable): {parts}")

    cfg = summary["config"]
    lines += ["", "## Pre-registered config", "",
              f"- source: {cfg['source']}"
              + (" (config.yaml absent — DEFAULT used)" if cfg["used_default"] else ""),
              f"- materiality thresholds: {cfg['materiality']}",
              f"- tool-call adherence floor: {cfg['tool_call_adherence_floor']}",
              f"- min sample per arm/metric: {cfg['min_sample']}",
              ""]
    return "\n".join(lines)


def main() -> int:
    config, config_source = _load_config()
    rows = _load_rows()
    summary = analyze(rows, config, config_source)

    SUMMARY_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    RESULTS_MD_PATH.write_text(_render_md(summary))

    print(f"wrote {SUMMARY_JSON_PATH}")
    print(f"wrote {RESULTS_MD_PATH}")
    print(f"verdict: {summary['verdict']}")
    for r in summary["reasons"]:
        print(f"  - {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
