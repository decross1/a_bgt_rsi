"""Tests for orchestrator/calibration_cli.py — the pre-verdict calibration
writer of record (P4, ARCH §6.5.4).

Covers the happy path, the boundary inclusivity of [0,1], every rejection
case (out-of-range / NaN / Infinity / bool / empty prediction / empty ref-id),
the rule-4 anti-coercion assertion (an out-of-range value is NEVER written as a
clamped one), append-only, and the CLI main() stdout-envelope + reject contract.

Runs under MOCK_LLM=1 (no real model touched); all IO is via tmp_path with the
module DEFAULT monkeypatched — never the real run_state/events.jsonl.
"""
import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator import calibration_cli

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads(
    (REPO_ROOT / "schema" / "calibration_pre_verdict.schema.json").read_text()
)
_VALIDATOR = jsonschema.Draft7Validator(SCHEMA)

CLOCK = "2026-06-17T16:08:14Z"


# ----------------------------------------------------------- happy path

def test_happy_path_appends_one_schema_valid_row(tmp_path):
    path = tmp_path / "events.jsonl"
    row = calibration_cli.append_calibration(
        "F-1", "coop will rise", 0.7, "human:ui", path=path, clock_iso=CLOCK
    )
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    on_disk = json.loads(lines[0])
    assert on_disk == row
    _VALIDATOR.validate(on_disk)
    assert on_disk == {
        "event_type": "calibration_entry",
        "phase": "pre_verdict",
        "timestamp": CLOCK,
        "ref_id": "F-1",
        "prediction": "coop will rise",
        "confidence": 0.7,
        "by": "human:ui",
    }
    # confidence is a JSON number, not a string.
    assert isinstance(on_disk["confidence"], float)


def test_by_defaults_to_human(tmp_path):
    path = tmp_path / "events.jsonl"
    row = calibration_cli.append_calibration(
        "F-1", "x", 0.5, path=path, clock_iso=CLOCK
    )
    assert row["by"] == "human"


@pytest.mark.parametrize("conf", [0.0, 1.0])
def test_boundary_values_accepted(tmp_path, conf):
    # The interval is CLOSED: both 0.0 and 1.0 are valid.
    path = tmp_path / "events.jsonl"
    row = calibration_cli.append_calibration(
        "F-1", "x", conf, path=path, clock_iso=CLOCK
    )
    assert row["confidence"] == conf
    _VALIDATOR.validate(json.loads(path.read_text().splitlines()[0]))


# ----------------------------------------------------- rejection / rule 4

@pytest.mark.parametrize("conf", [1.5, -0.1, 2.0, 100.0])
def test_out_of_range_confidence_rejected_writes_nothing(tmp_path, conf):
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="in \\[0,1\\]"):
        calibration_cli.append_calibration("F-1", "x", conf, path=path, clock_iso=CLOCK)
    assert not path.exists()


@pytest.mark.parametrize("conf", [float("nan"), float("inf"), float("-inf")])
def test_nan_inf_confidence_rejected_writes_nothing(tmp_path, conf):
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="finite"):
        calibration_cli.append_calibration("F-1", "x", conf, path=path, clock_iso=CLOCK)
    assert not path.exists()


def test_bool_confidence_rejected(tmp_path):
    # bool is an int subclass — must be rejected explicitly (rule 4 / cockpit guard).
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="bool"):
        calibration_cli.append_calibration("F-1", "x", True, path=path, clock_iso=CLOCK)
    assert not path.exists()


@pytest.mark.parametrize("pred", ["", "   ", "\t\n"])
def test_empty_prediction_rejected(tmp_path, pred):
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="prediction"):
        calibration_cli.append_calibration("F-1", pred, 0.5, path=path, clock_iso=CLOCK)
    assert not path.exists()


