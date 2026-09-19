"""Bounded reader tests for opt-in local model stream snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.model_io import register

NOW = datetime(2026, 9, 18, 12, 0, 10, tzinfo=timezone.utc)


def _snapshot(request_id: str, *, updated: str, status: str = "streaming"):
    return {
        "schema": "local-model-trace/v1",
        "request_id": request_id,
        "model": "qwen3.8-flash-next-mia",
        "backend": "flash",
        "source": "flash-personal-client",
        "started_at": "2026-09-18T11:58:00+00:00",
        "updated_at": updated,
        "elapsed_s": 10.0,
        "prompt_preview": "Question",
        "prompt_truncated": False,
        "status": status,
        "reasoning_content": "checking the mechanism",
        "content": "answer",
        "tool_calls": [],
        "usage": {"completion_tokens": 7},
        "usage_truncated": False,
        "finish_reason": None,
        "error": None,
        "truncated": {
            "reasoning_content": False,
            "content": False,
            "tool_calls": False,
        },
    }


def _client(logs: Path, traces: Path) -> TestClient:
    app = FastAPI()
    register(
        app,
        logs_dir=logs,
        model_trace_dir=traces,
        trace_clock=lambda: NOW,
    )
    return TestClient(app)


def test_absent_and_empty_trace_sources_are_distinct(tmp_path):
    trace_dir = tmp_path / "model_traces"
    client = _client(tmp_path / "logs", trace_dir)
    absent = client.get("/api/model_traces").json()
    assert absent["available"] is False
    assert absent["traces"] == []

    trace_dir.mkdir()
    empty = client.get("/api/model_traces").json()
    assert empty["available"] is True
    assert empty["traces"] == []
    assert empty["scan_truncated"] is False
    assert empty["source"] == "logs/model_traces"


def test_traces_are_validated_sorted_and_freshness_is_explicit(tmp_path):
    trace_dir = tmp_path / "model_traces"
    trace_dir.mkdir()
    older_id = "1" * 32
    newer_id = "2" * 32
    (trace_dir / f"{older_id}.json").write_text(json.dumps(
        _snapshot(older_id, updated="2026-09-18T11:59:00+00:00",
                  status="completed")
    ))
    (trace_dir / f"{newer_id}.json").write_text(json.dumps(
        _snapshot(newer_id, updated="2026-09-18T12:00:08+00:00")
    ))

    body = _client(tmp_path / "logs", trace_dir).get(
        "/api/model_traces?limit=8"
    ).json()
    assert [row["request_id"] for row in body["traces"]] == [
        newer_id, older_id
    ]
    assert body["traces"][0]["freshness"] == {
        "state": "live", "age_s": 2.0
    }
    assert body["traces"][1]["freshness"] == {
        "state": "stale", "age_s": 70.0
    }
    # A terminal writer status passes through; the reader adds no success or
    # correctness claim.
    assert body["traces"][1]["status"] == "completed"


def test_malformed_oversized_and_symlinked_snapshots_are_disclosed(tmp_path):
    trace_dir = tmp_path / "model_traces"
    trace_dir.mkdir()
    good_id = "a" * 32
    (trace_dir / f"{good_id}.json").write_text(json.dumps(
        _snapshot(good_id, updated="2026-09-18T12:00:08+00:00")
    ))
    (trace_dir / "malformed.json").write_text("{")
    (trace_dir / "oversized.json").write_bytes(b"x" * (512 * 1024 + 1))
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_snapshot(
        "b" * 32, updated="2026-09-18T12:00:09+00:00"
    )))
    (trace_dir / "linked.json").symlink_to(outside)

    body = _client(tmp_path / "logs", trace_dir).get("/api/model_traces").json()
    assert [row["request_id"] for row in body["traces"]] == [good_id]
    assert body["skipped_files"] == 3


def test_unknown_status_and_channel_over_byte_bound_are_rejected(tmp_path):
    trace_dir = tmp_path / "model_traces"
    trace_dir.mkdir()
    unknown = _snapshot("c" * 32, updated="2026-09-18T12:00:08+00:00")
    unknown["status"] = "passed"
    (trace_dir / f"{'c' * 32}.json").write_text(json.dumps(unknown))
    too_long = _snapshot("d" * 32, updated="2026-09-18T12:00:08+00:00")
    too_long["content"] = "語" * (128 * 1024)
    (trace_dir / f"{'d' * 32}.json").write_text(json.dumps(too_long))

    body = _client(tmp_path / "logs", trace_dir).get("/api/model_traces").json()
    assert body["traces"] == []
    assert body["skipped_files"] == 2


def test_future_and_filename_mismatched_snapshots_are_rejected(tmp_path):
    trace_dir = tmp_path / "model_traces"
    trace_dir.mkdir()
    future = _snapshot("e" * 32, updated="2026-09-18T12:01:00+00:00")
    future["started_at"] = "2026-09-18T12:00:30+00:00"
    (trace_dir / f"{'e' * 32}.json").write_text(json.dumps(future))
    mismatched = _snapshot("f" * 32, updated="2026-09-18T12:00:08+00:00")
    (trace_dir / f"{'0' * 32}.json").write_text(json.dumps(mismatched))

    body = _client(tmp_path / "logs", trace_dir).get("/api/model_traces").json()
    assert body["traces"] == []
    assert body["skipped_files"] == 2


def test_directory_scan_bound_fails_closed_instead_of_selecting_partial_tail(
        tmp_path):
    trace_dir = tmp_path / "model_traces"
    trace_dir.mkdir()
    for index in range(513):
        (trace_dir / f"junk-{index}.txt").write_text("")
    body = _client(tmp_path / "logs", trace_dir).get("/api/model_traces").json()
    assert body["available"] is True
    assert body["scan_truncated"] is True
    assert body["traces"] == []
