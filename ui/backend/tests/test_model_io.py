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

from backend.model_io import _session_id, register


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


# ─── session threads (owner 2026-08-19: "I posed 3 questions … but it shows
#     up as 6 cards instead of maybe 1 or 2 (since it goes to 2 models)") ──
#
# The finding-session engine is a STATELESS REPLAY (orchestrator/
# finding_session.py): every turn re-sends the whole message stack, so a
# 3-question two-voice interrogation is 6 wrapper calls each carrying the
# entire growing prompt. The pins below are: those rows group into ONE
# thread, the per-turn payload is the NEW question only (the prefix is a
# COUNT), non-session rows are untouched, detection never guesses, and a
# thread costs ONE row of the page's limit.

GEMMA = "gemma-4-26b-a4b"
QWEN38 = "qwen3.8-27b-nvfp4-mtp"

QUESTIONS = [
    "what is the reason we should kill this idea",
    "what would you do if you thought the idea was good, but we are just "
    "lacking validation on the expiermentation front?",
    "So if you both could give just 1 word, kill or reframe what would it be?",
]


def _session_call(ts: str, req: str, *, session: str = "fs-6eddb609a03a",
                  stance: str | None = "defender", model: str = GEMMA,
                  backend: str = "vllm-gemma", prior=(), question: str = "q",
                  completion: str = "an answer") -> dict:
    """One finding-session wrapper call, REPLAY AND ALL.

    `prior` is the [(question, answer), ...] already exchanged with THIS
    voice — the engine re-sends them ahead of the new question every turn,
    which is exactly what the thread grouping has to collapse."""
    messages = [{"role": "system", "content": "You are the " + str(stance)}]
    for q, a in prior:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": question})
    tag = "finding_session" if stance is None else f"finding_session_{stance}"
    return {
        "timestamp": ts, "request_id": req, "parent_request_id": None,
        "model": model, "backend": backend, "caller_tag": tag,
        "run_id": f"finding_session_{session}",
        "prompt_messages": messages, "completion": completion,
        "usage": {"input_tokens": 2695, "output_tokens": 709},
        "latency_ms": 27457.8,
    }


def _two_voice_rows(session: str = "fs-6eddb609a03a", questions=None,
                    start: int = 0) -> list[dict]:
    """The owner's real shape: N questions, each asked of BOTH voices —
    defender on gemma, attacker on qwen — in chronological file order."""
    questions = QUESTIONS if questions is None else questions
    voices = (("defender", GEMMA, "vllm-gemma"),
              ("attacker", QWEN38, "vllm-qwen"))
    prior: dict[str, list] = {"defender": [], "attacker": []}
    rows: list[dict] = []
    clock = start
    for i, question in enumerate(questions):
        for stance, model, backend in voices:
            answer = f"{stance} answer to q{i}"
            rows.append(_session_call(
                _pts(clock), f"{stance[:3]}-{i}", session=session,
                stance=stance, model=model, backend=backend,
                prior=list(prior[stance]), question=question,
                completion=answer))
            prior[stance].append((question, answer))
            clock += 1
    return rows


def test_three_questions_two_models_is_ONE_thread(tmp_path):
    # The owner's exact complaint: 6 wrapper calls, 1 card, 3 questions x 2
    # answers — and not one of them left in the per-call list.
    client = _client(_setup(tmp_path, _two_voice_rows()))
    body = client.get("/api/model_io").json()
    assert body["calls"] == []
    assert len(body["threads"]) == 1
    thread = body["threads"][0]
    assert thread["kind"] == "session_thread"
    assert thread["session_id"] == "fs-6eddb609a03a"
    assert thread["run_id"] == "finding_session_fs-6eddb609a03a"
    assert thread["turn_count"] == 6
    # NO question_count on the wire (dropped 2026-08-19): a card can be
    # assembled from several page slices, so the only correct count is the
    # one the card derives from the turns it holds. The evidence that count
    # is built from is here — the per-turn user_delta sequence.
    assert "question_count" not in thread
    assert [t["user_delta"] for t in thread["turns"]] == [
        QUESTIONS[0], QUESTIONS[0], QUESTIONS[1], QUESTIONS[1],
        QUESTIONS[2], QUESTIONS[2]]
    assert thread["stances"] == ["attacker", "defender"]
    assert thread["models"] == [GEMMA, QWEN38]
    assert thread["caller_tags"] == ["finding_session_attacker",
                                     "finding_session_defender"]
    # Whole session in hand (every voice's opening [system, user] call).
    assert thread["turns_complete"] is True
    # Chronological, and the two voices interleave per question.
    assert [t["stance"] for t in thread["turns"]] == [
        "defender", "attacker"] * 3
    assert thread["started"] == _pts(0)
    assert thread["ended"] == _pts(5)
    assert thread["wall_ms"] == 5000.0


