"""Cross-session context — the tutor and the two voices share what the human
explored in OTHER interrogation sessions on the SAME finding (read-only context,
no memory store, no model call). The transcripts already coexist on disk under
memory/finding_sessions/<finding_id>/; this just reads the siblings.

Offline: wrapper.call_sync is stubbed via monkeypatch — never hits a real model.
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator import finding_session as fs


def _write_session(root: Path, finding_id: str, session_id: str,
                   rows: list[dict]) -> Path:
    p = root / finding_id / f"{session_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return p


# --------------------------------------------------------------------------- #
# _cross_session_context — the pure helper                                     #
# --------------------------------------------------------------------------- #

def test_cross_session_context_gathers_sibling_turns(tmp_path):
    root = tmp_path / "finding_sessions"
    fid = "sf-x"
    _write_session(root, fid, "fs-tutor", [
        {"type": "system_seed", "mode": "tutor", "content": "seed"},
        {"type": "user", "content": "what does VCG truthfulness mean here?"},
        {"type": "assistant", "content": "truthful bidding is dominant."},
    ])
    cur = _write_session(root, fid, "fs-2v", [
        {"type": "system_seed", "stance": "defender", "content": "seed"},
    ])
    ctx = fs._cross_session_context(cur)
    assert ctx is not None
    assert "what does VCG truthfulness mean here?" in ctx
    assert "truthful bidding is dominant." in ctx
    assert "[tutor]" in ctx
    # honest framing: read-only, not a verdict (the fence holds in spirit).
    assert "NOT a verdict" in ctx


def test_cross_session_context_excludes_own_session(tmp_path):
    """A session is never fed its OWN turns back as 'cross-session' context."""
    root = tmp_path / "finding_sessions"
    fid = "sf-y"
    cur = _write_session(root, fid, "fs-self", [
        {"type": "system_seed", "stance": "defender", "content": "seed"},
        {"type": "user", "content": "MY OWN private turn"},
        {"type": "assistant", "stance": "defender", "content": "my own reply"},
    ])
    assert fs._cross_session_context(cur) is None


def test_cross_session_context_none_when_no_siblings(tmp_path):
    root = tmp_path / "finding_sessions"
    cur = _write_session(root, "sf-z", "fs-only", [
        {"type": "system_seed", "stance": "defender", "content": "seed"},
    ])
    assert fs._cross_session_context(cur) is None


def test_cross_session_context_caps_to_recent_turns(tmp_path):
    root = tmp_path / "finding_sessions"
    fid = "sf-cap"
    _write_session(root, fid, "fs-long", [
        {"type": "system_seed", "mode": "tutor", "content": "seed"},
        *[{"type": "user", "content": f"q{i}"} for i in range(20)],
    ])
    cur = _write_session(root, fid, "fs-2v", [
        {"type": "system_seed", "stance": "defender", "content": "seed"},
    ])
    ctx = fs._cross_session_context(cur, max_turns=3)
    assert ctx is not None
    assert "q19" in ctx and "q0" not in ctx  # only the most recent kept


# --------------------------------------------------------------------------- #
# integration: a turn's message stack carries the sibling discussion           #
# --------------------------------------------------------------------------- #

def _offline(monkeypatch):
    monkeypatch.setattr(fs.active_run, "write_active_run", lambda *a, **k: None)
    monkeypatch.setattr(fs.active_run, "clear_active_run", lambda: None)
    monkeypatch.setattr(fs, "set_run_id", lambda *a, **k: None)


def test_two_voice_defender_sees_tutor_discussion(tmp_path, monkeypatch):
    _offline(monkeypatch)
    root = tmp_path / "finding_sessions"
    fid = "sf-int"
    _write_session(root, fid, "fs-tut", [
        {"type": "system_seed", "mode": "tutor", "content": "TUTOR SEED"},
        {"type": "user", "content": "is the 0.965 fraction robust?"},
        {"type": "assistant", "content": "the trial count is only 150, modest."},
    ])
    _write_session(root, fid, "fs-2v", [
        {"type": "system_seed", "stance": "defender",
         "backend": "vllm-gemma", "content": "DEF SEED"},
        {"type": "system_seed", "stance": "attacker",
         "backend": "vllm-qwen", "content": "ATK SEED"},
    ])
    captured: dict[str, list] = {}

    def _capture(messages, **kw):
        captured.setdefault(kw.get("backend"), []).append(messages)
        return {"completion": "ok", "request_id": "r"}

    monkeypatch.setattr(fs, "call_sync", _capture)
    fs.two_voice_turn(
        fid, "fs-2v", "defend the robustness claim",
        addressee="defender", sessions_root=root, run_state_dir=tmp_path,
    )
    blob = json.dumps(captured["vllm-gemma"][0])
    assert "CROSS-SESSION CONTEXT" in blob
    assert "is the 0.965 fraction robust?" in blob
    assert "the trial count is only 150, modest." in blob


def test_tutor_sees_two_voice_discussion_symmetric(tmp_path, monkeypatch):
    _offline(monkeypatch)
    root = tmp_path / "finding_sessions"
    fid = "sf-sym"
    _write_session(root, fid, "fs-2v", [
        {"type": "system_seed", "stance": "attacker",
         "backend": "vllm-qwen", "content": "ATK SEED"},
        {"type": "user", "content": "attack the trial design"},
        {"type": "assistant", "stance": "attacker",
         "content": "150 trials cannot rule out the confound"},
    ])
    _write_session(root, fid, "fs-tut", [
        {"type": "system_seed", "mode": "tutor",
         "backend": "vllm-qwen", "content": "TUTOR SEED"},
    ])
    captured: list = []

    def _capture(messages, **kw):
        captured.append(messages)
        return {"completion": "ok", "request_id": "r"}

    monkeypatch.setattr(fs, "call_sync", _capture)
    fs.tutor_turn(fid, "fs-tut", "explain that confound", sessions_root=root)
    blob = json.dumps(captured[0])
    assert "CROSS-SESSION CONTEXT" in blob
    assert "150 trials cannot rule out the confound" in blob


# --------------------------------------------------------------------------- #
# apparatus primer — every interrogation seed cues the agent on the system     #
# --------------------------------------------------------------------------- #

def test_apparatus_primer_in_all_seeds():
    for builder in (fs._build_seed, fs._build_skeptic_seed, fs._build_tutor_seed):
        seed = builder({}, {}, "", [])
        assert "CORPUS-RELATIVE" in seed
        assert "5-step chain" in seed
        assert "top-10 nearest neighbors" in seed
        assert "ml_intern" in seed
