"""Tests for orchestrator/gate_cli.py — the Step-8 human-gate feedback edge.

Covers:
  - a valid verdict appends exactly one schema-valid row
  - an invalid verdict (e.g. "great") raises and appends NOTHING
  - the CLI main() rejects an invalid verdict with a nonzero exit
  - timestamp is injectable (clock_iso) for determinism

Runs under MOCK_LLM (no real model touched); all IO is via tmp_path.
"""
import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator import gate_cli

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((REPO_ROOT / "schema" / "loop_feedback.schema.json").read_text())
_VALIDATOR = jsonschema.Draft7Validator(SCHEMA)

CLOCK = "2026-06-05T12:00:00Z"


def test_valid_verdict_appends_schema_valid_row(tmp_path):
    path = tmp_path / "loop_feedback.jsonl"
    row = gate_cli.append_feedback(
        "iter-2026-06-05-001",
        "valid",
        note="looks good",
        gated_by="derrick",
        path=path,
        clock_iso=CLOCK,
    )
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    on_disk = json.loads(lines[0])
    assert on_disk == row
    _VALIDATOR.validate(on_disk)
    assert on_disk == {
        "iteration_id": "iter-2026-06-05-001",
        "verdict": "valid",
        "note": "looks good",
        "gated_at": CLOCK,
        "gated_by": "derrick",
    }


@pytest.mark.parametrize("verdict", ["needs_revision", "invalid"])
def test_other_valid_verdicts_accepted(tmp_path, verdict):
    path = tmp_path / "loop_feedback.jsonl"
    row = gate_cli.append_feedback(
        "iter-2026-06-05-002", verdict, path=path, clock_iso=CLOCK
    )
    assert row["verdict"] == verdict
    _VALIDATOR.validate(json.loads(path.read_text().splitlines()[0]))


def test_invalid_verdict_raises_and_writes_nothing(tmp_path):
    path = tmp_path / "loop_feedback.jsonl"
    with pytest.raises(jsonschema.ValidationError):
        gate_cli.append_feedback(
            "iter-2026-06-05-003", "great", path=path, clock_iso=CLOCK
        )
    assert not path.exists()


def test_cli_main_rejects_invalid_verdict_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(gate_cli, "DEFAULT", tmp_path / "loop_feedback.jsonl")
    with pytest.raises(SystemExit) as exc:
        gate_cli.main(
            ["--iteration-id", "iter-2026-06-05-004", "--verdict", "great"]
        )
    assert exc.value.code != 0
    assert not (tmp_path / "loop_feedback.jsonl").exists()


def test_cli_main_valid_verdict_appends(tmp_path, monkeypatch):
    path = tmp_path / "loop_feedback.jsonl"
    monkeypatch.setattr(gate_cli, "DEFAULT", path)
    rc = gate_cli.main(
        ["--iteration-id", "iter-2026-06-05-005", "--verdict", "valid"]
    )
    assert rc == 0
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    _VALIDATOR.validate(json.loads(lines[0]))