@pytest.mark.parametrize("ref", ["", "   "])
def test_empty_ref_id_rejected(tmp_path, ref):
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="ref_id"):
        calibration_cli.append_calibration(ref, "x", 0.5, path=path, clock_iso=CLOCK)
    assert not path.exists()


def test_rule4_out_of_range_never_written_as_clamped(tmp_path):
    # The load-bearing anti-coercion assertion: a rejected 1.5 must NOT appear
    # on disk as a clamped 1.0 (or in any form). Nothing is written at all.
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError):
        calibration_cli.append_calibration("F-1", "x", 1.5, path=path, clock_iso=CLOCK)
    assert not path.exists()
    # And after a subsequent valid write, only the valid row exists — no clamp.
    calibration_cli.append_calibration("F-1", "x", 0.9, path=path, clock_iso=CLOCK)
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["confidence"] == 0.9
    assert all(r["confidence"] != 1.0 for r in rows)


# ----------------------------------------------------------- append-only

def test_append_only_two_rows_first_preserved(tmp_path):
    path = tmp_path / "events.jsonl"
    r1 = calibration_cli.append_calibration("F-1", "first", 0.3, path=path, clock_iso=CLOCK)
    r2 = calibration_cli.append_calibration("F-2", "second", 0.8, path=path, clock_iso=CLOCK)
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    assert rows == [r1, r2]
    assert rows[0]["prediction"] == "first"


# ----------------------------------------------------------------- CLI

def test_cli_main_happy_path(tmp_path, monkeypatch, capsys):
    path = tmp_path / "events.jsonl"
    monkeypatch.setattr(calibration_cli, "DEFAULT", path)
    rc = calibration_cli.main([
        "calibration", "--ref-id", "F-1", "--prediction", "x",
        "--confidence", "0.5", "--by", "human:ui",
    ])
    assert rc == 0
    out_row = json.loads(capsys.readouterr().out)
    on_disk = json.loads(path.read_text().splitlines()[0])
    assert out_row == on_disk
    assert out_row["event_type"] == "calibration_entry"
    assert out_row["phase"] == "pre_verdict"
    assert out_row["confidence"] == 0.5


def test_cli_main_out_of_range_returns_1_writes_nothing(tmp_path, monkeypatch, capsys):
    path = tmp_path / "events.jsonl"
    monkeypatch.setattr(calibration_cli, "DEFAULT", path)
    rc = calibration_cli.main([
        "calibration", "--ref-id", "F-1", "--prediction", "x", "--confidence", "1.5",
    ])
    assert rc == 1
    assert "rejected" in capsys.readouterr().err
    assert not path.exists()


def test_cli_main_non_float_confidence_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration_cli, "DEFAULT", tmp_path / "events.jsonl")
    with pytest.raises(SystemExit) as exc:
        calibration_cli.main([
            "calibration", "--ref-id", "F-1", "--prediction", "x",
            "--confidence", "abc",
        ])
    assert exc.value.code not in (0, None)
    assert not (tmp_path / "events.jsonl").exists()


def test_cli_main_missing_ref_id_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration_cli, "DEFAULT", tmp_path / "events.jsonl")
    with pytest.raises(SystemExit) as exc:
        calibration_cli.main([
            "calibration", "--prediction", "x", "--confidence", "0.5",
        ])
    assert exc.value.code not in (0, None)
    assert not (tmp_path / "events.jsonl").exists()


def test_cli_requires_calibration_subcommand_token(tmp_path, monkeypatch):
    # The argv the UI execs carries the 'calibration' subcommand token; the
    # bare flat form must be rejected so a UI built against the contract is not
    # silently wrong.
    monkeypatch.setattr(calibration_cli, "DEFAULT", tmp_path / "events.jsonl")
    with pytest.raises(SystemExit) as exc:
        calibration_cli.main([
            "--ref-id", "F-1", "--prediction", "x", "--confidence", "0.5",
        ])
    assert exc.value.code not in (0, None)
    assert not (tmp_path / "events.jsonl").exists()
