"""The chain walker is forward-compatible: unknown call-log fields survive.

ui_plan.md section 5.2 / section 7: the week-1 build adds JSONL fields over
time. The walker keys only on the structural fields and passes everything
else through in `raw`, so a future day-2 schema addition must not break it.
"""
import json

from backend.chain import LogStore, build_chain
from backend.tests.fixtures.gen import write_fixtures


def test_unknown_optional_field_does_not_break_walk(tmp_path):
    write_fixtures(tmp_path)
    store = LogStore(tmp_path)
    chain = build_chain(store, "day6_task_01")
    worker_request_id = chain["root"]["children"][0]["request_id"]

    # Simulate a future schema addition: a call record with fields the
    # walker has never seen, appended into an existing chain.
    extra = {
        "request_id": "future-call-1",
        "parent_request_id": worker_request_id,
        "caller_tag": "wrapper",
        "timestamp": "2026-05-18T10:00:09.000+00:00",
        "latency_ms": 42,
        "experimental_cooperation_score": 0.83,          # unknown scalar
        "another_new_field": {"nested": True},           # unknown object
    }
    with open(tmp_path / "day6_5seq.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(extra) + "\n")

    # Same store: incremental refresh picks up the appended line.
    updated = build_chain(store, "day6_task_01")
    assert updated["node_count"] == chain["node_count"] + 1
    assert updated["total_latency_ms"] == chain["total_latency_ms"] + 42

    worker = updated["root"]["children"][0]
    new_nodes = [c for c in worker["children"] if c["request_id"] == "future-call-1"]
    assert len(new_nodes) == 1
    raw = new_nodes[0]["raw"]
    assert raw["experimental_cooperation_score"] == 0.83
    assert raw["another_new_field"] == {"nested": True}
