"""Tests for workers/evidence_ladder.py — pure rung derivation.

Exhaustive rung-boundary table + the named non-coercion regression pins:
  - redteam fatal_flaw + critique survives NEVER reaches L1;
  - missing signal never passes a rung;
  - adversarial survived=False caps below L4.
Hermetic: no I/O, no network, no model calls.
"""
from __future__ import annotations

import pytest

from workers.evidence_ladder import derive_level, next_test_owed

# ── row builders (field shapes grounded in memory/loop_memory.jsonl) ─────


def _l1_row(**overrides) -> dict:
    """A row that has earned exactly L1."""
    row = {
        "iteration_id": "iter-2026-08-04-001",
        "retrieval": {
            "k": 10,
            "relevance": {"relevance": 0.41, "low_confidence": False,
                          "reason": "on-domain"},
        },
        "novelty": {"class": "novel", "rationale": "absent from corpus",
                    "low_confidence": False},
        "critique": {"verdict": "survives", "rationale": "no contradiction"},
    }
    row.update(overrides)
    return row


def _l2_row(**overrides) -> dict:
    row = _l1_row()
    row["experiment_outcome"] = {
        "experiment_id": "exp004_combinatorial_auction",
        "metric": "vcg_truthful_fraction",
        "value": 0.965,
        "summary": "VCG verdict=YES. 96.50% truthful.",
        "trials": 150,
    }
    row.update(overrides)
    return row


def _l3_row(**overrides) -> dict:
    row = _l2_row()
    row["cross_tier_comparison"] = {
        "claim": "replicates across auction complexity",
        "agreement": True,
    }
    row.update(overrides)
    return row


def _l4_row(**overrides) -> dict:
    row = _l3_row()
    row["redteam"] = {"verdict": "proceed", "critique": "no fatal issue"}
    row.update(overrides)
    return row


_ADV_OK = {"survived": True, "n_voting": 3, "n_refuted": 0}
_FEEDBACK_OK = {"iteration_id": "iter-2026-08-04-001", "verdict": "valid",
                "gated_by": "decross1"}


def derive(row, feedback=None, adversarial=None, health=None, admission=None):
    return derive_level(
        row, feedback, adversarial, health or [], admission_context=admission
    )


def _as_v2(row: dict) -> dict:
    row["campaign"] = {
        "schema_version": "research-campaign-link/v1",
        "campaign_id": "v2-test-campaign",
        "campaign_manifest_sha256": "a" * 64,
        "research_question_id": "rq-test",
        "research_question_sha256": "b" * 64,
        "topic_id": "topic-test",
        "topic_sha256": "c" * 64,
    }
    text = "Agents condition equilibrium play on a disclosed payoff signal."
    row["hypothesis"] = {
        "text": text,
        "candidates_considered": 1,
        "all_candidates": [text],
    }
    return row


# ── L0 / L1 boundary ─────────────────────────────────────────────────────


def test_empty_row_is_l0():
    out = derive({})
    assert out["level"] == "L0"
    assert out["missing_for_next"]  # L1 requirements enumerated
    assert out["provisional"] == []


def test_l1_earned_with_redteam_absent():
    out = derive(_l1_row())
    assert out["level"] == "L1"
    assert "experiment_outcome absent" in out["missing_for_next"]


def test_l1_earned_with_redteam_proceed():
    out = derive(_l1_row(redteam={"verdict": "proceed"}))
    assert out["level"] == "L1"


def test_v2_canonical_hypothesis_can_earn_l1():
    assert derive(_as_v2(_l1_row()))["level"] == "L1"


def test_literal_protocol_word_inside_a_claim_is_not_channel_leakage():
    row = _as_v2(_l1_row())
    text = "Agents receiving the literal token <think> defect more often."
    row["hypothesis"] = {"text": text, "candidates_considered": 1, "all_candidates": [text]}
    assert derive(row)["level"] == "L1"


@pytest.mark.parametrize(
    "hypothesis",
    [
        None,
        {"text": '{"candidates":["raw"', "candidates_considered": 1},
        {
            "text": "<think>private route</think> Public claim.",
            "candidates_considered": 1,
            "all_candidates": ["<think>private route</think> Public claim."],
        },
        {
            "text": "Selected claim.",
            "candidates_considered": 2,
            "all_candidates": ["Different claim."],
        },
        {
            "text": "x" * 1201,
            "candidates_considered": 1,
            "all_candidates": ["x" * 1201],
        },
        {
            "text": "Selected claim.",
            "candidates_considered": 2,
            "all_candidates": ["Selected claim.", "<analysis>private route</analysis>"],
        },
    ],
)
def test_v2_missing_raw_or_incoherent_hypothesis_cannot_earn_l1(hypothesis):
    row = _as_v2(_l1_row())
    if hypothesis is None:
        row.pop("hypothesis")
    else:
        row["hypothesis"] = hypothesis
    out = derive(row)
    assert out["level"] == "L0"
    assert any("V2 hypothesis" in note for note in out["missing_for_next"])


