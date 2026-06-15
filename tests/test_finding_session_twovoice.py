"""Tests for the TWO-VOICE interrogation seam (orchestrator/finding_session).

These cover the additive two-stance path (Gemma defends / Qwen attacks), the
stance-tagged transcript, the both-stances-as-one-turn budget, fail-open on an
attacker call failure, the concurrency-guard warn, and the SEAM 3 directive
sign-off. The single-voice path lives in tests/test_finding_session.py and is
untouched here.

Offline: wrapper.call_sync is stubbed via monkeypatch — never hits a real
model. active_run.write/clear are stubbed to no-ops so nothing under
run_state/ is touched; the concurrency guard is driven through its
`run_state_dir` arg pointed at a tmp dir. Runs green under MOCK_LLM.
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


def _stance_call_sync(by_backend: dict[str, str], request_id: str = "req-tv"):
    """A call_sync stub that returns a per-BACKEND reply so a test can tell the
    defender (vllm-gemma) and attacker (vllm-qwen) responses apart. Captures
    the last messages/backend it was handed under .captured."""
    captured: dict = {}

    def _stub(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        captured.setdefault("backends", []).append(kwargs.get("backend"))
        reply = by_backend.get(kwargs.get("backend"), "default reply")
        return {"request_id": request_id, "completion": reply}

    _stub.captured = captured
    return _stub


@pytest.fixture(autouse=True)
def _no_active_run(monkeypatch):
    """Keep every two-voice test hermetic: the active-run mirror write/clear
    are no-ops (the run_state/ side is exercised separately via the guard's
    run_state_dir arg). Mirrors nothing under the real run_state/."""
    monkeypatch.setattr(fs.active_run, "write_active_run",
                        lambda *a, **k: None)
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


def _open_two_voice(env):
    return fs.start_two_voice_session(
        env["finding_id"],
        surfaced_path=env["surfaced"],
        loop_memory_path=env["loop_memory"],
        sessions_root=env["sessions_root"],
    )


def _rows(env, sid):
    path = env["sessions_root"] / env["finding_id"] / f"{sid}.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


# --------------------------------------------------------------------------- #
# start_two_voice_session — two stance seeds                                   #
# --------------------------------------------------------------------------- #


def test_start_two_voice_writes_both_stance_seeds(env):
    opened = _open_two_voice(env)
    assert opened["session_id"].startswith("fs-")
    assert opened["stances"] == ["defender", "attacker"]
    rows = _rows(env, opened["session_id"])
    assert [r["type"] for r in rows] == ["system_seed", "system_seed"]
    seeds = {r["stance"]: r for r in rows}
    assert set(seeds) == {"defender", "attacker"}
    # Each stance is seeded to its OWN backend (D-044 independence).
    assert seeds["defender"]["backend"] == "vllm-gemma"
    assert seeds["attacker"]["backend"] == "vllm-qwen"
    # Defender seed = honest-defender framing; attacker seed = honest skeptic.
    assert "defend" in seeds["defender"]["content"].lower()
    assert "attack" in seeds["attacker"]["content"].lower()
    # Both seeds carry the claim + survived-attack context.
    assert _CLAIM in seeds["defender"]["content"]
    assert _CLAIM in seeds["attacker"]["content"]
    assert _REDTEAM_CRITIQUE in seeds["attacker"]["content"]


# --------------------------------------------------------------------------- #
# two_voice_turn — addressing one stance / both; stance recorded               #
# --------------------------------------------------------------------------- #


def test_turn_addressed_to_attacker_only(env, monkeypatch):
    opened = _open_two_voice(env)
    sid = opened["session_id"]
    stub = _stance_call_sync({"vllm-gemma": "I defend it.",
                              "vllm-qwen": "Your grid was too narrow."})
    monkeypatch.setattr(fs, "call_sync", stub)

    res = fs.two_voice_turn(
        env["finding_id"], sid, "Attack the trial design.",
        addressee="attacker", sessions_root=env["sessions_root"],
    )
    assert res["addressee"] == "attacker"
    assert res["turn_index"] == 1
    assert len(res["replies"]) == 1
    assert res["replies"][0]["stance"] == "attacker"
    assert res["replies"][0]["reply"] == "Your grid was too narrow."
    # Only the attacker backend was called.
    assert stub.captured["backends"] == ["vllm-qwen"]

    rows = _rows(env, sid)
    # seed, seed, user, assistant(attacker)
    assert [r["type"] for r in rows] == [
        "system_seed", "system_seed", "user", "assistant"]
    user_row = rows[2]
    assert user_row["addressee"] == "attacker"
    assistant_row = rows[3]
    assert assistant_row["stance"] == "attacker"
    assert assistant_row["backend"] == "vllm-qwen"
    assert assistant_row["turn_index"] == 1


def test_turn_addressed_to_both_records_two_stances(env, monkeypatch):
    opened = _open_two_voice(env)
    sid = opened["session_id"]
    stub = _stance_call_sync({"vllm-gemma": "DEFENDER: it holds.",
                              "vllm-qwen": "ATTACKER: prior art exists."})
    monkeypatch.setattr(fs, "call_sync", stub)

    res = fs.two_voice_turn(
        env["finding_id"], sid, "Both of you: weigh in.",
        addressee="both", sessions_root=env["sessions_root"],
    )
    assert res["addressee"] == "both"
    assert res["turn_index"] == 1
    stances = [r["stance"] for r in res["replies"]]
    assert stances == ["defender", "attacker"]
    # Both backends invoked, exactly once each, this single turn.
    assert sorted(stub.captured["backends"]) == ["vllm-gemma", "vllm-qwen"]

    rows = _rows(env, sid)
    # seed, seed, user, assistant(defender), assistant(attacker)
    assert [r["type"] for r in rows] == [
        "system_seed", "system_seed", "user", "assistant", "assistant"]
    assert rows[2]["addressee"] == "both"
    asst = [r for r in rows if r["type"] == "assistant"]
    assert {r["stance"] for r in asst} == {"defender", "attacker"}
    # Both assistant rows share the SAME turn_index (one turn).
    assert {r["turn_index"] for r in asst} == {1}


def test_attacker_does_not_see_defender_same_turn(env, monkeypatch):
    """In a both-turn, the attacker answers the human in parallel — it must
    NOT be handed the defender's just-produced reply from the same turn."""
    opened = _open_two_voice(env)
    sid = opened["session_id"]

    seen: dict[str, list] = {}

    def _stub(messages, **kwargs):
        seen[kwargs.get("backend")] = list(messages)
        return {"request_id": "r", "completion": f"{kwargs.get('backend')} reply"}

    monkeypatch.setattr(fs, "call_sync", _stub)
    fs.two_voice_turn(env["finding_id"], sid, "weigh in",
                      addressee="both", sessions_root=env["sessions_root"])
    # Attacker stack = its own system seed + the single human turn only.
    attacker_msgs = seen["vllm-qwen"]
    assert [m["role"] for m in attacker_msgs] == ["system", "user"]
    assert "attack" in attacker_msgs[0]["content"].lower()


