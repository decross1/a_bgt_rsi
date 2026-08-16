"""orchestrator/lab_channel.py — timeline merge/determinism, turn stub +
fail-open context, delegate seams, and the fence (CLI surface + no
disposition imports). Hermetic: tmp_path everywhere, MOCK_LLM=1 forced —
the real memory/lab_channel.jsonl is NEVER touched by tests."""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator import lab_channel
from orchestrator import runtime as runtime_mod
from orchestrator.packet_dispatcher import consume_authorize_fix_queue
from workers import idea_ledger

IDEA_SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schema"
     / "idea_ledger.schema.json").read_text())


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    """Hermetic regardless of shell env: the stub path is the behavior."""
    monkeypatch.setenv("MOCK_LLM", "1")


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _ledgers(tmp_path):
    """One coherent set of tmp ledgers spanning 2026-08-09..14."""
    paths = dict(
        transcript_path=tmp_path / "lab_channel.jsonl",
        cycles_path=tmp_path / "coordinator_cycles.jsonl",
        idea_ledger_path=tmp_path / "idea_ledger.jsonl",
        surfaced_path=tmp_path / "surfaced_findings.jsonl",
        loop_alert_path=tmp_path / "loop_alert.json",
    )
    _jsonl(paths["transcript_path"], [
        {"ts": "2026-08-10T00:00:00Z", "kind": "human", "message": "status?"},
        {"ts": "2026-08-10T00:00:05Z", "kind": "nara", "message": "running"},
    ])
    _jsonl(paths["cycles_path"], [
        {"timestamp": "2026-08-11T00:00:00Z", "topic": "T1",
         "status": "executed",
         "plan": [{"action": "run_loop_iteration", "args": {}}],
         "promoted_finding_ids": ["sf-1"],
         "planner_state": {"gaps": ["g1"]}},
    ])
    _jsonl(paths["idea_ledger_path"], [
        {"event_type": "cluster_created", "ts": "2026-08-09T00:00:00Z",
         "cluster_id": "cl-a", "origin": "iteration", "member_id": "iter-1"},
        {"event_type": "cluster_created", "ts": "2026-08-12T00:00:00Z",
         "cluster_id": "cl-b", "origin": "consolidation", "member_id": "i2"},
        {"event_type": "cluster_created", "ts": "2026-08-12T00:00:00Z",
         "cluster_id": "cl-c", "origin": "consolidation", "member_id": "i3"},
        {"event_type": "cluster_created", "ts": "2026-08-12T00:00:00Z",
         "cluster_id": "cl-d", "origin": "consolidation", "member_id": "i4"},
        {"event_type": "cluster_killed", "ts": "2026-08-12T06:00:00Z",
         "cluster_id": "cl-a",
         "kill_reason": {"code": "redteam_fatal_flaw",
                         "evidence_key": "iteration:iter-1:redteam",
                         "detail": "redteam verdict fatal_flaw on iter-1"},
         "reopening_condition": {"requires": "new_evidence",
                                 "evidence_kind": "redteam_proceed_on_revision"}},
        {"event_type": "cluster_reopened", "ts": "2026-08-13T00:00:00Z",
         "cluster_id": "cl-a",
         "evidence": {"evidence_kind": "redteam_proceed_on_revision"}},
    ])
    _jsonl(paths["surfaced_path"], [
        {"finding_id": "sf-1", "title": "Finding one",
         "promoted_at": "2026-08-11T12:00:00Z"},
    ])
    paths["loop_alert_path"].write_text(json.dumps(
        {"level": "ok", "reasons": [],
         "updated_at": "2026-08-14T00:00:00+00:00"}))
    return paths


# ── timeline ─────────────────────────────────────────────────────────────────

