"""Fixed-root personal serving projection and endpoint selection."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import model_runtime as runtime_module
from backend import model_runtime_personal as personal
from backend.model_runtime import project_model_runtime
from backend.served_models import register

NOW = datetime(2026, 9, 19, 4, 0, tzinfo=timezone.utc)
CID_A = "a" * 64
CID_B = "b" * 64


def _write(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return raw


def _proc(proc_root: Path, pid: int, ticks: int, argv: list[str], *, parent: int = 1):
    path = proc_root / str(pid)
    path.mkdir(parents=True, exist_ok=True)
    # Fields after comm start at field 3; starttime is field 22 / tail index 19.
    tail = ["S", str(parent)] + ["0"] * 17 + [str(ticks)] + ["0"] * 20
    (path / "stat").write_text(f"{pid} (python3) " + " ".join(tail) + "\n")
    (path / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")


def _mia(root: Path, proc_root: Path, *, phase="starting", age=1, cid=CID_A):
    pid, parent, ticks = 41001, 41000, 123456
    state = {
        "phase": phase,
        "candidate_id": cid,
        "output": str(root),
        "parent_pid": parent,
    }
    if phase == "ready":
        state["readiness"] = {
            "data": [{"id": "qwen3.8-flash-next-mia", "max_model_len": 32768}]
        }
    _write(root / "state.json", state)
    _write(
        root / "heartbeat.json",
        {"at": (NOW - timedelta(seconds=age)).isoformat(), "phase": phase, "pid": pid},
    )
    _write(root / "policy.json", {"worker_heartbeat_max_age_s": 45})
    _write(
        root / "supervisor.json",
        {"pid": parent, "worker_pid": pid, "worker_start_ticks": ticks},
    )
    argv = [
        "/usr/bin/python3", "-m", "bench.flash_next_ab.personal_session", "--worker",
        "--output-dir", str(root), "--hours", "4", "--floor", "20",
        "--initial-profile", "mtp3-fp32-auto",
    ]
    _proc(proc_root, pid, ticks, argv, parent=parent)


def _sglang(root: Path, proc_root: Path, *, phase="starting", age=1, ticks=654321):
    pid = 42001
    receipt_sha = "c" * 64
    nonce = "d" * 32
    launch = {
        "cid": CID_B,
        "image": personal.SG_IMAGE,
        "model": personal.SG_MODEL,
        "model_sha": personal.SG_MODEL_REVISION,
        "profile_sha256": personal.SG_PROFILE_SHA256,
        "receipt_sha256": receipt_sha,
        "nonce": nonce,
        "argv": ["docker", "create", "--publish", "127.0.0.1:30080:30000"],
    }
    launch_raw = _write(root / "guard-state/launch-record.json", launch)
    state = {
        "schema": "flash-sglang-session-state/v1",
        "phase": phase,
        "candidate_id": CID_B,
        "candidate_name": "qwen38fn-" + nonce,
        "candidate_stop_at_or_before": (NOW + timedelta(hours=2)).isoformat(),
        "guard_pid": pid,
        "guard_start_ticks": ticks,
        "launch_record_sha256": hashlib.sha256(launch_raw).hexdigest(),
        "receipt": {"receipt_sha256": receipt_sha},
    }
    _write(root / "state.json", state)
    passive = None
    if phase == "ready":
        identity = {"id": personal.SG_MODEL, "max_model_len": 32768}
        passive = {
            "schema": "flash-sglang-passive-model-heartbeat/v1",
            "kind": "passive_models_identity",
            "status": 200,
            "models": [personal.SG_MODEL],
            "max_model_len": 32768,
            "identity_projection": identity,
            "canonical_identity_sha256": hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    _write(
        root / "heartbeat.json",
        {
            "at": (NOW - timedelta(seconds=age)).isoformat(),
            "phase": "live", "candidate_id": CID_B,
            "passive_models_heartbeat": passive,
        },
    )
    _write(
        root / "policy.json",
        {
            "image_id": personal.SG_IMAGE,
            "model": personal.SG_MODEL,
            "model_revision": personal.SG_MODEL_REVISION,
            "profile_sha256": personal.SG_PROFILE_SHA256,
            "context_length": 32768,
        },
    )
    _write(
        root / "guard-process.json",
        {"schema": "flash-sglang-guard-process/v1", "pid": pid, "start_ticks": ticks},
    )
    argv = [
        "/usr/bin/python3", str(personal.SG_ADAPTER),
        "--image", personal.SG_IMAGE,
        "--profile", str(personal.SG_PROFILE),
        "--sources", str(personal.SG_SOURCES),
        "--receipt-sha256", receipt_sha,
        "--state-dir", str(root / "guard-state"),
        "--max-watch-seconds", "0",
    ]
    _proc(proc_root, pid, ticks, argv)


def test_starting_mia_and_ready_sglang_project_exact_public_contract(tmp_path):
    proc = tmp_path / "proc"
    mia = tmp_path / "session-mia"
    absent = tmp_path / "session-absent"
    _mia(mia, proc)
    row = personal.maybe_project_personal(
        mia_root=mia, sglang_root=absent, proc_root=proc, observed=NOW
    )
    assert row is not None
    assert {key: row[key] for key in (
        "mode", "mode_source", "run_id", "phase", "personal_endpoint", "candidate_id"
    )} == {
        "mode": "candidate_research",
        "mode_source": "personal_session_state",
        "run_id": "session-mia",
        "phase": "starting",
        "personal_endpoint": "mia",
        "candidate_id": CID_A,
    }
    assert row["candidate_variant"] is None

    sg = tmp_path / "session-sg"
    _sglang(sg, proc, phase="ready")
    # Make the Mia root terminal so only the fixed SGLang owner remains.
    _write(mia / "state.json", {"phase": "restored", "restoration": {"status": "verified"}})
    row = personal.maybe_project_personal(
        mia_root=mia, sglang_root=sg, proc_root=proc, observed=NOW
    )
    assert row is not None
    assert row["phase"] == "ready"
    assert row["personal_endpoint"] == "sglang"
    assert row["candidate_id"] == CID_B
    assert len(row["mode_source_sha256"]) == 64


def test_verified_terminal_sessions_are_not_an_active_overlay(tmp_path):
    mia = tmp_path / "session-mia"
    sg = tmp_path / "session-sg"
    _write(mia / "state.json", {"phase": "restored", "restoration": {"status": "verified"}})
    _write(
        sg / "state.json",
        {
            "schema": "flash-sglang-session-state/v1",
            "phase": "restored_after_failure",
            "restoration": {"status": "verified"},
        },
    )
    assert personal.maybe_project_personal(
        mia_root=mia, sglang_root=sg, proc_root=tmp_path / "proc", observed=NOW
    ) is None


def test_nonterminal_transition_does_not_fall_through_to_old_runtime(tmp_path):
    mia = tmp_path / "session-mia"
    _write(mia / "state.json", {"phase": "restoring"})
    row = personal.maybe_project_personal(
        mia_root=mia,
        sglang_root=tmp_path / "session-none",
        proc_root=tmp_path / "proc",
        observed=NOW,
    )
    assert row["mode"] == "unknown"
    assert row["mode_source"] == "personal_session_state"


def test_bounded_discovery_finds_new_session_and_old_terminal_failure_does_not_mask_it(
    tmp_path,
):
    proc = tmp_path / "proc"
    _write(
        tmp_path / "session-old/state.json",
        {"phase": "restoration_failed"},
    )
    _mia(tmp_path / "session-new", proc)
    row = personal.maybe_project_personal(
        mia_base=tmp_path,
        sglang_root=tmp_path / "session-none",
        proc_root=proc,
        observed=NOW,
    )
    assert row["run_id"] == "session-new"
    assert row["personal_endpoint"] == "mia"


def test_discovery_rejects_session_symlink(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / "session-linked").symlink_to(target, target_is_directory=True)
    row = personal.maybe_project_personal(
        mia_base=tmp_path,
        sglang_root=tmp_path / "session-none",
        proc_root=tmp_path / "proc",
        observed=NOW,
    )
    assert row["mode"] == "unknown"


def test_discovery_caps_direct_session_receipts(tmp_path):
    for number in range(personal.MAX_MIA_SESSIONS + 1):
        (tmp_path / f"session-{number}").mkdir()
    row = personal.maybe_project_personal(
        mia_base=tmp_path,
        sglang_root=tmp_path / "session-none",
        proc_root=tmp_path / "proc",
        observed=NOW,
    )
    assert row["mode"] == "unknown"


def test_absent_optional_personal_roots_do_not_override_resident_projection(tmp_path):
    assert personal.maybe_project_personal(
        mia_base=tmp_path / "artifacts-not-installed",
        sglang_root=tmp_path / "session-none",
        proc_root=tmp_path / "proc",
        observed=NOW,
    ) is None


def test_stale_heartbeat_and_reused_pid_fail_closed(tmp_path):
    proc = tmp_path / "proc"
    sg = tmp_path / "session-sg"
    _sglang(sg, proc, age=20)
    stale = personal.maybe_project_personal(
        mia_root=tmp_path / "session-none", sglang_root=sg, proc_root=proc, observed=NOW
    )
    assert stale["mode"] == "unknown"
    assert stale["personal_endpoint"] is None

    stat_path = proc / "42001/stat"
    stat_path.write_text(stat_path.read_text().replace("654321", "999999"))
    reused = personal.maybe_project_personal(
        mia_root=tmp_path / "session-none", sglang_root=sg, proc_root=proc, observed=NOW
    )
    assert reused["mode"] == "unknown"
    assert reused["candidate_id"] is None


def test_two_live_fixed_sessions_are_ambiguous(tmp_path):
    proc = tmp_path / "proc"
    mia = tmp_path / "session-mia"
    sg = tmp_path / "session-sg"
    _mia(mia, proc)
    _sglang(sg, proc)
    row = personal.maybe_project_personal(
        mia_root=mia, sglang_root=sg, proc_root=proc, observed=NOW
    )
    assert row["mode"] == "unknown"
    assert "multiple fixed personal sessions" in row["source_error"]


def test_active_personal_projection_precedes_historical_runtime_sources(monkeypatch):
    expected = personal._unknown(NOW, "fixed test projection")
    monkeypatch.setattr(personal, "maybe_project_personal", lambda **_kwargs: expected)
    assert project_model_runtime() is expected


def test_concurrent_live_runtime_owner_forces_unknown_personal_selection():
    personal_row = {
        "mode": "candidate_research",
        "mode_source": "personal_session_state",
        "mode_source_sha256": "a" * 64,
        "resident_services_expected": "stopped",
        "nara_service_expected": "paused",
        "run_id": "session-new",
        "phase": "ready",
        "candidate_variant": None,
        "personal_endpoint": "mia",
        "candidate_id": CID_A,
        "source_error": None,
    }
    conflict = runtime_module._reconcile_personal_runtime(
        personal_row,
        {"mode": "transitioning", "mode_source": "stable_benchmark_state"},
    )
    assert conflict["mode"] == "unknown"
    assert conflict["personal_endpoint"] is None
    assert conflict["candidate_id"] is None
    assert "another live runtime owner" in conflict["source_error"]

    assert runtime_module._reconcile_personal_runtime(
        personal_row,
        {"mode": "resident", "resident_services_expected": "online"},
    ) is personal_row


class _Response:
    def __init__(self, value, url):
        self.value, self.url, self.status = value, url, 200

    def read(self, limit=None):
        raw = self.value.encode() if isinstance(self.value, str) else json.dumps(self.value).encode()
        return raw if limit is None else raw[:limit]

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_served_inventory_switches_fixed_endpoint_identity_and_metrics_backend():
    selected = {"endpoint": "sglang", "candidate": CID_B}
    calls = []

    def runtime():
        return {
            "mode": "candidate_research", "mode_source": "personal_session_state",
            "phase": "ready", "personal_endpoint": selected["endpoint"],
            "candidate_id": selected["candidate"],
        }

    sglang_metrics = (
        "sglang:num_running_reqs 0\nsglang:num_queue_reqs 0\n"
        "sglang:full_token_usage 0.25\nsglang:spec_accept_rate 0.5\n"
    )
    vllm_metrics = (
        "vllm:num_requests_running 0\nvllm:num_requests_waiting 0\n"
        "vllm:kv_cache_usage_perc 0.5\n"
    )
    mapping = {
        "http://127.0.0.1:8000/v1/models": {"data": [{"id": "gemma-4-26b-a4b"}]},
        "http://127.0.0.1:8000/metrics": vllm_metrics,
        "http://127.0.0.1:8001/v1/models": {"data": [{"id": "qwen3.8-27b-nvfp4-mtp"}]},
        "http://127.0.0.1:8001/metrics": vllm_metrics,
        "http://127.0.0.1:30080/v1/models": {"data": [{"id": personal.SG_MODEL, "max_model_len": 32768}]},
        "http://127.0.0.1:30080/metrics": sglang_metrics,
        "http://127.0.0.1:8012/v1/models": {"data": [{"id": "qwen3.8-flash-next-mia", "max_model_len": 32768}]},
        "http://127.0.0.1:8012/metrics": vllm_metrics,
    }

    def opener(url, timeout=None):
        del timeout
        calls.append(url)
        return _Response(mapping[url], url)

    app = FastAPI()
    register(app, opener=opener, runtime_projector=runtime, ttl_s=60)
    client = TestClient(app)
    first = client.get("/api/served_models").json()["flash"]
    assert first["url"] == "http://127.0.0.1:30080"
    assert first["configured_model"] == personal.SG_MODEL
    assert first["identity_status"] == "match"
    assert first["metrics_endpoint_status"] == "available"

    before = len(calls)
    selected.update(endpoint="mia", candidate=CID_A)
    second = client.get("/api/served_models").json()["flash"]
    assert len(calls) > before  # selection invalidates the otherwise-fresh cache
    assert second["url"] == "http://127.0.0.1:8012"
    assert second["configured_model"] == "qwen3.8-flash-next-mia"
    assert second["identity_status"] == "match"
    assert second["metrics_endpoint_status"] == "available"
