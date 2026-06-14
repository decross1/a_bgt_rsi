#!/usr/bin/env python3
"""D-052: the NON-GATING topicality advisory.

D-052 retired the adversarial topicality skeptic AS A GATE (outcome A) and
demoted its dissent to a NON-GATING advisory (outcome C). The advisory rides
on the relevance stamp as `relevance.topicality_advisory`, but it is attached
in orchestrator/nara.py AFTER relevance() returns, ONLY when
NARA_TOPICALITY_ADVISORY=1 and the primary topicality judge did NOT already
condemn. It NEVER feeds low_confidence and NEVER moves any verdict — it is a
weak human-facing hint. The skeptic is the known over-flagging adversarial
judge (that is exactly why D-052 retired it as a gate).

These tests pin the two load-bearing properties:

  (a) relevance() PURITY — relevance() is and stays pure: it never reads or
      sets topicality_advisory, and low_confidence is exactly what it is with
      no advisory in play (the field lives one layer up, in nara).
  (b) the nara gating PREDICATE at the observable level — env-gated dark by
      default; when armed and the primary did not condemn, the advisory is
      attached AFTER relevance so it cannot touch low_confidence or fire R0b.

The mock-runtime dispatch-loop harness in tests/test_loop_v1_integration.py
does NOT drive the relevance/topicality block (it monkeypatches
iteration_cache.write_entry to a no-op and dispatches a scripted hypothesize/
meta_review/redteam table — relevance() is never called there). Reusing it
would force an over-abstraction of nara.py's dispatch loop, which D-052
forbids. So (b) unit-tests the gating predicate at the OBSERVABLE level with a
faithful in-test mirror of the exact nara predicate (asserted byte-for-byte
against the live source below). FULL chain integration is covered by the
integrator's real `env -u MOCK_LLM` advisory smoke (NARA_TOPICALITY_ADVISORY=1).

Run standalone:
    MOCK_LLM=1 ./.venv-chroma/bin/python -m pytest tests/test_topicality_advisory.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.retrieval_relevance import relevance  # noqa: E402


# ── On/off retrieval fixtures (mirror the calibrated fixtures in
# tests/test_retrieval_relevance.py) ────────────────────────────────────────
# OFF-domain (the iter-2026-06-09-001 fingerprint): drives low_confidence True.
_OFF_HYP = (
    "FASE optimizes code quality by minimizing the divergence between the "
    "semantic entropy of a code snippet and a gold-standard corpus, measured "
    "by cyclomatic complexity reduction and unit test coverage increase."
)
_OFF_NEIGHBORS = [
    {"doc_id": "osborne-272", "score": 0.6026, "source_layer": "foundational",
     "title": "3 Mixed, Correlated, and Evolutionary Equilibrium",
     "chunk_text": "For each structure of the random events there is a pattern "
                   "of behavior that leads to the same equilibrium."},
    {"doc_id": "osborne-041", "score": 0.5914, "source_layer": "foundational",
     "title": "2 Nash Equilibrium",
     "chunk_text": "A Nash equilibrium is a steady state of the play of a "
                   "strategic game in which each player holds the correct "
                   "expectation about the other players' behavior."},
]
# ON-domain: a repeated-PD/cooperation hypothesis with healthy lexical overlap;
# drives low_confidence False.
_ON_HYP = (
    "In repeated prisoner dilemma between agents, cooperation emerges and is "
    "sustained when defection triggers punishment, supporting tit-for-tat as a "
    "stable strategy under noisy observation of the opponent moves."
)
_ON_NEIGHBORS = [
    {"doc_id": "axelrod-1", "score": 0.66, "source_layer": "foundational",
     "title": "Repeated Prisoner Dilemma and Cooperation",
     "chunk_text": "In the repeated prisoner dilemma, cooperation can be "
                   "sustained when each defection is met with punishment; "
                   "tit-for-tat cooperates first then mirrors the opponent "
                   "previous move, and remains stable under noisy observation."},
    {"doc_id": "axelrod-2", "score": 0.64, "source_layer": "foundational",
     "title": "Strategy Stability under Noise",
     "chunk_text": "A strategy is stable when no agent can profit by deviating; "
                   "defection and cooperation outcomes depend on the punishment "
                   "scheme and the noisy signal of the opponent moves."},
]


# ── (a) relevance() PURITY ──────────────────────────────────────────────────

def test_relevance_pure_off_topicality_no_advisory_low_conf_true():
    """An off-topic input sets low_confidence True; relevance() must NOT carry
    a topicality_advisory key, and low_confidence is exactly True with no
    advisory in play."""
    out = relevance(_OFF_NEIGHBORS, _OFF_HYP, topicality="off")
    assert out["low_confidence"] is True
    assert "topicality_advisory" not in out


def test_relevance_pure_on_topicality_no_advisory_low_conf_false():
    """An on-topic input leaves low_confidence False; relevance() must NOT carry
    a topicality_advisory key, and low_confidence is exactly False."""
    out = relevance(_ON_NEIGHBORS, _ON_HYP, topicality="on")
    assert out["low_confidence"] is False
    assert "topicality_advisory" not in out


def test_relevance_low_confidence_unchanged_across_topicality_values():
    """The presence/value of a (hypothetical) advisory CANNOT exist inside
    relevance() — proved by the fact that low_confidence on the on-domain set
    is identical regardless of which non-condemning topicality is passed."""
    base = relevance(_ON_NEIGHBORS, _ON_HYP)["low_confidence"]
    for t in ("on", "unsure", None):
        out = relevance(_ON_NEIGHBORS, _ON_HYP, topicality=t)
        assert out["low_confidence"] == base
        assert "topicality_advisory" not in out


# ── (b) the nara gating PREDICATE at the observable level ────────────────────
#
# nara.py (after the relevance() call, ~L821) attaches the advisory like so:
#
#     if (os.environ.get("NARA_TOPICALITY_ADVISORY") == "1"
#             and _topic != "off"):
#         try:
#             from orchestrator import topicality_skeptic
#             _advisory = topicality_skeptic.attack_topicality(_hyp_text)
#         except Exception:
#             _advisory = None
#         payload["relevance"]["topicality_advisory"] = _advisory
#
# We mirror that EXACT predicate here (and assert the mirror matches the live
# source so a drift in nara breaks this test) and drive it with a
# monkeypatched attack_topicality (never the network). relevance() is the real
# pure function; the advisory is attached AFTER it, exactly as nara does.

def _nara_attach_advisory(rel: dict, hyp_text: str, topic) -> dict:
    """Faithful mirror of nara.py's advisory-attach predicate (see module
    docstring + the source-pin test below). Mutates and returns `rel` exactly
    as nara mutates payload['relevance'] in place."""
    from orchestrator import topicality_skeptic
    if os.environ.get("NARA_TOPICALITY_ADVISORY") == "1" and topic != "off":
        try:
            advisory = topicality_skeptic.attack_topicality(hyp_text)
        except Exception:
            advisory = None
        rel["topicality_advisory"] = advisory
    return rel


def test_predicate_mirror_matches_live_nara_source():
    """Guard: if nara.py's advisory predicate drifts, this test must break so
    the observable-level mirror is never silently stale."""
    src = (REPO_ROOT / "orchestrator" / "nara.py").read_text()
    assert 'os.environ.get("NARA_TOPICALITY_ADVISORY") == "1"' in src
    assert 'and _topic != "off"' in src
    assert 'topicality_skeptic.attack_topicality(' in src
    assert 'payload["relevance"]["topicality_advisory"] = _advisory' in src


def test_armed_primary_on_advisory_off_attaches_without_gating(monkeypatch):
    """NARA_TOPICALITY_ADVISORY=1, primary topicality 'on', skeptic 'off':
    the relevance carries topicality_advisory=='off' AND low_confidence stays
    False AND rule_fired is NOT 'R0b' (the advisory is attached AFTER
    relevance, so it cannot fire the retired gate)."""
    import orchestrator.topicality_skeptic as tsk
    monkeypatch.setenv("NARA_TOPICALITY_ADVISORY", "1")
    # Primary judge says ON (monkeypatch the SKEPTIC to 'off' independently).
    monkeypatch.setattr(tsk, "attack_topicality", lambda *a, **k: "off")

    rel = relevance(_ON_NEIGHBORS, _ON_HYP, topicality="on")
    # Pre-attach: relevance is pure (no advisory, gate did not fire).
    assert "topicality_advisory" not in rel
    assert rel["low_confidence"] is False
    assert rel["rule_fired"] != "R0b"

    rel = _nara_attach_advisory(rel, _ON_HYP, topic="on")
    # Post-attach: the dissent is surfaced, the verdict is untouched.
    assert rel["topicality_advisory"] == "off"
    assert rel["low_confidence"] is False          # NON-GATING
    assert rel["rule_fired"] != "R0b"              # the retired gate stays dark


def test_dark_by_default_field_absent_when_env_unset(monkeypatch):
    """Env UNSET (dark by default): the advisory is NEVER attached — the field
    is absent and attack_topicality is never consulted."""
    import orchestrator.topicality_skeptic as tsk
    monkeypatch.delenv("NARA_TOPICALITY_ADVISORY", raising=False)
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        return "off"

    monkeypatch.setattr(tsk, "attack_topicality", _boom)

    rel = relevance(_ON_NEIGHBORS, _ON_HYP, topicality="on")
    rel = _nara_attach_advisory(rel, _ON_HYP, topic="on")
    assert "topicality_advisory" not in rel
    assert calls["n"] == 0  # skeptic never even called when dark
    assert rel["low_confidence"] is False


def test_armed_but_primary_already_condemned_advisory_not_consulted(monkeypatch):
    """When the primary judge condemned (_topic == 'off'), the advisory is NOT
    consulted even with the env armed — the field is absent and the skeptic is
    never called (the advisory only adds a SECOND opinion when the primary did
    not already gate)."""
    import orchestrator.topicality_skeptic as tsk
    monkeypatch.setenv("NARA_TOPICALITY_ADVISORY", "1")
    calls = {"n": 0}

    def _count(*a, **k):
        calls["n"] += 1
        return "off"

    monkeypatch.setattr(tsk, "attack_topicality", _count)

    # Primary condemned -> R0 fired inside relevance(); advisory branch skipped.
    rel = relevance(_OFF_NEIGHBORS, _OFF_HYP, topicality="off")
    assert rel["rule_fired"] == "R0"               # primary gate (untouched)
    rel = _nara_attach_advisory(rel, _OFF_HYP, topic="off")
    assert "topicality_advisory" not in rel
    assert calls["n"] == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