def test_timeline_merge_ordering_and_kinds(tmp_path):
    tl = lab_channel.timeline(**_ledgers(tmp_path))
    ts_list = [e["ts"] for e in tl]
    assert ts_list == sorted(ts_list)
    assert tl[0]["message"] == "cluster created: cl-a (iteration)"
    assert tl[-1]["message"] == "loop alert: ok"
    assert tl[-1]["ts"] == "2026-08-14T00:00:00Z"  # +00:00 normalized
    stored = [e for e in tl if e["kind"] in ("human", "nara", "pi")]
    derived = [e for e in tl if e["kind"] == "event"]
    # cycle + single-create + batch-create + kill + reopen + promotion + alert
    assert len(stored) == 2 and len(derived) == 7
    assert {e["kind"] for e in tl} == {"human", "nara", "event"}


def test_timeline_cycle_kill_reopen_promotion_lines(tmp_path):
    msgs = [e["message"] for e in lab_channel.timeline(**_ledgers(tmp_path))]
    assert ("cycle: T1 · executed · 1 plan action(s) · promoted 1") in msgs
    assert ("cluster killed: cl-a — redteam_fatal_flaw: "
            "redteam verdict fatal_flaw on iter-1") in msgs
    assert "cluster reopened: cl-a — redteam_proceed_on_revision" in msgs
    assert "promoted: sf-1 — Finding one" in msgs


def test_timeline_consolidation_batching(tmp_path):
    msgs = [e["message"] for e in lab_channel.timeline(**_ledgers(tmp_path))]
    assert msgs.count("clusters created: 3 (consolidation)") == 1
    assert not any("cl-b" in m or "cl-c" in m or "cl-d" in m for m in msgs)


def test_timeline_deterministic_and_pure(tmp_path):
    paths = _ledgers(tmp_path)
    before = {k: Path(p).read_text() for k, p in paths.items()}
    first = lab_channel.timeline(**paths)
    second = lab_channel.timeline(**paths)
    assert first == second  # derived at read time: same ledgers, same merge
    after = {k: Path(p).read_text() for k, p in paths.items()}
    assert before == after  # pure read: nothing stored anywhere
    assert set(tmp_path.iterdir()) == {Path(p) for p in paths.values()}


def test_timeline_since_and_limit(tmp_path):
    paths = _ledgers(tmp_path)
    since = lab_channel.timeline(**paths, since="2026-08-12T00:00:00Z")
    assert all(e["ts"] >= "2026-08-12T00:00:00Z" for e in since)
    assert len(since) == 4  # batch-create, kill, reopen, alert
    full = lab_channel.timeline(**paths)
    assert lab_channel.timeline(**paths, limit=2) == full[-2:]
    assert lab_channel.timeline(**paths, limit=0) == []


def test_timeline_missing_ledgers_is_empty(tmp_path):
    tl = lab_channel.timeline(
        transcript_path=tmp_path / "t.jsonl",
        cycles_path=tmp_path / "c.jsonl",
        idea_ledger_path=tmp_path / "i.jsonl",
        surfaced_path=tmp_path / "s.jsonl",
        loop_alert_path=tmp_path / "a.json")
    assert tl == []


# ── turn ─────────────────────────────────────────────────────────────────────

def _turn_paths(tmp_path, with_context=True):
    kw = dict(
        transcript_path=tmp_path / "lab_channel.jsonl",
        cycles_path=tmp_path / "cycles.jsonl",
        loop_alert_path=tmp_path / "alert.json",
        ideas_md_path=tmp_path / "ideas.md",
    )
    if with_context:
        kw["ideas_md_path"].write_text(
            "# Ideas\n- cl-a · L1 · next: synthetic experiment\n")
        _jsonl(kw["cycles_path"], [
            {"timestamp": "2026-08-11T00:00:00Z", "topic": "T1",
             "status": "planned", "plan": [], "planner_state": {"gaps": []}}])
        kw["loop_alert_path"].write_text(json.dumps(
            {"level": "ok", "reasons": [], "updated_at": "2026-08-11T00:00:00Z"}))
    return kw


