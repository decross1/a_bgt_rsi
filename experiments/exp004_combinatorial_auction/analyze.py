#!/usr/bin/env python3
"""exp004 — analyze trials.jsonl into a PER-MECHANISM truthfulness verdict.

exp004 is the HARDEST SYNTHETIC rung of the sandbox spectrum: combinatorial
auctions over two items with KNOWN, exactly-computable optimal solutions. It is
the on-ramp to — but is NOT yet — the semi-synthetic mechanism-DESIGN tier; the
mechanisms here are hand-written and verified against brute-force optimal
welfare, not designed by the model.

Reads ``results/trials.jsonl`` (written by ``run.py``). Each row is one trial
and carries the shared private valuations plus a per-mechanism block. The
expected per-trial schema is::

    {
      "trial": int,
      "valuations": [ {bundle_tuple_str: float}, ... ],   # one per bidder
      "mechanisms": {
        "<mechanism_name>": {
          "bids":        [ {bundle_tuple_str: float}, ... ],  # one per bidder
          "residuals":   [float, ...],   # flat per-bundle (bid - valuation)
          "reasonings":  [str, ...],      # one per bidder; parse failures are
                                          # prefixed "parse_failure" (see bidder)
          "allocative_efficiency": float,
          "revenue":     float
        },
        ...
      }
    }

PER MECHANISM we compute:
  - truthful_bid_fraction at eps=5 over the flat per-bundle residuals
  - mean allocative_efficiency
  - mean revenue
  - parse_failure_rate (fraction of bidder calls whose reasoning is a
    parse failure)

VERDICT per mechanism:
  - "YES" if truthful_bid_fraction >= 0.75
  - "NO"  otherwise
  - "INVALID" if parse_failure_rate > 0.25 — OVERRIDES the truthful test.
    On a parse failure the bidder defaults bid := valuation, so residual ≈ 0
    and the bid would FALSELY read as truthful. A run riddled with parse
    failures must never silently pass as a rediscovery; the gate makes it
    observable. (Carryover #4: validations are never silently coerced.)

Run:
    ./.venv-chroma/bin/python experiments/exp004_combinatorial_auction/analyze.py
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

EXP_DIR = Path(__file__).resolve().parent
TRIALS_PATH = EXP_DIR / "results" / "trials.jsonl"
SUMMARY_MD_PATH = EXP_DIR / "results" / "summary.md"
SUMMARY_JSON_PATH = EXP_DIR / "results" / "summary.json"

EPS_TIGHT = 5.0
TRUTHFUL_THRESHOLD = 0.75       # >= this truthful fraction -> YES
PARSE_FAILURE_GATE = 0.25       # > this parse-failure rate -> INVALID


def _load_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"FATAL: {path} does not exist — run run.py first")
    rows: list[dict] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _mechanism_names(rows: list[dict]) -> list[str]:
    """Stable, sorted union of mechanism names seen across non-error rows."""
    names: set[str] = set()
    for r in rows:
        if "error" in r:
            continue
        names.update((r.get("mechanisms") or {}).keys())
    return sorted(names)


def _is_parse_failure(reason) -> bool:
    return isinstance(reason, str) and reason.startswith("parse_failure")


def analyze_mechanism(rows: list[dict], name: str) -> dict:
    """Compute metrics + verdict for a single mechanism over all trials."""
    residuals: list[float] = []
    efficiencies: list[float] = []
    revenues: list[float] = []
    parse_failures = 0
    total_bidder_calls = 0

    for r in rows:
        if "error" in r:
            continue
        block = (r.get("mechanisms") or {}).get(name)
        if block is None:
            continue
        residuals.extend(float(x) for x in block.get("residuals", []))
        if "allocative_efficiency" in block:
            efficiencies.append(float(block["allocative_efficiency"]))
        if "revenue" in block:
            revenues.append(float(block["revenue"]))
        reasonings = block.get("reasonings", [])
        total_bidder_calls += len(reasonings)
        parse_failures += sum(1 for reason in reasonings if _is_parse_failure(reason))

    n_resid = len(residuals)
    truthful = sum(1 for x in residuals if abs(x) <= EPS_TIGHT)
    truthful_fraction = truthful / n_resid if n_resid else 0.0
    mean_efficiency = mean(efficiencies) if efficiencies else 0.0
    mean_revenue = mean(revenues) if revenues else 0.0
    parse_failure_rate = (
        parse_failures / total_bidder_calls if total_bidder_calls else 0.0
    )

    # Parse-failure gate OVERRIDES the truthful test (carryover #4).
    if parse_failure_rate > PARSE_FAILURE_GATE:
        verdict = "INVALID"
    elif truthful_fraction >= TRUTHFUL_THRESHOLD:
        verdict = "YES"
    else:
        verdict = "NO"

    return {
        "mechanism": name,
        "truthful_fraction": truthful_fraction,
        "mean_efficiency": mean_efficiency,
        "mean_revenue": mean_revenue,
        "parse_failure_rate": parse_failure_rate,
        "verdict": verdict,
        # internal counts for the markdown narrative (not in summary.json schema)
        "_n_residuals": n_resid,
        "_truthful": truthful,
        "_parse_failures": parse_failures,
        "_total_bidder_calls": total_bidder_calls,
    }


def build_summary(rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    names = _mechanism_names(rows)
    per_mechanism = [analyze_mechanism(rows, name) for name in names]
    return {"per_mechanism": per_mechanism, "n_trials": len(ok)}


def _verdict_blurb(m: dict) -> str:
    if m["verdict"] == "INVALID":
        return (
            f"INVALID — parse_failure_rate {100*m['parse_failure_rate']:.1f}% "
            f"exceeds the {100*PARSE_FAILURE_GATE:.0f}% gate "
            f"({m['_parse_failures']}/{m['_total_bidder_calls']} bidder calls "
            "failed to parse; bid:=valuation would falsely read as truthful)."
        )
    return (
        f"{m['verdict']} — {m['_truthful']}/{m['_n_residuals']} per-bundle bids "
        f"({100*m['truthful_fraction']:.1f}%) within eps={EPS_TIGHT:.0f}, "
        f"threshold {100*TRUTHFUL_THRESHOLD:.0f}%."
    )


def render_markdown(summary: dict) -> str:
    body = [
        "# exp004 — combinatorial-auction truthfulness summary",
        "",
        "exp004 is the HARDEST SYNTHETIC rung: combinatorial auctions over two "
        "items with KNOWN optimal solutions. It is the on-ramp to — NOT yet — "
        "the semi-synthetic mechanism-DESIGN tier (the mechanisms here are "
        "hand-written and verified against brute-force optimal welfare).",
        "",
        f"Trials: {summary['n_trials']}",
        "",
        "## Per-mechanism verdicts",
        "",
    ]
    if not summary["per_mechanism"]:
        body.append("_No mechanisms found in trials.jsonl._")
    for m in summary["per_mechanism"]:
        body.extend([
            f"### {m['mechanism']}",
            "",
            f"**Verdict: {_verdict_blurb(m)}**",
            "",
            f"- truthful_fraction (eps={EPS_TIGHT:.0f}): "
            f"{m['truthful_fraction']:.3f}",
            f"- mean_efficiency: {m['mean_efficiency']:.3f}",
            f"- mean_revenue: {m['mean_revenue']:.2f}",
            f"- parse_failure_rate: {m['parse_failure_rate']:.3f}",
            "",
        ])
    body.extend([
        "## Verdict rule (pre-registered)",
        "",
        f"Per mechanism: YES iff truthful_fraction >= {TRUTHFUL_THRESHOLD}; "
        f"otherwise NO. BUT if parse_failure_rate > {PARSE_FAILURE_GATE}, the "
        "verdict is INVALID and overrides the truthful test — a high "
        "parse-failure run defaults bid:=valuation and would otherwise read as "
        "falsely truthful (carryover #4).",
        "",
    ])
    return "\n".join(body)


def _public_summary(summary: dict) -> dict:
    """summary.json schema — drops the internal _-prefixed narrative counts."""
    return {
        "per_mechanism": [
            {
                "mechanism": m["mechanism"],
                "truthful_fraction": m["truthful_fraction"],
                "mean_efficiency": m["mean_efficiency"],
                "mean_revenue": m["mean_revenue"],
                "parse_failure_rate": m["parse_failure_rate"],
                "verdict": m["verdict"],
            }
            for m in summary["per_mechanism"]
        ],
        "n_trials": summary["n_trials"],
    }


def main() -> int:
    rows = _load_rows(TRIALS_PATH)
    summary = build_summary(rows)

    SUMMARY_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_MD_PATH.write_text(render_markdown(summary))
    SUMMARY_JSON_PATH.write_text(json.dumps(_public_summary(summary), indent=2))

    print(f"wrote {SUMMARY_MD_PATH}")
    print(f"wrote {SUMMARY_JSON_PATH}")
    for m in summary["per_mechanism"]:
        print(f"  {m['mechanism']}: verdict={m['verdict']} "
              f"truthful={m['truthful_fraction']:.3f} "
              f"parse_fail={m['parse_failure_rate']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
