"""Tests for workers.redteam_critic (Step 2.5 pre-experiment red-team).

The worker delegates to orchestrator.subagent.run_subagent. We stub that
function with scripted SubAgentResults to exercise every status + verdict +
consistency-guard path. Unlike critic_loop_v0 this worker takes
`hypothesis_text` directly (no iteration_cache read), so no cache fixture is
needed and the test is fully self-contained under MOCK_LLM.

D-075 R1b polarity pins live here too: every sub-agent failure path yields
verdict 'unscored' (never fail-open to 'proceed'), and 'unscored' behaves
as an ABSENT redteam signal downstream (evidence ladder L1-eligible, never
L4; consolidate_memory kill builder refuses it).
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import redteam_critic as rt_mod
from orchestrator.subagent import SubAgentResult


def _fake_run_subagent(*, status, result, errors=None, wrapper_call_ids=None,
                       turns_used=2, wall_seconds=1.5, output_tokens_used=200):
    """Build a stub returning a fixed SubAgentResult regardless of args."""
    def stub(**kwargs):
        return SubAgentResult(
            status=status,
            result=result,
            errors=errors or [],
            wrapper_call_ids=wrapper_call_ids or ["sa-rid-1"],
            turns_used=turns_used,
            wall_seconds=wall_seconds,
            output_tokens_used=output_tokens_used,
        )
    return stub


# ── shape + verdict (the headline assertion the brief calls for) ──────


def test_shape_and_verdict_enum_under_mock_llm(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "proceed",
            "critique": "No fatal flaw; the claim is testable.",
            "suggested_revision": None,
            "confidence": 0.8,
        },
    ))
    out = rt_mod.redteam_critic("some hypothesis", "iter-2026-06-05-001")
    assert out["status"] == "passed"
    res = out["result"]
    assert set(["verdict", "critique", "suggested_revision", "confidence"]).issubset(res)
    # REGRESSION PIN (D-075 R1b): a genuine 'proceed' passes through
    # untouched — polarity fix touches only the failure paths.
    assert res["verdict"] == "proceed"
    assert res["verdict"] in {"fatal_flaw", "proceed"}
    assert isinstance(res["critique"], str)
    assert isinstance(res["confidence"], float)
    assert res["subagent_status"] == "passed"
    assert res["subagent_turns_used"] == 2


# ── input validation ─────────────────────────────────────────────────


def test_empty_hypothesis_errors():
    out = rt_mod.redteam_critic("", "iter-1")
    assert out["status"] == "error"
    assert any("hypothesis_text" in e for e in out["errors"])


def test_empty_iteration_id_errors():
    out = rt_mod.redteam_critic("h", "")
    assert out["status"] == "error"
    assert any("iteration_id" in e for e in out["errors"])


# ── verdict paths (sub-agent passed) ─────────────────────────────────


def test_fatal_flaw_verdict_keeps_revision(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "fatal_flaw",
            "critique": "Contradicts backward induction.",
            "suggested_revision": "Restrict to infinite horizon.",
            "confidence": 0.9,
        },
    ))
    out = rt_mod.redteam_critic("h", "iter-2")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "fatal_flaw"
    assert out["result"]["suggested_revision"] == "Restrict to infinite horizon."


# ── consistency guards ───────────────────────────────────────────────


def test_revision_nulled_on_proceed(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "proceed",
            "critique": "ok",
            "suggested_revision": "leftover revision",
            "confidence": 0.7,
        },
    ))
    out = rt_mod.redteam_critic("h", "iter-3")
    assert out["status"] == "passed"
    assert out["result"]["suggested_revision"] is None
    assert any("nulling per schema" in e for e in out["errors"])


def test_confidence_clamped(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "proceed",
            "critique": "ok",
            "suggested_revision": None,
            "confidence": 1.7,
        },
    ))
    out = rt_mod.redteam_critic("h", "iter-4")
    assert out["result"]["confidence"] == 1.0


def test_critique_strips_channel_markup(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="passed",
        result={
            "verdict": "proceed",
            "critique": "<channel|>thought\nThe claim is well-posed.",
            "suggested_revision": None,
            "confidence": 0.5,
        },
    ))
    out = rt_mod.redteam_critic("h", "iter-5")
    assert "<channel|>" not in out["result"]["critique"]
    assert "The claim is well-posed" in out["result"]["critique"]


# ── failure paths yield 'unscored' — never fail-open (D-075 R1b) ─────


def test_schema_mismatch_yields_unscored_never_proceed(monkeypatch):
    """REGRESSION PIN (D-075 R1b): a parse-failure row must NEVER yield
    'proceed' — the August parser-accident pathway minted 4 fake L1→L4
    climbs through exactly this branch."""
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="schema_mismatch",
        result={"some": "bad payload"},
        errors=["payload didn't validate"],
    ))
    out = rt_mod.redteam_critic("h", "iter-6")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "unscored"
    assert out["result"]["verdict"] != "proceed"
    assert out["result"]["subagent_status"] == "schema_mismatch"
    assert any("schema mismatch" in e for e in out["errors"])
    assert any("unscored" in e for e in out["errors"])


def test_timeout_yields_unscored_never_proceed(monkeypatch):
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="timeout",
        result=None,
        errors=["max_wall_seconds exceeded"],
        turns_used=3,
        wall_seconds=46.0,
    ))
    out = rt_mod.redteam_critic("h", "iter-7")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "unscored"
    assert out["result"]["subagent_status"] == "timeout"
    assert out["result"]["subagent_wall_seconds"] == 46.0


def test_subagent_error_yields_unscored(monkeypatch):
    """D-075 R1b: the dispatch-error path carries the same polarity —
    worker status 'passed', verdict 'unscored', honest subagent_status,
    original errors preserved."""
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status="error",
        result=None,
        errors=["vllm down"],
    ))
    out = rt_mod.redteam_critic("h", "iter-8")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "unscored"
    assert out["result"]["subagent_status"] == "error"
    assert any("vllm down" in e for e in out["errors"])


@pytest.mark.parametrize("sa_status", ["schema_mismatch", "timeout", "error"])
def test_no_failure_path_ever_yields_proceed(monkeypatch, sa_status):
    """REGRESSION PIN (D-075 R1b): every sub-agent failure status maps to
    'unscored'. 'proceed' is only ever awarded by the sub-agent itself."""
    monkeypatch.setattr(rt_mod, "run_subagent", _fake_run_subagent(
        status=sa_status,
        result=None,
        errors=["boom"],
    ))
    out = rt_mod.redteam_critic("h", f"iter-pin-{sa_status}")
    assert out["status"] == "passed"
    assert out["result"]["verdict"] == "unscored"
    assert out["result"]["verdict"] not in rt_mod.ALLOWED_VERDICTS


# ── downstream polarity pins: 'unscored' behaves as ABSENT ───────────
# (evidence ladder: L1-eligible, never L4; kill builder: refuses it)


_L1_ROW = {
    "iteration_id": "iter-ladder-l1",
    "retrieval": {"relevance": {"low_confidence": False}},
    "novelty": {"class": "novel"},
    "critique": {"verdict": "survives"},
}

_L3_ROW = {
    **_L1_ROW,
    "iteration_id": "iter-ladder-l3",
    "experiment_outcome": {"trials": 30, "summary": "beta=0.4, clean run"},
    "cross_tier_comparison": {"tiers": ["t0", "t1"]},
}


def test_unscored_row_derives_l1_eligible():
    """REGRESSION PIN (D-075 R1b): an 'unscored' redteam block behaves as
    ABSENT at L1 — the row still earns L1 (unlike fatal_flaw's hard cap)."""
    from workers.evidence_ladder import derive_level

    row = {**_L1_ROW, "redteam": {"verdict": "unscored"}}
    derived = derive_level(row, None, None, [])
    assert derived["level"] == "L1"

    capped = {**_L1_ROW, "redteam": {"verdict": "fatal_flaw"}}
    assert derive_level(capped, None, None, [])["level"] == "L0"


def test_unscored_row_never_derives_l4():
    """REGRESSION PIN (D-075 R1b): 'unscored' blocks L4 exactly like an
    absent signal — only a genuine 'proceed' opens the L3→L4 rung."""
    from workers.evidence_ladder import derive_level

    adv = {"survived": True}
    unscored = {**_L3_ROW, "redteam": {"verdict": "unscored"}}
    derived = derive_level(unscored, None, adv, [])
    assert derived["level"] == "L3"
    assert any("redteam" in m for m in derived["missing_for_next"])

    proceed = {**_L3_ROW, "redteam": {"verdict": "proceed"}}
    assert derive_level(proceed, None, adv, [])["level"] == "L4"


def test_kill_builder_refuses_unscored():
    """consolidate_memory's kill path fires only on fatal_flaw; the
    builder must refuse to coerce an 'unscored' row into a kill."""
    from workers.idea_ledger import kill_reason_from_redteam

    with pytest.raises(ValueError):
        kill_reason_from_redteam(
            {"iteration_id": "i1", "redteam": {"verdict": "unscored"}})
    kill = kill_reason_from_redteam(
        {"iteration_id": "i1", "redteam": {"verdict": "fatal_flaw"}})
    assert kill["code"] == "redteam_fatal_flaw"


# ── budget + wiring ──────────────────────────────────────────────────


def test_default_budget_when_omitted(monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "proceed", "critique": "ok",
                    "suggested_revision": None, "confidence": 0.5},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(rt_mod, "run_subagent", stub)
    rt_mod.redteam_critic("h", "iter-9")
    assert captured["budget"].max_turns == 3
    assert captured["budget"].max_wall_seconds == 45.0


def test_parent_request_id_threads_through(monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "proceed", "critique": "ok",
                    "suggested_revision": None, "confidence": 0.5},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(rt_mod, "run_subagent", stub)
    rt_mod.redteam_critic("h", "iter-10", parent_request_id="iter-root-9")
    assert captured["parent_request_id"] == "iter-root-9"


def test_caller_tag_in_subagent_call(monkeypatch):
    captured = {}
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "proceed", "critique": "ok",
                    "suggested_revision": None, "confidence": 0.5},
            wrapper_call_ids=["x"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    monkeypatch.setattr(rt_mod, "run_subagent", stub)
    rt_mod.redteam_critic("h", "iter-11")
    assert captured["name"] == "redteam_critic"


def test_adopted_prompt_sha256_pins_d076_artifact():
    """D-076 adoption anchor (review catch): the module constant must stay
    byte-identical to the R1a WINNING ARM's prompt (gemma-revised artifact
    prompt_sha256). A coordinated edit of the constant AND the frozen
    revised_prompt.txt would drift silently past the relative seam test;
    this absolute pin catches it. Changing the production prompt again
    requires a new calibration battery (and then this pin changes WITH the
    new artifact's hash)."""
    import hashlib
    from workers.redteam_critic import REDTEAM_AGENT_SYSTEM_PROMPT
    assert hashlib.sha256(
        REDTEAM_AGENT_SYSTEM_PROMPT.encode()
    ).hexdigest() == (
        "7d44820d99f71485b0734ad4362cb95212c0f327481c7de043d8079cc3f52dba"
    )