def test_turn_stub_round_trip_and_append_order(tmp_path):
    kw = _turn_paths(tmp_path)
    out = lab_channel.turn(role="nara", message="what is running?", **kw)
    assert out["status"] == "passed"
    assert out["reply"].startswith("[MOCK_LLM stub · nara]")
    assert out["wrapper_request_id"] is None  # nothing real was called
    rows = _rows(kw["transcript_path"])
    assert [r["kind"] for r in rows] == ["human", "nara"]
    assert rows[0]["message"] == "what is running?"
    assert rows[1]["message"] == out["reply"]
    assert rows[1]["context_digest"] == out["context_digest"]
    assert "wrapper_request_id" not in rows[1]


def test_turn_stub_deterministic(tmp_path):
    a = lab_channel.turn(role="pi", message="same q",
                         **_turn_paths(tmp_path))["reply"]
    # Second turn sees a longer tail -> digest tail count changes by design;
    # compare against a fresh, identical context instead.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    b = lab_channel.turn(role="pi", message="same q",
                         **_turn_paths(fresh))["reply"]
    assert a == b


def test_turn_context_fail_open_markers(tmp_path):
    kw = _turn_paths(tmp_path, with_context=False)
    out = lab_channel.turn(role="pi", message="anything there?", **kw)
    digest = out["context_digest"]
    assert "ideas.md=unavailable" in digest
    assert "coordinator_cycle=unavailable" in digest
    assert "loop_alert=unavailable" in digest
    assert "tail=0" in digest
    assert "unavailable" in out["reply"]  # the stub echoes the honest digest


def test_turn_context_ok_marks(tmp_path):
    out = lab_channel.turn(role="nara", message="hi", **_turn_paths(tmp_path))
    digest = out["context_digest"]
    for mark in ("ideas.md=ok", "coordinator_cycle=ok", "loop_alert=ok",
                 "tail=0"):
        assert mark in digest


def test_turn_refuses_empty_message_and_bad_role(tmp_path):
    kw = _turn_paths(tmp_path, with_context=False)
    with pytest.raises(ValueError, match="non-empty"):
        lab_channel.turn(role="nara", message="", **kw)
    with pytest.raises(ValueError, match="non-empty"):
        lab_channel.turn(role="nara", message="   ", **kw)
    with pytest.raises(ValueError, match="role"):
        lab_channel.turn(role="qwen", message="hi", **kw)
    assert not kw["transcript_path"].exists()  # raise wrote NOTHING


def test_turn_author_defaults_to_human_and_records_oracle(tmp_path):
    """The steward's turns are attributable: the stored row kind IS the author
    (2026-08-16). Default stays "human" so every existing caller is unchanged."""
    kw = _turn_paths(tmp_path)
    lab_channel.turn(role="nara", message="owner asking", **kw)
    lab_channel.turn(role="pi", message="steward asking", author="oracle", **kw)
    assert [r["kind"] for r in _rows(kw["transcript_path"])] == [
        "human", "nara", "oracle", "pi"]


def test_turn_rejects_unknown_author(tmp_path):
    """An unregistered author is refused, not coerced to human — an
    unattributable row would be worse than no row (rule 4)."""
    kw = _turn_paths(tmp_path, with_context=False)
    with pytest.raises(ValueError, match="author"):
        lab_channel.turn(role="nara", message="hi", author="anon", **kw)
    assert not kw["transcript_path"].exists()


def test_author_header_names_the_steward_and_its_limits():
    """The header the voices read must SAY the oracle is an observer — the
    participant list grants identity, never capability."""
    assert lab_channel._author_header("human") == "HUMAN MESSAGE:"
    oracle = lab_channel._author_header("oracle")
    assert "ORACLE" in oracle
    assert "observer" in oracle and "never edits" in oracle


