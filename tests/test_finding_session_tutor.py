"""Tests for the NO-VERDICT tutor seam + per-turn chat CLI (D-054).

Covers the single-voice teaching path (start_tutor_session/tutor_turn), its
verdict fence (it writes NOTHING to loop_feedback/status-audit/followups and
end_session rejects it), and the `chat` CLI envelope for both the tutor and
the two-voice modes. The verdict-bearing single/two-voice paths are tested
elsewhere; this file only exercises the additive tutor + CLI surface.

Offline: wrapper.call_sync is stubbed via monkeypatch — never hits a real
model. active_run.write/clear/set_run_id are no-ops so nothing under
run_state/ is touched. All paths are tmp. Runs green under MOCK_LLM.
"""
from __future__ import annotations

import json

import pytest

from orchestrator import finding_session as fs


_CLAIM = (
    "In a sealed-bid Vickrey auction, LLM agents bid truthfully at their "
    "private valuation in 100% of trials."
)
_REDTEAM_CRITIQUE = (
    "The truthfulness may be a memorized textbook result rather than "
    "reasoned dominant-strategy play; valuations were drawn from a narrow grid."
)


def _fake_call_sync(reply_text: str, request_id: str = "req-tutor"):
    """A drop-in for wrapper.call_sync: returns a record whose completion is
    `reply_text` and captures the messages/kwargs it was handed."""
    captured: dict = {}

    def _stub(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return {"request_id": request_id, "completion": reply_text}

    _stub.captured = captured
    return _stub


def _stance_call_sync(by_backend: dict[str, str], request_id: str = "req-tv"):
    captured: dict = {}

    def _stub(messages, **kwargs):
        captured["messages"] = messages
        captured.setdefault("backends", []).append(kwargs.get("backend"))
        return {"request_id": request_id,
                "completion": by_backend.get(kwargs.get("backend"), "default")}

    _stub.captured = captured
    return _stub


@pytest.fixture(autouse=True)
def _no_active_run(monkeypatch):
    """Hermetic: the active-run mirror write/clear and set_run_id are no-ops —
    nothing under the real run_state/ is touched."""
    monkeypatch.setattr(fs.active_run, "write_active_run", lambda *a, **k: None)
    monkeypatch.setattr(fs.active_run, "clear_active_run", lambda: None)
    monkeypatch.setattr(fs, "set_run_id", lambda *a, **k: None)


@pytest.fixture
def env(tmp_path):
    """A self-contained finding + iteration_record + journal on tmp paths."""
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
        "journal_entry_path": str(journal),
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


def _open_tutor(env):
    return fs.start_tutor_session(
        env["finding_id"],
        surfaced_path=env["surfaced"],
        loop_memory_path=env["loop_memory"],
        sessions_root=env["sessions_root"],
    )


def _rows(env, sid):
    path = env["sessions_root"] / env["finding_id"] / f"{sid}.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _patch_cli_defaults(env, monkeypatch):
    """Bind the tmp env into the openers/turns the chat CLI calls with no path
    args. Their `sessions_root`/`surfaced_path` defaults are bound at def time,
    so monkeypatching the module attrs would not reach them — wrap the
    functions to inject the tmp paths instead (the CLI just forwards finding_id/
    session_id/message/addressee)."""
    import functools

    _real_start_tutor = fs.start_tutor_session
    _real_tutor_turn = fs.tutor_turn
    _real_start_2v = fs.start_two_voice_session
    _real_2v_turn = fs.two_voice_turn

    monkeypatch.setattr(fs, "start_tutor_session", functools.partial(
        _real_start_tutor, surfaced_path=env["surfaced"],
        loop_memory_path=env["loop_memory"], sessions_root=env["sessions_root"]))
    monkeypatch.setattr(fs, "tutor_turn", functools.partial(
        _real_tutor_turn, sessions_root=env["sessions_root"]))
    monkeypatch.setattr(fs, "start_two_voice_session", functools.partial(
        _real_start_2v, surfaced_path=env["surfaced"],
        loop_memory_path=env["loop_memory"], sessions_root=env["sessions_root"]))
    monkeypatch.setattr(fs, "two_voice_turn", functools.partial(
        _real_2v_turn, sessions_root=env["sessions_root"]))


# --------------------------------------------------------------------------- #
# (1) start_tutor_session — one no-verdict seed                                #
# --------------------------------------------------------------------------- #


def test_start_tutor_writes_one_mode_tagged_seed(env):
    opened = _open_tutor(env)
    assert opened["session_id"].startswith("fs-")
    assert opened["finding"]["finding_id"] == env["finding_id"]

    rows = _rows(env, opened["session_id"])
    assert len(rows) == 1
    seed = rows[0]
    assert seed["type"] == "system_seed"
    assert seed["mode"] == "tutor"
    assert seed["backend"] == "vllm-qwen"
    # Same context blocks as _build_seed: claim + evidence + refutation.
    assert _CLAIM in seed["content"]
    assert "truthful_bid_fraction" in seed["content"]
    assert "50" in seed["content"]
    assert _REDTEAM_CRITIQUE in seed["content"]
    # Neutral teaching prose — no recommendation/disposition language.
    low = seed["content"].lower()
    assert "you should accept" not in low
    assert "i recommend" not in low
    assert "verdict" in low  # the seed explicitly forbids rendering one


def test_start_tutor_unknown_finding_raises(env):
    with pytest.raises(KeyError):
        fs.start_tutor_session(
            "find-does-not-exist",
            surfaced_path=env["surfaced"],
            loop_memory_path=env["loop_memory"],
            sessions_root=env["sessions_root"],
        )


# --------------------------------------------------------------------------- #
# (2)(3) tutor_turn — replay, backend pin, second-turn stack                   #
# --------------------------------------------------------------------------- #


def test_tutor_turn_appends_user_and_assistant_qwen_backend(env, monkeypatch):
    opened = _open_tutor(env)
    sid = opened["session_id"]
    stub = _fake_call_sync("The metric is truthful_bid_fraction = 1.0 over 50 trials.",
                           "req-1")
    monkeypatch.setattr(fs, "call_sync", stub)

    res = fs.tutor_turn(env["finding_id"], sid,
                        "What does the evidence actually show?",
                        sessions_root=env["sessions_root"])
    assert res["reply"].startswith("The metric")
    assert res["request_id"] == "req-1"
    assert res["turn_index"] == 1
    assert res["capped"] is False

    rows = _rows(env, sid)
    assert [r["type"] for r in rows] == ["system_seed", "user", "assistant"]

    # Replay = system + user; backend pinned to vllm-qwen (teach != author).
    msgs = stub.captured["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"
    assert stub.captured["kwargs"]["backend"] == "vllm-qwen"
    assert stub.captured["kwargs"]["max_tokens"] == 4096
    # Assistant row records the pinned backend too.
    assert rows[-1]["backend"] == "vllm-qwen"


def test_tutor_second_turn_replays_full_single_voice_stack(env, monkeypatch):
    opened = _open_tutor(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _fake_call_sync("reply one", "r1"))
    fs.tutor_turn(env["finding_id"], sid, "first",
                  sessions_root=env["sessions_root"])
    stub2 = _fake_call_sync("reply two", "r2")
    monkeypatch.setattr(fs, "call_sync", stub2)
    res = fs.tutor_turn(env["finding_id"], sid, "second",
                        sessions_root=env["sessions_root"])
    assert res["turn_index"] == 2
    msgs = stub2.captured["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == "reply one"


# --------------------------------------------------------------------------- #
# (4) MAX_TURNS cap — no model call past cap; NO verdict language              #
# --------------------------------------------------------------------------- #


def test_tutor_turn_cap_no_model_no_verdict(env, monkeypatch):
    opened = _open_tutor(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _fake_call_sync("ok", "r"))
    for i in range(fs.MAX_TURNS):
        fs.tutor_turn(env["finding_id"], sid, f"q{i}",
                      sessions_root=env["sessions_root"])

    sentinel = _fake_call_sync("SHOULD NOT BE CALLED", "nope")
    monkeypatch.setattr(fs, "call_sync", sentinel)
    res = fs.tutor_turn(env["finding_id"], sid, "one too many",
                        sessions_root=env["sessions_root"])
    assert res["request_id"] is None
    assert res["capped"] is True
    assert "cap reached" in res["reply"]
    assert "messages" not in sentinel.captured  # model NOT invoked
    # The cap reply carries NO verdict/disposition language.
    low = res["reply"].lower()
    for word in ("verdict", "validate", "reject", "disposition"):
        assert word not in low


# --------------------------------------------------------------------------- #
# (5) FENCE: tutor path writes NOTHING to loop_feedback/status/followups       #
# --------------------------------------------------------------------------- #


def test_tutor_path_writes_no_verdict_artifacts(env, monkeypatch):
    opened = _open_tutor(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _fake_call_sync("teaching reply", "r"))
    fs.tutor_turn(env["finding_id"], sid, "explain it",
                  sessions_root=env["sessions_root"])
    fs.tutor_turn(env["finding_id"], sid, "and the limits?",
                  sessions_root=env["sessions_root"])

    # No verdict-bearing artifact exists; effective status stays None.
    assert not env["feedback"].exists()
    assert not env["status_audit"].exists()
    assert not env["followups"].exists()
    assert fs.effective_status(
        env["finding_id"], status_audit_path=env["status_audit"]) is None
    # The transcript holds ONLY system_seed/user/assistant rows.
    assert {r["type"] for r in _rows(env, sid)} == {
        "system_seed", "user", "assistant"}


# --------------------------------------------------------------------------- #
# (6) end_session guard rejects a tutor session — writes nothing               #
# --------------------------------------------------------------------------- #


def test_end_session_rejects_tutor_transcript(env):
    opened = _open_tutor(env)
    sid = opened["session_id"]
    with pytest.raises(ValueError, match="verdict-fenced"):
        fs.end_session(
            env["finding_id"], sid, outcome="validated", note="should not work",
            sessions_root=env["sessions_root"], feedback_path=env["feedback"],
            status_audit_path=env["status_audit"], followups_path=env["followups"],
        )
    # Nothing written by the rejected close.
    assert not env["feedback"].exists()
    assert not env["status_audit"].exists()
    assert not env["followups"].exists()


# --------------------------------------------------------------------------- #
# (7)(8) chat CLI — tutor start + turn envelopes                               #
# --------------------------------------------------------------------------- #


def test_cli_chat_start_tutor(env, monkeypatch, capsys):
    _patch_cli_defaults(env, monkeypatch)
    rc = fs.main(["chat", "start", "--mode", "tutor",
                  "--finding-id", env["finding_id"]])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["mode"] == "tutor"
    assert out["action"] == "start"
    assert out["finding_id"] == env["finding_id"]
    assert out["session_id"].startswith("fs-")
    assert out["stances"] is None


def test_cli_chat_turn_tutor_one_reply(env, monkeypatch, capsys):
    _patch_cli_defaults(env, monkeypatch)
    opened = _open_tutor(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync",
                        _fake_call_sync("a clear explanation", "req-c"))
    rc = fs.main(["chat", "turn", "--mode", "tutor",
                  "--finding-id", env["finding_id"], "--session-id", sid,
                  "--message", "explain the claim"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["mode"] == "tutor"
    assert out["turn_index"] == 1
    assert out["capped"] is False
    assert out["warning"] is None
    assert len(out["replies"]) == 1
    assert out["replies"][0]["stance"] is None
    assert out["replies"][0]["reply"] == "a clear explanation"
    assert out["replies"][0]["request_id"] == "req-c"


# --------------------------------------------------------------------------- #
# (9) chat CLI — two_voice start + turn pass-through smoke                     #
# --------------------------------------------------------------------------- #


def test_cli_chat_two_voice_start_and_turn(env, monkeypatch, capsys):
    _patch_cli_defaults(env, monkeypatch)
    rc = fs.main(["chat", "start", "--mode", "two_voice",
                  "--finding-id", env["finding_id"]])
    assert rc == 0
    start_out = json.loads(capsys.readouterr().out)
    assert start_out["mode"] == "two_voice"
    assert start_out["stances"] == ["defender", "attacker"]
    sid = start_out["session_id"]

    monkeypatch.setattr(fs, "call_sync", _stance_call_sync(
        {"vllm-gemma": "DEFENDER reply", "vllm-qwen": "ATTACKER reply"}))
    rc = fs.main(["chat", "turn", "--mode", "two_voice",
                  "--finding-id", env["finding_id"], "--session-id", sid,
                  "--message", "both weigh in", "--addressee", "both"])
    assert rc == 0
    turn_out = json.loads(capsys.readouterr().out)
    assert turn_out["mode"] == "two_voice"
    assert turn_out["addressee"] == "both"
    assert turn_out["turn_index"] == 1
    assert turn_out["capped"] is False
    stances = [r["stance"] for r in turn_out["replies"]]
    assert stances == ["defender", "attacker"]


# --------------------------------------------------------------------------- #
# (10) chat CLI — tutor mode rejects --addressee                               #
# --------------------------------------------------------------------------- #


def test_cli_chat_tutor_rejects_addressee(env, monkeypatch, capsys):
    _patch_cli_defaults(env, monkeypatch)
    rc = fs.main(["chat", "turn", "--mode", "tutor",
                  "--finding-id", env["finding_id"], "--session-id", "fs-x",
                  "--message", "hi", "--addressee", "defender"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout stays empty on error
    err = json.loads(captured.err)
    assert err["ok"] is False
    assert "addressee" in err["error"]


def test_cli_chat_unknown_finding_errors_to_stderr(env, monkeypatch, capsys):
    _patch_cli_defaults(env, monkeypatch)
    rc = fs.main(["chat", "start", "--mode", "tutor",
                  "--finding-id", "find-nope"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    err = json.loads(captured.err)
    assert err["ok"] is False
    assert "KeyError" in err["error"]
