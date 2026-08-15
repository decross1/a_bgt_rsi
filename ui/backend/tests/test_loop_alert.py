"""Loop-alert + ideas read-seam tests (2026-08-14 work order A + C).

Side-effect-free: every path points at tmp_path (mirrors
test_coordinator.py's TestClient idiom). Covers: absent file = 204,
present file = verbatim payload, garbled alert = honest 500, and the
human_todo evidence_level pass-through (work order B's backend half).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def _client(tmp_path) -> TestClient:
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "loop_alert"}), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    bench = tmp_path / "day1.csv"
    bench.write_text(
        "prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s\n0,256,8.0,32.0\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    loop_run_state = tmp_path / "loop_run_state"
    loop_run_state.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)

    app = create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=bench,
        mtp_csv=tmp_path / "mtp.csv",
        loop_v0_repo=repo,
        loop_v0_run_state=loop_run_state,
        loop_v0_journal=journal_dir,
        loop_v0_memory=tmp_path / "loop_memory.jsonl",
        # Dirs intentionally NOT pre-created: absent-file tests rely on that.
        coordinator_run_state=tmp_path / "coord_run_state",
        coordinator_memory=tmp_path / "coord_memory",
    )
    return TestClient(app)


# ─── /api/loop_alert ───────────────────────────────────────────────────


def test_loop_alert_absent_is_204(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/loop_alert")
    assert resp.status_code == 204


def test_loop_alert_returns_flag_verbatim(tmp_path):
    client = _client(tmp_path)
    flag = {
        "level": "red",
        "reasons": ["no promote in 3 cycles", "qwen skeptic empty-content"],
        "updated_at": "2026-08-15T01:19:08+00:00",
    }
    run_state = tmp_path / "coord_run_state"
    run_state.mkdir(parents=True, exist_ok=True)
    (run_state / "loop_alert.json").write_text(json.dumps(flag), encoding="utf-8")
    resp = client.get("/api/loop_alert")
    assert resp.status_code == 200
    assert resp.json() == flag


def test_loop_alert_garbled_is_honest_500(tmp_path):
    client = _client(tmp_path)
    run_state = tmp_path / "coord_run_state"
    run_state.mkdir(parents=True, exist_ok=True)
    (run_state / "loop_alert.json").write_text("{not json", encoding="utf-8")
    resp = client.get("/api/loop_alert")
    assert resp.status_code == 500
    assert "loop_alert unreadable" in resp.json()["detail"]


# ─── /api/ideas ────────────────────────────────────────────────────────


def test_ideas_absent_is_204(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/ideas")
    assert resp.status_code == 204


def test_ideas_returns_markdown_verbatim(tmp_path):
    client = _client(tmp_path)
    md = "# Ideas\n\n## Live work\n\n- cl-iter-001 · L1 · next: synthetic experiment\n"
    memory = tmp_path / "coord_memory"
    memory.mkdir(parents=True, exist_ok=True)
    (memory / "ideas.md").write_text(md, encoding="utf-8")
    resp = client.get("/api/ideas")
    assert resp.status_code == 200
    assert resp.json() == {"markdown": md}


# ─── human_todo evidence_level pass-through (work order B) ─────────────


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_human_todo_finding_carries_evidence_level_when_present(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "surfaced_findings.jsonl", [
        {"finding_id": "sf-new-001", "title": "ladder finding",
         "status": "surfaced", "promoted_at": "2026-08-14T00:00:00Z",
         "evidence_level": "L4"},
        {"finding_id": "sf-legacy-001", "title": "legacy finding",
         "status": "surfaced", "promoted_at": "2026-06-01T00:00:00Z"},
        # Non-string level must NOT pass through (producer-owned field).
        {"finding_id": "sf-weird-001", "title": "weird level",
         "status": "surfaced", "promoted_at": "2026-08-01T00:00:00Z",
         "evidence_level": 4},
    ])
    resp = client.get("/api/human_todo")
    assert resp.status_code == 200
    by_id = {item["id"]: item for item in resp.json()["items"]}
    assert by_id["sf-new-001"]["evidence_level"] == "L4"
    assert "evidence_level" not in by_id["sf-legacy-001"]
    assert "evidence_level" not in by_id["sf-weird-001"]