def test_second_turn_replays_only_that_stance_history(env, monkeypatch):
    """A stance's second turn replays the shared user turns + ITS OWN prior
    assistant rows, not the other stance's."""
    opened = _open_two_voice(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _stance_call_sync(
        {"vllm-gemma": "d1", "vllm-qwen": "a1"}))
    fs.two_voice_turn(env["finding_id"], sid, "q1", addressee="both",
                      sessions_root=env["sessions_root"])

    seen: dict[str, list] = {}

    def _stub(messages, **kwargs):
        seen[kwargs.get("backend")] = list(messages)
        return {"request_id": "r2", "completion": "d2"}

    monkeypatch.setattr(fs, "call_sync", _stub)
    res = fs.two_voice_turn(env["finding_id"], sid, "q2", addressee="defender",
                            sessions_root=env["sessions_root"])
    assert res["turn_index"] == 2
    # Defender replay: system, user(q1), assistant(d1), user(q2). The
    # attacker's "a1" must NOT appear in the defender stack.
    defender_msgs = seen["vllm-gemma"]
    assert [m["role"] for m in defender_msgs] == [
        "system", "user", "assistant", "user"]
    assert defender_msgs[2]["content"] == "d1"
    assert all(m["content"] != "a1" for m in defender_msgs)


# --------------------------------------------------------------------------- #
# MAX_TURNS — both-as-one; explicit cap                                        #
# --------------------------------------------------------------------------- #


def test_both_turn_counts_as_one_against_max_turns(env, monkeypatch):
    opened = _open_two_voice(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _stance_call_sync(
        {"vllm-gemma": "d", "vllm-qwen": "a"}))
    # MAX_TURNS 'both' turns -> 2*MAX_TURNS assistant rows but MAX_TURNS turns.
    for i in range(fs.MAX_TURNS):
        res = fs.two_voice_turn(env["finding_id"], sid, f"q{i}",
                                addressee="both",
                                sessions_root=env["sessions_root"])
    assert res["turn_index"] == fs.MAX_TURNS
    rows = _rows(env, sid)
    assert sum(1 for r in rows if r["type"] == "user") == fs.MAX_TURNS
    assert sum(1 for r in rows if r["type"] == "assistant") == 2 * fs.MAX_TURNS

    # The next turn is capped: explicit message, NO model call.
    sentinel = _stance_call_sync({"vllm-gemma": "NO", "vllm-qwen": "NO"})
    monkeypatch.setattr(fs, "call_sync", sentinel)
    capped = fs.two_voice_turn(env["finding_id"], sid, "one too many",
                               addressee="both",
                               sessions_root=env["sessions_root"])
    assert capped["capped"] is True
    assert "cap reached" in capped["replies"][0]["reply"]
    assert "messages" not in sentinel.captured  # model not invoked