def test_turn_writes_run_log_row(tmp_path):
    lab_channel.turn(role="nara", message="log me",
                     **_turn_paths(tmp_path, with_context=False))
    rows = _rows(runtime_mod.RUN_LOG_PATH)  # conftest redirects to tmp
    row = rows[-1]
    assert row["agent"] == "lab_channel"
    assert row["task_id"] == "lab_channel:turn:nara"
    assert row["status"] == "passed"
    assert {"observable_actual", "observable_expected",
            "duration_ms"} <= set(row)


# ── delegate ─────────────────────────────────────────────────────────────────

def test_delegate_research_auto_creates_standing_cluster(tmp_path):
    ledger = tmp_path / "idea_ledger.jsonl"
    transcript = tmp_path / "lab_channel.jsonl"
    out = lab_channel.delegate(kind="research", text="explore X",
                               idea_ledger_path=ledger,
                               transcript_path=transcript)
    rows = _rows(ledger)
    assert [r["event_type"] for r in rows] == ["cluster_created",
                                               "agenda_item_added"]
    for row in rows:  # contract: events validate against the ledger schema
        jsonschema.validate(row, IDEA_SCHEMA)
    assert rows[0]["cluster_id"] == "cl-human-delegations"
    assert rows[0]["origin"] == "manual"
    assert rows[1]["topic"] == "explore X" and rows[1]["source"] == "human"
    state = idea_ledger.load_state(ledger)
    agenda = state["cl-human-delegations"]["agenda"]
    assert [(a["topic"], a["source"], a["status"]) for a in agenda] == [
        ("explore X", "human", "pending")]
    assert _rows(transcript)[-1]["message"] == "DELEGATED[research]: explore X"
    assert out["rows"] == rows


def test_delegate_research_standing_cluster_created_once(tmp_path):
    ledger = tmp_path / "idea_ledger.jsonl"
    for topic in ("first", "second"):
        lab_channel.delegate(kind="research", text=topic,
                             idea_ledger_path=ledger,
                             transcript_path=tmp_path / "t.jsonl")
    events = _rows(ledger)
    assert [e["event_type"] for e in events] == [
        "cluster_created", "agenda_item_added", "agenda_item_added"]
    assert len(idea_ledger.load_state(ledger)["cl-human-delegations"]["agenda"]) == 2


def test_delegate_research_named_cluster(tmp_path):
    ledger = tmp_path / "idea_ledger.jsonl"
    idea_ledger.append_event(ledger, {
        "event_type": "cluster_created", "ts": "2026-08-10T00:00:00Z",
        "cluster_id": "cl-x", "origin": "iteration", "member_id": "iter-9"})
    lab_channel.delegate(kind="research", text="push on cl-x",
                         cluster_id="cl-x", idea_ledger_path=ledger,
                         transcript_path=tmp_path / "t.jsonl")
    events = _rows(ledger)
    assert events[-1]["cluster_id"] == "cl-x"
    assert events[-1]["event_type"] == "agenda_item_added"
    assert len(events) == 2  # no auto-create when the named cluster exists


def test_delegate_research_unknown_named_cluster_raises(tmp_path):
    ledger = tmp_path / "idea_ledger.jsonl"
    with pytest.raises(ValueError, match="not found"):
        lab_channel.delegate(kind="research", text="orphan",
                             cluster_id="cl-nope", idea_ledger_path=ledger,
                             transcript_path=tmp_path / "t.jsonl")
    assert not ledger.exists()  # nothing written on refusal


