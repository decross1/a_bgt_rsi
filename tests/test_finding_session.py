"""Tests for the rubberbanding-session engine (orchestrator/finding_session).

Offline: wrapper.call_sync is stubbed via monkeypatch — never hits a real
model. All paths are tmp; no shared state (memory/, run_state/) is touched.
Runs green under MOCK_LLM (call_sync is patched anyway).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator import finding_session as fs


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


_CLAIM = (
    "In a sealed-bid Vickrey auction, LLM agents bid truthfully at their "
    "private valuation in 100% of trials."
)
_REDTEAM_CRITIQUE = (
    "The truthfulness may be a memorized textbook result rather than "
    "reasoned dominant-strategy play; valuations were drawn from a narrow grid."
)


def _fake_call_sync(reply_text: str, request_id: str = "req-fs"):
    """A drop-in for wrapper.call_sync: ignores model I/O, returns a record
    whose completion is `reply_text`. Captures the messages it was handed so
    a test can assert on the replayed stack."""
    captured: dict = {}

    def _stub(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return {"request_id": request_id, "completion": reply_text}

    _stub.captured = captured
    return _stub


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Build a self-contained finding + iteration_record + journal on tmp
    paths and return the path bundle. call_sync is NOT patched here (each
    test installs its own stub) but feedback/audit/followup paths are tmp."""
    surfaced = tmp_path / "surfaced_findings.jsonl"
    loop_memory = tmp_path / "loop_memory.jsonl"
    journal = tmp_path / "journal" / "iter-2026-06-06-001.md"
    sessions_root = tmp_path / "finding_sessions"
    feedback = tmp_path / "loop_feedback.jsonl"
    status_audit = tmp_path / "surfaced_findings.status.jsonl"
    followups = tmp_path / "finding_followups.jsonl"

    iteration_id = "iter-2026-06-06-001"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("# Iteration\n\nThe Vickrey rediscovery probe ran 50 trials.\n")

    iteration_record = {
        "iteration_id": iteration_id,
        "started_at": "2026-06-06T00:00:00Z",
        "ended_at": "2026-06-06T00:05:00Z",
        "seed": {"topic": "vickrey", "source": "human_cli"},
        "nara_summary": "ran the vickrey probe",
        "tool_calls_made": [],
        "journal_entry_path": str(journal),  # absolute -> read as-is
        "model_version": "vllm/vllm-openai:v0.21.0/gemma-4-26b-a4b",
        "wrapper_call_ids": ["w-1"],
        "hypothesis": {"text": _CLAIM, "candidates_considered": 1},
        "novelty": {"class": "rediscovery", "rationale": "matches Vickrey 1961"},
        "redteam": {"verdict": "proceed", "critique": _REDTEAM_CRITIQUE,
                    "confidence": 0.7},
        "experiment_outcome": {
            "experiment_id": "exp003_vickrey_rediscovery",
            "metric": "truthful_bid_fraction", "value": 1.0, "trials": 50,
            "summary": "100% truthful across 50 trials.",
        },
    }
    loop_memory.write_text(json.dumps(iteration_record) + "\n")

    finding = {
        "finding_id": "find-vickrey-001",
        "iteration_id": iteration_id,
        "claim": _CLAIM,
    }
    surfaced.write_text(json.dumps(finding) + "\n")

    return {
        "surfaced": surfaced, "loop_memory": loop_memory, "journal": journal,
        "sessions_root": sessions_root, "feedback": feedback,
        "status_audit": status_audit, "followups": followups,
        "iteration_id": iteration_id, "finding_id": "find-vickrey-001",
    }


def _open(env):
    return fs.start_session(
        env["finding_id"],
        backend="vllm-qwen",
        surfaced_path=env["surfaced"],
        loop_memory_path=env["loop_memory"],
        sessions_root=env["sessions_root"],
    )


# --------------------------------------------------------------------------- #
# start_session                                                               #
# --------------------------------------------------------------------------- #


