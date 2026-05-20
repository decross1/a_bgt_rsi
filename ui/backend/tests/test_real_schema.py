"""The backend ingests the apparatus's real committed schema + day-2 logs.

ui_plan.md sections 4.2, 5.2, 10: the chain walker was developed against
fixtures while only the structural call-log fields were pinned. The
apparatus has since committed schema/calls.jsonl.schema.json and the first
real call log, logs/day2.jsonl (day 2). These tests check the backend
against the real artifacts — and skip cleanly when Track A has not
committed them yet, so the suite still passes on a fresh checkout.

Note: day-2 records are standalone calls (parent_request_id null — chains
start day 4), so there is no chain to walk and no orchestrator.jsonl; the
check here is that ingestion and indexing are clean against real data.
"""
import json
from pathlib import Path

import pytest

from backend.chain import LogStore

_REPO = Path(__file__).resolve().parents[3]
_SCHEMA = _REPO / "schema" / "calls.jsonl.schema.json"
_LOGS_DIR = _REPO / "logs"
_DAY2_LOG = _LOGS_DIR / "day2.jsonl"

# The call-log fields the chain walker keys on (ui_plan.md section 4.2).
# Everything else is opaque passthrough rendered generically; these five
# are structural and must not drift out of the schema without notice.
_STRUCTURAL_FIELDS = ["request_id", "parent_request_id", "caller_tag",
                      "timestamp", "latency_ms"]


def _load_jsonl(path):
    return [json.loads(line) for line
            in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.skipif(not _SCHEMA.exists(),
                    reason="apparatus has not committed schema/calls.jsonl.schema.json")
def test_structural_fields_present_in_committed_schema():
    """The walker's structural fields are all present and required."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    for field in _STRUCTURAL_FIELDS:
        assert field in props, f"{field} absent from committed schema properties"
        assert field in required, f"{field} not required by committed schema"


@pytest.mark.skipif(not (_SCHEMA.exists() and _DAY2_LOG.exists()),
                    reason="apparatus has not committed schema + logs/day2.jsonl")
def test_real_day2_log_validates_against_committed_schema():
    """Every logs/day2.jsonl record validates against the committed schema."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    records = _load_jsonl(_DAY2_LOG)
    assert records, "logs/day2.jsonl is empty"
    validator = jsonschema.Draft202012Validator(schema)
    for i, record in enumerate(records):
        errors = sorted(validator.iter_errors(record), key=str)
        assert not errors, f"day2.jsonl line {i + 1}: {errors[0].message}"


@pytest.mark.skipif(not _DAY2_LOG.exists(),
                    reason="apparatus has not committed logs/day2.jsonl")
def test_logstore_ingests_real_day2_log():
    """LogStore indexes the real day-2 call log by request_id without crashing."""
    store = LogStore(_LOGS_DIR)
    store.refresh()
    for record in _load_jsonl(_DAY2_LOG):
        assert record["request_id"] in store.calls_by_id
    # No orchestrator.jsonl until day 6 — no dispatches should be indexed.
    if not (_LOGS_DIR / "orchestrator.jsonl").exists():
        assert store.orch_by_task == {}