def test_turn_carries_the_NEW_question_and_a_prefix_COUNT(tmp_path):
    # The replayed stack is never repeated per turn: each turn ships the last
    # USER message (the new ask) plus the number of messages ahead of it.
    client = _client(_setup(tmp_path, _two_voice_rows()))
    turns = client.get("/api/model_io").json()["threads"][0]["turns"]
    assert [t["user_delta"] for t in turns] == [
        QUESTIONS[0], QUESTIONS[0], QUESTIONS[1], QUESTIONS[1],
        QUESTIONS[2], QUESTIONS[2]]
    # [system,user] -> 1; then +2 replayed messages per prior exchange.
    assert [t["prefix_message_count"] for t in turns] == [1, 1, 3, 3, 5, 5]
    # No turn carries the replayed prose itself.
    for turn in turns:
        assert QUESTIONS[0] not in turn["completion"]
    first = turns[0]
    assert first["stance"] == "defender"
    assert first["model"] == GEMMA
    assert first["backend"] == "vllm-gemma"
    assert first["tokens_in"] == 2695 and first["tokens_out"] == 709
    assert first["latency_ms"] == 27457.8
    assert first["request_id"] == "def-0"
    assert first["empty"] is False


def test_turn_order_preserves_the_ask_sequence_for_the_card(tmp_path):
    # The card collapses CONSECUTIVE identical asks into one question block
    # (a "both" turn fans one question to two voices) and honestly treats a
    # repeat asked later as a second question. That derivation lives in
    # SessionThreadCard.questionGroups — the backend's job is to hand over
    # the ask sequence in chronological order, unscrambled.
    rows = _two_voice_rows(questions=["same", "other", "same"])
    thread = _client(_setup(tmp_path, rows)).get(
        "/api/model_io").json()["threads"][0]
    assert thread["turn_count"] == 6
    assert [t["user_delta"] for t in thread["turns"]] == [
        "same", "same", "other", "other", "same", "same"]


def test_non_session_calls_keep_their_per_call_rows(tmp_path):
    # Iteration chains / batteries / promotion panels are untouched: they
    # stay in `calls` with the same summary shape as before the grouping.
    rows = [_call(_pts(0), "iter-1"),
            *_two_voice_rows(start=1),
            _call(_pts(7), "iter-2", tag="subagent.finding_skeptic_1",
                  run_id="promote_findings_abc")]
    body = _client(_setup(tmp_path, rows)).get("/api/model_io").json()
    assert [c["request_id"] for c in body["calls"]] == ["iter-2", "iter-1"]
    assert body["calls"][0]["completion_preview"] == "a completion"
    assert len(body["threads"]) == 1
    assert body["threads"][0]["turn_count"] == 6


def test_session_detection_is_conservative(tmp_path):
    # BOTH signals are required. A session-shaped run_id under a foreign
    # caller_tag, or a session caller_tag with no session run_id, is NOT
    # grouped — the grouping never guesses a session into existence.
    tag_only = _session_call(_pts(0), "tag-only")
    tag_only["run_id"] = None
    run_only = _call(_pts(1), "run-only", tag="nara.run_iteration",
                     run_id="finding_session_fs-deadbeef")
    look_alike = _call(_pts(2), "look-alike", tag="finding_promotion.synthesize",
                       run_id="promote_findings_abc")
    body = _client(_setup(tmp_path, [tag_only, run_only, look_alike])) \
        .get("/api/model_io").json()
    assert body["threads"] == []
    assert [c["request_id"] for c in body["calls"]] == ["look-alike",
                                                        "run-only", "tag-only"]