def test_delegate_improvement_row_is_consumable(tmp_path):
    queue = tmp_path / "authorize_fix_queue.jsonl"
    transcript = tmp_path / "lab_channel.jsonl"
    lab_channel.delegate(kind="improvement", text="fix the flaky battery",
                         objective="make battery report deterministic",
                         fix_queue_path=queue, transcript_path=transcript)
    row = _rows(queue)[0]
    assert row["status"] == "enqueued" and row["outcome"] == "authorize_fix"
    assert row["authorized_by"] == "human:lab_channel"
    assert row["note"] == "fix the flaky battery"
    assert {"task_statement", "done_condition", "skill_subset",
            "authority_cap", "self_gating_rules", "reporting_format",
            "escalation_path", "budget", "state_basis"} <= set(row["contract"])
    packets = consume_authorize_fix_queue(queue)  # the seam's own consumer
    assert len(packets) == 1
    assert packets[0]["objective"] == "make battery report deterministic"
    assert packets[0]["task_id"].startswith("PKT-fix-lab-")
    assert (_rows(transcript)[-1]["message"]
            == "DELEGATED[improvement]: fix the flaky battery")


def test_delegate_improvement_objective_defaults_to_text(tmp_path):
    queue = tmp_path / "q.jsonl"
    lab_channel.delegate(kind="improvement", text="tighten the tail parser",
                         fix_queue_path=queue,
                         transcript_path=tmp_path / "t.jsonl")
    assert consume_authorize_fix_queue(queue)[0]["objective"] == \
        "tighten the tail parser"


def test_delegate_refuses_empty_text_and_bad_kind(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        lab_channel.delegate(kind="research", text=" ",
                             idea_ledger_path=tmp_path / "i.jsonl",
                             transcript_path=tmp_path / "t.jsonl")
    with pytest.raises(ValueError, match="kind"):
        lab_channel.delegate(kind="dispose", text="x",
                             transcript_path=tmp_path / "t.jsonl")


def test_delegate_writes_run_log_row(tmp_path):
    lab_channel.delegate(kind="research", text="log me",
                         idea_ledger_path=tmp_path / "i.jsonl",
                         transcript_path=tmp_path / "t.jsonl")
    row = _rows(runtime_mod.RUN_LOG_PATH)[-1]
    assert row["agent"] == "lab_channel"
    assert row["task_id"] == "lab_channel:delegate:research"


# ── fence ────────────────────────────────────────────────────────────────────

def test_cli_surface_is_exactly_three_subcommands():
    sub = next(a for a in lab_channel.build_parser()._actions
               if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == {"timeline", "turn", "delegate"}


def test_no_disposition_imports_in_module_source():
    src = inspect.getsource(lab_channel)
    for forbidden in ("gate_cli", "finding_session", "attest"):
        assert forbidden not in src, f"fence breach: {forbidden!r} in module"


def test_cli_main_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(lab_channel, "DEFAULT_TRANSCRIPT",
                        tmp_path / "lab_channel.jsonl")
    monkeypatch.setattr(lab_channel, "DEFAULT_CYCLES", tmp_path / "c.jsonl")
    monkeypatch.setattr(lab_channel, "DEFAULT_IDEA_LEDGER",
                        tmp_path / "i.jsonl")
    monkeypatch.setattr(lab_channel, "DEFAULT_SURFACED", tmp_path / "s.jsonl")
    monkeypatch.setattr(lab_channel, "DEFAULT_LOOP_ALERT", tmp_path / "a.json")
    monkeypatch.setattr(lab_channel, "DEFAULT_IDEAS_MD", tmp_path / "ideas.md")
    monkeypatch.setattr(lab_channel, "DEFAULT_FIX_QUEUE", tmp_path / "q.jsonl")
    assert lab_channel.main(["turn", "--role", "pi", "--message", "hi"]) == 0
    assert lab_channel.main(["delegate", "--kind", "research",
                             "--text", "try X"]) == 0
    assert lab_channel.main(["timeline"]) == 0
    assert lab_channel.main(["turn", "--role", "pi", "--message", ""]) == 1
    assert lab_channel.main(["turn", "--role", "nara", "--message", "steward",
                             "--as", "oracle"]) == 0
    rows = _rows(tmp_path / "lab_channel.jsonl")
    assert [r["kind"] for r in rows] == ["human", "pi", "human",
                                         "oracle", "nara"]
    assert rows[2]["message"] == "DELEGATED[research]: try X"
