"""Unit tests for exp007 edge_analysis + strategy_memo (PAPER ONLY).

DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).

Hand-computed fixture with binary-exact probabilities so the paper-pnl
arithmetic asserts EXACTLY (no almost-equal). No LLM, no network — green
under MOCK_LLM (the default shell env); writes only under tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp007_polymarket import strategy_memo
from experiments.exp007_polymarket.edge_analysis import analyze_edges

SCHEMA = json.loads(
    (REPO_ROOT / "schema" / "strategy_memo.schema.json").read_text())

# 4 resolved rows + 1 unresolved. Probs are exact binary fractions.
FIXTURE_ROWS = [
    # yes-edge WIN: edge=+0.25 > 0.05 -> BUY YES @0.5, pnl = 1 - 0.5 = +0.5
    {"market_id": "m1", "prob": 0.75, "market_prob": 0.5, "outcome": 1.0},
    # yes-edge LOSS: edge=+0.25 -> BUY YES @0.5, pnl = 0 - 0.5 = -0.5
    {"market_id": "m2", "prob": 0.75, "market_prob": 0.5, "outcome": 0.0},
    # no-edge WIN: edge=-0.25 -> BUY NO @0.5, pnl = (1-0) - (1-0.5) = +0.5
    {"market_id": "m3", "prob": 0.25, "market_prob": 0.5, "outcome": 0.0},
    # below threshold: edge=0.0 -> no action
    {"market_id": "m4", "prob": 0.5, "market_prob": 0.5, "outcome": 1.0},
    # unresolved: big edge (0.625) but outcome None -> never actionable
    {"market_id": "m5", "prob": 0.875, "market_prob": 0.25, "outcome": None},
]

# analyze.py summary.json shape (verdict/n/briers/bss/note/errors/min_sample).
SUMMARY = {
    "verdict": "BELOW_MARKET",
    "n": 4,
    "mean_brier_model": 0.21,
    "mean_brier_market": 0.19,
    "bss": -0.1053,
    "calibration_note": "model trails market over 4 resolved rows",
    "errors": 0,
    "min_sample": 10,
}


def test_edge_counts_and_pnl_exact():
    out = analyze_edges(FIXTURE_ROWS, threshold=0.05)
    assert out["threshold"] == 0.05
    assert out["n_total"] == 5
    assert out["n_skipped"] == 0
    assert out["n_resolved"] == 4
    assert out["n_actionable"] == 3
    # mean |edge| over RESOLVED rows only: (0.25 + 0.25 + 0.25 + 0.0) / 4
    assert out["mean_abs_edge"] == 0.1875
    assert out["hypothetical_pnl_units"] == 0.5  # +0.5 - 0.5 + 0.5
    assert out["hit_rate"] == 2 / 3  # 2 of 3 paper bets with pnl > 0


def test_per_market_sides_and_pnls_exact():
    out = analyze_edges(FIXTURE_ROWS, threshold=0.05)
    by_id = {e["market_id"]: e for e in out["per_market"]}
    assert len(by_id) == 5
    assert by_id["m1"]["side"] == "yes" and by_id["m1"]["pnl_units"] == 0.5
    assert by_id["m2"]["side"] == "yes" and by_id["m2"]["pnl_units"] == -0.5
    assert by_id["m3"]["side"] == "no" and by_id["m3"]["pnl_units"] == 0.5
    assert by_id["m4"]["side"] is None and by_id["m4"]["pnl_units"] is None
    # unresolved: edge still reported, but no side / no pnl
    assert by_id["m5"]["edge"] == 0.625
    assert by_id["m5"]["side"] is None and by_id["m5"]["pnl_units"] is None


def test_malformed_rows_skipped_not_raised():
    rows = FIXTURE_ROWS + [
        # run.py error-row shape (no prob/market_prob)
        {"market_id": "e1", "error": "TimeoutError: boom", "wall_s": 1.2},
        {"market_id": "e2", "prob": "high", "market_prob": 0.5, "outcome": 1.0},
    ]
    out = analyze_edges(rows, threshold=0.05)
    assert out["n_total"] == 7
    assert out["n_skipped"] == 2
    assert out["n_resolved"] == 4 and out["n_actionable"] == 3
    assert len(out["per_market"]) == 5  # n_total - n_skipped


def test_no_actionable_hit_rate_null():
    out = analyze_edges(
        [{"market_id": "m", "prob": 0.5, "market_prob": 0.5, "outcome": 1.0}])
    assert out["n_actionable"] == 0
    assert out["hit_rate"] is None
    assert out["hypothetical_pnl_units"] == 0.0
    assert any("slippage" in a for a in out["assumptions"])


def test_memo_round_trip(tmp_path):
    edges = analyze_edges(FIXTURE_ROWS, threshold=0.05)
    record = strategy_memo.write_strategy_memo(
        SUMMARY, edges, out_dir=tmp_path, clock_iso="2026-06-10T12:00:00Z")
    jsonschema.validate(record, SCHEMA)  # record validates vs the schema
    assert record["strategy_id"] == "exp007_polymarket_20260610T120000Z"
    assert record["disclaimer"] == strategy_memo.DISCLAIMER
    eo = record["experiment_outcome"]
    assert eo["experiment_id"] == "exp007_polymarket"
    assert eo["metric"] == "brier_skill_score"
    assert eo["value"] == SUMMARY["bss"] and eo["trials"] == SUMMARY["n"]
    assert "BELOW_MARKET" in eo["summary"]
    # per_market dropped; top_edges = up-to-5 largest-|edge| entries
    assert "per_market" not in record["edge_analysis"]
    tops = record["edge_analysis"]["top_edges"]
    assert len(tops) == 5 and tops[0]["market_id"] == "m5"
    # written artifacts: json parses back to the record; md leads with the
    # disclaimer (blockquote before the headline), verbatim
    on_disk = json.loads((tmp_path / "strategy_memo.json").read_text())
    assert on_disk == record
    md = (tmp_path / "strategy_memo.md").read_text()
    assert strategy_memo.DISCLAIMER in md
    assert md.index(strategy_memo.DISCLAIMER) < md.index("Headline")


def test_disclaimer_is_schema_const():
    assert (SCHEMA["properties"]["disclaimer"]["const"]
            == strategy_memo.DISCLAIMER)


def test_tampered_disclaimer_rejected_nothing_written(tmp_path, monkeypatch):
    monkeypatch.setattr(strategy_memo, "DISCLAIMER", "trust me")
    edges = analyze_edges(FIXTURE_ROWS)
    with pytest.raises(jsonschema.ValidationError):
        strategy_memo.write_strategy_memo(SUMMARY, edges, out_dir=tmp_path)
    assert not (tmp_path / "strategy_memo.json").exists()
    assert not (tmp_path / "strategy_memo.md").exists()


def test_cli_smoke(tmp_path, capsys):
    forecasts = tmp_path / "forecasts.jsonl"
    forecasts.write_text(
        "\n".join(json.dumps(r) for r in FIXTURE_ROWS) + "\n")
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(SUMMARY))
    out_dir = tmp_path / "out"
    rc = strategy_memo.main([
        "--forecasts", str(forecasts), "--summary", str(summary_path),
        "--threshold", "0.05", "--out-dir", str(out_dir)])
    assert rc == 0
    assert (out_dir / "strategy_memo.json").exists()
    assert (out_dir / "strategy_memo.md").exists()
    printed = json.loads(capsys.readouterr().out)
    assert printed["disclaimer"] == strategy_memo.DISCLAIMER