def test_start_session_seed_has_claim_and_refutation(env):
    opened = _open(env)
    assert opened["session_id"].startswith("fs-")
    assert opened["finding"]["finding_id"] == env["finding_id"]

    # Read the system_seed row back from the transcript.
    path = env["sessions_root"] / env["finding_id"] / f"{opened['session_id']}.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    seed = rows[0]
    assert seed["type"] == "system_seed"
    # The seed grounds the defender in the claim AND in a refutation summary.
    assert _CLAIM in seed["content"]
    assert _REDTEAM_CRITIQUE in seed["content"]
    assert seed["refutation_count"] >= 1
    # Cross-tier evidence (metric + trial-count) is wired in.
    assert "truthful_bid_fraction" in seed["content"]
    assert "50" in seed["content"]


def test_start_session_unknown_finding_raises(env):
    with pytest.raises(KeyError):
        fs.start_session(
            "find-does-not-exist",
            surfaced_path=env["surfaced"],
            loop_memory_path=env["loop_memory"],
            sessions_root=env["sessions_root"],
        )


# --------------------------------------------------------------------------- #
# session_turn                                                                #
# --------------------------------------------------------------------------- #


def test_session_turn_appends_user_and_assistant(env, monkeypatch):
    opened = _open(env)
    sid = opened["session_id"]
    stub = _fake_call_sync("It survived because the dominant strategy is provable.", "req-1")
    monkeypatch.setattr(fs, "call_sync", stub)

    res = fs.session_turn(
        env["finding_id"], sid,
        "Isn't 100% suspicious — could it be memorized?",
        sessions_root=env["sessions_root"],
    )
    assert res["reply"].startswith("It survived")
    assert res["request_id"] == "req-1"
    assert res["turn_index"] == 1

    path = env["sessions_root"] / env["finding_id"] / f"{sid}.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    types = [r["type"] for r in rows]
    assert types == ["system_seed", "user", "assistant"]

    # The replayed stack handed to call_sync was system + user (seed grounded).
    msgs = stub.captured["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"
    assert "memorized" in msgs[-1]["content"]


def test_second_turn_replays_full_transcript(env, monkeypatch):
    opened = _open(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _fake_call_sync("reply one", "r1"))
    fs.session_turn(env["finding_id"], sid, "first question",
                    sessions_root=env["sessions_root"])
    stub2 = _fake_call_sync("reply two", "r2")
    monkeypatch.setattr(fs, "call_sync", stub2)
    res = fs.session_turn(env["finding_id"], sid, "second question",
                          sessions_root=env["sessions_root"])
    assert res["turn_index"] == 2
    # Replay carries system + (user, assistant) + new user = 4 messages.
    msgs = stub2.captured["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == "reply one"


def test_session_turn_cap(env, monkeypatch):
    opened = _open(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _fake_call_sync("ok", "r"))
    for i in range(fs.MAX_TURNS):
        fs.session_turn(env["finding_id"], sid, f"q{i}",
                        sessions_root=env["sessions_root"])
    # The (MAX_TURNS+1)th turn is capped: explicit message, no model call.
    sentinel = _fake_call_sync("SHOULD NOT BE CALLED", "nope")
    monkeypatch.setattr(fs, "call_sync", sentinel)
    res = fs.session_turn(env["finding_id"], sid, "one too many",
                          sessions_root=env["sessions_root"])
    assert res["request_id"] is None
    assert "cap reached" in res["reply"]
    assert "messages" not in sentinel.captured  # model not invoked


# --------------------------------------------------------------------------- #
# end_session — three feedback paths, no in-place mutation                     #
# --------------------------------------------------------------------------- #


def test_end_session_validated_writes_feedback_and_audit_no_mutation(env, monkeypatch):
    opened = _open(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _fake_call_sync("defended", "r"))
    fs.session_turn(env["finding_id"], sid, "push", sessions_root=env["sessions_root"])

    surfaced_before = env["surfaced"].read_bytes()

    res = fs.end_session(
        env["finding_id"], sid,
        outcome="validated", note="held up under three rounds of pressure",
        sessions_root=env["sessions_root"],
        feedback_path=env["feedback"],
        status_audit_path=env["status_audit"],
        followups_path=env["followups"],
    )

    # (a1) loop_feedback row written with verdict == "valid".
    fb_rows = [json.loads(l) for l in env["feedback"].read_text().splitlines() if l.strip()]
    assert len(fb_rows) == 1
    assert fb_rows[0]["verdict"] == "valid"
    assert fb_rows[0]["iteration_id"] == env["iteration_id"]
    assert res["loop_feedback_row"]["verdict"] == "valid"

    # (a2) status-audit row written (append-only audit; effective = last).
    audit_rows = [json.loads(l) for l in env["status_audit"].read_text().splitlines() if l.strip()]
    assert len(audit_rows) == 1
    assert audit_rows[0]["finding_id"] == env["finding_id"]
    assert audit_rows[0]["status"] == "valid"
    assert audit_rows[0]["session_id"] == sid
    assert fs.effective_status(env["finding_id"], status_audit_path=env["status_audit"]) == "valid"

    # surfaced_findings.jsonl is byte-for-byte UNCHANGED (no in-place mutation).
    assert env["surfaced"].read_bytes() == surfaced_before


def test_end_session_rejected_writes_invalid_verdict(env):
    opened = _open(env)
    sid = opened["session_id"]
    res = fs.end_session(
        env["finding_id"], sid, outcome="rejected", note="memorization confirmed",
        sessions_root=env["sessions_root"], feedback_path=env["feedback"],
        status_audit_path=env["status_audit"], followups_path=env["followups"],
    )
    assert res["loop_feedback_row"]["verdict"] == "invalid"
    assert fs.effective_status(env["finding_id"], status_audit_path=env["status_audit"]) == "invalid"


def test_end_session_spawn_topic_queues_not_runs(env):
    opened = _open(env)
    sid = opened["session_id"]
    res = fs.end_session(
        env["finding_id"], sid, outcome="spawn_topic",
        note="probe whether truthfulness survives a continuous valuation grid",
        new_topic="vickrey truthfulness on continuous valuations",
        sessions_root=env["sessions_root"], feedback_path=env["feedback"],
        status_audit_path=env["status_audit"], followups_path=env["followups"],
    )
    # A queue row exists; NO loop_feedback row (the loop is not run here).
    fu_rows = [json.loads(l) for l in env["followups"].read_text().splitlines() if l.strip()]
    assert len(fu_rows) == 1
    assert fu_rows[0]["new_topic"] == "vickrey truthfulness on continuous valuations"
    assert res["loop_feedback_row"] is None
    assert not env["feedback"].exists()


def test_end_session_refine_marks_in_review_preserves_original(env):
    opened = _open(env)
    sid = opened["session_id"]
    surfaced_before = env["surfaced"].read_bytes()
    res = fs.end_session(
        env["finding_id"], sid, outcome="refine",
        note="narrow the claim", refined_claim="...truthfully in >=95% of trials.",
        sessions_root=env["sessions_root"], feedback_path=env["feedback"],
        status_audit_path=env["status_audit"], followups_path=env["followups"],
    )
    assert res["status_audit_row"]["status"] == "in_review"
    assert "refined_claim" in res["status_audit_row"]["reason"]
    # Original surfaced row preserved untouched.
    assert env["surfaced"].read_bytes() == surfaced_before


def test_end_session_bad_outcome_raises(env):
    opened = _open(env)
    with pytest.raises(ValueError):
        fs.end_session(env["finding_id"], opened["session_id"],
                       outcome="bogus", note="",
                       sessions_root=env["sessions_root"],
                       feedback_path=env["feedback"],
                       status_audit_path=env["status_audit"],
                       followups_path=env["followups"])
