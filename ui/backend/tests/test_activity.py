"""PAGE A (/api/activity) endpoint tests. Read-only over fixture logs;
each test builds its own FastAPI app with register(app, <tmp paths>)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.activity import register


# ─── fixtures ─────────────────────────────────────────────────────────

# An orchestrator dispatch (root) -> worker_invocation (running) for one
# in-flight task, plus a second task that has a clean receipt (passed).
ORCH_ROWS = [
    {"timestamp": "2026-05-23T05:15:43.5Z", "request_id": "root-1",
     "parent_request_id": None, "stage": "orchestrator_dispatch",
     "task_id": "seq-1", "task_type": "summarize_paper", "status": "dispatched",
     "worker_pid": 4242, "detail": "dispatching"},
    {"timestamp": "2026-05-23T05:15:43.6Z", "request_id": "inv-1",
     "parent_request_id": "root-1", "stage": "worker_invocation",
     "task_id": "seq-1", "task_type": "summarize_paper", "status": "running",
     "worker_pid": 4242, "detail": "spawning worker"},
    {"timestamp": "2026-05-23T05:16:10.0Z", "request_id": "root-2",
     "parent_request_id": None, "stage": "orchestrator_dispatch",
     "task_id": "seq-2", "task_type": "play_pd_match", "status": "dispatched",
     "worker_pid": 4343, "detail": "dispatching"},
    {"timestamp": "2026-05-23T05:16:14.0Z", "request_id": "rcpt-2",
     "parent_request_id": "root-2", "stage": "orchestrator_receipt",
     "task_id": "seq-2", "task_type": "play_pd_match", "status": "passed",
     "worker_pid": 4343, "detail": "worker returned"},
]

# A wrapper call-log line whose parent_request_id is the root_request_id
# of seq-1. build_chain's root.request_id == the latest orch record's
# parent_request_id (here "root-1" — the dispatch's own request_id), and
# the chain walk attaches call-log children keyed by that id. This is the
# real apparatus linkage (orchestrator_receipt.parent -> worker_invocation
# request_id -> wrapper call). See chain.py build_chain.
CALL_ROWS = [
    {"timestamp": "2026-05-23T05:15:44.0Z", "request_id": "call-a",
     "parent_request_id": "root-1", "caller_tag": "summarize_paper/llm",
     "latency_ms": 473.0, "completion": "ok"},
]

TELEMETRY_SAMPLE = {
    "timestamp": "2026-06-05T00:38:41.3Z",
    "processes": [
        {"pid": 4242, "name": "worker", "cpu_pct": 12.5, "rss_mb": 660.2, "threads": 8},
        {"pid": 9999, "name": "other", "cpu_pct": 1.0, "rss_mb": 50.0, "threads": 2},
    ],
}


def _write_logs(logs_dir: Path, *, orch=ORCH_ROWS, calls=CALL_ROWS) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "orchestrator.jsonl").write_text(
        "\n".join(json.dumps(r) for r in orch) + "\n", encoding="utf-8")
    if calls is not None:
        (logs_dir / "day_test.jsonl").write_text(
            "\n".join(json.dumps(r) for r in calls) + "\n", encoding="utf-8")


def _client(logs_dir: Path, telemetry: Path) -> TestClient:
    app = FastAPI()
    register(app, logs_dir=logs_dir, telemetry_file=telemetry)
    return TestClient(app)


# ─── graph ────────────────────────────────────────────────────────────

def test_graph_available_with_nodes_and_edges(tmp_path):
    logs = tmp_path / "logs"
    _write_logs(logs)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(json.dumps(TELEMETRY_SAMPLE) + "\n", encoding="utf-8")
    client = _client(logs, telemetry)
    payload = client.get("/api/activity/graph").json()
    assert payload["available"] is True
    ids = {n["id"] for n in payload["nodes"]}
    # Dispatch roots present (id == build_chain root.request_id, which is
    # the latest orch record's parent_request_id — the dispatch's own
    # request_id "root-1"/"root-2").
    assert "root-1" in ids
    assert "root-2" in ids
    # The wrapper call chained under root-1 is present and deep-linkable.
    call_node = next(n for n in payload["nodes"] if n["id"] == "call-a")
    assert call_node["request_id"] == "call-a"
    assert call_node["kind"] == "call"
    # Edge from the dispatch root to its child wrapper call exists.
    edge_pairs = {(e["source"], e["target"]) for e in payload["edges"]}
    assert ("root-1", "call-a") in edge_pairs
    # In-flight dispatch (seq-1, latest record = worker_invocation/running)
    # is colored 'active'; the receipt-passed one (seq-2) is 'ok'.
    root1 = next(n for n in payload["nodes"] if n["id"] == "root-1")
    root2 = next(n for n in payload["nodes"] if n["id"] == "root-2")
    assert root1["status"] == "active"
    assert root2["status"] == "ok"


def test_graph_node_ids_unique(tmp_path):
    logs = tmp_path / "logs"
    _write_logs(logs)
    client = _client(logs, tmp_path / "telemetry.jsonl")
    nodes = client.get("/api/activity/graph").json()["nodes"]
    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids))


def test_graph_available_false_when_orchestrator_absent(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    client = _client(logs, tmp_path / "telemetry.jsonl")
    payload = client.get("/api/activity/graph").json()
    assert payload["available"] is False
    assert payload["nodes"] == []
    assert payload["edges"] == []


def test_graph_tolerates_malformed_rows(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "orchestrator.jsonl").write_text(
        json.dumps(ORCH_ROWS[0]) + "\n"
        + "this-is-not-json\n"
        + json.dumps(ORCH_ROWS[2]) + "\n",
        encoding="utf-8")
    client = _client(logs, tmp_path / "telemetry.jsonl")
    payload = client.get("/api/activity/graph").json()
    # The malformed middle line is skipped (chain.py JsonlTailer tolerance);
    # both well-formed dispatch tasks still surface as dispatch root nodes.
    assert payload["available"] is True
    dispatch_nodes = [n for n in payload["nodes"] if n["kind"] == "dispatch"]
    assert len(dispatch_nodes) == 2
    assert payload["task_count"] == 2


def test_graph_caps_node_count_when_chain_explodes(tmp_path, monkeypatch):
    # A single task whose call chain is longer than the node budget must be
    # truncated, not rendered whole. Guards the /activity perf fix: one
    # experiment task can transitively pull in thousands of wrapper calls.
    monkeypatch.setattr("backend.activity.MAX_GRAPH_NODES", 4)
    logs = tmp_path / "logs"
    logs.mkdir()
    orch = [
        {"timestamp": "2026-05-23T05:15:43.5Z", "request_id": "root-1",
         "parent_request_id": None, "stage": "orchestrator_dispatch",
         "task_id": "seq-1", "task_type": "summarize_paper",
         "status": "dispatched", "worker_pid": 4242, "detail": "d"},
        {"timestamp": "2026-05-23T05:15:43.6Z", "request_id": "inv-1",
         "parent_request_id": "root-1", "stage": "worker_invocation",
         "task_id": "seq-1", "task_type": "summarize_paper",
         "status": "running", "worker_pid": 4242, "detail": "s"},
    ]
    # A linear chain of 20 wrapper calls under root-1 — far over the budget.
    calls = []
    parent = "root-1"
    for i in range(20):
        rid = f"call-{i}"
        calls.append({"timestamp": "2026-05-23T05:15:44.0Z", "request_id": rid,
                      "parent_request_id": parent, "caller_tag": f"step{i}",
                      "latency_ms": 1.0, "completion": "ok"})
        parent = rid
    (logs / "orchestrator.jsonl").write_text(
        "\n".join(json.dumps(r) for r in orch) + "\n", encoding="utf-8")
    (logs / "day_test.jsonl").write_text(
        "\n".join(json.dumps(r) for r in calls) + "\n", encoding="utf-8")
    client = _client(logs, tmp_path / "telemetry.jsonl")
    payload = client.get("/api/activity/graph").json()
    assert payload["available"] is True
    assert payload["truncated"] is True
    assert payload["node_limit"] == 4
    assert len(payload["nodes"]) == 4


def test_graph_overview_is_dispatch_only(tmp_path):
    # detail=overview returns one node per task (dispatch roots) and no
    # children/edges — the navigable default. detail=full expands the chain.
    logs = tmp_path / "logs"
    _write_logs(logs)  # seq-1 has a wrapper call (call-a) chained under it
    client = _client(logs, tmp_path / "telemetry.jsonl")

    overview = client.get("/api/activity/graph?detail=overview").json()
    assert overview["available"] is True
    assert overview["detail"] == "overview"
    kinds = {n["kind"] for n in overview["nodes"]}
    assert kinds == {"dispatch"}
    assert overview["edges"] == []
    # call-a (a wrapper call, depth 1) must NOT appear in the overview.
    assert all(n["id"] != "call-a" for n in overview["nodes"])

    full = client.get("/api/activity/graph?detail=full").json()
    assert any(n["id"] == "call-a" for n in full["nodes"])
    assert ("root-1", "call-a") in {
        (e["source"], e["target"]) for e in full["edges"]
    }


# ─── monitor ──────────────────────────────────────────────────────────

def test_monitor_active_and_proc_cross_reference(tmp_path):
    logs = tmp_path / "logs"
    _write_logs(logs)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(json.dumps(TELEMETRY_SAMPLE) + "\n", encoding="utf-8")
    client = _client(logs, telemetry)
    payload = client.get("/api/activity/monitor").json()
    assert payload["available"] is True
    assert payload["telemetry_available"] is True
    # seq-1 is dispatched (active); seq-2 passed (not active).
    active_ids = {a["task_id"] for a in payload["active"]}
    assert active_ids == {"seq-1"}
    seq1 = next(a for a in payload["active"] if a["task_id"] == "seq-1")
    assert seq1["worker_pid"] == 4242
    assert seq1["cpu_pct"] == 12.5
    assert seq1["rss_mb"] == 660.2


def test_monitor_rows_carry_detail_stage_and_last_activity(tmp_path):
    # enrich() must pass `detail` + `stage` straight through (it used to drop
    # them), and the monitor must report `last_activity_at` = the most recent
    # timestamp across recent tasks. These drive the HERO worker rows' "what
    # it's doing" + the idle empty-state's "last activity … ago".
    logs = tmp_path / "logs"
    _write_logs(logs)
    client = _client(logs, tmp_path / "telemetry.jsonl")
    payload = client.get("/api/activity/monitor").json()
    seq1 = next(a for a in payload["active"] if a["task_id"] == "seq-1")
    # seq-1's latest orchestrator record is the worker_invocation row.
    assert seq1["stage"] == "worker_invocation"
    assert seq1["detail"] == "spawning worker"
    # last_activity_at == the newest timestamp across all recent tasks
    # (seq-2's receipt at 05:16:14.0 is the max).
    assert payload["last_activity_at"] == "2026-05-23T05:16:14.0Z"


def test_monitor_idle_when_no_active_tasks(tmp_path):
    # All tasks resolved (none in an ACTIVE_STATUS): active is empty but the
    # monitor is still available and reports last_activity_at so the frontend
    # can render "No agents active — last activity … ago".
    logs = tmp_path / "logs"
    resolved = [
        {"timestamp": "2026-05-23T05:16:10.0Z", "request_id": "root-2",
         "parent_request_id": None, "stage": "orchestrator_dispatch",
         "task_id": "seq-2", "task_type": "play_pd_match", "status": "dispatched",
         "worker_pid": 4343, "detail": "dispatching"},
        {"timestamp": "2026-05-23T05:16:14.0Z", "request_id": "rcpt-2",
         "parent_request_id": "root-2", "stage": "orchestrator_receipt",
         "task_id": "seq-2", "task_type": "play_pd_match", "status": "passed",
         "worker_pid": 4343, "detail": "worker returned summary (747 chars)"},
    ]
    _write_logs(logs, orch=resolved, calls=None)
    client = _client(logs, tmp_path / "telemetry.jsonl")
    payload = client.get("/api/activity/monitor").json()
    assert payload["available"] is True
    assert payload["active"] == []
    assert payload["last_activity_at"] == "2026-05-23T05:16:14.0Z"


def test_monitor_last_activity_orders_by_instant_not_string(tmp_path):
    # Regression: last_activity_at must compare timestamps by instant, not by
    # raw ISO string. datetime.isoformat() drops the fractional second when
    # microseconds == 0 ('…14Z') but keeps it otherwise ('…14.5Z'). At the
    # same integer second, a string max compares '.' (0x2E) vs 'Z' (0x5A) and
    # so picks '…14.5Z' < '…14Z' WRONG — the .5s row IS the more recent one.
    logs = tmp_path / "logs"
    rows = [
        {"timestamp": "2026-05-23T05:16:14Z", "request_id": "root-a",
         "parent_request_id": None, "stage": "orchestrator_dispatch",
         "task_id": "seq-a", "task_type": "summarize_paper",
         "status": "dispatched", "worker_pid": 4242, "detail": "d"},
        {"timestamp": "2026-05-23T05:16:14Z", "request_id": "rcpt-a",
         "parent_request_id": "root-a", "stage": "orchestrator_receipt",
         "task_id": "seq-a", "task_type": "summarize_paper",
         "status": "passed", "worker_pid": 4242, "detail": "done"},
        {"timestamp": "2026-05-23T05:16:13Z", "request_id": "root-b",
         "parent_request_id": None, "stage": "orchestrator_dispatch",
         "task_id": "seq-b", "task_type": "play_pd_match",
         "status": "dispatched", "worker_pid": 4343, "detail": "d"},
        # Same integer second as seq-a's receipt, but with a fractional part —
        # this is the genuinely most-recent timestamp.
        {"timestamp": "2026-05-23T05:16:14.5Z", "request_id": "rcpt-b",
         "parent_request_id": "root-b", "stage": "orchestrator_receipt",
         "task_id": "seq-b", "task_type": "play_pd_match",
         "status": "passed", "worker_pid": 4343, "detail": "done"},
    ]
    _write_logs(logs, orch=rows, calls=None)
    client = _client(logs, tmp_path / "telemetry.jsonl")
    payload = client.get("/api/activity/monitor").json()
    # By-instant max picks the fractional ".5Z"; a string max would have
    # picked the bare "…14Z".
    assert payload["last_activity_at"] == "2026-05-23T05:16:14.5Z"


def test_monitor_synthetic_inference_marked(tmp_path):
    logs = tmp_path / "logs"
    _write_logs(logs)
    client = _client(logs, tmp_path / "telemetry.jsonl")
    payload = client.get("/api/activity/monitor").json()
    syn = payload["synthetic_inference"]
    assert syn["synthetic"] is True
    assert "worker_activity.jsonl" in syn["needs"]
    assert isinstance(syn["workers"], list) and syn["workers"]


def test_monitor_telemetry_absent_yields_null_metrics(tmp_path):
    logs = tmp_path / "logs"
    _write_logs(logs)
    # No telemetry file at all.
    client = _client(logs, tmp_path / "missing.jsonl")
    payload = client.get("/api/activity/monitor").json()
    assert payload["available"] is True
    assert payload["telemetry_available"] is False
    seq1 = next(a for a in payload["active"] if a["task_id"] == "seq-1")
    assert seq1["cpu_pct"] is None
    assert seq1["rss_mb"] is None


def test_monitor_available_false_when_orchestrator_absent(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    client = _client(logs, tmp_path / "telemetry.jsonl")
    payload = client.get("/api/activity/monitor").json()
    assert payload["available"] is False
    assert payload["active"] == []
    # Synthetic block still surfaced (with its marker) even when unavailable.
    assert payload["synthetic_inference"]["synthetic"] is True
