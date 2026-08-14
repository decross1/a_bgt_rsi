"""D-059: the evidence ladder supersedes D-053's advisory flip.

The adversarial promotion vote is now the L3->L4 rung — neither a binary
gate nor a non-gating advisory:

  - The retired NARA_PROMOTION_VOTE_ADVISORY flag is INERT: a 3/3-refuted
    candidate never promotes, no matter the env.
  - The vote runs ONLY on candidates already at L3 (a below-L3 candidate is
    near-missed with the exact test it owes, and no Qwen spend happens).
  - Surfacing requires the post-vote derived level to reach L4+, which
    consults BOTH previously-ignored negatives: the vote outcome AND
    redteam.verdict == "proceed".
  - NARA_PROMOTION_MAX_CANDIDATES (int): unchanged — when set, lifts/
    overrides the max_candidates cap. Unset = the caller's value.
  - NARA_FRONTIER_SCREEN (D-061): DARK by default — unset leaves the funnel
    frontier-free (no frontier near-misses, no frontier_screen annotation).

Same offline harness as tests/test_finding_promotion.py: run_subagent (the
Qwen skeptics) and call_sync (the Gemma synthesis) are monkeypatched, so
nothing leaves the process under MOCK_LLM=1; all jsonl fixtures in tmp_path.

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
         hypothesis="Unprimed LLMs rediscover strategyproof truthful bidding.",
         exp="default", redteam="proceed", relevance=True, ctc=True):
    if exp == "default":
        exp = {"experiment_id": "exp_fixture", "metric": "m", "value": 1.0,
               "trials": 1000, "summary": "Verdict=YES. fixture effect +0.8%."}
    r = {
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
    if relevance:
        r["retrieval"] = {"relevance": {"relevance": 0.8, "low_confidence": False,
                                        "reason": "fixture"}}
    if redteam is not None:
        r["redteam"] = {"verdict": redteam, "critique": f"redteam {iid}",
                        "confidence": 0.8}
    if exp is not None:
        r["experiment_outcome"] = exp
    if ctc:
        r["cross_tier_comparison"] = {"replicated": True, "note": "fixture"}
    return r


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


# ── 1. the retired advisory flag is INERT ──────────────────────────────


def test_refuted_never_promotes_even_with_retired_flag_set(monkeypatch, tmp_path):
    """A 3/3-refuted candidate never promotes — NARA_PROMOTION_VOTE_ADVISORY=1
    is dead env (D-059 retired the D-053 flip)."""
    monkeypatch.setenv("NARA_PROMOTION_VOTE_ADVISORY", "1")
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["refuted", "refuted", "refuted"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert out["promoted"] == []
    nm = [n for n in out["near_misses"] if n["stage"] == "adversarial"]
    assert len(nm) == 1
    assert "refuted" in nm[0]["reason"]


def test_promoted_finding_has_no_advisory_field(monkeypatch, tmp_path):
    """No promotion_vote_advisory key exists anymore — the vote outcome lives
    in `adversarial` and the derived `evidence_level`."""
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert len(out["promoted"]) == 1
    finding = out["promoted"][0]
    assert "promotion_vote_advisory" not in finding
    assert finding["evidence_level"] == "L4"
    line = json.loads(p["surfaced_path"].read_text().splitlines()[0])
    assert "promotion_vote_advisory" not in line
    assert line["evidence_level"] == "L4"


# ── 2. the ladder is the gate ──────────────────────────────────────────


def test_survivor_without_redteam_proceed_capped_below_l4(monkeypatch, tmp_path):
    """Vote survived but redteam absent -> derived level < L4 -> near_miss at
    the ladder stage (the second previously-ignored negative is load-bearing)."""
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"],
                 [_row("iter-2026-06-01-001", redteam=None)])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert out["promoted"] == []
    nm = [n for n in out["near_misses"] if n["stage"] == "ladder"]
    assert len(nm) == 1
    assert "redteam" in nm[0]["reason"]


def test_below_l3_candidate_defers_vote_no_qwen_spend(monkeypatch, tmp_path):
    """A literature-only candidate (no experiment) is near-missed with the
    test it owes and the Qwen skeptics are never invoked."""
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"],
                 [_row("iter-2026-06-01-001", exp=None, ctc=False)])
    calls = _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert out["promoted"] == []
    nm = [n for n in out["near_misses"] if n["stage"] == "ladder"]
    assert len(nm) == 1
    assert "vote deferred" in nm[0]["reason"]
    assert calls["i"] == 0  # no skeptic spend below L3


def test_frontier_screen_dark_by_default(monkeypatch, tmp_path):
    """NARA_FRONTIER_SCREEN unset: no frontier near-misses, no annotation."""
    monkeypatch.delenv("NARA_FRONTIER_SCREEN", raising=False)
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert len(out["promoted"]) == 1
    assert "frontier_screen" not in out["promoted"][0]
    assert all(n["stage"] != "frontier" for n in out["near_misses"])
    assert not fp._frontier_screen_enabled()


# ── 3. NARA_PROMOTION_MAX_CANDIDATES (unchanged by D-059) ──────────────


def test_max_candidates_env_lifts_caller_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("NARA_PROMOTION_MAX_CANDIDATES", "2")
    p = _paths(tmp_path)
    rows = [_row(f"iter-2026-06-01-00{i}") for i in range(1, 4)]
    _write_jsonl(p["loop_memory_path"], rows)
    _stub_skeptics(monkeypatch, ["stands"] * 9)
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3, max_candidates=1)
    assert len(out["promoted"]) == 2
    capped = [n for n in out["near_misses"] if "capped" in n["reason"]]
    assert len(capped) == 1


def test_max_candidates_env_unset_keeps_caller_cap(monkeypatch, tmp_path):
    monkeypatch.delenv("NARA_PROMOTION_MAX_CANDIDATES", raising=False)
    p = _paths(tmp_path)
    rows = [_row(f"iter-2026-06-01-00{i}") for i in range(1, 4)]
    _write_jsonl(p["loop_memory_path"], rows)
    _stub_skeptics(monkeypatch, ["stands"] * 9)
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3, max_candidates=1)
    assert len(out["promoted"]) == 1


def test_max_candidates_env_bad_value_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("NARA_PROMOTION_MAX_CANDIDATES", "not-an-int")
    p = _paths(tmp_path)
    rows = [_row(f"iter-2026-06-01-00{i}") for i in range(1, 3)]
    _write_jsonl(p["loop_memory_path"], rows)
    _stub_skeptics(monkeypatch, ["stands"] * 6)
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3, max_candidates=1)
    assert len(out["promoted"]) == 1
