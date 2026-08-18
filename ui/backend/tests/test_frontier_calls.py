"""Frontier-calls endpoint tests (backend/frontier_calls.py).

Read-only over fixture ledgers; each test builds its own FastAPI app with
register(app, ledger_path=<tmp>, ...). The load-bearing pins:

1. rows are newest-first PASSTHROUGH — verdict null / "veto" / "pass" and
   the review-layer fields (candidate_id, reasoning_digest) come back
   exactly as written, absent fields stay absent, nothing derived;
2. the vendor-down streaks match loop_health's shape: consecutive nonzero
   exit_codes from the newest row per vendor, threshold 3, unjudgeable
   rows never scored either way (the 08-16 dead-codex lesson);
3. the tail-read bound is honest — rows beyond the byte window are out,
   window_truncated says so, and the summary is derived from the SAME
   (bounded) tail;
4. empty / absent ledgers degrade honestly (never a 500, never rows).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.frontier_calls import register


# ─── fixtures ─────────────────────────────────────────────────────────

def _now_iso(minutes_ago: float = 0.0) -> str:
    instant = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return instant.isoformat().replace("+00:00", "Z")


def _row(ts: str, *, vendor: str = "claude",
         role: str = "methods_reviewer", verdict=None,
         exit_code: int = 0, duration_ms: int = 1500, **extra) -> dict:
    rec = {
        "timestamp": ts,
        "vendor": vendor,
        "cli_version": "2.1.233 (Claude Code)" if vendor == "claude"
        else "codex-cli 0.147.0",
        "role": role,
        "verdict": verdict,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "prompt_sha256": "ab" * 32,
    }
    rec.update(extra)
    return rec


def _write(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


def _client(ledger: Path, tail_bytes: int | None = None) -> TestClient:
    app = FastAPI()
    kwargs: dict = {"ledger_path": ledger}
    if tail_bytes is not None:
        kwargs["tail_bytes"] = tail_bytes
    register(app, **kwargs)
    return TestClient(app)


# ─── passthrough + order ──────────────────────────────────────────────

def test_rows_are_newest_first_passthrough_including_null_verdict(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    _write(ledger, [
        _row(_now_iso(30), vendor="claude", role="equivalence_judge",
             verdict=None),
        _row(_now_iso(20), vendor="codex", role="novelty_reviewer",
             verdict="veto", candidate_id="cand-7",
             reasoning_digest="prior art: Axelrod 1984 §3 covers this"),
        _row(_now_iso(10), vendor="claude", role="methods_reviewer",
             verdict="pass", candidate_id="cand-7"),
    ])
    body = _client(ledger).get("/api/frontier_calls").json()
    assert body["available"] is True
    calls = body["calls"]
    assert [c["role"] for c in calls] == [
        "methods_reviewer", "novelty_reviewer", "equivalence_judge"]
    # verdict passthrough: "pass", "veto", and an honest null.
    assert [c["verdict"] for c in calls] == ["pass", "veto", None]
    # Review-layer fields come through verbatim; absent stays absent
    # (frontier_cli rows never carry them — nothing is backfilled).
    assert calls[1]["candidate_id"] == "cand-7"
    assert calls[1]["reasoning_digest"].startswith("prior art")
    assert "candidate_id" not in calls[2]
    assert body["rows_in_window"] == 3
    assert body["summary"]["last_call_ts"] == calls[0]["timestamp"]


def test_limit_caps_the_page_not_the_summary(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    _write(ledger, [_row(_now_iso(9 - i)) for i in range(9)])
    body = _client(ledger).get("/api/frontier_calls?limit=4").json()
    assert len(body["calls"]) == 4
    # The summary is derived from the whole scanned tail, not the page.
    assert body["rows_in_window"] == 9
    assert body["summary"]["calls_24h"] == 9


# ─── vendor-down streaks (the 08-16 dead-codex lesson) ────────────────

def test_consecutive_nonzero_streak_flags_the_vendor_down(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    _write(ledger, [
        # An OLD codex failure before a clean call must NOT extend the
        # streak — a clean exit closes it.
        _row(_now_iso(120), vendor="codex", exit_code=1),
        _row(_now_iso(100), vendor="codex", exit_code=0),
        _row(_now_iso(50), vendor="codex", exit_code=1),
        _row(_now_iso(40), vendor="claude", exit_code=0),  # interleaved
        _row(_now_iso(30), vendor="codex", exit_code=1),
        _row(_now_iso(10), vendor="codex", exit_code=1),
    ])
    body = _client(ledger).get("/api/frontier_calls").json()
    summary = body["summary"]
    assert summary["consecutive_nonzero_exit_by_vendor"] == {
        "codex": 3, "claude": 0}
    assert summary["vendors_down"] == ["codex"]
    assert summary["down_streak_threshold"] == 3


def test_two_failures_are_a_coincidence_not_down(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    _write(ledger, [
        _row(_now_iso(30), vendor="codex", exit_code=0),
        _row(_now_iso(20), vendor="codex", exit_code=1),
        _row(_now_iso(10), vendor="codex", exit_code=1),
    ])
    summary = _client(ledger).get("/api/frontier_calls").json()["summary"]
    assert summary["consecutive_nonzero_exit_by_vendor"] == {"codex": 2}
    assert summary["vendors_down"] == []


def test_unjudgeable_rows_are_never_scored_either_way(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    rows = [
        _row(_now_iso(50), vendor="codex", exit_code=1),
        _row(_now_iso(40), vendor="codex", exit_code=1),
        # A string exit_code and a missing vendor are unknown, not
        # failures — and not successes that would close the streak.
        _row(_now_iso(30), vendor="codex"),
        _row(_now_iso(20), vendor="codex", exit_code=1),
    ]
    rows[2]["exit_code"] = "1"
    _write(ledger, rows + [
        {"timestamp": _now_iso(10), "exit_code": 1, "role": "x",
         "cli_version": "?", "verdict": None, "duration_ms": 1,
         "prompt_sha256": "ab" * 32},
    ])
    summary = _client(ledger).get("/api/frontier_calls").json()["summary"]
    # 3 judgeable nonzero codex rows in a row (the "1"-string row skipped,
    # the vendorless row skipped) → down.
    assert summary["consecutive_nonzero_exit_by_vendor"] == {"codex": 3}
    assert summary["vendors_down"] == ["codex"]


# ─── bound honesty ────────────────────────────────────────────────────

def test_tail_bound_is_real_and_stated(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    # An old CLEAN codex row followed by newer failures: if the bound
    # were a lie, the old row would be visible; with the bound honored it
    # is out of the window AND out of the summary (the streak still runs
    # to the window edge — derived from the SAME tail).
    old = _row("2020-01-01T00:00:00Z", vendor="codex", exit_code=0,
               role="ancient_row_beyond_window")
    recent = [_row(_now_iso(30 - i), vendor="codex", exit_code=1)
              for i in range(4)]
    _write(ledger, [old] + recent)
    # A window big enough for the 4 recent rows (~330 B each) but not the
    # 5th: each json row here is ~230-260 B; 1100 bytes holds ~4.
    body = _client(ledger, tail_bytes=1100).get("/api/frontier_calls").json()
    roles = [c["role"] for c in body["calls"]]
    assert "ancient_row_beyond_window" not in roles
    assert body["window_truncated"] is True
    assert body["window_bytes"] == 1100
    # The old clean exit beyond the window cannot close the streak.
    streak = body["summary"]["consecutive_nonzero_exit_by_vendor"]["codex"]
    assert streak == len(body["calls"])
    assert streak >= 3
    # And the 24h count is over the window only (the 2020 row excluded).
    assert body["summary"]["calls_24h"] == len(body["calls"])


def test_untruncated_window_says_so(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    _write(ledger, [_row(_now_iso(1))])
    body = _client(ledger).get("/api/frontier_calls").json()
    assert body["window_truncated"] is False


def test_calls_24h_excludes_older_parseable_and_unparseable_rows(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    _write(ledger, [
        _row("2026-01-01T00:00:00Z"),          # parseable, > 24h old
        _row("not-a-timestamp"),               # unparseable → never inside
        _row(_now_iso(5)),
    ])
    body = _client(ledger).get("/api/frontier_calls").json()
    assert body["summary"]["calls_24h"] == 1
    # All three rows still pass through — the filter is for the COUNT only.
    assert body["rows_in_window"] == 3


# ─── honest degradations ──────────────────────────────────────────────

def test_empty_file_is_available_with_no_rows(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    ledger.write_text("", encoding="utf-8")
    body = _client(ledger).get("/api/frontier_calls").json()
    assert body["available"] is True
    assert body["calls"] == []
    assert body["rows_in_window"] == 0
    assert body["summary"] == {
        "last_call_ts": None, "calls_24h": 0,
        "consecutive_nonzero_exit_by_vendor": {}, "vendors_down": [],
        "down_streak_threshold": 3,
    }
    assert body["window_truncated"] is False


def test_missing_file_is_unavailable_never_a_500(tmp_path):
    resp = _client(tmp_path / "nope.jsonl").get("/api/frontier_calls")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["calls"] == []
    assert body["summary"]["vendors_down"] == []


def test_malformed_lines_are_skipped_not_a_crash(tmp_path):
    ledger = tmp_path / "frontier_calls.jsonl"
    good = _row(_now_iso(1), verdict="inconclusive")
    ledger.write_text('{"broken\n[1,2]\n' + json.dumps(good) + "\n",
                      encoding="utf-8")
    body = _client(ledger).get("/api/frontier_calls").json()
    assert [c["verdict"] for c in body["calls"]] == ["inconclusive"]
    assert body["rows_in_window"] == 1