def test_single_voice_session_has_no_invented_stance(tmp_path):
    # The bare "finding_session" tag (chat seam) and the tutor still thread —
    # the bare one simply has no stance, rather than being assigned one.
    rows = [_session_call(_pts(0), "chat-1", stance=None, question="hi"),
            _session_call(_pts(1), "tut-1", session="fs-tutor",
                          stance="tutor", model=QWEN38, backend="vllm-qwen",
                          question="teach me")]
    threads = _client(_setup(tmp_path, rows)).get(
        "/api/model_io").json()["threads"]
    by_id = {t["session_id"]: t for t in threads}
    assert by_id["fs-6eddb609a03a"]["stances"] == []
    assert by_id["fs-6eddb609a03a"]["turns"][0]["stance"] is None
    assert by_id["fs-tutor"]["stances"] == ["tutor"]


def test_thread_counts_as_ONE_row_of_the_page_limit(tmp_path):
    # Pagination unit = a row AS THE UI SEES IT. Over 3 plain calls sitting
    # on top of a 6-call session: limit=3 is the three calls and nothing
    # else; limit=4 adds the whole session as the FOURTH row (not 6 rows,
    # and not a stump).
    rows = [*_two_voice_rows(),
            _call(_pts(6), "c-1"), _call(_pts(7), "c-2"),
            _call(_pts(8), "c-3")]
    client = _client(_setup(tmp_path, rows))
    body3 = client.get("/api/model_io?limit=3").json()
    assert [c["request_id"] for c in body3["calls"]] == ["c-3", "c-2", "c-1"]
    assert body3["threads"] == []
    body4 = client.get("/api/model_io?limit=4").json()
    assert [c["request_id"] for c in body4["calls"]] == ["c-3", "c-2", "c-1"]
    assert len(body4["threads"]) == 1
    # The thread opened at the limit boundary is still COMPLETE: the bounded
    # backfill walks its remaining turns rather than showing a stump.
    assert body4["threads"][0]["turn_count"] == 6
    assert body4["threads"][0]["turns_complete"] is True


def test_default_limit_counts_threads_as_rows(tmp_path):
    # 20 plain calls + a 6-call session = 21 rows; the default page shows 20
    # of them, and the newest 20 rows here are the calls (the session is
    # oldest), so it drops out entirely rather than eating 6 slots.
    rows = [*_two_voice_rows(), *[_call(_pts(6 + i), f"c-{i}")
                                  for i in range(20)]]
    body = _client(_setup(tmp_path, rows)).get("/api/model_io").json()
    assert len(body["calls"]) == 20
    assert body["threads"] == []


# ─── paging coverage: page1 ∪ page2 = the span, exactly once ───────────
#
# THE BUG THESE REPLACE (2026-08-19). The two green tests here built
# CONTIGUOUS sessions — no plain rows inside the thread's span — which is the
# ONLY shape where "page from the thread's `started`" looks right. Real logs
# interleave: the coordinator, the daemon and the batteries all write to
# calls.jsonl while a chat session is open. The page's guaranteed coverage
# ends at its FILL POINT, but THREAD_BACKFILL_ROWS lets the scan walk up to
# 60 rows PAST that point to finish an open thread, and every non-session row
# it walked was DROPPED. The client then paged from the thread's `started` —
# older than the fill point — so those dropped rows appeared on NEITHER page
# and the UI went on to announce "beginning of log reached".
#
# The fix is a wire contract, not a smarter client guess: the scan reports
# its own fill point as `next_before_ts`, and returns every row it walked.
# The tests below drive the pager the way the UI does — page 1, then
# before_ts = THE SERVER'S next_before_ts — and assert set equality against
# the fixture, which is what "no gap AND no duplicate" actually means.


def _interleaved_session_rows(questions: int = 2) -> list[dict]:
    """A two-voice session with PLAIN calls BETWEEN its turns.

    Chronological: plain, def-0, plain, att-0, plain, def-1, plain, att-1,
    plain — i.e. every session turn has unrelated traffic on both sides,
    which is the shape the old paging rule silently lost rows in."""
    voices = (("defender", GEMMA, "vllm-gemma"),
              ("attacker", QWEN38, "vllm-qwen"))
    prior: dict[str, list] = {"defender": [], "attacker": []}
    rows = [_call(_pts(0), "plain-0")]
    clock = 1
    for i in range(questions):
        for stance, model, backend in voices:
            answer = f"{stance} answer to q{i}"
            rows.append(_session_call(
                _pts(clock), f"{stance[:3]}-{i}", stance=stance, model=model,
                backend=backend, prior=list(prior[stance]),
                question=QUESTIONS[i], completion=answer))
            prior[stance].append((QUESTIONS[i], answer))
            clock += 1
            rows.append(_call(_pts(clock), f"plain-{clock}"))
            clock += 1
    return rows


