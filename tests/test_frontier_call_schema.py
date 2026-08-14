"""Tests for schema/frontier_call.schema.json (LOOP_V1 P2, spawn lv2-sdlc-docs-schema).

Covers:
  * Self-validation under Draft 2020-12; root closed; required set pinned.
  * The true seam test: a row actually written by
    agent_wrapper.frontier_cli.invoke_frontier's MOCK_LLM stub path (into a
    tmp_path ledger) validates against the schema -- the writer is the source
    of truth, and this test breaks if writer and schema ever drift.
  * Each required field, when removed, is rejected; extra properties rejected.
  * Field constraints: vendor enum, verdict enum, prompt_sha256 pattern,
    negative duration_ms, optional review-layer fields (candidate_id,
    reasoning_digest) accepted when present.

Hermetic: MOCK_LLM forced on, ledger in tmp_path, no subprocess ever spawned.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from agent_wrapper import frontier_cli as fc

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "frontier_call.schema.json"

REQUIRED_FIELDS = [
    "timestamp",
    "vendor",
    "cli_version",
    "role",
    "verdict",
    "duration_ms",
    "exit_code",
    "prompt_sha256",
]


def _schema():
    return json.loads(SCHEMA_PATH.read_text())


def _validator():
    return Draft202012Validator(_schema())


def _errors(row):
    return list(_validator().iter_errors(row))


@pytest.fixture
def stub_row(monkeypatch, tmp_path):
    """A row produced by the REAL writer (frontier_cli MOCK_LLM stub path)."""
    monkeypatch.setenv("MOCK_LLM", "1")

    def boom(*a, **k):  # pragma: no cover - failure path
        raise AssertionError("subprocess.run must not be called under MOCK_LLM")

    monkeypatch.setattr(fc.subprocess, "run", boom)
    ledger = tmp_path / "frontier_calls.jsonl"
    res = fc.invoke_frontier(
        "claude", "seam-test prompt", timeout_s=5, role="methods_reviewer",
        ledger_path=ledger,
    )
    assert res["error"] is None
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(rows) == 1
    return rows[0]


# ------------------------------------------------------- schema itself ------


def test_schema_is_a_valid_draft_2020_12_schema():
    Draft202012Validator.check_schema(_schema())


def test_required_set_is_pinned():
    # The writer always emits exactly these eight; pin so a future edit
    # relaxing or extending `required` fails loudly.
    assert sorted(_schema()["required"]) == sorted(REQUIRED_FIELDS)


def test_root_is_closed():
    assert _schema()["additionalProperties"] is False


# --------------------------------------------------- the true seam test -----


def test_writer_stub_row_validates(stub_row):
    assert _errors(stub_row) == []


def test_writer_stub_row_shape(stub_row):
    # Belt and braces on the writer's fixed fields at this layer.
    assert stub_row["verdict"] is None
    assert stub_row["cli_version"] == "mock"
    assert stub_row["exit_code"] == 0
    assert set(stub_row) == set(REQUIRED_FIELDS)


# ------------------------------------------------- rejection coverage -------


def test_each_missing_required_field_fails(stub_row):
    for field in REQUIRED_FIELDS:
        row = dict(stub_row)
        del row[field]
        assert _errors(row) != [], f"missing {field} should fail"


def test_extra_property_fails(stub_row):
    row = dict(stub_row)
    row["prompt"] = "raw prompt text"  # never logged, never allowed
    assert _errors(row) != []


def test_unknown_vendor_fails(stub_row):
    row = dict(stub_row)
    row["vendor"] = "gemini"
    assert _errors(row) != []


def test_non_null_verdict_in_enum_passes(stub_row):
    for verdict in ("veto", "pass", "inconclusive"):
        row = dict(stub_row)
        row["verdict"] = verdict
        assert _errors(row) == [], f"verdict {verdict} should pass"


def test_verdict_outside_enum_fails(stub_row):
    row = dict(stub_row)
    row["verdict"] = "maybe"
    assert _errors(row) != []


def test_bad_prompt_sha256_fails(stub_row):
    row = dict(stub_row)
    row["prompt_sha256"] = "not-a-hex-digest"
    assert _errors(row) != []


def test_negative_duration_fails(stub_row):
    row = dict(stub_row)
    row["duration_ms"] = -1
    assert _errors(row) != []


def test_timeout_and_launch_failure_exit_codes_pass(stub_row):
    # The writer emits -1 on timeout and 127 on launch failure.
    for code in (-1, 127):
        row = dict(stub_row)
        row["exit_code"] = code
        assert _errors(row) == [], f"exit_code {code} should pass"


def test_optional_review_layer_fields_pass(stub_row):
    # candidate_id / reasoning_digest: declared per LOOP_V1 P2 for the
    # review layer, optional because frontier_cli does not write them.
    row = dict(stub_row)
    row["candidate_id"] = "cand-2026-08-14-001"
    row["reasoning_digest"] = "novelty overlap with prior cluster"
    assert _errors(row) == []
    row["candidate_id"] = None
    row["reasoning_digest"] = None
    assert _errors(row) == []
