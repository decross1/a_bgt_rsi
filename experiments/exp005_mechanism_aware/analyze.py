#!/usr/bin/env python3
"""exp005 — analyze trials.jsonl into a PER-MECHANISM behaviour verdict.

exp005 sharpens exp004's rediscovery probe: the bidder is told each
mechanism's PAYMENT rule in plain mechanics (no auction-theory priming) and
bids SEPARATELY into each one. So unlike exp004 the bids DIFFER per mechanism,
and the headline signal is the MEAN SIGNED RESIDUAL (bid - valuation) per
mechanism:

  - first_price: a NEGATIVE mean signed residual = bid-SHADING (bidders bid
    below their value because they pay their own bid).
  - vcg: a mean signed residual ~0 = truthful (you pay others' harm, not your
    bid, so there is no reason to shade).

Reads ``results/trials.jsonl`` (written by run.py). Each row is one trial and
carries the shared private valuations plus a per-mechanism block. The expected
per-trial schema is::

    {
      "trial": int,
      "valuations": [ {bundle_tuple_str: float}, ... ],   # one per bidder
      "mechanisms": {
        "<mechanism_name>": {
          "bids":        [ {bundle_tuple_str: float}, ... ],
          "residuals":   [float, ...],   # flat per-bundle SIGNED (bid - val)
          "reasonings":  [str, ...],      # parse failures prefixed "parse_failure"
          "allocative_efficiency": float,
          "revenue":     float
        },
        ...
      }
    }

PER MECHANISM we compute:
  - truthful_fraction at eps=5 over the flat per-bundle |residuals|
  - mean_signed_residual (the shading signal; negative under first_price)
  - parse_failure_rate (fraction of bidder calls whose reasoning is a parse
    failure)

VERDICT per mechanism (same parse-failure-gated pattern as exp004):
  - "INVALID" if parse_failure_rate > 0.25 — OVERRIDES everything else.
    On a parse failure the bidder defaults bid := valuation, so the residual
    is ~0 and would FALSELY read as truthful (mean_signed_residual would be
    dragged toward 0, masking shading). A run riddled with parse failures must
    never silently pass. (Carryover #4: validations are never silently coerced.)
  - "YES" if truthful_fraction >= 0.75 (the model bid its value).
  - "NO"  otherwise (the model departed from its value — e.g. shading).

Run:
    ./.venv-chroma/bin/python experiments/exp005_mechanism_aware/analyze.py
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
    parse_failures = 0
    total_bidder_calls = 0

    for r in rows:
        if "error" in r:
            continue
        block = (r.get("mechanisms") or {}).get(name)
        if block is None:
            continue
        residuals.extend(float(x) for x in block.get("residuals", []))
        reasonings = block.get("reasonings", [])
        total_bidder_calls += len(reasonings)
        parse_failures += sum(1 for reason in reasonings if _is_parse_failure(reason))

    n_resid = len(residuals)
    truthful = sum(1 for x in residuals if abs(x) <= EPS_TIGHT)
    truthful_fraction = truthful / n_resid if n_resid else 0.0
    mean_signed_residual = mean(residuals) if residuals else 0.0
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
        "mean_signed_residual": mean_signed_residual,
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
            "failed to parse; bid:=valuation would falsely read as truthful "
            "and mask any shading)."
        )
    return (
        f"{m['verdict']} — {m['_truthful']}/{m['_n_residuals']} per-bundle bids "
        f"({100*m['truthful_fraction']:.1f}%) within eps={EPS_TIGHT:.0f}, "
        f"threshold {100*TRUTHFUL_THRESHOLD:.0f}%; "
        f"mean signed residual {m['mean_signed_residual']:+.2f}."
    )


def render_markdown(summary: dict) -> str:
    body = [
        "# exp005 — mechanism-aware bidding summary",
        "",
        "exp005 sharpens exp004's rediscovery probe: the bidder is told each "
        "mechanism's PAYMENT rule in plain mechanics (no auction-theory "
        "priming) and bids SEPARATELY into each one. The headline signal is "
        "the MEAN SIGNED RESIDUAL (bid - valuation): a NEGATIVE mean under "
        "first_price = bid-shading; ~0 under vcg = truthful.",
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
            f"- mean_signed_residual: {m['mean_signed_residual']:+.3f}",
            f"- parse_failure_rate: {m['parse_failure_rate']:.3f}",
            "",
        ])
    body.extend([
        "## Verdict rule (pre-registered)",
        "",
        f"Per mechanism: YES iff truthful_fraction >= {TRUTHFUL_THRESHOLD}; "
        f"otherwise NO. BUT if parse_failure_rate > {PARSE_FAILURE_GATE}, the "
        "verdict is INVALID and overrides everything — a high parse-failure "
        "run defaults bid:=valuation, which would read as falsely truthful and "
        "drag the mean signed residual toward 0, masking shading (carryover "
        "#4).",
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
                "mean_signed_residual": m["mean_signed_residual"],
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
              f"mean_signed_residual={m['mean_signed_residual']:+.3f} "
              f"parse_fail={m['parse_failure_rate']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