def _delivered(body: dict) -> list[str]:
    """Every LOG ROW a page actually delivered — plain calls AND the turns
    inside its threads. Coverage is measured in rows, not in UI cards."""
    ids = [c["request_id"] for c in body["calls"]]
    for thread in body["threads"]:
        ids.extend(t["request_id"] for t in thread["turns"])
    return ids


def _walk_pages(client, limit: int, query: str = "") -> list[dict]:
    """Drive the pager exactly as the UI does: page 1, then before_ts = the
    SERVER's next_before_ts, until the server says end_of_log. Never infers
    a boundary from the rendered items — that inference is the bug."""
    pages: list[dict] = []
    before: str | None = None
    for _ in range(30):                      # loop guard, never a stop rule
        url = f"/api/model_io?limit={limit}{query}"
        if before is not None:
            url += "&before_ts=" + before
        body = client.get(url).json()
        pages.append(body)
        if body["end_of_log"] or body["next_before_ts"] is None:
            break
        before = body["next_before_ts"]
    assert pages[-1]["end_of_log"] or pages[-1]["next_before_ts"] is None
    return pages


def test_pages_tile_a_log_that_INTERLEAVES_plain_calls_with_a_session(
        tmp_path):
    # THE B1 REGRESSION PIN. 9 rows: 5 plain calls interleaved with a
    # 4-turn session. limit=3 fills the page mid-session, so the backfill
    # walk crosses three plain rows on its way to the session's openers.
    rows = _interleaved_session_rows()
    client = _client(_setup(tmp_path, rows))
    pages = _walk_pages(client, limit=3)
    delivered = [rid for page in pages for rid in _delivered(page)]
    expected = [r["request_id"] for r in rows]
    # No gap: every row in the fixture came back. No duplicate: exactly once.
    assert sorted(delivered) == sorted(expected)
    assert len(delivered) == len(set(delivered)) == len(rows)
    # The session is ONE thread across the walk (its turns may split across
    # pages; the client folds the slices by session_id).
    sessions = {t["session_id"] for p in pages for t in p["threads"]}
    assert sessions == {"fs-6eddb609a03a"}


def test_page_one_covers_down_to_ITS_OWN_fill_point_not_the_thread_start(
        tmp_path):
    # The precise shape of the old defect: the thread's `started` sits
    # OLDER than / at the fill point while plain rows walked during the
    # backfill sat in between. Page 1 must DELIVER those rows — paging from
    # `started` while dropping them is what lost them.
    rows = _interleaved_session_rows()
    client = _client(_setup(tmp_path, rows))
    page1 = client.get("/api/model_io?limit=3").json()
    boundary = page1["next_before_ts"]
    assert boundary is not None and page1["end_of_log"] is False
    # The backfill really did run past the row budget (3 rows budgeted,
    # more than 3 rows delivered) — the ingredients of the bug are present.
    assert len(_delivered(page1)) > 3
    thread = page1["threads"][0]
    assert thread["started"] is not None
    # Every fixture row at or newer than the stated boundary is on page 1 …
    in_span = {r["request_id"] for r in rows if r["timestamp"] >= boundary}
    assert set(_delivered(page1)) == in_span
    # … including the plain rows that sit INSIDE the thread's own span,
    # which is where the old rule lost them: page 1 dropped them (they were
    # walked during the backfill) and a page keyed on the thread's `started`
    # is strictly older, so it never hands them back either.
    inside = [r["request_id"] for r in rows
              if _session_id(r) is None
              and thread["started"] <= r["timestamp"] <= thread["ended"]]
    assert inside                          # the fixture really interleaves
    assert set(inside) <= set(_delivered(page1))
    old_rule_page2 = client.get(
        "/api/model_io?before_ts=" + thread["started"]).json()
    assert set(inside) & set(_delivered(old_rule_page2)) == set()
    # … and page 2, keyed on the STATED boundary, tiles exactly, no overlap.
    page2 = client.get("/api/model_io?before_ts=" + boundary).json()
    assert set(_delivered(page1)) & set(_delivered(page2)) == set()
    assert set(_delivered(page1)) | set(_delivered(page2)) == {
        r["request_id"] for r in rows}


