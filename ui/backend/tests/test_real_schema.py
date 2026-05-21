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

from backend.chain import LogStore, build_chain_by_request_id

_REPO = Path(__file__).resolve().parents[3]
_SCHEMA = _REPO / "schema" / "calls.jsonl.schema.json"
_EVENTS_SCHEMA = _REPO / "schema" / "events.jsonl.schema.json"
_LOGS_DIR = _REPO / "logs"
_DAY2_LOG = _LOGS_DIR / "day2.jsonl"
_DAY4_E2E_LOG = _LOGS_DIR / "day4_e2e.jsonl"
_DAY4_ROBUST_LOG = _LOGS_DIR / "day4_robust.jsonl"

# The call-log fields the chain walker keys on (ui_plan.md section 4.2).
# Everything else is opaque passthrough rendered generically; these five
# are structural and must not drift out of the schema without notice.
_STRUCTURAL_FIELDS = ["request_id", "parent_request_id", "caller_tag",
                      "timestamp", "latency_ms"]

# The retrieval_context item keys the UI's reader + table commit to:
# backend chain.py passes the list through; the frontend RetrievalDoc type
# and ChainTree's RetrievalContext table render exactly these columns.
_RETRIEVAL_CONTEXT_KEYS = {"doc_id", "content_hash", "chunk_offset",
                           "chunk_length"}


def _load_jsonl(path):
    return [json.loads(line) for line
            in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _flatten(node):
    if node is None:
        return []
    out = [node]
    for child in node.get("children", []):
        out.extend(_flatten(child))
    return out


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


@pytest.mark.skipif(not _SCHEMA.exists(),
                    reason="apparatus has not committed schema/calls.jsonl.schema.json")
def test_retrieval_context_whitelisted_keys_match_ui():
    """The committed retrieval_context item keys match the UI's reader/table.

    Day 3.5 whitelisted retrieval_context as a property and kept
    additionalProperties:false. If Track A drifts the item keys, ChainTree's
    retrieval table renders the wrong columns — this fails loudly first.
    """
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    rc = schema.get("properties", {}).get("retrieval_context")
    assert rc is not None, "retrieval_context absent from committed schema"
    item = rc["items"]
    assert item.get("additionalProperties") is False, \
        "retrieval_context items must keep additionalProperties:false"
    assert set(item["properties"]) == _RETRIEVAL_CONTEXT_KEYS
    assert set(item["required"]) == _RETRIEVAL_CONTEXT_KEYS


@pytest.mark.skipif(not (_SCHEMA.exists() and _DAY4_E2E_LOG.exists()
                         and _DAY4_ROBUST_LOG.exists()),
                    reason="apparatus has not committed the day-4 call logs")
def test_real_day4_logs_validate_against_committed_schema():
    """Every day4_e2e.jsonl / day4_robust.jsonl record validates."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for log in (_DAY4_E2E_LOG, _DAY4_ROBUST_LOG):
        records = _load_jsonl(log)
        assert records, f"{log.name} is empty"
        for i, record in enumerate(records):
            errors = sorted(validator.iter_errors(record), key=str)
            assert not errors, f"{log.name} line {i + 1}: {errors[0].message}"


@pytest.mark.skipif(not _DAY4_ROBUST_LOG.exists(),
                    reason="apparatus has not committed logs/day4_robust.jsonl")
def test_read_robustness_on_real_day4_log():
    """read_robustness derives a real invocation rate from the chained log.

    Regression for the day-5 sync: the day-4 fixture modelled a per-trial
    summary, but Track A's real day4_robust.jsonl is a chained call log.
    The pre-sync reader keyed on an `invoked` flag and reported 0% against
    the real file.
    """
    from backend.day4 import read_robustness
    summary = read_robustness(_DAY4_ROBUST_LOG)
    assert summary["available"] is True
    assert summary["trial_count"] > 0
    # The regression: the pre-sync reader keyed on a per-trial `invoked`
    # flag the chained log does not carry and reported 0%. Assert the
    # property (a real, non-zero rate is derived), not the exact value —
    # the exact rate is a function of the sweep's data, not the reader.
    assert summary["invocation_rate"] is not None
    assert summary["invocation_rate"] > 0.0
    assert summary["invocations"] > 0
    assert summary["median_latency_ms"] is not None


@pytest.mark.skipif(not _DAY4_E2E_LOG.exists(),
                    reason="apparatus has not committed logs/day4_e2e.jsonl")
def test_real_day4_e2e_chain_synthesizes_completion_tool_call():
    """The real day4_e2e.jsonl chain renders a synthesized tool node.

    Track A logs the tool call in `completion` as an OpenAI-style JSON
    string (shape 3). build_chain_by_request_id must synthesize a
    kind="tool" child from it rather than leave it buried in raw text.
    """
    store = LogStore(_LOGS_DIR)
    store.refresh()
    roots = [r for r in _load_jsonl(_DAY4_E2E_LOG)
             if r.get("parent_request_id") is None]
    assert roots, "day4_e2e.jsonl has no wrapper-root record"
    result = build_chain_by_request_id(store, roots[0]["request_id"])
    assert result["found"] is True
    tool_nodes = [n for n in _flatten(result["root"]) if n["kind"] == "tool"]
    assert tool_nodes, "no tool node synthesized from the completion field"


@pytest.mark.skipif(not _EVENTS_SCHEMA.exists(),
                    reason="apparatus has not committed schema/events.jsonl.schema.json")
def test_events_fixtures_validate_against_committed_schema():
    """The day-4 events fixtures match the committed events schema.

    EventsViewer's per-type renderer is written from this schema; the
    fixtures must stay conformant so the frontend tests render real shapes.
    """
    jsonschema = pytest.importorskip("jsonschema")
    from backend.tests.fixtures.gen import EVENTS_FIXTURES
    schema = json.loads(_EVENTS_SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for event in EVENTS_FIXTURES:
        errors = sorted(validator.iter_errors(event), key=str)
        assert not errors, f"{event['event_type']}: {errors[0].message}"
