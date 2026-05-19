"""Healthy-baseline card is data-driven when sources exist, documented otherwise.

See ui_plan.md sections 5.3, 9 and backend/baseline.py.
"""
import json

from backend.baseline import compute_baseline


def _row(result, key):
    return next(r for r in result["rows"] if r["key"] == key)


def _write_bench(path, values):
    lines = ["prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s"]
    for i, v in enumerate(values):
        lines.append(f"{i},256,8.0,{v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_state(path, tok_s):
    path.write_text(json.dumps({"metric_log": {"day1_tokens_per_sec": tok_s}}),
                    encoding="utf-8")


def test_decode_row_is_measured_from_bench_and_state(tmp_path):
    bench = tmp_path / "day1.csv"
    state = tmp_path / "week1.state.json"
    _write_bench(bench, [31.34, 32.05, 32.03, 32.02, 32.05])
    _write_state(state, 32.03)

    row = _row(compute_baseline(bench, state), "decode_tok_per_s")
    assert row["source"] == "measured"
    assert "median 32.03" in row["value"] or "median 32.0" in row["value"]
    assert "5 prompts" in row["value"]
    assert "32.03 tok/s" in row["value"]                 # state metric_log
    assert row["documented"]                             # expected figure carried alongside


def test_decode_row_is_documented_when_no_sources(tmp_path):
    # Neither file exists — Track A may still be on day 1.
    row = _row(compute_baseline(tmp_path / "missing.csv",
                                tmp_path / "missing.json"), "decode_tok_per_s")
    assert row["source"] == "documented"
    assert "documented" not in row                       # no measured expectation to carry
    assert "NVFP4" in row["value"]


def test_decode_row_measured_from_state_alone(tmp_path):
    # metric_log populated but bench/day1.csv absent — still measured.
    state = tmp_path / "week1.state.json"
    _write_state(state, 52.0)
    row = _row(compute_baseline(tmp_path / "missing.csv", state), "decode_tok_per_s")
    assert row["source"] == "measured"
    assert "52.0 tok/s" in row["value"]


def test_unpopulated_metric_log_falls_back(tmp_path):
    # metric_log present but day1_tokens_per_sec is null (not yet measured).
    state = tmp_path / "week1.state.json"
    state.write_text(json.dumps({"metric_log": {"day1_tokens_per_sec": None}}),
                     encoding="utf-8")
    row = _row(compute_baseline(tmp_path / "missing.csv", state), "decode_tok_per_s")
    assert row["source"] == "documented"


def test_malformed_bench_csv_degrades(tmp_path):
    # A bench file with no usable decode column degrades, does not crash.
    bench = tmp_path / "day1.csv"
    bench.write_text("prompt_idx,elapsed_s\n0,8.0\n", encoding="utf-8")
    row = _row(compute_baseline(bench, tmp_path / "missing.json"), "decode_tok_per_s")
    assert row["source"] == "documented"


def test_non_decode_rows_stay_documented(tmp_path):
    _write_bench(tmp_path / "day1.csv", [32.0])
    result = compute_baseline(tmp_path / "day1.csv", tmp_path / "missing.json")
    for key in ("idle_power_w", "gpu_temp", "cpu_temp", "gpu_power", "stack"):
        assert _row(result, key)["source"] == "documented"