def test_pages_tile_when_a_thread_sits_at_EVERY_page_boundary(tmp_path):
    # Same interleaved log, every page size from 1 to 8: whichever row the
    # budget lands on — plain call, first turn, middle turn — the walk still
    # covers every row exactly once. A page size is not a special case.
    rows = _interleaved_session_rows(questions=3)
    client = _client(_setup(tmp_path, rows))
    expected = sorted(r["request_id"] for r in rows)
    for limit in range(1, 9):
        delivered = [rid for page in _walk_pages(client, limit=limit)
                     for rid in _delivered(page)]
        assert sorted(delivered) == expected, f"limit={limit}"
        assert len(delivered) == len(set(delivered)), f"limit={limit}"


def test_pages_tile_when_the_filter_thins_the_thread(tmp_path):
    # The coverage contract is over MATCHING rows: a model filter that
    # keeps only one voice still tiles, with no gap and no repeat.
    rows = _interleaved_session_rows(questions=3)
    client = _client(_setup(tmp_path, rows))
    pages = _walk_pages(client, limit=2, query="&model=gemma")
    delivered = [rid for page in pages for rid in _delivered(page)]
    expected = sorted(r["request_id"] for r in rows
                      if "gemma" in r["model"].lower())
    assert sorted(delivered) == expected
    assert len(delivered) == len(set(delivered))


def test_a_page_never_stops_MID_TIMESTAMP(tmp_path):
    # before_ts is STRICTLY older, so a page that stops on one of two rows
    # sharing an instant would leave the other on neither page. Rows tying
    # the boundary ride this page instead.
    rows = [_call(_pts(0), "tie-old"),
            _call(_pts(1), "tie-a"), _call(_pts(1), "tie-b"),
            _call(_pts(2), "tie-new")]
    client = _client(_setup(tmp_path, rows))
    delivered = [rid for page in _walk_pages(client, limit=1)
                 for rid in _delivered(page)]
    assert sorted(delivered) == ["tie-a", "tie-b", "tie-new", "tie-old"]
    assert len(delivered) == 4


def test_end_of_log_and_next_before_ts_are_STATED_not_inferred(tmp_path):
    # The client no longer guesses "beginning of log" from a short page —
    # a short page can also mean "the byte cap stopped me". The two answers
    # are separate wire fields.
    client = _client(_setup(tmp_path, PAGE_ROWS))
    page1 = client.get("/api/model_io?limit=3").json()
    assert page1["end_of_log"] is False
    assert page1["next_before_ts"] == page1["calls"][-1]["ts"]
    last = client.get(
        "/api/model_io?limit=3&before_ts=" + _pts(1)).json()
    assert last["end_of_log"] is True
    assert last["next_before_ts"] is None
    # Byte cap: the walk stopped for a DIFFERENT reason, and says so.
    logs = tmp_path / "capped"
    logs.mkdir()
    filler = "".join(json.dumps(_call(_pts(3), f"f-{i}")) + "\n"
                     for i in range(200))
    (logs / "calls.jsonl").write_text(
        json.dumps(_call(_pts(0), "way-old")) + "\n" + filler,
        encoding="utf-8")
    capped_body = _client(logs, max_scan_bytes=16 * 1024).get(
        "/api/model_io?before_ts=" + _pts(2)).json()
    assert capped_body["calls"] == []
    assert capped_body["window_truncated"] is True
    assert capped_body["end_of_log"] is False


