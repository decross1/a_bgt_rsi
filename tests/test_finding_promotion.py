"""Tests for orchestrator.finding_promotion.

Fully offline under MOCK_LLM: run_subagent (the Qwen skeptic dispatch) and
call_sync (the Gemma synthesis) are monkeypatched; all loop_memory /
loop_feedback / surfaced_findings fixtures live in tmp_path so no shared
state is touched.

Covers: the cheap threshold gate (novel/survives passes; rediscovery,
falsified-critic, human-invalid, and a weak/INVALID experiment outcome fail;
an exp005-shaped unclear + Verdict=NO passes), the adversarial multi-vote
(3 stands -> promoted with margin +3; 2/3 refuted -> near_miss; 1 refuted ->
promoted with margin +1), the Qwen-failure path (2 timeouts + 1 stands ->
n_voting below quorum -> NOT promoted, qwen_failures==2, never silent),
idempotency, schema validity, and the max_candidates cap.
"""
import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import finding_promotion as fp
from orchestrator.subagent import SubAgentResult

SCHEMA = json.loads((REPO_ROOT / "schema" / "surfaced_finding.schema.json").read_text())
VALIDATOR = jsonschema.Draft7Validator(SCHEMA)


# ── fixtures ──────────────────────────────────────────────────────────


def _row(
    iid,
    *,
    novelty="novel",
    critic="survives",
    hypothesis="Unprimed LLMs rediscover strategyproof truthful bidding.",
    exp="default",
    redteam="proceed",
    relevance=True,
    ctc=True,
):
    # D-059 fixtures carry ladder-grade evidence by default: sound retrieval
    # relevance (L1), a sound experiment (L2), replication evidence (L3), and
    # a redteam "proceed" (required at L4) — so vote-path tests exercise the
    # L3->L4 rung the vote now IS. Tests that pin a specific rejection
    # override these.
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
    """Patch run_subagent so successive calls return the scripted verdicts.

    Each item is one of: "stands", "refuted", "timeout", "error",
    "schema_mismatch", "no_verdict". The first three model verdicts and the
    failure modes the pipeline must count as qwen_failures.
    """
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
        if v == "no_verdict":
            return SubAgentResult(status="passed",
                                  result={"attack": "x", "confidence": 0.5},
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


def _stub_synthesis(monkeypatch, why="why matters", change="what would change"):
    def stub(messages, **kwargs):
        return {
            "request_id": "req-synth",
            "completion": json.dumps(
                {"why_it_matters": why, "what_would_change_it": change}
            ),
        }
    monkeypatch.setattr(fp, "call_sync", stub)


# ── 1. cheap threshold gate ────────────────────────────────────────────


def test_threshold_novel_survives_passes(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p)
    assert len(out["promoted"]) == 1
    assert out["near_misses"] == []


def test_threshold_rediscovery_is_near_miss(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"],
                 [_row("iter-2026-06-01-001", novelty="rediscovery")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p)
    assert out["promoted"] == []
    assert len(out["near_misses"]) == 1
    nm = out["near_misses"][0]
    assert nm["stage"] == "threshold"
    assert "novelty" in nm["reason"]


def test_threshold_falsified_critic_is_near_miss(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"],
                 [_row("iter-2026-06-01-001", critic="falsified")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p)
    assert out["promoted"] == []
    assert any("critique.verdict='falsified'" in nm["reason"]
               for nm in out["near_misses"])


def test_threshold_human_invalid_is_near_miss(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _write_jsonl(p["feedback_path"], [{
        "iteration_id": "iter-2026-06-01-001", "verdict": "invalid",
        "note": "", "gated_at": "2026-06-01T00:00:00Z", "gated_by": "human",
    }])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p)
    assert out["promoted"] == []
    assert any("invalid" in nm["reason"] for nm in out["near_misses"])


def test_threshold_low_trials_experiment_is_near_miss(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    exp = {"experiment_id": "expX", "metric": "m", "value": 1.0,
           "trials": 10, "summary": "Verdict=YES."}
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001", exp=exp)])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p)
    assert out["promoted"] == []
    assert any("trials" in nm["reason"] for nm in out["near_misses"])


def test_threshold_invalid_experiment_summary_is_near_miss(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    exp = {"experiment_id": "expX", "metric": "m", "value": 1.0,
           "trials": 50, "summary": "Verdict=INVALID. run aborted."}
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001", exp=exp)])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p)
    assert out["promoted"] == []
    assert any("INVALID" in nm["reason"] for nm in out["near_misses"])


def test_threshold_exp005_shaped_unclear_verdict_no_passes(monkeypatch, tmp_path):
    """exp005-shaped: novelty 'unclear' + an experiment_outcome whose summary
    carries a Verdict=NO (surprising-vs-theory) -> passes the gate."""
    p = _paths(tmp_path)
    exp = {"experiment_id": "exp006_mechanism_design", "metric": "eff",
           "value": 0.71, "trials": 40,
           "summary": "Verdict=NO. Mean allocative efficiency 71.02%."}
    _write_jsonl(p["loop_memory_path"],
                 [_row("iter-2026-06-01-001", novelty="unclear", exp=exp)])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p)
    assert len(out["promoted"]) == 1, out["near_misses"]


# ── 2. adversarial multi-vote ──────────────────────────────────────────


def test_vote_all_stands_promoted_margin_plus3(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert len(out["promoted"]) == 1
    adv = out["promoted"][0]["adversarial"]
    assert adv["n_voting"] == 3
    assert adv["n_refuted"] == 0
    assert adv["adversarial_margin"] == 3
    assert adv["survived"] is True


def test_vote_two_of_three_refuted_is_near_miss(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["refuted", "refuted", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert out["promoted"] == []
    nm = [n for n in out["near_misses"] if n["stage"] == "adversarial"]
    assert len(nm) == 1
    assert "refuted" in nm[0]["reason"]


def test_vote_one_refuted_minority_promoted_margin_plus1(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["refuted", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert len(out["promoted"]) == 1
    adv = out["promoted"][0]["adversarial"]
    assert adv["n_refuted"] == 1
    assert adv["n_voting"] == 3
    assert adv["adversarial_margin"] == 1
    assert adv["refutation_summaries"] == ["attack(refuted)"]


# ── 3. Qwen failures observable, never silent ──────────────────────────


def test_qwen_failures_unmet_quorum_not_promoted(monkeypatch, tmp_path):
    """2 timeouts + 1 stands: n_voting=1 < quorum=2 -> NOT promoted; the two
    failures are counted in qwen_failures and never treated as refutations."""
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["timeout", "timeout", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert out["promoted"] == []
    assert out["qwen_failures"] == 2
    nm = [n for n in out["near_misses"] if n["stage"] == "adversarial"]
    assert len(nm) == 1
    assert "inconclusive" in nm[0]["reason"]
    assert "quorum" in nm[0]["reason"]


def test_no_verdict_payload_counts_as_qwen_failure(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["no_verdict", "no_verdict", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, n_skeptics=3)
    assert out["promoted"] == []
    assert out["qwen_failures"] == 2


# ── 4. idempotency ─────────────────────────────────────────────────────


def test_idempotent_second_run_skips(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out1 = fp.promote_findings(**p)
    assert len(out1["promoted"]) == 1
    # Second run: re-stub the skeptics (generator was consumed).
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    out2 = fp.promote_findings(**p)
    assert out2["promoted"] == []
    assert out2["skipped_already_surfaced"] == 1
    # Only one row was written to disk.
    lines = [l for l in p["surfaced_path"].read_text().splitlines() if l.strip()]
    assert len(lines) == 1


def test_dry_run_skips_write(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, dry_run=True)
    assert len(out["promoted"]) == 1
    assert not p["surfaced_path"].exists()


# ── 5. schema validity ─────────────────────────────────────────────────


def test_promoted_finding_is_schema_valid(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    exp = {"experiment_id": "exp003", "metric": "truthful", "value": 1.0,
           "trials": 50, "summary": "Verdict=YES.",
           "results_path": "experiments/exp003/results/summary.md"}
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001", exp=exp)])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p)
    assert len(out["promoted"]) == 1
    VALIDATOR.validate(out["promoted"][0])
    # And the persisted line validates too.
    line = p["surfaced_path"].read_text().splitlines()[0]
    VALIDATOR.validate(json.loads(line))


# ── 6. max_candidates caps the expensive vote ──────────────────────────


def test_max_candidates_caps_after_gate(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    rows = [_row(f"iter-2026-06-01-00{i}") for i in range(1, 4)]
    _write_jsonl(p["loop_memory_path"], rows)
    # Three gate-survivors; only one slot. Count run_subagent calls to prove
    # the cap bounds the expensive vote (1 candidate * 3 skeptics = 3 calls).
    calls = _stub_skeptics(monkeypatch, ["stands"] * 9)
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, max_candidates=1, n_skeptics=3)
    assert len(out["promoted"]) == 1
    assert calls["i"] == 3
    capped = [n for n in out["near_misses"] if "capped" in n["reason"]]
    assert len(capped) == 2


def test_since_filters_old_iterations(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    rows = [_row("iter-2026-06-01-001"), _row("iter-2026-06-05-001")]
    _write_jsonl(p["loop_memory_path"], rows)
    _stub_skeptics(monkeypatch, ["stands"] * 9)
    _stub_synthesis(monkeypatch)
    out = fp.promote_findings(**p, since="iter-2026-06-05-000")
    assert out["examined"] == 1
    assert len(out["promoted"]) == 1
    assert out["promoted"][0]["source_iteration_id"] == "iter-2026-06-05-001"


def test_synthesis_failure_falls_back_deterministically(monkeypatch, tmp_path):
    p = _paths(tmp_path)
    _write_jsonl(p["loop_memory_path"], [_row("iter-2026-06-01-001")])
    _stub_skeptics(monkeypatch, ["stands", "stands", "stands"])

    def boom(messages, **kwargs):
        raise RuntimeError("gemma down")
    monkeypatch.setattr(fp, "call_sync", boom)

    out = fp.promote_findings(**p)
    assert len(out["promoted"]) == 1
    f = out["promoted"][0]
    assert f["why_it_matters"]
    assert f["what_would_change_it"]
    VALIDATOR.validate(f)