def test_missing_relevance_blocks_l1():
    out = derive(_l1_row(retrieval={"k": 10}))
    assert out["level"] == "L0"


def test_missing_retrieval_entirely_blocks_l1():
    row = _l1_row()
    del row["retrieval"]
    assert derive(row)["level"] == "L0"


def test_low_confidence_relevance_blocks_l1():
    row = _l1_row()
    row["retrieval"]["relevance"]["low_confidence"] = True
    assert derive(row)["level"] == "L0"


def test_relevance_low_confidence_missing_blocks_l1():
    # low_confidence key absent != low_confidence False — missing never passes.
    row = _l1_row()
    del row["retrieval"]["relevance"]["low_confidence"]
    assert derive(row)["level"] == "L0"


def test_novelty_rediscovery_blocks_l1():
    row = _l1_row()
    row["novelty"]["class"] = "rediscovery"
    assert derive(row)["level"] == "L0"


def test_novelty_missing_blocks_l1():
    row = _l1_row()
    del row["novelty"]
    assert derive(row)["level"] == "L0"


def test_critique_refuted_blocks_l1():
    row = _l1_row()
    row["critique"]["verdict"] = "refuted"
    assert derive(row)["level"] == "L0"


def test_critique_missing_blocks_l1():
    row = _l1_row()
    del row["critique"]
    assert derive(row)["level"] == "L0"


# ── the named regression pin: fatal_flaw caps below L1 ───────────────────


def test_fatal_flaw_plus_survives_never_reaches_l1():
    """REGRESSION PIN: redteam fatal_flaw + critique survives -> L0, always."""
    row = _l1_row(redteam={"verdict": "fatal_flaw", "critique": "circular"})
    out = derive(row)
    assert out["level"] == "L0"
    assert any("fatal_flaw" in r for r in out["reasons"])


def test_fatal_flaw_caps_l0_even_with_all_higher_evidence():
    row = _l4_row(redteam={"verdict": "fatal_flaw"})
    out = derive(row, feedback=_FEEDBACK_OK, adversarial=_ADV_OK)
    assert out["level"] == "L0"


# ── L2 boundary ──────────────────────────────────────────────────────────


def test_l2_earned_at_150_trials():
    assert derive(_l2_row())["level"] == "L2"


def test_l2_boundary_trials_exactly_30_passes():
    row = _l2_row()
    row["experiment_outcome"]["trials"] = 30
    assert derive(row)["level"] == "L2"


def test_l2_boundary_trials_29_fails():
    row = _l2_row()
    row["experiment_outcome"]["trials"] = 29
    out = derive(row)
    assert out["level"] == "L1"
    assert any("trials=29" in m for m in out["missing_for_next"])


def test_l2_trials_missing_fails():
    row = _l2_row()
    del row["experiment_outcome"]["trials"]
    assert derive(row)["level"] == "L1"


def test_l2_invalid_summary_fails():
    row = _l2_row()
    row["experiment_outcome"]["summary"] = "INVALID: harness crashed"
    assert derive(row)["level"] == "L1"


def test_l2_invalid_summary_case_insensitive():
    """2026-08-14 review regression: lowercase 'invalid' must also fail L2
    (the pre-D-059 gate was case-insensitive)."""
    for s in ("invalid: harness crashed", "Invalid run, Verdict=NO"):
        row = _l2_row()
        row["experiment_outcome"]["summary"] = s
        assert derive(row)["level"] == "L1", s


def test_l2_summary_missing_fails():
    row = _l2_row()
    del row["experiment_outcome"]["summary"]
    assert derive(row)["level"] == "L1"


def test_v2_plausible_outcome_and_self_asserted_flag_do_not_earn_l2():
    row = _as_v2(_l2_row())
    row["experiment_outcome"] = {
        "experiment_id": "forged",
        "metric": "forged",
        "value": 1,
        "trials": 30,
        "summary": "ok",
        "verified": True,
    }
    row["experiment_admission_ref"] = {"verified": True}
    out = derive(row, admission={"verified": True})
    assert out["level"] == "L1"
    assert out["missing_for_next"] == [
        "verified experiment admission absent for V2 outcome"
    ]