def test_an_older_page_may_OPEN_a_thread_and_say_it_is_incomplete(tmp_path):
    # The thread does not start on the live page: page 2's own fill point is
    # where the session first appears, and its opening turns sit beyond the
    # scan's byte cap. The page says turns_complete False rather than
    # implying the card is the whole conversation — and the two pages still
    # tile the span they cover, with no row on neither page.
    # Chronological AND file order (the scan reads file order backward):
    # the two openers, 30 unrelated calls, the session's later turns, then
    # two fresh calls on top.
    rows = [
        _session_call(_pts(0), "def-0", stance="defender",
                      question=QUESTIONS[0], completion="d0"),
        _session_call(_pts(1), "att-0", stance="attacker", model=QWEN38,
                      backend="vllm-qwen", question=QUESTIONS[0],
                      completion="a0"),
        *[_call(_pts(2 + i), f"f-{i}") for i in range(30)],
        _session_call(_pts(32), "def-1", stance="defender",
                      prior=[(QUESTIONS[0], "d0")], question=QUESTIONS[1],
                      completion="d1"),
        _session_call(_pts(33), "att-1", stance="attacker", model=QWEN38,
                      backend="vllm-qwen", prior=[(QUESTIONS[0], "a0")],
                      question=QUESTIONS[1], completion="a1"),
        _call(_pts(34), "n-0"), _call(_pts(35), "n-1"),
    ]
    client = _client(_setup(tmp_path, rows), max_scan_bytes=6 * 1024)

    page1 = client.get("/api/model_io?limit=2").json()
    assert [c["request_id"] for c in page1["calls"]] == ["n-1", "n-0"]
    assert page1["threads"] == []                # the session is older
    boundary = page1["next_before_ts"]
    assert boundary is not None

    page2 = client.get(
        "/api/model_io?limit=2&before_ts=" + boundary).json()
    thread = page2["threads"][0]
    assert thread["session_id"] == "fs-6eddb609a03a"
    # The thread OPENED at page 2's own fill point and its opening turns are
    # outside the scanned window — it says so instead of implying the card
    # is the whole conversation.
    assert thread["turns_complete"] is False
    assert min(t["prefix_message_count"] for t in thread["turns"]) > 1
    assert {t["request_id"] for t in thread["turns"]} == {"def-1", "att-1"}
    # No overlap between the pages, and nothing in the span they cover is
    # missing from their union.
    assert set(_delivered(page1)) & set(_delivered(page2)) == set()
    covered_from = page2["next_before_ts"]
    assert covered_from is not None and page2["end_of_log"] is False
    span = {r["request_id"] for r in rows
            if r["timestamp"] >= covered_from}
    assert set(_delivered(page1)) | set(_delivered(page2)) == span


def test_a_page_bounds_the_turns_of_ONE_thread_and_says_so(tmp_path):
    # Turns do NOT consume the page's row budget (a session is one row), so
    # before the page fills a huge session could append without limit and
    # blow the polled response. THREAD_MAX_TURNS bounds it — by STOPPING the
    # page (never by dropping a row): the boundary freezes at the last turn
    # returned and the next page continues the session.
    from backend.model_io import THREAD_MAX_TURNS
    n = THREAD_MAX_TURNS + 5
    rows = [_session_call(_pts(i), f"t-{i}", stance="tutor",
                          prior=[("q", "a")] * i, question=f"q{i}")
            for i in range(n)]
    client = _client(_setup(tmp_path, rows))
    page1 = client.get("/api/model_io?limit=20").json()
    thread = page1["threads"][0]
    assert thread["turn_count"] == THREAD_MAX_TURNS
    assert thread["turns_truncated"] is True
    assert thread["turns_complete"] is False
    assert page1["end_of_log"] is False
    # Bounded, not lossy: the walk resumes exactly where it stopped.
    delivered = [rid for page in _walk_pages(client, limit=20)
                 for rid in _delivered(page)]
    assert sorted(delivered) == sorted(r["request_id"] for r in rows)
    assert len(delivered) == n


def test_turns_truncated_is_false_on_an_ordinary_thread(tmp_path):
    thread = _client(_setup(tmp_path, _two_voice_rows())).get(
        "/api/model_io").json()["threads"][0]
    assert thread["turns_truncated"] is False


def test_filters_apply_to_rows_and_thin_the_thread_honestly(tmp_path):
    # A model filter over a two-voice session yields a ONE-stance thread —
    # the qwen turns are not smuggled in behind the matching gemma ones.
    client = _client(_setup(tmp_path, _two_voice_rows()))
    thread = client.get("/api/model_io?model=gemma").json()["threads"][0]
    assert thread["stances"] == ["defender"]
    assert thread["turn_count"] == 3
    assert [t["stance"] for t in thread["turns"]] == ["defender"] * 3
    assert client.get("/api/model_io?model=gemma").json()["calls"] == []


