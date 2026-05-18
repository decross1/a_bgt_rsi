"""Chain reconstruction is exact against known synthetic fixtures."""
import json

from backend.chain import LogStore, build_chain, recent_tasks
from backend.tests.fixtures.gen import TASKS, write_fixtures


def test_chain_reconstruction_is_exact(tmp_path):
    manifest = write_fixtures(tmp_path)
    store = LogStore(tmp_path)
    for task_id, expected in manifest.items():
        chain = build_chain(store, task_id)
        assert chain["found"] is True
        assert chain["malformed"] is False
        assert chain["node_count"] == expected["node_count"]
        assert chain["total_latency_ms"] == expected["total_latency_ms"]
        root = chain["root"]
        assert root["kind"] == "dispatch"
        assert root["task_id"] == task_id
        assert root["status"] == expected["status"]
        # the dispatch has exactly one child: the top "worker" call
        assert len(root["children"]) == 1
        assert root["children"][0]["caller_tag"] == "worker"


def test_unknown_task_not_found(tmp_path):
    write_fixtures(tmp_path)
    result = build_chain(LogStore(tmp_path), "no_such_task")
    assert result["found"] is False
    assert result["root"] is None


def test_parse_error_node_flagged(tmp_path):
    write_fixtures(tmp_path)
    chain = build_chain(LogStore(tmp_path), "day6_task_02")
    worker = chain["root"]["children"][0]
    parse_error_flags = [child["parse_error"] for child in worker["children"]]
    assert parse_error_flags.count(True) == 1


def test_nested_tool_calls_reconstructed(tmp_path):
    write_fixtures(tmp_path)
    chain = build_chain(LogStore(tmp_path), "exp001_round_07")
    worker = chain["root"]["children"][0]
    first_wrapper = worker["children"][0]
    assert [c["caller_tag"] for c in first_wrapper["children"]] == ["tool", "tool"]


def test_recent_tasks_latest_first(tmp_path):
    write_fixtures(tmp_path)
    tasks = recent_tasks(LogStore(tmp_path), limit=10)
    assert len(tasks) == len(TASKS)
    assert tasks[0]["task_id"] == "exp001_round_07"      # latest dispatch_ts
    statuses = {t["task_id"]: t["status"] for t in tasks}
    assert statuses["day6_task_03"] == "started"


def test_cycle_marked_malformed(tmp_path):
    # A re-run reused request id "AAA" -> parent_request_id forms a cycle.
    root = "ROOT-RID"
    (tmp_path / "orchestrator.jsonl").write_text(json.dumps({
        "task_id": "cyclic", "task_type": "t", "status": "passed",
        "worker_pid": 1, "parent_request_id": root,
        "dispatch_ts": "2026-05-18T10:00:00.000+00:00", "receipt_ts": None,
    }) + "\n")
    (tmp_path / "day6_5seq.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"request_id": "AAA", "parent_request_id": root, "caller_tag": "worker",
         "latency_ms": 10, "timestamp": "t"},
        {"request_id": "BBB", "parent_request_id": "AAA", "caller_tag": "wrapper",
         "latency_ms": 10, "timestamp": "t"},
        {"request_id": "AAA", "parent_request_id": "BBB", "caller_tag": "wrapper",
         "latency_ms": 10, "timestamp": "t"},
    ]) + "\n")
    chain = build_chain(LogStore(tmp_path), "cyclic")
    assert chain["found"] is True
    assert chain["malformed"] is True
