"""PAGE A (/api/activity) endpoint tests. Read-only over fixture logs;
each test builds its own FastAPI app with register(app, <tmp paths>)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
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


def _client(logs_dir: Path, telemetry: Path,
            active_run: Path | None = None,
            worker_activity: Path | None = None) -> TestClient:
    app = FastAPI()
    kwargs = {}
    if active_run is not None:
        kwargs["active_run_path"] = active_run
    # Default the worker_activity path to logs_dir/worker_activity.jsonl for the
    # tests that pre-date the path split (they write the file into logs_dir),
    # but let a test pin a path DISTINCT from logs_dir to prove the production
    # split (worker_activity lives in the primary checkout, logs_dir in the UI
    # worktree).
    kwargs["worker_activity_path"] = (
        worker_activity if worker_activity is not None
        else logs_dir / "worker_activity.jsonl")
    register(app, logs_dir=logs_dir, telemetry_file=telemetry, **kwargs)
    return TestClient(app)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── live calls (run-mode-agnostic "active now" signal) ───────────────

def test_monitor_live_calls_active_on_recent_wrapper_calls(tmp_path):
    # The exp-run blind spot: orchestrator rows are stale (ORCH_ROWS, 2026-05)
    # but a run is actively making wrapper calls (calls.jsonl, NOW). live_calls
    # must light up with the caller_tag + model even though active[] is empty.
    logs = tmp_path / "logs"
    _write_logs(logs)
    (logs / "calls.jsonl").write_text(
        json.dumps({"timestamp": _now_iso(), "caller_tag": "nara.run_iteration",
                    "model": "fake-model", "request_id": "live-1"}) + "\n",
        encoding="utf-8")
    lc = _client(logs, tmp_path / "telemetry.jsonl").get(
        "/api/activity/monitor").json()["live_calls"]
    assert lc["active"] is True
    assert lc["count"] >= 1
    assert lc["model"] == "fake-model"
    assert lc["caller_tags"][0]["tag"] == "nara.run_iteration"
    assert lc["last_call_at"] is not None


def test_monitor_live_calls_inactive_when_calls_are_old(tmp_path):
    # Only the stale 2026-05 day_test call -> outside the window -> not live.
    logs = tmp_path / "logs"
    _write_logs(logs)
    lc = _client(logs, tmp_path / "telemetry.jsonl").get(
        "/api/activity/monitor").json()["live_calls"]
    assert lc["active"] is False
    assert lc["count"] == 0


def test_monitor_live_calls_present_on_unavailable_path(tmp_path):
    # orchestrator.jsonl absent -> available False, but a run can still be
    # making calls — live_calls is computed regardless so the hero can light up.
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "calls.jsonl").write_text(
        json.dumps({"timestamp": _now_iso(), "caller_tag": "nara.run_iteration",
                    "model": "fake-model", "request_id": "live-1"}) + "\n",
        encoding="utf-8")
    payload = _client(logs, tmp_path / "telemetry.jsonl").get(
        "/api/activity/monitor").json()
    assert payload["available"] is False
    assert payload["live_calls"]["active"] is True


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


# ─── real inference internals (worker_activity.jsonl) ─────────────────

def test_monitor_real_inference_when_worker_activity_recent(tmp_path):
    # A recent worker_activity.jsonl row REPLACES the synthetic fixture. The
    # `synthetic` flag is load-bearing: it must be False only over genuinely
    # measured data. The latest row per task_id wins.
    logs = tmp_path / "logs"
    _write_logs(logs)
    rows = [
        {"timestamp": _now_iso(), "run_id": "exp-9", "task_id": "t/a",
         "tokens_generated": 100, "tokens_target": 512, "tok_per_s": 41.0,
         "eta_s": 10.0, "synthetic": False},
        # A SECOND, later row for the same task_id — the latest must win.
        {"timestamp": _now_iso(), "run_id": "exp-9", "task_id": "t/a",
         "tokens_generated": 220, "tokens_target": 512, "tok_per_s": 44.0,
         "eta_s": 6.6, "synthetic": False},
    ]
    (logs / "worker_activity.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    syn = _client(logs, tmp_path / "telemetry.jsonl").get(
        "/api/activity/monitor").json()["synthetic_inference"]
    assert syn["synthetic"] is False
    assert syn["source"] == "worker_activity.jsonl"
    assert len(syn["workers"]) == 1
    w = syn["workers"][0]
    assert w["task_id"] == "t/a"
    assert w["run_id"] == "exp-9"
    assert w["tokens_generated"] == 220  # latest row, not the first
    assert w["tok_per_s"] == 44.0


def test_monitor_falls_back_to_synthetic_when_worker_activity_stale(tmp_path):
    # An old (2026-05) worker_activity row is outside the window -> fall back to
    # the labelled synthetic fixture (synthetic:True). Never present a stale row
    # as live measurement.
    logs = tmp_path / "logs"
    _write_logs(logs)
    (logs / "worker_activity.jsonl").write_text(
        json.dumps({"timestamp": "2026-05-23T05:15:44.0Z", "run_id": None,
                    "task_id": "t/old", "tokens_generated": 5,
                    "tokens_target": 5, "tok_per_s": 1.0, "eta_s": 0.0,
                    "synthetic": False}) + "\n", encoding="utf-8")
    syn = _client(logs, tmp_path / "telemetry.jsonl").get(
        "/api/activity/monitor").json()["synthetic_inference"]
    assert syn["synthetic"] is True
    assert "worker_activity.jsonl" in syn["needs"]


def test_monitor_falls_back_to_synthetic_when_worker_activity_absent(tmp_path):
    # No worker_activity.jsonl at all -> labelled synthetic fixture.
    logs = tmp_path / "logs"
    _write_logs(logs)
    syn = _client(logs, tmp_path / "telemetry.jsonl").get(
        "/api/activity/monitor").json()["synthetic_inference"]
    assert syn["synthetic"] is True


def test_monitor_real_inference_sourced_from_path_distinct_from_logs_dir(tmp_path):
    # HIGH finding regression: in production logs_dir is the UI worktree logs
    # dir but worker_activity.jsonl is written to the PRIMARY checkout's logs
    # dir. _real_inference must read worker_activity_path, NOT logs_dir. Here the
    # file lives in a SEPARATE dir from logs_dir; if the router keyed off
    # logs_dir it would miss the file and fall back to synthetic. It must not.
    logs = tmp_path / "ui_worktree" / "logs"
    _write_logs(logs)
    primary_logs = tmp_path / "primary" / "logs"
    primary_logs.mkdir(parents=True)
    wa = primary_logs / "worker_activity.jsonl"
    wa.write_text(
        json.dumps({"timestamp": _now_iso(), "run_id": "exp-9", "task_id": "t/a",
                    "tokens_generated": 200, "tokens_target": 512,
                    "tok_per_s": 44.0, "eta_s": 6.6, "synthetic": False}) + "\n",
        encoding="utf-8")
    # No worker_activity.jsonl inside logs_dir — only in the distinct path.
    assert not (logs / "worker_activity.jsonl").exists()
    syn = _client(logs, tmp_path / "telemetry.jsonl", worker_activity=wa).get(
        "/api/activity/monitor").json()["synthetic_inference"]
    assert syn["synthetic"] is False
    assert syn["source"] == "worker_activity.jsonl"
    assert syn["workers"][0]["task_id"] == "t/a"


def test_monitor_drops_worker_activity_row_flagged_synthetic_true(tmp_path):
    # A row that flags ITSELF synthetic:True is a producer placeholder; it must
    # be dropped, not surfaced under the load-bearing synthetic:False block. The
    # only recent row here is synthetic:True -> fall back to the labelled fixture.
    logs = tmp_path / "logs"
    _write_logs(logs)
    (logs / "worker_activity.jsonl").write_text(
        json.dumps({"timestamp": _now_iso(), "run_id": None, "task_id": "t/ph",
                    "tokens_generated": 1, "tokens_target": 2, "tok_per_s": 0,
                    "eta_s": None, "synthetic": True}) + "\n", encoding="utf-8")
    syn = _client(logs, tmp_path / "telemetry.jsonl").get(
        "/api/activity/monitor").json()["synthetic_inference"]
    assert syn["synthetic"] is True
    assert "worker_activity.jsonl" in syn["needs"]


def test_monitor_real_inference_accepts_future_skew_timestamp(tmp_path):
    # A slightly-future timestamp (clock skew between the primary writer and the
    # UI reader) is still inside the window (ts > cutoff) and counts as live.
    # Documents the current behavior so a future change to clamp future skew is
    # a deliberate, tested decision rather than a silent regression.
    from datetime import timedelta
    logs = tmp_path / "logs"
    _write_logs(logs)
    future = (datetime.now(timezone.utc) + timedelta(seconds=5)) \
        .isoformat().replace("+00:00", "Z")
    (logs / "worker_activity.jsonl").write_text(
        json.dumps({"timestamp": future, "run_id": "exp-f", "task_id": "t/f",
                    "tokens_generated": 10, "tokens_target": 512,
                    "tok_per_s": 40.0, "eta_s": 12.5, "synthetic": False}) + "\n",
        encoding="utf-8")
    syn = _client(logs, tmp_path / "telemetry.jsonl").get(
        "/api/activity/monitor").json()["synthetic_inference"]
    assert syn["synthetic"] is False
    assert syn["workers"][0]["task_id"] == "t/f"


def test_monitor_real_inference_passes_through_null_eta(tmp_path):
    # A real row with tok_per_s 0 -> producer writes eta_s null. The backend
    # passes it through verbatim (synthetic:False); the frontend renders the
    # bare dash. Proves eta_s null reaches the live panel as a real measurement.
    logs = tmp_path / "logs"
    _write_logs(logs)
    (logs / "worker_activity.jsonl").write_text(
        json.dumps({"timestamp": _now_iso(), "run_id": "exp-0", "task_id": "t/z",
                    "tokens_generated": 0, "tokens_target": 512, "tok_per_s": 0,
                    "eta_s": None, "synthetic": False}) + "\n", encoding="utf-8")
    syn = _client(logs, tmp_path / "telemetry.jsonl").get(
        "/api/activity/monitor").json()["synthetic_inference"]
    assert syn["synthetic"] is False
    w = syn["workers"][0]
    assert w["task_id"] == "t/z"
    assert w["eta_s"] is None
    assert w["tok_per_s"] == 0


# (The SINGULAR /active_run mirror cases died with that endpoint in UI
# simplification S3 — /active_runs is the live-run source and carries its own
# suite, including the legacy-mirror fallback.)


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