def test_unknown_addressee_rejected(env):
    opened = _open_two_voice(env)
    with pytest.raises(ValueError, match="addressee"):
        fs.two_voice_turn(env["finding_id"], opened["session_id"], "hi",
                          addressee="judge", sessions_root=env["sessions_root"])


def test_two_voice_turn_on_missing_session_raises(env):
    with pytest.raises(KeyError):
        fs.two_voice_turn(env["finding_id"], "fs-nope", "hi",
                          addressee="both", sessions_root=env["sessions_root"])


# --------------------------------------------------------------------------- #
# Fail-open — attacker call failure never fabricates a concession              #
# --------------------------------------------------------------------------- #


def test_failopen_attacker_call_failure_is_noncommittal(env, monkeypatch):
    opened = _open_two_voice(env)
    sid = opened["session_id"]

    def _boom(messages, **kwargs):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(fs, "call_sync", _boom)
    res = fs.two_voice_turn(env["finding_id"], sid, "Attack it.",
                            addressee="attacker",
                            sessions_root=env["sessions_root"])
    reply = res["replies"][0]["reply"]
    assert res["replies"][0]["stance"] == "attacker"
    assert res["replies"][0]["request_id"] is None
    # Non-committal AND explicitly NOT an endorsement/concession (the
    # dangerous failure direction novelty_skeptic.attack guards against).
    assert "attacker unavailable" in reply.lower()
    assert "not a concession" in reply.lower() or "not an endorsement" in reply.lower()
    assert "RuntimeError" in reply
    # The failure is still persisted as the attacker's stance row (audit).
    rows = _rows(env, sid)
    asst = [r for r in rows if r["type"] == "assistant"]
    assert len(asst) == 1
    assert asst[0]["stance"] == "attacker"
    assert asst[0]["request_id"] is None


def test_failopen_in_both_turn_defender_succeeds_attacker_fails(env, monkeypatch):
    """One stance failing does not poison the other; the turn still counts once."""
    opened = _open_two_voice(env)
    sid = opened["session_id"]

    def _stub(messages, **kwargs):
        if kwargs.get("backend") == "vllm-qwen":
            raise RuntimeError("qwen down")
        return {"request_id": "rd", "completion": "defender holds the line"}

    monkeypatch.setattr(fs, "call_sync", _stub)
    res = fs.two_voice_turn(env["finding_id"], sid, "both weigh in",
                            addressee="both", sessions_root=env["sessions_root"])
    assert res["turn_index"] == 1
    by_stance = {r["stance"]: r for r in res["replies"]}
    assert by_stance["defender"]["reply"] == "defender holds the line"
    assert "unavailable" in by_stance["attacker"]["reply"].lower()
    assert "not a concession" in by_stance["attacker"]["reply"].lower() \
        or "not an endorsement" in by_stance["attacker"]["reply"].lower()


# --------------------------------------------------------------------------- #
# Concurrency guard — warn-and-proceed (not a hard block)                      #
# --------------------------------------------------------------------------- #


def test_concurrency_guard_warns_when_run_live_but_proceeds(env, monkeypatch, tmp_path):
    opened = _open_two_voice(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _stance_call_sync(
        {"vllm-gemma": "d", "vllm-qwen": "a"}))

    # A live run mid-flight: an active_run.json present in the pointed dir.
    rs_dir = tmp_path / "run_state"
    rs_dir.mkdir()
    (rs_dir / "active_run.json").write_text(json.dumps(
        {"run_id": "loop_v0_iter1", "kind": "loop_v0", "label": "iter",
         "started_at": "2026-06-15T00:00:00Z"}))

    res = fs.two_voice_turn(env["finding_id"], sid, "weigh in",
                            addressee="both", sessions_root=env["sessions_root"],
                            run_state_dir=rs_dir)
    # Warned, but the turn PROCEEDED (replies produced, turn recorded).
    assert res["warning"] is not None
    assert "live run" in res["warning"]
    assert len(res["replies"]) == 2
    assert res["turn_index"] == 1


def test_concurrency_guard_silent_when_idle(env, monkeypatch, tmp_path):
    opened = _open_two_voice(env)
    sid = opened["session_id"]
    monkeypatch.setattr(fs, "call_sync", _stance_call_sync(
        {"vllm-gemma": "d", "vllm-qwen": "a"}))
    rs_dir = tmp_path / "run_state"
    rs_dir.mkdir()  # no active_run.json -> idle
    res = fs.two_voice_turn(env["finding_id"], sid, "weigh in",
                            addressee="both", sessions_root=env["sessions_root"],
                            run_state_dir=rs_dir)
    assert res["warning"] is None
    assert len(res["replies"]) == 2


