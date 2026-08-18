"""Model I/O + dispatch-trace endpoint tests (backend/model_io.py).

Read-only over fixture logs; each test builds its own FastAPI app with
register(app, logs_dir=<tmp>, ...). The load-bearing pins:

1. the scan is a BOUNDED backward tail read — a 10k-junk-line prefix costs
   nothing, and a row older than max_scan_bytes is honestly out of window
   (window_truncated / detail-404), never silently searched for;
2. summaries are pure passthrough + previews (last USER message, ~200 chars,
   empty-completion flag) — nothing derived, nothing fabricated;
3. filters compose and an unparseable since_ts is a 400, not a silent no-op;
4. the dispatch trace joins the orchestrator triples by task_id (receipt owns
   the final status/duration) and passes the spawn ledger through, both
   spellings of its timestamp field included.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.model_io import register


# ─── fixtures ─────────────────────────────────────────────────────────

def _call(ts: str, req: str, *, model: str = "gemma-4-26b-a4b",
          backend: str | None = "vllm-gemma", tag: str = "nara.run_iteration",
          run_id: str | None = None, completion: str = "a completion",
          user_msg: str = "Evaluate this research topic",
          parent: str | None = None) -> dict:
    rec = {
        "timestamp": ts,
        "request_id": req,
        "parent_request_id": parent,
        "model": model,
        "model_version": "unknown",
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": None,
        "prompt_messages": [
            {"role": "system", "content": "You are Nara."},
            {"role": "user", "content": user_msg},
        ],
        "completion": completion,
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "latency_ms": 512.5,
        "host_metadata": {},
        "caller_tag": tag,
    }
    if backend is not None:
        rec["backend"] = backend
    if run_id is not None:
        rec["run_id"] = run_id
    return rec


CALL_ROWS = [
    _call("2026-08-18T01:00:00Z", "req-1"),
    _call("2026-08-18T01:00:01Z", "req-2", model="qwen3.8-27b-nvfp4-mtp",
          backend="vllm-qwen", tag="skeptic_battery", run_id="iter-9"),
    _call("2026-08-18T01:00:02Z", "req-3", tag="nara.meta_review",
          completion="", run_id="iter-9"),
]

ORCH_ROWS = [
    {"timestamp": "2026-08-18T02:00:00.1Z", "request_id": "d-1",
     "parent_request_id": "run-root", "stage": "orchestrator_dispatch",
     "task_id": "task-a", "task_type": "experiment_trial",
     "status": "dispatched", "detail": "dispatching"},
    {"timestamp": "2026-08-18T02:00:00.2Z", "request_id": "w-1",
     "parent_request_id": "d-1", "stage": "worker_invocation",
     "task_id": "task-a", "task_type": "experiment_trial",
     "status": "running", "detail": "running"},
    {"timestamp": "2026-08-18T02:00:00.3Z", "request_id": "r-1",
     "parent_request_id": "w-1", "stage": "orchestrator_receipt",
     "task_id": "task-a", "task_type": "experiment_trial",
     "status": "passed", "detail": "passed", "duration_ms": 0.2},
    {"timestamp": "2026-08-18T02:00:05.0Z", "request_id": "d-2",
     "parent_request_id": "run-root", "stage": "orchestrator_dispatch",
     "task_id": "task-b", "task_type": "summarize_paper",
     "status": "dispatched", "detail": "dispatching"},
]

SPAWN_ROWS = [
    {"ts": "2026-08-18T00:49:00Z", "spawn_id": "agent-1", "status": "spawned",
     "contract": {"task_statement": "Build the 3c two-voice battery driver "
                                    "per LOCKED prereg v2 " + "x" * 200}},
    # Closing line: no contract — the statement must be backfilled from the
    # opener above, never invented.
    {"ts": "2026-08-18T00:55:00Z", "spawn_id": "agent-1",
     "status": "completed"},
    # Legacy spelling: "timestamp" instead of "ts".
    {"timestamp": "2026-08-18T01:10:00Z", "spawn_id": "agent-2",
     "status": "spawned", "contract": {"task_statement": "short task"}},
]


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


def _client(logs_dir: Path, spawn: Path | None = None,
            max_scan_bytes: int | None = None) -> TestClient:
    app = FastAPI()
    kwargs: dict = {"logs_dir": logs_dir,
                    "spawn_path": spawn if spawn is not None
                    else logs_dir / "spawn.jsonl"}
    if max_scan_bytes is not None:
        kwargs["max_scan_bytes"] = max_scan_bytes
    register(app, **kwargs)
    return TestClient(app)


def _setup(tmp_path: Path, calls=CALL_ROWS) -> Path:
    logs = tmp_path / "logs"
    _write_jsonl(logs / "calls.jsonl", calls)
    return logs


# ─── /api/model_io — summaries ────────────────────────────────────────

def test_model_io_newest_first_summaries(tmp_path):
    client = _client(_setup(tmp_path))
    body = client.get("/api/model_io").json()
    assert [c["request_id"] for c in body["calls"]] == ["req-3", "req-2",
                                                        "req-1"]
    assert body["source"] == "logs/calls.jsonl"
    assert body["window_truncated"] is False
    row = body["calls"][1]
    assert row["model"] == "qwen3.8-27b-nvfp4-mtp"
    assert row["backend"] == "vllm-qwen"
    assert row["caller_tag"] == "skeptic_battery"
    assert row["run_id"] == "iter-9"
    assert row["latency_ms"] == 512.5
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 20


def test_model_io_previews_and_empty_flag(tmp_path):
    long_user = "u" * 500
    long_completion = "c" * 500
    rows = [
        _call("2026-08-18T01:00:00Z", "req-long", user_msg=long_user,
              completion=long_completion),
        _call("2026-08-18T01:00:01Z", "req-empty", completion="  \n"),
    ]
    client = _client(_setup(tmp_path, rows))
    calls = client.get("/api/model_io").json()["calls"]
    by_id = {c["request_id"]: c for c in calls}
    # ~200-char previews, never the whole payload.
    assert by_id["req-long"]["prompt_preview"] == "u" * 200
    assert by_id["req-long"]["completion_preview"] == "c" * 200
    assert by_id["req-long"]["empty"] is False
    # Whitespace-only completion == the model returned nothing.
    assert by_id["req-empty"]["empty"] is True
    # The preview is the LAST USER message, not the system prompt.
    assert "You are Nara" not in (by_id["req-empty"]["prompt_preview"] or "")


def test_model_io_limit_caps_rows(tmp_path):
    client = _client(_setup(tmp_path))
    calls = client.get("/api/model_io?limit=2").json()["calls"]
    assert [c["request_id"] for c in calls] == ["req-3", "req-2"]


def test_model_io_filter_model_substring_case_insensitive(tmp_path):
    client = _client(_setup(tmp_path))
    calls = client.get("/api/model_io?model=QWEN").json()["calls"]
    assert [c["request_id"] for c in calls] == ["req-2"]


def test_model_io_filter_caller_tag_substring(tmp_path):
    client = _client(_setup(tmp_path))
    calls = client.get("/api/model_io?caller_tag=nara.").json()["calls"]
    assert [c["request_id"] for c in calls] == ["req-3", "req-1"]


def test_model_io_filter_run_id_exact(tmp_path):
    client = _client(_setup(tmp_path))
    calls = client.get("/api/model_io?run_id=iter-9").json()["calls"]
    assert [c["request_id"] for c in calls] == ["req-3", "req-2"]
    # Exact, not substring.
    assert client.get("/api/model_io?run_id=iter").json()["calls"] == []


def test_model_io_filter_combo(tmp_path):
    client = _client(_setup(tmp_path))
    calls = client.get(
        "/api/model_io?run_id=iter-9&model=gemma&caller_tag=meta"
    ).json()["calls"]
    assert [c["request_id"] for c in calls] == ["req-3"]


def test_model_io_since_ts(tmp_path):
    client = _client(_setup(tmp_path))
    calls = client.get(
        "/api/model_io?since_ts=2026-08-18T01:00:01Z").json()["calls"]
    assert [c["request_id"] for c in calls] == ["req-3", "req-2"]


def test_model_io_unparseable_since_ts_is_a_400(tmp_path):
    # Inviolate rule 4: a broken filter fails loudly, never silently no-ops.
    client = _client(_setup(tmp_path))
    resp = client.get("/api/model_io?since_ts=yesterdayish")
    assert resp.status_code == 400
    assert "since_ts" in resp.json()["detail"]


# ─── /api/model_io?before_ts= — pagination (owner 2026-08-18: "show only
#     last 20 interactions" + a load-older walk) ────────────────────────

def _pts(i: int) -> str:
    return f"2026-08-18T01:00:{i:02d}Z"


PAGE_ROWS = [_call(_pts(i), f"pg-{i}") for i in range(7)]  # pg-0 oldest


def test_model_io_before_ts_strictly_older(tmp_path):
    client = _client(_setup(tmp_path, PAGE_ROWS))
    calls = client.get("/api/model_io?before_ts=" + _pts(4)).json()["calls"]
    # STRICTLY older: the boundary row (pg-4) itself is excluded, so the
    # client's next page can never duplicate the row it paged from.
    assert [c["request_id"] for c in calls] == ["pg-3", "pg-2", "pg-1",
                                                "pg-0"]


def test_model_io_paging_walk_tiles_with_no_overlap_no_gap(tmp_path):
    # The client's walk: newest page, then before_ts = the oldest ts of the
    # page just shown — pages must tile the log: no dupes, no gaps, and the
    # final page says the walk ended because the file did (not the cap).
    client = _client(_setup(tmp_path, PAGE_ROWS))
    page1 = client.get("/api/model_io?limit=3").json()["calls"]
    assert [c["request_id"] for c in page1] == ["pg-6", "pg-5", "pg-4"]
    page2 = client.get(
        "/api/model_io?limit=3&before_ts=" + page1[-1]["ts"]).json()["calls"]
    assert [c["request_id"] for c in page2] == ["pg-3", "pg-2", "pg-1"]
    body3 = client.get(
        "/api/model_io?limit=3&before_ts=" + page2[-1]["ts"]).json()
    assert [c["request_id"] for c in body3["calls"]] == ["pg-0"]
    assert body3["window_truncated"] is False
    ids = [c["request_id"] for c in page1 + page2 + body3["calls"]]
    assert len(ids) == len(set(ids)) == 7


def test_model_io_before_ts_composes_with_filters(tmp_path):
    rows = [
        _call(_pts(0), "old-q", model="qwen3.8-27b", backend="vllm-qwen"),
        _call(_pts(1), "old-g"),
        _call(_pts(2), "new-q", model="qwen3.8-27b", backend="vllm-qwen"),
    ]
    client = _client(_setup(tmp_path, rows))
    calls = client.get(
        "/api/model_io?model=qwen&before_ts=" + _pts(2)).json()["calls"]
    assert [c["request_id"] for c in calls] == ["old-q"]


def test_model_io_unparseable_before_ts_is_a_400(tmp_path):
    client = _client(_setup(tmp_path))
    resp = client.get("/api/model_io?before_ts=lastweekish")
    assert resp.status_code == 400
    assert "before_ts" in resp.json()["detail"]


def test_model_io_before_ts_excludes_unparseable_row_ts(tmp_path):
    # A row whose own timestamp does not parse cannot PROVE it is older
    # than the boundary — excluded while paging, never guessed in (the
    # same stance since_ts already takes).
    bad = _call(_pts(1), "pg-bad")
    bad["timestamp"] = "not-a-timestamp"
    client = _client(_setup(tmp_path, [_call(_pts(0), "pg-ok"), bad]))
    calls = client.get("/api/model_io?before_ts=" + _pts(5)).json()["calls"]
    assert [c["request_id"] for c in calls] == ["pg-ok"]


def test_model_io_before_ts_cap_hit_is_honest(tmp_path):
    # Older rows exist BEYOND the byte cap: the page comes back empty with
    # window_truncated True — the client's button reports "older rows
    # beyond scan window" off this flag instead of silently stopping.
    logs = tmp_path / "logs"
    logs.mkdir()
    old = json.dumps(_call("2026-08-01T00:00:00Z", "req-old")) + "\n"
    filler = "".join(
        json.dumps(_call("2026-08-18T01:00:00Z", f"req-f{i}")) + "\n"
        for i in range(200))                     # ≫ 16 KiB of newer rows
    (logs / "calls.jsonl").write_text(old + filler, encoding="utf-8")
    client = _client(logs, max_scan_bytes=16 * 1024)
    body = client.get(
        "/api/model_io?before_ts=2026-08-10T00:00:00Z").json()
    assert body["calls"] == []
    assert body["window_truncated"] is True


def test_model_io_default_limit_is_20(tmp_path):
    # Owner request: the page shows the last ~20 interactions by default;
    # the wire default matches (the frontend also passes limit=20).
    rows = [_call(f"2026-08-18T01:{i // 60:02d}:{i % 60:02d}Z", f"d-{i}")
            for i in range(25)]
    client = _client(_setup(tmp_path, rows))
    body = client.get("/api/model_io").json()
    assert len(body["calls"]) == 20
    assert body["calls"][0]["request_id"] == "d-24"


def test_model_io_absent_and_empty_file(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    client = _client(logs)                       # no calls.jsonl at all
    body = client.get("/api/model_io").json()
    assert body["calls"] == [] and body["window_truncated"] is False
    (logs / "calls.jsonl").write_text("", encoding="utf-8")
    assert client.get("/api/model_io").json()["calls"] == []


def test_model_io_malformed_lines_are_skipped(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "calls.jsonl").write_text(
        json.dumps(_call("2026-08-18T01:00:00Z", "req-ok")) + "\n"
        + "{not json}\n" + "[1,2,3]\n", encoding="utf-8")
    calls = _client(logs).get("/api/model_io").json()["calls"]
    assert [c["request_id"] for c in calls] == ["req-ok"]


# ─── the tail-read bound is REAL ──────────────────────────────────────

def test_model_io_works_with_10k_junk_line_prefix(tmp_path):
    # The production file is tens of MB; the endpoint reads backward from
    # EOF, so a huge prefix must be irrelevant — the real rows at the tail
    # come back and the junk is never parsed (bounded scan, small bound).
    logs = tmp_path / "logs"
    logs.mkdir()
    junk = "".join(f'{{"junk": {i}}}\n' for i in range(10_000))
    real = "".join(json.dumps(r) + "\n" for r in CALL_ROWS)
    (logs / "calls.jsonl").write_text(junk + real, encoding="utf-8")
    # Bound far smaller than the junk prefix: only a tail window is legal.
    client = _client(logs, max_scan_bytes=64 * 1024)
    body = client.get("/api/model_io?limit=3").json()
    assert [c["request_id"] for c in body["calls"]] == ["req-3", "req-2",
                                                        "req-1"]


def test_model_io_scan_bound_excludes_old_rows_honestly(tmp_path):
    # A matching row buried beyond max_scan_bytes is NOT found — and the
    # response says the window was truncated rather than pretending the
    # whole log was searched.
    logs = tmp_path / "logs"
    logs.mkdir()
    old = json.dumps(_call("2026-08-01T00:00:00Z", "req-old",
                           tag="needle_tag")) + "\n"
    filler = "".join(
        json.dumps(_call("2026-08-18T01:00:00Z", f"req-f{i}")) + "\n"
        for i in range(200))                     # ≫ 16 KiB of newer rows
    (logs / "calls.jsonl").write_text(old + filler, encoding="utf-8")
    client = _client(logs, max_scan_bytes=16 * 1024)
    body = client.get("/api/model_io?caller_tag=needle_tag").json()
    assert body["calls"] == []
    assert body["window_truncated"] is True


# ─── /api/model_io/{request_id} — the full row ────────────────────────

def test_model_io_detail_returns_the_full_row(tmp_path):
    client = _client(_setup(tmp_path))
    body = client.get("/api/model_io/req-2").json()
    assert body["found"] is True
    call = body["call"]
    # RAW passthrough: the full prompt_messages and completion, untruncated.
    assert call["prompt_messages"][0]["role"] == "system"
    assert call["prompt_messages"][1]["content"] == \
        "Evaluate this research topic"
    assert call["completion"] == "a completion"
    assert call["usage"] == {"input_tokens": 100, "output_tokens": 20}


def test_model_io_detail_404_for_unknown_id(tmp_path):
    client = _client(_setup(tmp_path))
    resp = client.get("/api/model_io/no-such-request")
    assert resp.status_code == 404
    assert "bounded scan window" in resp.json()["detail"]


def test_model_io_detail_404_beyond_the_bound(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    old = json.dumps(_call("2026-08-01T00:00:00Z", "req-old")) + "\n"
    filler = "".join(
        json.dumps(_call("2026-08-18T01:00:00Z", f"req-f{i}")) + "\n"
        for i in range(200))
    (logs / "calls.jsonl").write_text(old + filler, encoding="utf-8")
    client = _client(logs, max_scan_bytes=16 * 1024)
    assert client.get("/api/model_io/req-old").status_code == 404
    assert client.get("/api/model_io/req-f199").status_code == 200


# ─── /api/dispatch_trace ──────────────────────────────────────────────

def test_dispatch_trace_joins_triples_by_task_id(tmp_path):
    logs = _setup(tmp_path)
    _write_jsonl(logs / "orchestrator.jsonl", ORCH_ROWS)
    body = _client(logs).get("/api/dispatch_trace").json()
    assert body["orchestrator_available"] is True
    assert [t["task_id"] for t in body["tasks"]] == ["task-b", "task-a"]
    done = body["tasks"][1]
    # The receipt (latest row) owns the final status/stage/duration.
    assert done["task_type"] == "experiment_trial"
    assert done["status"] == "passed"
    assert done["stage"] == "orchestrator_receipt"
    assert done["duration_ms"] == 0.2
    assert done["ts"] == "2026-08-18T02:00:00.3Z"
    inflight = body["tasks"][0]
    assert inflight["status"] == "dispatched"
    assert inflight["duration_ms"] is None


def test_dispatch_trace_limit(tmp_path):
    logs = _setup(tmp_path)
    _write_jsonl(logs / "orchestrator.jsonl", ORCH_ROWS)
    body = _client(logs).get("/api/dispatch_trace?limit=1").json()
    assert [t["task_id"] for t in body["tasks"]] == ["task-b"]


def test_dispatch_trace_spawn_entries(tmp_path):
    logs = _setup(tmp_path)
    _write_jsonl(logs / "orchestrator.jsonl", ORCH_ROWS)
    spawn = tmp_path / "run_state" / "spawn.jsonl"
    _write_jsonl(spawn, SPAWN_ROWS)
    body = _client(logs, spawn=spawn).get("/api/dispatch_trace").json()
    assert body["spawn_available"] is True
    spawns = body["spawns"]
    # Newest-first; both timestamp spellings pass through.
    assert [s["spawn_id"] for s in spawns] == ["agent-2", "agent-1",
                                               "agent-1"]
    assert spawns[0]["ts"] == "2026-08-18T01:10:00Z"
    assert spawns[0]["task_statement"] == "short task"
    # The closing line (no contract) is backfilled from its opener…
    closing = spawns[1]
    assert closing["status"] == "completed"
    assert closing["task_statement"] is not None
    assert closing["task_statement"].startswith("Build the 3c two-voice")
    # …and statements are truncated for the compact strip.
    assert len(closing["task_statement"]) <= 140


def test_dispatch_trace_absent_files_degrade_honestly(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    body = _client(logs).get("/api/dispatch_trace").json()
    assert body == {
        "orchestrator_available": False, "spawn_available": False,
        "tasks": [], "spawns": [],
        "generated_at": body["generated_at"],
    }


# ─── /api/runtime_activity — the RUNTIME plane (owner feedback: the old
#     top cards conflated dev build agents with runtime agents) ─────────

# Shaped after the REAL caller_tag vocabulary observed in logs/calls.jsonl
# 2026-08-18: promotion-panel skeptics + synthesize share a
# promote_findings_<hash> run_id (parent null); two-voice session rows share
# a finding_session_fs-<hash> run_id; debate turns are run_subagent children
# tagged subagent.debate_<role> carrying the iteration id as
# parent_request_id.
QWEN = "qwen3.6-27b-nvfp4-mtp"
SUBAGENT_ROWS = [
    # Promotion panel run A: 3 skeptics (qwen) + the synthesize fan-in
    # (gemma) — ONE group keyed by the shared run_id.
    _call("2026-08-18T03:00:00Z", "sk1", model=QWEN, backend="vllm-qwen",
          tag="subagent.finding_skeptic_1", run_id="promote_findings_aaa"),
    _call("2026-08-18T03:00:01Z", "sk2", model=QWEN, backend="vllm-qwen",
          tag="subagent.finding_skeptic_2", run_id="promote_findings_aaa"),
    _call("2026-08-18T03:00:02Z", "sk3", model=QWEN, backend="vllm-qwen",
          tag="subagent.finding_skeptic_3", run_id="promote_findings_aaa"),
    _call("2026-08-18T03:00:03Z", "syn", tag="finding_promotion.synthesize",
          run_id="promote_findings_aaa"),
    # An OLDER promotion run B — a SEPARATE group (different run_id).
    _call("2026-08-18T02:00:00Z", "skb", model=QWEN, backend="vllm-qwen",
          tag="subagent.finding_skeptic_1", run_id="promote_findings_bbb"),
    # Two-voice session.
    _call("2026-08-18T03:10:00Z", "fsa", model=QWEN, backend="vllm-qwen",
          tag="finding_session_attacker", run_id="finding_session_fs-1"),
    _call("2026-08-18T03:10:05Z", "fsd", tag="finding_session_defender",
          run_id="finding_session_fs-1"),
    # Debate turns: no run_id; grouped by the shared parent_request_id.
    _call("2026-08-18T03:20:00Z", "dbc", model=QWEN, backend="vllm-qwen",
          tag="subagent.debate_challenger", parent="iter-2026-08-18-004"),
    _call("2026-08-18T03:20:10Z", "dbd", tag="subagent.debate_defender",
          parent="iter-2026-08-18-004"),
    # NOT subagent work — Nara chain/station calls must be EXCLUDED even
    # though they carry parent/run ids.
    _call("2026-08-18T03:30:00Z", "nara1", tag="nara.run_iteration",
          run_id="iter-2026-08-18-004", parent="iter-2026-08-18-004"),
    _call("2026-08-18T03:30:01Z", "hyp1", tag="hypothesize",
          run_id="iter-2026-08-18-004", parent="x-1"),
]


def test_runtime_activity_groups_subagent_families(tmp_path):
    # CALL_ROWS tags (nara.run_iteration / skeptic_battery / nara.meta_review)
    # are chain-plane too — none may leak into the groups.
    client = _client(_setup(tmp_path, CALL_ROWS + SUBAGENT_ROWS))
    body = client.get("/api/runtime_activity").json()
    assert body["calls_available"] is True
    groups = body["subagent_groups"]
    # Exactly the 4 evidence-backed groups, newest-first by last activity.
    assert [(g["family"], g["group_key"]) for g in groups] == [
        ("debate", "iter-2026-08-18-004"),
        ("two_voice_session", "finding_session_fs-1"),
        ("promotion_panel", "promote_findings_aaa"),
        ("promotion_panel", "promote_findings_bbb"),
    ]
    debate, two_voice, promo_a, promo_b = groups
    # Debate: keyed by parent_request_id (rows carry no run_id).
    assert debate["key_source"] == "parent_request_id"
    assert debate["calls"] == 2
    assert debate["label"] == "bounded debate"
    assert sorted(debate["caller_tags"]) == [
        "subagent.debate_challenger", "subagent.debate_defender"]
    # Two-voice session.
    assert two_voice["label"] == "two-voice session"
    assert two_voice["key_source"] == "run_id"
    assert two_voice["calls"] == 2
    # Promotion run A: 3 skeptics + synthesize = 4 calls, one group; the
    # skeptic count in the label is DERIVED from the tags present.
    assert promo_a["calls"] == 4
    assert promo_a["label"] == "promotion panel (3 skeptics)"
    assert promo_a["key_source"] == "run_id"
    assert set(promo_a["models"]) == {QWEN, "gemma-4-26b-a4b"}
    assert promo_a["first_ts"] == "2026-08-18T03:00:00Z"
    assert promo_a["last_ts"] == "2026-08-18T03:00:03Z"
    # Promotion run B stays its own group with its own derived count.
    assert promo_b["calls"] == 1
    assert promo_b["label"] == "promotion panel (1 skeptic)"
    # No chain-plane tag leaked into any group.
    all_tags = {t for g in groups for t in g["caller_tags"]}
    assert not any(t.startswith("nara.") or t == "hypothesize"
                   or t == "skeptic_battery" for t in all_tags)


def test_runtime_activity_generic_subagent_family(tmp_path):
    rows = [_call("2026-08-18T04:00:00Z", "gx",
                  tag="subagent.lit_scan", run_id="run-x")]
    body = _client(_setup(tmp_path, rows)).get("/api/runtime_activity").json()
    assert [(g["family"], g["label"]) for g in body["subagent_groups"]] == [
        ("subagent:lit_scan", "lit_scan")]


def test_runtime_activity_chain_joins_triples(tmp_path):
    logs = _setup(tmp_path)
    _write_jsonl(logs / "orchestrator.jsonl", ORCH_ROWS)
    body = _client(logs).get("/api/runtime_activity").json()
    assert body["orchestrator_available"] is True
    chain = body["chain"]
    assert [t["task_id"] for t in chain] == ["task-b", "task-a"]
    # The receipt (latest row) owns the joined task's final state — same
    # join as /api/dispatch_trace, shared helper.
    assert chain[1]["task_type"] == "experiment_trial"
    assert chain[1]["status"] == "passed"
    assert chain[1]["duration_ms"] == 0.2
    assert chain[0]["status"] == "dispatched"


def test_runtime_activity_group_cap(tmp_path):
    # 10 distinct promotion runs -> only the newest 8 groups come back.
    rows = [
        _call(f"2026-08-18T03:00:{i:02d}Z", f"cap-{i}", model=QWEN,
              tag="subagent.finding_skeptic_1",
              run_id=f"promote_findings_{i:02d}")
        for i in range(10)
    ]
    body = _client(_setup(tmp_path, rows)).get("/api/runtime_activity").json()
    groups = body["subagent_groups"]
    assert len(groups) == 8
    assert groups[0]["group_key"] == "promote_findings_09"
    assert groups[-1]["group_key"] == "promote_findings_02"


def test_runtime_activity_scan_bound_is_honest(tmp_path):
    # A subagent burst buried beyond the byte bound is NOT grouped — and the
    # response says the window was truncated rather than pretending the
    # whole log was searched.
    logs = tmp_path / "logs"
    logs.mkdir()
    old = json.dumps(
        _call("2026-08-01T00:00:00Z", "old-sk", model=QWEN,
              tag="subagent.finding_skeptic_1",
              run_id="promote_findings_old")) + "\n"
    filler = "".join(
        json.dumps(_call("2026-08-18T01:00:00Z", f"req-f{i}")) + "\n"
        for i in range(200))                     # ≫ 16 KiB of chain rows
    (logs / "calls.jsonl").write_text(old + filler, encoding="utf-8")
    body = _client(logs, max_scan_bytes=16 * 1024) \
        .get("/api/runtime_activity").json()
    assert body["subagent_groups"] == []
    assert body["window_truncated"] is True


def test_runtime_activity_absent_files_degrade_honestly(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    body = _client(logs).get("/api/runtime_activity").json()
    assert body["orchestrator_available"] is False
    assert body["calls_available"] is False
    assert body["chain"] == []
    assert body["subagent_groups"] == []
    assert body["window_truncated"] is False
