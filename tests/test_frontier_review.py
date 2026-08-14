"""Tests for workers.frontier_review.

Hermetic by construction: the frontier seam is an INJECTED invoke_fn
(signature = agent_wrapper.frontier_cli.invoke_frontier), so no subprocess,
no network, no real model call ever happens here — MOCK_LLM is irrelevant
to this worker (test-pinned in test_no_frontier_cli_import).

Pinned behaviors:
  - fail-open: ANY failure (invoke error/exception, non-zero exit,
    unparseable output, off-enum verdict) -> "inconclusive", NEVER "veto";
  - role->vendor routing (claude=methods, codex=novelty) + env overrides;
  - the disagreement protocol: veto+pass -> cross-run the vetoing role
    ONCE on the other vendor; cross veto -> veto; otherwise inconclusive
    with escalated=True.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import frontier_review as fr


CANDIDATE = {
    "finding_id": "find-001",
    "source_iteration_id": "iter-2026-06-06-001",
    "title": "Tit-for-tat drift under noisy payoffs",
    "claim": "Under 5% payoff noise, TFT populations drift to GTFT within 200 generations.",
    "novelty_class": "novel",
    "evidence": {"trials": 40, "effect": 0.31},
}


def _verdict_json(verdict, reasoning="grounded reasons", prior=None):
    return json.dumps({
        "verdict": verdict,
        "reasoning": reasoning,
        "closest_prior_work": prior,
    })


def _record(text, vendor="claude", exit_code=0, error=None):
    return {
        "text": text,
        "vendor": vendor,
        "cli_version": "test-1.0",
        "duration_ms": 5,
        "exit_code": exit_code,
        "error": error,
    }


def make_invoke(responses, calls=None):
    """Canned invoke_fn: `responses` maps (vendor, role) -> record | Exception.
    Every call is appended to `calls` as (vendor, role, prompt)."""
    def invoke(vendor, prompt, *, timeout_s, role, ledger_path=None):
        if calls is not None:
            calls.append((vendor, role, prompt))
        resp = responses[(vendor, role)]
        if isinstance(resp, Exception):
            raise resp
        return resp
    return invoke


# --- review_role: routing + parsing -----------------------------------------

def test_review_role_routes_methods_to_claude():
    calls = []
    invoke = make_invoke(
        {("claude", "methods_reviewer"): _record(_verdict_json("pass"))},
        calls,
    )
    out = fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert out["verdict"] == "pass"
    assert out["vendor"] == "claude"
    assert out["role"] == "methods_reviewer"
    assert out["parse_ok"] is True
    assert calls[0][0] == "claude" and calls[0][1] == "methods_reviewer"


def test_review_role_routes_novelty_to_codex():
    calls = []
    invoke = make_invoke(
        {("codex", "novelty_reviewer"): _record(
            _verdict_json("veto", prior="Nowak & Sigmund 1992"), vendor="codex")},
        calls,
    )
    out = fr.review_role("novelty_reviewer", CANDIDATE, invoke)
    assert out["verdict"] == "veto"
    assert out["vendor"] == "codex"
    assert out["closest_prior_work"] == "Nowak & Sigmund 1992"
    assert calls[0][0] == "codex"


def test_env_override_methods_vendor(monkeypatch):
    monkeypatch.setenv("FRONTIER_METHODS_VENDOR", "codex")
    calls = []
    invoke = make_invoke(
        {("codex", "methods_reviewer"): _record(_verdict_json("pass"))}, calls)
    out = fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert out["vendor"] == "codex"


def test_env_override_novelty_vendor(monkeypatch):
    monkeypatch.setenv("FRONTIER_NOVELTY_VENDOR", "claude")
    calls = []
    invoke = make_invoke(
        {("claude", "novelty_reviewer"): _record(_verdict_json("pass"))}, calls)
    out = fr.review_role("novelty_reviewer", CANDIDATE, invoke)
    assert out["vendor"] == "claude"


def test_prompt_carries_role_cues_and_candidate():
    calls = []
    invoke = make_invoke(
        {("claude", "methods_reviewer"): _record(_verdict_json("pass")),
         ("codex", "novelty_reviewer"): _record(_verdict_json("pass"))},
        calls,
    )
    fr.review_role("methods_reviewer", CANDIDATE, invoke)
    fr.review_role("novelty_reviewer", CANDIDATE, invoke)
    methods_prompt, novelty_prompt = calls[0][2], calls[1][2]
    assert "confound" in methods_prompt.lower()
    assert "missing" in methods_prompt.lower()  # missing controls
    assert "closest" in novelty_prompt.lower()  # closest prior work
    for p in (methods_prompt, novelty_prompt):
        assert CANDIDATE["claim"] in p
        assert "find-001" in p


def test_unknown_role_raises():
    with pytest.raises(ValueError):
        fr.review_role("vibes_reviewer", CANDIDATE, make_invoke({}))
    with pytest.raises(ValueError):
        fr.build_prompt("vibes_reviewer", CANDIDATE)


def test_reasoning_nonstring_defaults_empty_and_prior_type_nulled():
    invoke = make_invoke({("claude", "methods_reviewer"): _record(json.dumps({
        "verdict": "pass", "reasoning": 42,
        "closest_prior_work": ["a", "b"],  # invalid type -> nulled
    }))})
    out = fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert out["verdict"] == "pass"  # verdict untouched
    assert out["reasoning"] == ""
    assert out["closest_prior_work"] is None


# --- fail-open: every failure is inconclusive, never veto --------------------

def test_unparseable_output_is_inconclusive():
    invoke = make_invoke({("claude", "methods_reviewer"): _record(
        "I would veto this on methodological grounds.")})  # no JSON
    out = fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert out["verdict"] == "inconclusive"
    assert out["parse_ok"] is False
    assert "veto this" in out["reasoning"]  # raw text preserved for the human


def test_off_enum_verdict_is_inconclusive_not_coerced():
    invoke = make_invoke({("claude", "methods_reviewer"): _record(
        _verdict_json("hard-veto"))})
    out = fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert out["verdict"] == "inconclusive"
    assert "hard-veto" in out["reasoning"]


def test_invoke_error_field_is_inconclusive():
    invoke = make_invoke({("claude", "methods_reviewer"): _record(
        None, error="claude CLI not found")})
    out = fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert out["verdict"] == "inconclusive"
    assert "claude CLI not found" in out["reasoning"]


def test_nonzero_exit_code_is_inconclusive():
    invoke = make_invoke({("claude", "methods_reviewer"): _record(
        _verdict_json("veto"), exit_code=124)})  # timeout despite veto text
    out = fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert out["verdict"] == "inconclusive"
    assert "124" in out["reasoning"]


def test_invoke_exception_is_inconclusive():
    invoke = make_invoke({("claude", "methods_reviewer"):
                          TimeoutError("frontier timed out")})
    out = fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert out["verdict"] == "inconclusive"
    assert "frontier timed out" in out["reasoning"]


def test_non_dict_return_is_inconclusive():
    def invoke(vendor, prompt, *, timeout_s, role, ledger_path=None):
        return "not a dict"
    out = fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert out["verdict"] == "inconclusive"


# --- screen_candidate: combination ladder ------------------------------------

def _screen(methods_v, novelty_v, cross_v=None, calls=None):
    """Run screen_candidate with canned per-(vendor,role) verdicts. cross_v
    fills BOTH cross slots (vetoer role on the other vendor)."""
    responses = {
        ("claude", "methods_reviewer"): _record(_verdict_json(methods_v)),
        ("codex", "novelty_reviewer"): _record(
            _verdict_json(novelty_v), vendor="codex"),
    }
    if cross_v is not None:
        responses[("codex", "methods_reviewer")] = _record(
            _verdict_json(cross_v), vendor="codex")
        responses[("claude", "novelty_reviewer")] = _record(
            _verdict_json(cross_v))
    return fr.screen_candidate(CANDIDATE, make_invoke(responses, calls))


def test_both_pass_is_pass():
    calls = []
    out = _screen("pass", "pass", calls=calls)
    assert out["verdict"] == "pass"
    assert out["escalated"] is False
    assert out["methods"]["verdict"] == "pass"
    assert out["novelty"]["verdict"] == "pass"
    assert len(calls) == 2  # no cross-run


def test_both_veto_is_veto():
    out = _screen("veto", "veto")
    assert out["verdict"] == "veto"
    assert out["escalated"] is False


def test_veto_plus_inconclusive_is_veto():
    out = _screen("veto", "inconclusive")
    assert out["verdict"] == "veto"
    assert out["escalated"] is False


def test_pass_plus_inconclusive_is_pass_fail_open():
    out = _screen("pass", "inconclusive")
    assert out["verdict"] == "pass"
    assert out["escalated"] is False


def test_both_inconclusive_is_inconclusive():
    out = _screen("inconclusive", "inconclusive")
    assert out["verdict"] == "inconclusive"
    assert out["escalated"] is False


# --- the cross-run disagreement protocol -------------------------------------

def test_methods_veto_confirmed_by_cross_run_is_veto():
    calls = []
    out = _screen("veto", "pass", cross_v="veto", calls=calls)
    assert out["verdict"] == "veto"
    assert out["escalated"] is False
    # exactly one cross-run: the vetoing role (methods) on the OTHER vendor.
    assert len(calls) == 3
    assert calls[2] == (calls[2][0], "methods_reviewer", calls[2][2])
    assert calls[2][0] == "codex"
    cross = out["methods"]["cross_run"]
    assert cross["vendor"] == "codex" and cross["verdict"] == "veto"


def test_methods_veto_not_replicated_is_inconclusive_escalated():
    calls = []
    out = _screen("veto", "pass", cross_v="pass", calls=calls)
    assert out["verdict"] == "inconclusive"
    assert out["escalated"] is True
    assert len(calls) == 3  # cross-run happens ONCE, never a fourth call
    assert out["methods"]["cross_run"]["verdict"] == "pass"


def test_novelty_veto_cross_runs_on_claude():
    calls = []
    out = _screen("pass", "veto", cross_v="veto", calls=calls)
    assert out["verdict"] == "veto"
    assert out["escalated"] is False
    assert calls[2][1] == "novelty_reviewer"
    assert calls[2][0] == "claude"  # the other role's vendor
    assert out["novelty"]["cross_run"]["vendor"] == "claude"


def test_cross_run_inconclusive_is_persistent_disagreement():
    out = _screen("pass", "veto", cross_v="inconclusive")
    assert out["verdict"] == "inconclusive"
    assert out["escalated"] is True


def test_cross_run_failure_fails_open_to_escalation():
    # The cross-run vendor errors out: the veto is unconfirmable -> the
    # screen must NOT block the loop on it (fail-open), it escalates.
    responses = {
        ("claude", "methods_reviewer"): _record(_verdict_json("veto")),
        ("codex", "novelty_reviewer"): _record(
            _verdict_json("pass"), vendor="codex"),
        ("codex", "methods_reviewer"): _record(None, error="codex down"),
    }
    out = fr.screen_candidate(CANDIDATE, make_invoke(responses))
    assert out["verdict"] == "inconclusive"
    assert out["escalated"] is True
    assert out["methods"]["cross_run"]["verdict"] == "inconclusive"


# --- seam hygiene ------------------------------------------------------------

def test_no_frontier_cli_import():
    # The seam stays injected: this worker must never import the subprocess
    # module itself (hermeticity + parallel-build file disjointness).
    import workers.frontier_review as mod
    src = Path(mod.__file__).read_text()
    assert not any(l.startswith(("import agent_wrapper", "from agent_wrapper"))
                   for l in src.splitlines())


def test_timeout_env_override(monkeypatch):
    monkeypatch.setenv("FRONTIER_REVIEW_TIMEOUT_S", "17")
    seen = {}
    def invoke(vendor, prompt, *, timeout_s, role, ledger_path=None):
        seen["timeout_s"] = timeout_s
        return _record(_verdict_json("pass"))
    fr.review_role("methods_reviewer", CANDIDATE, invoke)
    assert seen["timeout_s"] == 17