# --------------------------------------------------------------------------- #
# SEAM 3 — directive sign-off (present vs absent)                              #
# --------------------------------------------------------------------------- #


def test_directive_signoff_present_on_end_session(env):
    opened = _open_two_voice(env)
    sid = opened["session_id"]
    res = fs.end_session(
        env["finding_id"], sid, outcome="validated",
        note="holds up under two-voice pressure",
        directive="proceed to a continuous-valuation replication",
        sessions_root=env["sessions_root"], feedback_path=env["feedback"],
        status_audit_path=env["status_audit"], followups_path=env["followups"],
    )
    # Recorded on the verdict status-audit row...
    assert res["status_audit_row"]["directive"] == \
        "proceed to a continuous-valuation replication"
    audit = json.loads(env["status_audit"].read_text().splitlines()[0])
    assert audit["directive"] == "proceed to a continuous-valuation replication"
    # ...and on the session-local feedback event row.
    rows = _rows(env, sid)
    fb = [r for r in rows if r["type"] == "feedback"][0]
    assert fb["directive"] == "proceed to a continuous-valuation replication"
    # The frozen loop_feedback row is UNCHANGED (no directive leaks into it).
    fb_row = json.loads(env["feedback"].read_text().splitlines()[0])
    assert "directive" not in fb_row
    assert fb_row["verdict"] == "valid"


def test_directive_absent_is_bare_signoff_unchanged(env):
    opened = _open_two_voice(env)
    sid = opened["session_id"]
    res = fs.end_session(
        env["finding_id"], sid, outcome="validated", note="fine",
        sessions_root=env["sessions_root"], feedback_path=env["feedback"],
        status_audit_path=env["status_audit"], followups_path=env["followups"],
    )
    # Absent directive -> no `directive` key on the audit row (back-compat).
    assert "directive" not in res["status_audit_row"]
    audit = json.loads(env["status_audit"].read_text().splitlines()[0])
    assert "directive" not in audit
    rows = _rows(env, sid)
    fb = [r for r in rows if r["type"] == "feedback"][0]
    assert "directive" not in fb


def test_directive_empty_string_treated_as_absent(env):
    opened = _open_two_voice(env)
    sid = opened["session_id"]
    res = fs.end_session(
        env["finding_id"], sid, outcome="validated", note="fine",
        directive="   ",
        sessions_root=env["sessions_root"], feedback_path=env["feedback"],
        status_audit_path=env["status_audit"], followups_path=env["followups"],
    )
    assert "directive" not in res["status_audit_row"]


def test_directive_signoff_on_set_status_oneshot(env):
    res = fs.set_status(
        env["finding_id"], "validated", "holds up on re-read", "human:ui",
        directive="proceed to promotion-bar recheck",
        surfaced_path=env["surfaced"], feedback_path=env["feedback"],
        status_audit_path=env["status_audit"],
    )
    assert res["status_audit_row"]["directive"] == "proceed to promotion-bar recheck"
    audit = json.loads(env["status_audit"].read_text().splitlines()[0])
    assert audit["directive"] == "proceed to promotion-bar recheck"
    # loop_feedback row stays the frozen shape.
    fb_row = json.loads(env["feedback"].read_text().splitlines()[0])
    assert "directive" not in fb_row


def test_set_status_without_directive_unchanged(env):
    res = fs.set_status(
        env["finding_id"], "validated", "holds up", "human:ui",
        surfaced_path=env["surfaced"], feedback_path=env["feedback"],
        status_audit_path=env["status_audit"],
    )
    assert "directive" not in res["status_audit_row"]


def test_cli_set_status_directive_superset(env, monkeypatch, capsys):
    """The --directive flag is a clean superset: present records it, and the
    existing bare argv (no --directive) still works."""
    monkeypatch.setattr(fs, "DEFAULT_SURFACED", env["surfaced"])
    monkeypatch.setattr(fs, "DEFAULT_STATUS_AUDIT", env["status_audit"])
    monkeypatch.setattr(fs.gate_cli, "DEFAULT", env["feedback"])
    rc = fs.main([
        "--set-status", env["finding_id"], "validated",
        "--note", "good claim", "--by", "human:ui",
        "--directive", "proceed to a follow-up probe",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status_audit_row"]["directive"] == "proceed to a follow-up probe"

    # Bare argv (no --directive) still degrades cleanly.
    rc = fs.main([
        "--set-status", env["finding_id"], "rejected", "--note", "nope",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "directive" not in out["status_audit_row"]
