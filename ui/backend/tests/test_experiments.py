"""exp004 summary reader: data-driven when the results file exists, a
graceful empty-state otherwise. See backend/experiments.py.
"""
import json

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.experiments import compute_exp004_summary

# Mirrors the experiment writer's shape (per_mechanism + n_trials).
SAMPLE = {
    "per_mechanism": [
        {
            "mechanism": "first_price",
            "truthful_fraction": 0.965,
            "mean_efficiency": 0.9988418692882004,
            "mean_revenue": 82.93,
            "parse_failure_rate": 0.0,
            "verdict": "YES",
        },
        {
            "mechanism": "vcg",
            "truthful_fraction": 0.965,
            "mean_efficiency": 0.9988418692882004,
            "mean_revenue": 63.66,
            "parse_failure_rate": 0.0,
            "verdict": "YES",
        },
    ],
    "n_trials": 150,
}


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_reads_per_mechanism_summary(tmp_path):
    summary = tmp_path / "summary.json"
    _write(summary, SAMPLE)
    result = compute_exp004_summary(summary)
    assert result["available"] is True
    assert result["n_trials"] == 150
    assert len(result["per_mechanism"]) == 2
    first = result["per_mechanism"][0]
    assert first["mechanism"] == "first_price"
    assert first["truthful_fraction"] == 0.965
    assert first["mean_efficiency"] == 0.9988418692882004
    assert first["mean_revenue"] == 82.93
    assert first["verdict"] == "YES"


def test_absent_file_is_empty_state(tmp_path):
    result = compute_exp004_summary(tmp_path / "missing.json")
    assert result == {"available": False, "per_mechanism": [], "n_trials": None}


def test_malformed_json_degrades(tmp_path):
    summary = tmp_path / "summary.json"
    summary.write_text("{not json", encoding="utf-8")
    assert compute_exp004_summary(summary)["available"] is False


def test_missing_per_mechanism_degrades(tmp_path):
    summary = tmp_path / "summary.json"
    _write(summary, {"n_trials": 5})
    assert compute_exp004_summary(summary)["available"] is False


def test_non_numeric_fields_become_none(tmp_path):
    summary = tmp_path / "summary.json"
    _write(summary, {
        "per_mechanism": [
            {"mechanism": "vcg", "truthful_fraction": "n/a", "verdict": "YES"}
        ],
        "n_trials": "lots",
    })
    result = compute_exp004_summary(summary)
    assert result["available"] is True
    assert result["per_mechanism"][0]["truthful_fraction"] is None
    assert result["per_mechanism"][0]["mean_efficiency"] is None
    assert result["n_trials"] is None


def test_endpoint_serves_summary(tmp_path):
    summary = tmp_path / "summary.json"
    _write(summary, SAMPLE)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "loop_v1"}), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    (tmp_path / "logs").mkdir(exist_ok=True)
    app = create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=tmp_path / "day1.csv",
        mtp_csv=tmp_path / "mtp.csv",
        exp004_summary=summary,
    )
    body = TestClient(app).get("/api/experiments/exp004").json()
    assert body["available"] is True
    assert body["n_trials"] == 150
    assert {m["mechanism"] for m in body["per_mechanism"]} == {"first_price", "vcg"}


def test_endpoint_empty_state_when_absent(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "loop_v1"}), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    (tmp_path / "logs").mkdir(exist_ok=True)
    app = create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=tmp_path / "day1.csv",
        mtp_csv=tmp_path / "mtp.csv",
        exp004_summary=tmp_path / "missing.json",
    )
    body = TestClient(app).get("/api/experiments/exp004").json()
    assert body == {"available": False, "per_mechanism": [], "n_trials": None}