def test_thread_turns_complete_is_false_when_the_first_turn_is_out_of_window(
        tmp_path):
    # Honest bounded window: when the byte cap stops the scan before the
    # session's opening calls, the thread says so instead of implying the
    # card is the whole conversation.
    logs = tmp_path / "logs"
    logs.mkdir()
    rows = _two_voice_rows()
    head = "".join(json.dumps(r) + "\n" for r in rows[:2])   # the two openers
    tail = "".join(json.dumps(r) + "\n" for r in rows[2:])
    filler = "".join(json.dumps(_call(_pts(0), f"f-{i}")) + "\n"
                     for i in range(20))
    (logs / "calls.jsonl").write_text(head + filler + tail, encoding="utf-8")
    body = _client(logs, max_scan_bytes=8 * 1024).get(
        "/api/model_io?limit=2").json()
    thread = body["threads"][0]
    assert thread["turns_complete"] is False
    assert min(t["prefix_message_count"] for t in thread["turns"]) > 1


def test_a_malformed_row_cannot_FORGE_thread_completeness(tmp_path):
    # prefix_message_count 0 is real evidence ("the stack IS the opening
    # question"), so a row with NO legible prompt_messages must not report 0
    # — it would forge that proof and make a truncated thread claim it was
    # the whole conversation. It reports null: no evidence, proves nothing.
    rows = [_session_call(_pts(0), "broken-1", stance="tutor")]
    rows[0]["prompt_messages"] = []
    thread = _client(_setup(tmp_path, rows)).get(
        "/api/model_io").json()["threads"][0]
    assert thread["turns"][0]["prefix_message_count"] is None
    assert thread["turns"][0]["user_delta"] is None
    assert thread["turns_complete"] is False


def test_a_genuine_zero_prefix_still_proves_the_opening_turn(tmp_path):
    # The other side of the same coin: a prompt that really is just the
    # question (no system message) has prefix 0 and IS the opening turn.
    rows = [_session_call(_pts(0), "bare-1", stance="tutor")]
    rows[0]["prompt_messages"] = [{"role": "user", "content": "first ask"}]
    thread = _client(_setup(tmp_path, rows)).get(
        "/api/model_io").json()["threads"][0]
    assert thread["turns"][0]["prefix_message_count"] == 0
    assert thread["turns_complete"] is True


def test_a_voice_whose_only_evidence_is_malformed_blocks_completeness(
        tmp_path):
    # Two voices; the defender's only turn is malformed. The attacker's
    # opener proves nothing about the defender, so the thread is NOT whole.
    rows = _two_voice_rows(questions=["only question"])
    rows[0]["prompt_messages"] = None                  # the defender turn
    thread = _client(_setup(tmp_path, rows)).get(
        "/api/model_io").json()["threads"][0]
    by_stance = {t["stance"]: t for t in thread["turns"]}
    assert by_stance["defender"]["prefix_message_count"] is None
    assert by_stance["attacker"]["prefix_message_count"] == 1
    assert thread["turns_complete"] is False


def test_thread_clips_a_runaway_completion_and_says_so(tmp_path):
    rows = [_session_call(_pts(0), "big-1", completion="x" * 9000,
                          question="y" * 3000)]
    turn = _client(_setup(tmp_path, rows)).get(
        "/api/model_io").json()["threads"][0]["turns"][0]
    assert turn["completion"] == "x" * 6000
    assert turn["completion_truncated"] is True
    assert turn["user_delta"] == "y" * 2000
    assert turn["user_delta_truncated"] is True


def test_thread_flags_an_empty_completion(tmp_path):
    rows = _two_voice_rows()
    rows[1]["completion"] = "  \n"
    thread = _client(_setup(tmp_path, rows)).get(
        "/api/model_io").json()["threads"][0]
    assert [t["empty"] for t in thread["turns"]] == [False, True, False,
                                                     False, False, False]


def test_threads_key_is_always_present(tmp_path):
    # Absent / empty log: the key exists and is empty — a consumer never has
    # to distinguish "no threads" from "old backend".
    logs = tmp_path / "logs"
    logs.mkdir()
    assert _client(logs).get("/api/model_io").json()["threads"] == []
    (logs / "calls.jsonl").write_text("", encoding="utf-8")
    assert _client(logs).get("/api/model_io").json()["threads"] == []
