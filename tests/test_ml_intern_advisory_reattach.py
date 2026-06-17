#!/usr/bin/env python3
"""D-052 known-gap close: re-attach the NON-GATING topicality advisory on the
ml_intern RE-RETRIEVAL path.

D-052 (commit a30f58f) demoted the adversarial topicality skeptic to a
NON-GATING advisory (`relevance.topicality_advisory`, dark behind
NARA_TOPICALITY_ADVISORY). The primary attach site in orchestrator/nara.py
(~L821-829, after the first-pass relevance() call) was wired. But the D-052
commit named one minor gap verbatim:

    "Known minor gap: the ml_intern re-retrieval path does not re-attach the
     advisory (dark-by-default edge case)."

When ml_intern escalation backfills topic papers and the orchestrator
RE-DISPATCHES retrieve_literature, nara recomputes relevance into
`re_ret['result']['relevance']` (~L968-973) and then caches it — but it does
NOT re-attach the advisory there. So an escalated (ml_intern-augmented)
iteration's recorded relevance silently lacks the advisory even when armed.

This test pins the SECOND attach site. It uses the same observable-level mirror
strategy as tests/test_topicality_advisory.py: relevance() is the real pure
function, the advisory is attached AFTER it by a faithful in-test mirror of the
re-retrieval predicate, and a source-pin asserts the live nara line exists so a
drift breaks the test. The mirror targets `re_ret['result']['relevance']` (the
DISTINCT re-retrieval line) — NOT the primary `payload['relevance']` line that
tests/test_topicality_advisory.py already pins.

The load-bearing properties, identical to the primary site:
  - armed + primary did not condemn (_topic != "off") -> the re-retrieval
    relevance carries topicality_advisory AND low_confidence is unchanged
    (NON-GATING) AND rule_fired is not the retired R0b gate;
  - dark by default (env unset) -> field absent, skeptic never consulted;
  - primary already condemned (_topic == "off") -> advisory not consulted.

Run standalone:
    MOCK_LLM=1 ./.venv-chroma/bin/python -m pytest tests/test_ml_intern_advisory_reattach.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.retrieval_relevance import relevance  # noqa: E402


# ── Retrieval fixtures (reuse the calibrated on/off fingerprints) ────────────
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


# ── Faithful mirror of nara's RE-RETRIEVAL advisory-attach predicate ─────────
#
# The integrator inserts this block in orchestrator/nara.py between the
# re-computed relevance() assignment (re_ret['result']['relevance'] = ...,
# ends ~L973) and iteration_cache.write_entry (~L974), at the indentation of
# the enclosing `if mi_ok: -> if (isinstance(re_ret, dict) ...)` branch:
#
#     if (os.environ.get("NARA_TOPICALITY_ADVISORY") == "1"
#             and _topic != "off"):
#         try:
#             from orchestrator import topicality_skeptic
#             _advisory = topicality_skeptic.attack_topicality(_hyp_text)
#         except Exception:
#             _advisory = None
#         re_ret["result"]["relevance"]["topicality_advisory"] = _advisory
#
# `re_ret`, `_hyp_text`, and `_topic` are all in scope at the insertion point
# (recomputed at ~L965-967); `os` is module-imported (L23); topicality_skeptic
# is lazy-imported as at the primary site (L824).

def _nara_reattach_advisory(re_ret: dict, hyp_text: str, topic) -> dict:
    """Faithful mirror of nara.py's RE-RETRIEVAL advisory predicate. Mutates
    re_ret['result']['relevance'] in place exactly as nara does, and returns
    re_ret."""
    from orchestrator import topicality_skeptic
    if os.environ.get("NARA_TOPICALITY_ADVISORY") == "1" and topic != "off":
        try:
            advisory = topicality_skeptic.attack_topicality(hyp_text)
        except Exception:
            advisory = None
        re_ret["result"]["relevance"]["topicality_advisory"] = advisory
    return re_ret


def _make_re_ret(neighbors, hyp_text, topic):
    """Build a re_ret-shaped envelope with relevance computed by the real pure
    relevance(), mirroring nara.py:961-973."""
    return {
        "status": "passed",
        "result": {
            "neighbors": neighbors,
            "relevance": relevance(neighbors, hyp_text, topicality=topic),
        },
    }


def test_reattach_source_pin_present_in_live_nara():
    """Guard: the re-retrieval re-attach line must exist in nara.py so this
    observable-level mirror is never silently stale once the integrator lands
    the spine edit. Targets the DISTINCT re_ret[...] line (NOT the primary
    payload['relevance'] line, which tests/test_topicality_advisory.py pins)."""
    src = (REPO_ROOT / "orchestrator" / "nara.py").read_text()
    assert 'os.environ.get("NARA_TOPICALITY_ADVISORY") == "1"' in src
    assert 'topicality_skeptic.attack_topicality(' in src
    # The distinct re-retrieval attach line (NOT payload["relevance"][...]):
    assert 're_ret["result"]["relevance"]["topicality_advisory"] = _advisory' in src


def test_armed_primary_on_reattaches_without_gating(monkeypatch):
    """NARA_TOPICALITY_ADVISORY=1, primary topicality 'on', skeptic 'off':
    the re-retrieval relevance carries topicality_advisory=='off' AND
    low_confidence stays False (NON-GATING) AND rule_fired is NOT 'R0b'."""
    import orchestrator.topicality_skeptic as tsk
    monkeypatch.setenv("NARA_TOPICALITY_ADVISORY", "1")
    monkeypatch.setattr(tsk, "attack_topicality", lambda *a, **k: "off")

    re_ret = _make_re_ret(_ON_NEIGHBORS, _ON_HYP, topic="on")
    rel = re_ret["result"]["relevance"]
    # Pre-attach: relevance is pure (no advisory, gate did not fire).
    assert "topicality_advisory" not in rel
    assert rel["low_confidence"] is False
    assert rel["rule_fired"] != "R0b"

    re_ret = _nara_reattach_advisory(re_ret, _ON_HYP, topic="on")
    rel = re_ret["result"]["relevance"]
    # Post-attach: the dissent is surfaced on the RE-RETRIEVAL stamp, untouched verdict.
    assert rel["topicality_advisory"] == "off"
    assert rel["low_confidence"] is False          # NON-GATING
    assert rel["rule_fired"] != "R0b"              # retired gate stays dark


def test_reattach_dark_by_default_field_absent(monkeypatch):
    """Env UNSET (dark by default): the advisory is NEVER re-attached on the
    re-retrieval path — field absent, attack_topicality never consulted."""
    import orchestrator.topicality_skeptic as tsk
    monkeypatch.delenv("NARA_TOPICALITY_ADVISORY", raising=False)
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        return "off"

    monkeypatch.setattr(tsk, "attack_topicality", _boom)

    re_ret = _make_re_ret(_ON_NEIGHBORS, _ON_HYP, topic="on")
    re_ret = _nara_reattach_advisory(re_ret, _ON_HYP, topic="on")
    rel = re_ret["result"]["relevance"]
    assert "topicality_advisory" not in rel
    assert calls["n"] == 0                          # skeptic never called when dark
    assert rel["low_confidence"] is False


def test_reattach_primary_condemned_not_consulted(monkeypatch):
    """When the primary judge condemned (_topic == 'off'), the re-retrieval
    advisory is NOT consulted even with the env armed — field absent, skeptic
    never called (the advisory only adds a SECOND opinion when the primary did
    not already gate)."""
    import orchestrator.topicality_skeptic as tsk
    monkeypatch.setenv("NARA_TOPICALITY_ADVISORY", "1")
    calls = {"n": 0}

    def _count(*a, **k):
        calls["n"] += 1
        return "off"

    monkeypatch.setattr(tsk, "attack_topicality", _count)

    re_ret = _make_re_ret(_OFF_NEIGHBORS, _OFF_HYP, topic="off")
    assert re_ret["result"]["relevance"]["rule_fired"] == "R0"  # primary gate untouched
    re_ret = _nara_reattach_advisory(re_ret, _OFF_HYP, topic="off")
    rel = re_ret["result"]["relevance"]
    assert "topicality_advisory" not in rel
    assert calls["n"] == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
