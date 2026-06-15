"""D-053: the NON-GATING adversarial PROMOTION vote (mirrors D-052).

D-053 demotes the adversarial promotion vote from a GATE to a NON-GATING
advisory, env-gated DARK by default:

  - Flag OFF (default, NARA_PROMOTION_VOTE_ADVISORY unset): EXACTLY today's
    behavior — a 3/3-refuted candidate does NOT promote, and the promoted
    finding carries NO advisory field. Byte-identical to before.
  - Flag ON (NARA_PROMOTION_VOTE_ADVISORY=1): a candidate that cleared
    _passes_threshold (novel + survives) PROMOTES regardless of the vote; the
    vote still RUNS (so its opinion is captured) and rides on the surfaced
    finding as an ADDITIVE `promotion_vote_advisory: {n_refuted, n_voting,
    survived, margin}` — recorded, never blocking. The vote's real outcome is
    NEVER silently coerced (inviolate rule 4): a 3/3 refute stays survived=False
    in the advisory even though the finding promotes.
  - NARA_PROMOTION_MAX_CANDIDATES (int): when set, lifts/overrides the
    max_candidates cap (for the cargo experiment). Unset = today's default.

These tests pin those properties. They reuse the same offline harness as
tests/test_finding_promotion.py: run_subagent (the Qwen skeptics) and call_sync
(the Gemma synthesis) are monkeypatched, so nothing leaves the process under
MOCK_LLM=1, and all jsonl fixtures live in tmp_path.

Run standalone:
    MOCK_LLM=1 ./.venv-chroma/bin/python -m pytest tests/test_promotion_vote_advisory.py
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import finding_promotion as fp
from orchestrator.subagent import SubAgentResult


# ── fixtures (mirror tests/test_finding_promotion.py) ──────────────────


def _row(iid, *, novelty="novel", critic="survives",
         hypothesis="Unprimed LLMs rediscover strategyproof truthful bidding."):
    return {
        "iteration_id": iid,
        "started_at": "2026-06-01T00:00:00Z",
        "ended_at": "2026-06-01T00:01:00Z",
        "seed": {"topic": f"topic for {iid}", "source": "human_cli"},
        "hypothesis": {"text": hypothesis, "candidates_considered": 1},
        "novelty": {"class": novelty, "rationale": f"novelty rationale {iid}"},
        "critique": {"verdict": critic, "rationale": f"critic rationale {iid}"},
        "journal_entry_path": "journal/iterations/001.md",
        "nara_summary": "summary",
        "tool_calls_made": ["journal_writer"],
        "model_version": "test",
        "wrapper_call_ids": ["x"],
    }


def _write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _paths(tmp_path):
    return {
        "loop_memory_path": tmp_path / "loop_memory.jsonl",
        "feedback_path": tmp_path / "loop_feedback.jsonl",
        "surfaced_path": tmp_path / "surfaced_findings.jsonl",
    }


def _stub_skeptics(monkeypatch, verdicts):
    """Patch run_subagent so successive calls return the scripted verdicts."""
    seq = list(verdicts)
    calls = {"i": 0}

    def stub(**kwargs):
        i = calls["i"]
        calls["i"] += 1
        v = seq[i] if i < len(seq) else "stands"
        if v in ("timeout", "error", "schema_mismatch"):
            return SubAgentResult(status=v, result=None, errors=[v],
                                  wrapper_call_ids=["sa"], turns_used=1,
                                  wall_seconds=0.1, output_tokens_used=10)
        return SubAgentResult(
            status="passed",
            result={"verdict": v, "attack": f"attack({v})", "confidence": 0.7},
            wrapper_call_ids=["sa"], turns_used=1, wall_seconds=0.1,
            output_tokens_used=10,
        )

    monkeypatch.setattr(fp, "run_subagent", stub)
    return calls


def _stub_synthesis(monkeypatch):
    def stub(messages, **kwargs):
        return {
            "request_id": "req-synth",
            "completion": json.dumps(
                {"why_it_matters": "why", "what_would_change_it": "change"}
            ),
        }
    monkeypatch.setattr(fp, "call_sync", stub)


# ── 1. flag OFF (DARK default): the vote still gates; no advisory field ──


def test_flag_off_three_of_three_refuted_not_promoted(monkeypatch, tmp_path):
    """NARA_PROMOTION_VOTE_ADVISORY unset: a 3/3-refuted candidate is NOT
    promoted (today's gate) and lands as an adversarial near_miss."""
    monkeypatch.delenv("NARA_PROMOTION_VOTE_ADVISORY", raising=False)
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["refuted", "refuted", "refuted"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert out["promoted"] == []
    nm = [n for n in out["near_misses"] if n["stage"] == "adversarial"]
    assert len(nm) == 1
    assert "refuted" in nm[0]["reason"]


def test_flag_off_promoted_finding_has_no_advisory_field(monkeypatch, tmp_path):
    """Flag OFF: a survivor promotes WITHOUT a promotion_vote_advisory key — the
    OFF-path finding is byte-identical to before."""
    monkeypatch.delenv("NARA_PROMOTION_VOTE_ADVISORY", raising=False)
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert len(out["promoted"]) == 1
    assert "promotion_vote_advisory" not in out["promoted"][0]
    # And the persisted line carries no advisory either.
    line = p["surfaced_path"].read_text().splitlines()[0]
    assert "promotion_vote_advisory" not in json.loads(line)


# ── 2. flag ON: the same 3/3-refuted candidate PROMOTES with the advisory ──


def test_flag_on_three_of_three_refuted_is_promoted_with_advisory(
    monkeypatch, tmp_path
):
    """NARA_PROMOTION_VOTE_ADVISORY=1: the same 3/3-refuted candidate IS
    promoted AND carries promotion_vote_advisory recording the REAL vote
    outcome (survived=False, n_refuted=3) — recorded, never coerced (rule 4)."""
    monkeypatch.setenv("NARA_PROMOTION_VOTE_ADVISORY", "1")
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["refuted", "refuted", "refuted"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert len(out["promoted"]) == 1
    adv = out["promoted"][0]["promotion_vote_advisory"]
    assert adv == {
        "n_refuted": 3, "n_voting": 3, "survived": False, "margin": -3
    }
    # The vote's verdict is recorded, NOT silently coerced into survival.
    assert out["promoted"][0]["adversarial"]["survived"] is False
    # The dissent is still surfaced as a near_miss (observable, never silent).
    assert any(n["stage"] == "adversarial" for n in out["near_misses"])
    # Persisted line carries the advisory too.
    line = p["surfaced_path"].read_text().splitlines()[0]
    assert json.loads(line)["promotion_vote_advisory"]["survived"] is False


def test_flag_on_survivor_records_true_outcome(monkeypatch, tmp_path):
    """Flag ON, a genuine 3/3-stands survivor: it promotes AND its advisory
    records survived=True (the real outcome, not a blanket override)."""
    monkeypatch.setenv("NARA_PROMOTION_VOTE_ADVISORY", "1")
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert len(out["promoted"]) == 1
    adv = out["promoted"][0]["promotion_vote_advisory"]
    assert adv == {
        "n_refuted": 0, "n_voting": 3, "survived": True, "margin": 3
    }


def test_flag_on_inconclusive_quorum_still_promotes_with_advisory(
    monkeypatch, tmp_path
):
    """Flag ON: even an unmet-quorum (inconclusive) vote does not block a
    threshold-passer; the advisory records the real n_voting below quorum."""
    monkeypatch.setenv("NARA_PROMOTION_VOTE_ADVISORY", "1")
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    # 2 timeouts + 1 stands -> n_voting=1 < quorum=2 (inconclusive).
    _stub_skeptics(monkeypatch, ["timeout", "timeout", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert len(out["promoted"]) == 1
    adv = out["promoted"][0]["promotion_vote_advisory"]
    assert adv["n_voting"] == 1
    assert adv["survived"] is False
    assert out["qwen_failures"] == 2
    assert any("inconclusive" in n["reason"] for n in out["near_misses"])


# ── 3. NARA_PROMOTION_MAX_CANDIDATES lifts the cap ─────────────────────


def test_max_candidates_env_lifts_caller_cap(monkeypatch, tmp_path):
    """NARA_PROMOTION_MAX_CANDIDATES=3 overrides a caller max_candidates=1:
    all three gate-survivors are voted + promoted (the cargo lever)."""
    monkeypatch.setenv("NARA_PROMOTION_MAX_CANDIDATES", "3")
    monkeypatch.delenv("NARA_PROMOTION_VOTE_ADVISORY", raising=False)
    p = _paths(tmp_path)
    rows = [_row(f"iter-2026-06-01-00{i}") for i in range(1, 4)]
    _write_jsonl(p["loop_memory_path"], rows)
    calls = _stub_skeptics(monkeypatch, ["stands"] * 9)
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, max_candidates=1, n_skeptics=3)
    assert len(out["promoted"]) == 3       # cap lifted from 1 -> 3
    assert calls["i"] == 9                  # 3 candidates * 3 skeptics
    assert not any("capped" in n["reason"] for n in out["near_misses"])


def test_max_candidates_env_unset_keeps_caller_cap(monkeypatch, tmp_path):
    """Env UNSET (dark default): the caller's max_candidates=1 is honored
    exactly as today — two survivors are capped."""
    monkeypatch.delenv("NARA_PROMOTION_MAX_CANDIDATES", raising=False)
    p = _paths(tmp_path)
    rows = [_row(f"iter-2026-06-01-00{i}") for i in range(1, 4)]
    _write_jsonl(p["loop_memory_path"], rows)
    calls = _stub_skeptics(monkeypatch, ["stands"] * 9)
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, max_candidates=1, n_skeptics=3)
    assert len(out["promoted"]) == 1
    assert calls["i"] == 3
    assert len([n for n in out["near_misses"] if "capped" in n["reason"]]) == 2


def test_max_candidates_env_bad_value_ignored(monkeypatch, tmp_path):
    """A non-int env value is IGNORED (never silently coerced) — the caller's
    cap stands."""
    monkeypatch.setenv("NARA_PROMOTION_MAX_CANDIDATES", "not-an-int")
    p = _paths(tmp_path)
    rows = [_row(f"iter-2026-06-01-00{i}") for i in range(1, 4)]
    _write_jsonl(p["loop_memory_path"], rows)
    _stub_skeptics(monkeypatch, ["stands"] * 9)
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, max_candidates=1, n_skeptics=3)
    assert len(out["promoted"]) == 1       # bad env ignored, cap=1 stands


# ── 4. dark-default byte-identical (helpers are no-ops when unset) ─────


def test_helpers_dark_by_default(monkeypatch):
    """With both env flags unset the D-053 helpers are no-ops: the vote stays
    gating and the cap is the caller's value unchanged."""
    monkeypatch.delenv("NARA_PROMOTION_VOTE_ADVISORY", raising=False)
    monkeypatch.delenv("NARA_PROMOTION_MAX_CANDIDATES", raising=False)
    assert fp._promotion_vote_advisory() is False
    assert fp._max_candidates_override(None) is None
    assert fp._max_candidates_override(3) == 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