def test_v2_surprising_route_cannot_bootstrap_from_unadmitted_outcome():
    row = _as_v2(_l2_row())
    row["novelty"]["class"] = "unclear"
    row["experiment_outcome"]["summary"] = "Verdict=NO. Surprising result."
    out = derive(row)
    assert out["level"] == "L0"
    assert any("not surprising-vs-theory" in note for note in out["missing_for_next"])


# ── L3 boundary ──────────────────────────────────────────────────────────


def test_l3_earned_with_cross_tier_comparison():
    assert derive(_l3_row())["level"] == "L3"


def test_l3_absent_caps_at_l2():
    out = derive(_l2_row())
    assert out["level"] == "L2"
    assert any("cross_tier_comparison" in m for m in out["missing_for_next"])


def test_l3_empty_dict_is_missing():
    row = _l2_row(cross_tier_comparison={})
    assert derive(row)["level"] == "L2"


# ── L4 boundary ──────────────────────────────────────────────────────────


def test_l4_earned_survived_true_and_redteam_proceed():
    assert derive(_l4_row(), adversarial=_ADV_OK)["level"] == "L4"


def test_adversarial_survived_false_caps_below_l4():
    """REGRESSION PIN: survived=False caps below L4."""
    out = derive(_l4_row(), adversarial={"survived": False, "n_refuted": 2})
    assert out["level"] == "L3"


def test_adversarial_block_absent_caps_below_l4():
    assert derive(_l4_row())["level"] == "L3"


def test_redteam_absent_blocks_l4_even_with_adversarial_survival():
    # redteam absent is acceptable at L1 but NEVER passes the L4 rung.
    row = _l3_row()
    assert "redteam" not in row
    out = derive(row, adversarial=_ADV_OK)
    assert out["level"] == "L3"
    assert any("redteam" in m for m in out["missing_for_next"])


def test_redteam_revise_blocks_l4():
    row = _l4_row(redteam={"verdict": "revise"})
    assert derive(row, adversarial=_ADV_OK)["level"] == "L3"


# ── L5 boundary ──────────────────────────────────────────────────────────


def test_l5_earned_with_valid_feedback():
    out = derive(_l4_row(), feedback=_FEEDBACK_OK, adversarial=_ADV_OK)
    assert out["level"] == "L5"
    assert out["missing_for_next"] == []


def test_feedback_invalid_caps_at_l4():
    fb = dict(_FEEDBACK_OK, verdict="invalid")
    out = derive(_l4_row(), feedback=fb, adversarial=_ADV_OK)
    assert out["level"] == "L4"


def test_feedback_absent_caps_at_l4():
    assert derive(_l4_row(), adversarial=_ADV_OK)["level"] == "L4"


# ── no rung-skipping: higher evidence never rescues a failed lower rung ──


def test_experiment_cannot_skip_failed_l1():
    row = _l2_row()
    row["retrieval"]["relevance"]["low_confidence"] = True
    out = derive(row, feedback=_FEEDBACK_OK, adversarial=_ADV_OK)
    assert out["level"] == "L0"


def test_valid_feedback_cannot_skip_missing_experiment():
    out = derive(_l1_row(), feedback=_FEEDBACK_OK, adversarial=_ADV_OK)
    assert out["level"] == "L1"


# ── provisional: external_search_blind ───────────────────────────────────


def test_provisional_external_search_blind_on_matching_health_row():
    health = [{"signal": "ml_intern_zero_papers",
               "iteration_id": "iter-2026-08-04-001", "severity": "degraded"}]
    out = derive(_l1_row(), health=health)
    assert out["level"] == "L1"
    assert out["provisional"] == ["external_search_blind"]


def test_provisional_ignores_other_iterations_and_signals():
    health = [
        {"signal": "ml_intern_zero_papers", "iteration_id": "iter-other-999"},
        {"signal": "qwen_degraded_empty_content",
         "iteration_id": "iter-2026-08-04-001"},
    ]
    assert derive(_l1_row(), health=health)["provisional"] == []


# ── next_test_owed ───────────────────────────────────────────────────────


def test_next_test_owed_mapping():
    assert next_test_owed("L1") == "synthetic experiment"
    assert next_test_owed("L2") == "robustness battery"
    assert next_test_owed("L3") == "adversarial panel"
    assert next_test_owed("L4") == "human review"
    assert "literature" in next_test_owed("L0")
    assert next_test_owed("L5").startswith("none")


def test_next_test_owed_unknown_level_raises():
    with pytest.raises(ValueError):
        next_test_owed("L6")
    with pytest.raises(ValueError):
        next_test_owed("asserted")
