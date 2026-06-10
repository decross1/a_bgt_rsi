#!/usr/bin/env python3
# DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).
"""exp007 — paper-strategy memo writer (NO TRADING).

Consumes analyze.py's ``results/summary.json`` (verdict / BSS shape) plus
``edge_analysis.analyze_edges`` output, builds the memo record, validates
it against ``schema/strategy_memo.schema.json`` (validate-then-write,
mirroring orchestrator/gate_cli.py — an invalid record is REJECTED and
nothing is written), then writes ``strategy_memo.json`` +
``strategy_memo.md`` under ``--out-dir``.

The memo is retrodictive paper accounting only. The schema pins the
paper-only disclaimer as a const, so a memo missing it cannot validate.

Run (offline; reads the committed exp007 results by default):
    ./.venv-chroma/bin/python -m experiments.exp007_polymarket.strategy_memo
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp007_polymarket.edge_analysis import analyze_edges  # noqa: E402

EXP_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = REPO_ROOT / "schema" / "strategy_memo.schema.json"
_VALIDATOR = jsonschema.Draft7Validator(json.loads(SCHEMA_PATH.read_text()))

DISCLAIMER = (
    "PAPER STRATEGY ONLY. No real trading. No live capital at risk. "
    "For research purposes only. Do not use to place real orders."
)
RESULTS_PATH = "experiments/exp007_polymarket/results/summary.json"
PAPER_RULE = (
    "Hypothetical 1-unit stake per actionable market (abs(prob - market_prob) "
    "> threshold, resolved markets only): BUY YES at market_prob when edge > "
    "+threshold (pnl = outcome - market_prob); BUY NO at 1 - market_prob when "
    "edge < -threshold (pnl = (1 - outcome) - (1 - market_prob)). Retrodictive "
    "paper accounting only — no order is or will be placed."
)
LIMITATIONS = [
    "Retrodictive: forecasts were made on already-resolved markets, so this "
    "measures calibration against the frozen fetch-time price, not live "
    "tradability.",
    "Fixture prices, no order book: no slippage, no fees, no fill "
    "uncertainty, no position sizing; pnl units are not money.",
    "Small, non-random market sample; hypothetical units do not compound.",
    "Polymarket is design-only (CLAUDE.md out-of-scope) until CFTC "
    "compliance work is done; this memo must never drive a real order.",
]


def _render_md(record: dict) -> str:
    eo, ea = record["experiment_outcome"], record["edge_analysis"]
    lines = [
        "# exp007 — Polymarket PAPER strategy memo",
        "",
        f"> {record['disclaimer']}",
        "",
        f"**Headline:** {eo['summary']}",
        "",
        "## Top edges (hypothetical, retrodictive)",
        "",
        "| market_id | edge | side | pnl_units |",
        "| --- | --- | --- | --- |",
    ]
    for e in ea["top_edges"]:
        pnl = "—" if e["pnl_units"] is None else f"{e['pnl_units']:+.4f}"
        lines.append(f"| {e['market_id']} | {e['edge']:+.4f} "
                     f"| {e['side'] or '—'} | {pnl} |")
    lines += ["", "## Paper rule", "", record["paper_rule"], "",
              "Assumptions:", ""]
    lines += [f"- {a}" for a in ea["assumptions"]]
    lines += ["", "## Limitations", ""]
    lines += [f"- {l}" for l in record["limitations"]]
    return "\n".join(lines) + "\n"


def write_strategy_memo(summary: dict, edges: dict, *, out_dir,
                        clock_iso: str | None = None) -> dict:
    """Build, schema-validate, and write the memo record. Returns it.

    Raises jsonschema.ValidationError on an invalid record (e.g. a
    tampered disclaimer) — nothing is written in that case.
    """
    now = (datetime.fromisoformat(clock_iso.replace("Z", "+00:00"))
           if clock_iso else datetime.now(timezone.utc))
    edge_block = {k: v for k, v in edges.items() if k != "per_market"}
    edge_block["top_edges"] = sorted(
        edges.get("per_market", []),
        key=lambda e: abs(e["edge"]), reverse=True)[:5]
    record = {
        "strategy_id": "exp007_polymarket_" + now.strftime("%Y%m%dT%H%M%SZ"),
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "experiment_outcome": {
            "experiment_id": "exp007_polymarket",
            "metric": "brier_skill_score",
            "value": summary["bss"],
            "trials": summary["n"],
            "summary": (
                f"Verdict={summary.get('verdict')}. Brier Skill Score vs the "
                f"market-implied probability over {summary['n']} resolved "
                f"markets: {summary['bss']:.4f} (forecasting skill, not "
                "trading P&L)."
            ),
            "results_path": RESULTS_PATH,
        },
        "edge_analysis": edge_block,
        "paper_rule": PAPER_RULE,
        "limitations": list(LIMITATIONS),
        "disclaimer": DISCLAIMER,
    }
    errs = list(_VALIDATOR.iter_errors(record))
    if errs:
        raise jsonschema.ValidationError(
            f"strategy memo invalid: {errs[0].message} "
            f"(path: {list(errs[0].absolute_path)})")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "strategy_memo.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    (out_dir / "strategy_memo.md").write_text(_render_md(record))
    return record


def build_and_write_memo(
    *,
    forecasts_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    threshold: float = 0.05,
    out_dir: str | Path | None = None,
) -> dict:
    """Library entry for callers with no argv (the coordinator's
    forecast_markets handler): default-path memo build. Raises ordinary
    exceptions (FileNotFoundError, jsonschema.ValidationError) — NEVER
    SystemExit, which would escape the coordinator dispatch loop's
    `except Exception` and kill the whole cycle."""
    forecasts_path = Path(forecasts_path or EXP_DIR / "results" / "forecasts.jsonl")
    summary_path = Path(summary_path or EXP_DIR / "results" / "summary.json")
    out_dir = Path(out_dir or EXP_DIR / "results")
    rows = [json.loads(line)
            for line in forecasts_path.read_text().splitlines()
            if line.strip()]
    edges = analyze_edges(rows, threshold=threshold)
    return write_strategy_memo(json.loads(summary_path.read_text()),
                               edges, out_dir=out_dir)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="exp007 paper-strategy memo writer (NO TRADING)")
    p.add_argument("--forecasts",
                   default=str(EXP_DIR / "results" / "forecasts.jsonl"))
    p.add_argument("--summary",
                   default=str(EXP_DIR / "results" / "summary.json"))
    p.add_argument("--threshold", type=float, default=0.05)
    p.add_argument("--out-dir", default=str(EXP_DIR / "results"))
    args = p.parse_args(argv)

    forecasts_path, summary_path = Path(args.forecasts), Path(args.summary)
    if not forecasts_path.exists():
        raise SystemExit(f"FATAL: {forecasts_path} missing — run run.py first")
    if not summary_path.exists():
        raise SystemExit(
            f"FATAL: {summary_path} missing — run analyze.py first")
    rows = [json.loads(line)
            for line in forecasts_path.read_text().splitlines()
            if line.strip()]
    edges = analyze_edges(rows, threshold=args.threshold)
    record = write_strategy_memo(json.loads(summary_path.read_text()),
                                 edges, out_dir=args.out_dir)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
