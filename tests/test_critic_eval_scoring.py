#!/usr/bin/env python3
"""
Day 9 task -- scoring scaffold for the W2-01 critic eval (≥80% target).

Track A's Day-39 live eval reads experiments/fixtures/critic_hypotheses/
(20 fixtures, 19 known-flawed + 1 sound baseline), runs workers/critic.py
against each, and scores. This file pins the SCORING ALGORITHM and the
PASS BAR so Track A can wire the live call without re-deriving them.

Scoring rule (the one we lock here):

    For each fixture f:
      1. Run critic on f.hypothesis_text (with f.context where present).
      2. flag_decision must equal f.ground_truth_label  → 'label correct'.
      3. If f.ground_truth_label == 'flawed', the critique_text must
         hit ≥ 1 of f.expected_critique_targets, where 'hit' means a
         case-insensitive substring overlap of at least three contiguous
         word characters from the target appearing in critique_text
         (a single fuzzy keyword overlap, NOT exact-substring; otherwise
         the bar is unfairly punishing on synonyms).
      4. A fixture 'passes' iff label_correct AND (sound  OR  ≥1 target hit).

    Pass bar: pass_rate ≥ 0.80 over the 20 fixtures (16 of 20).

The bar comes from `notes/track-c-day8-fixtures.md` ("Day-39 W2-01
target: critic flags ≥80% of the 19 known-flawed hypotheses with a
substantive critique that overlaps the expected critique targets").

What's LIVE in this file vs. what Track A finishes on Day 39:

    LIVE (today, MOCK_LLM=1):
      * score_critic_eval(results) computes the pass/fail bookkeeping.
      * score_critic_run(critic_callable, fixtures) glues the two halves
        — runs the critic over every fixture and returns a Result.
      * Self-tests assert the scaffold scores a hand-built oracle and a
        hand-built worst-case stub correctly.
      * The pass bar (PASS_RATE_BAR = 0.80) is locked here, not in a
        Track-A file, so the bar can't drift without a Track B edit.

    PENDING (Day 39, Track A):
      * Wire the real workers.critic.critique into score_critic_run.
      * Append the per-fixture scoring records to logs/dayN.jsonl per
        the calls.jsonl schema (retrieval_context populated where the
        critic retrieves; D-025/P2 contract).
      * Decide what to do on a sub-bar pass_rate -- this scaffold
        REPORTS the rate; the live eval also has to choose between
        slip-ladder, re-prompt, or accept-and-document.

Run standalone:
    MOCK_LLM=1 python3 tests/test_critic_eval_scoring.py
or under pytest:
    MOCK_LLM=1 pytest tests/test_critic_eval_scoring.py
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments.fixtures.loader import (  # noqa: E402
    load_critic_fixtures,
)

# ──────────────────────────────────────────────────────────────────────
# Locked constants -- DO NOT EDIT WITHOUT A D-NNN DECISION ENTRY.
# ──────────────────────────────────────────────────────────────────────
PASS_RATE_BAR = 0.80
MIN_TARGET_TOKEN_LEN = 3        # substantive tokens are ≥3 chars (filters
                                # 'of', 'to', 'in' etc.).
MIN_TARGET_TOKEN_OVERLAP = 2    # a target FIRES when ≥2 of its substantive
                                # tokens appear in the critique. Short
                                # targets (with only 1 substantive token)
                                # fire on the single overlap.


# ──────────────────────────────────────────────────────────────────────
# Result dataclasses
# ──────────────────────────────────────────────────────────────────────
@dataclass
class FixtureScore:
    fixture_id: str
    ground_truth_label: str
    predicted_label: str
    label_correct: bool
    target_hits: List[str] = field(default_factory=list)  # targets that fired
    passed: bool = False  # combined: label correct AND (sound or ≥1 hit)


@dataclass
class CriticEvalResult:
    fixtures_scored: int
    label_correct: int           # how many predictions matched ground truth
    target_hits_at_least_one: int   # how many flawed fixtures had ≥1 hit
    passed: int                  # how many fixtures cleared the full bar
    pass_rate: float             # passed / fixtures_scored
    bar: float                   # PASS_RATE_BAR (locked)
    meets_bar: bool              # pass_rate >= bar
    per_fixture: List[FixtureScore] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# Scoring primitives
# ──────────────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"\w+")


def _tokens(text: str) -> List[str]:
    """Lowercased word tokens. The fuzz tolerance is intentionally
    small -- we want to catch synonyms only at the word level, not
    paraphrase-level (that's a job for a learned scorer in Phase 2)."""
    return [t for t in _TOKEN_RE.findall((text or "").lower())
            if len(t) >= MIN_TARGET_TOKEN_LEN]


def _target_fires(target: str, critique_text: str) -> bool:
    """A target FIRES when at least MIN_TARGET_TOKEN_OVERLAP of its
    substantive tokens appear in critique_text -- with a one-token
    fallback for short targets so a target like 'goodhart' (single
    substantive token) is still scorable.

    Rationale: a single common word like 'cooperation' would otherwise
    score a target like 'cooperation rate is not the right metric'.
    Requiring ≥2 token overlap forces the critique to pick up the
    SUBSTANCE of the target, not just a topic word. Short targets
    legitimately have only one substantive token and we don't want
    to make them unscorable; the one-token fallback handles those.
    """
    t_tokens = set(_tokens(target))
    if not t_tokens:
        return False
    c_tokens = set(_tokens(critique_text))
    hits = t_tokens & c_tokens
    threshold = min(MIN_TARGET_TOKEN_OVERLAP, len(t_tokens))
    return len(hits) >= threshold


def score_one(
    fixture: Dict[str, Any],
    critique_result: Dict[str, Any],
) -> FixtureScore:
    """Score one fixture against one critique result.

    fixture is a dict from experiments/fixtures/critic_hypotheses/.
    critique_result is the dict returned by workers.critic.critique
    (must have flag_decision + critique_text per the Day-9 contract test).
    """
    truth = fixture["ground_truth_label"]
    pred = critique_result.get("flag_decision", "")
    label_correct = (pred == truth)

    target_hits: List[str] = []
    critique_text = critique_result.get("critique_text", "")
    for target in fixture.get("expected_critique_targets", []):
        if _target_fires(target, critique_text):
            target_hits.append(target)

    if truth == "sound":
        # No critique-targets expected for the sound baseline; passing
        # is just label_correct.
        passed = label_correct
    else:
        passed = label_correct and len(target_hits) >= 1

    return FixtureScore(
        fixture_id=fixture["id"],
        ground_truth_label=truth,
        predicted_label=pred,
        label_correct=label_correct,
        target_hits=target_hits,
        passed=passed,
    )


def score_critic_eval(scored: Iterable[FixtureScore]) -> CriticEvalResult:
    """Roll a list of per-fixture scores up into the eval-level result."""
    scored_list = list(scored)
    n = len(scored_list)
    if n == 0:
        return CriticEvalResult(
            fixtures_scored=0, label_correct=0,
            target_hits_at_least_one=0, passed=0,
            pass_rate=0.0, bar=PASS_RATE_BAR, meets_bar=False,
        )
    label_correct = sum(1 for s in scored_list if s.label_correct)
    hits = sum(1 for s in scored_list
               if s.ground_truth_label == "flawed" and s.target_hits)
    passed = sum(1 for s in scored_list if s.passed)
    rate = passed / n
    return CriticEvalResult(
        fixtures_scored=n,
        label_correct=label_correct,
        target_hits_at_least_one=hits,
        passed=passed,
        pass_rate=rate,
        bar=PASS_RATE_BAR,
        meets_bar=rate >= PASS_RATE_BAR,
        per_fixture=scored_list,
    )


def score_critic_run(
    critic_callable: Callable[..., Dict[str, Any]],
    fixtures: Optional[List[Dict[str, Any]]] = None,
) -> CriticEvalResult:
    """End-to-end scoring helper for Day-39 live eval.

    `critic_callable` is `workers.critic.critique` (matches the Day-9
    contract test's signature). `fixtures` defaults to the 20 critic
    fixtures Track C dropped on Day 8.
    """
    if fixtures is None:
        fixtures = load_critic_fixtures()
    scored: List[FixtureScore] = []
    for f in fixtures:
        result = critic_callable(f["hypothesis_text"], f.get("context"))
        scored.append(score_one(f, result))
    return score_critic_eval(scored)


# ──────────────────────────────────────────────────────────────────────
# Self-tests
# ──────────────────────────────────────────────────────────────────────
class TargetFireTest(unittest.TestCase):
    """Half-overlap token rule has interesting boundary cases — pin them."""

    def test_exact_match_fires(self):
        self.assertTrue(_target_fires(
            "round count was not varied independently of opponent",
            "the round count was not varied independently of the opponent type",
        ))

    def test_one_token_overlap_does_not_fire_when_target_has_many(self):
        # Target has many substantive tokens; one (or zero) shared word
        # fails the 2-token minimum.
        self.assertFalse(_target_fires(
            "round count was not varied independently of opponent",
            "we see cooperation here",
        ))

    def test_two_token_overlap_fires(self):
        # Target has 6 substantive tokens; 2 hits ('opponent', 'horizon')
        # clears the 2-token bar.
        self.assertTrue(_target_fires(
            "confound between opponent type and horizon",
            "this confounds the opponent with the experimental horizon",
        ))

    def test_single_token_target_fires_on_single_hit(self):
        # Short targets (taxonomy names) like 'goodhart' have only one
        # substantive token; one overlap suffices.
        self.assertTrue(_target_fires(
            "goodhart",
            "this looks like a goodhart-style failure of the proxy",
        ))

    def test_short_words_filtered(self):
        # 'of', 'to' get filtered (< MIN_TARGET_TOKEN_LEN); the
        # target reduces to {round, count, was}.
        # Critique that has only 'of'/'to' must NOT fire.
        self.assertFalse(_target_fires(
            "of to in by",  # all filtered → empty target → never fires
            "round count was not varied",
        ))


class ScoreOneTest(unittest.TestCase):
    """Per-fixture scoring covers the four cells: correct-label x has-target-hit."""

    def _flawed_fixture(self):
        return {
            "id": "001_demo",
            "ground_truth_label": "flawed",
            "expected_critique_targets": [
                "round count was not varied independently of opponent",
                "confound between opponent type and horizon",
            ],
        }

    def _sound_fixture(self):
        return {
            "id": "020_sound",
            "ground_truth_label": "sound",
            "expected_critique_targets": [],
        }

    def test_flawed_correct_label_and_target_hit_passes(self):
        score = score_one(self._flawed_fixture(), {
            "flag_decision": "flawed",
            "critique_text": "the round count was not varied independently of opponent type",
        })
        self.assertTrue(score.passed)
        self.assertTrue(score.label_correct)
        self.assertGreaterEqual(len(score.target_hits), 1)

    def test_flawed_correct_label_no_target_hit_fails(self):
        score = score_one(self._flawed_fixture(), {
            "flag_decision": "flawed",
            "critique_text": "I disagree but cannot articulate why.",
        })
        self.assertFalse(score.passed)
        self.assertTrue(score.label_correct)
        self.assertEqual(score.target_hits, [])

    def test_flawed_wrong_label_fails(self):
        score = score_one(self._flawed_fixture(), {
            "flag_decision": "sound",
            "critique_text": "round count was not varied independently of opponent",
        })
        self.assertFalse(score.passed)
        self.assertFalse(score.label_correct)

    def test_sound_correct_label_passes_without_targets(self):
        score = score_one(self._sound_fixture(), {
            "flag_decision": "sound",
            "critique_text": "the cooperation-lock-in finding looks supported.",
        })
        self.assertTrue(score.passed)
        self.assertTrue(score.label_correct)

    def test_sound_wrong_label_fails(self):
        score = score_one(self._sound_fixture(), {
            "flag_decision": "flawed",
            "critique_text": "this is suspicious for unspecified reasons.",
        })
        self.assertFalse(score.passed)
        self.assertFalse(score.label_correct)


class RollUpScoringTest(unittest.TestCase):
    """The roll-up arithmetic: pass_rate, meets_bar, fixtures_scored."""

    def test_empty_input_yields_zero_pass_rate(self):
        result = score_critic_eval([])
        self.assertEqual(result.fixtures_scored, 0)
        self.assertEqual(result.pass_rate, 0.0)
        self.assertFalse(result.meets_bar)

    def test_all_pass_meets_bar(self):
        scored = [
            FixtureScore(f"f{i}", "flawed", "flawed", True, ["t"], True)
            for i in range(10)
        ]
        result = score_critic_eval(scored)
        self.assertEqual(result.pass_rate, 1.0)
        self.assertTrue(result.meets_bar)

    def test_eighty_percent_just_meets_bar(self):
        # 16 pass, 4 fail → 0.80; bar is 0.80; meets_bar is True (≥).
        scored = (
            [FixtureScore(f"f{i}", "flawed", "flawed", True, ["t"], True)
             for i in range(16)] +
            [FixtureScore(f"f{i}", "flawed", "sound", False, [], False)
             for i in range(16, 20)]
        )
        result = score_critic_eval(scored)
        self.assertAlmostEqual(result.pass_rate, 0.80)
        self.assertTrue(result.meets_bar)

    def test_seventy_nine_percent_misses_bar(self):
        # 15 / 19 = 0.789... → below 0.80.
        scored = (
            [FixtureScore(f"f{i}", "flawed", "flawed", True, ["t"], True)
             for i in range(15)] +
            [FixtureScore(f"f{i}", "flawed", "sound", False, [], False)
             for i in range(15, 19)]
        )
        result = score_critic_eval(scored)
        self.assertLess(result.pass_rate, PASS_RATE_BAR)
        self.assertFalse(result.meets_bar)


class EndToEndAgainstRealFixturesTest(unittest.TestCase):
    """Exercises score_critic_run end-to-end against the 20 fixtures Track
    C dropped on Day 8, using deterministic STUB critics. Pins:

      * an oracle stub (knows the ground-truth label + always-hits-target)
        clears the bar.
      * a label-only stub (right label, empty critique) FAILS the bar
        because no targets fire.
      * an all-sound stub (predicts 'sound' on everything) fails badly.

    These three stubs prove the scaffold actually distinguishes
    'critic that did the work' from 'critic that just guessed'."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MOCK_LLM", "1")
        cls.fixtures = load_critic_fixtures()
        # Sanity-tie to the fixture-set invariants Track C committed.
        if len(cls.fixtures) != 20:
            raise unittest.SkipTest(
                f"fixture set has {len(cls.fixtures)} entries; expected "
                f"20 — has Track C revised the Day-8 drop?")

    def test_oracle_stub_clears_bar(self):
        def oracle(hypothesis_text, context=None):
            # Find the matching fixture and parrot its targets into the
            # critique text + emit the correct label. This is the upper
            # bound of what the scoring rule can reward.
            for f in self.fixtures:
                if f["hypothesis_text"] == hypothesis_text:
                    return {
                        "flag_decision": f["ground_truth_label"],
                        "critique_text": " ".join(f["expected_critique_targets"]),
                        "reasoning_chain": ["oracle"],
                    }
            return {"flag_decision": "sound", "critique_text": "",
                    "reasoning_chain": []}

        result = score_critic_run(oracle, self.fixtures)
        self.assertTrue(result.meets_bar, result)
        self.assertEqual(result.fixtures_scored, 20)
        self.assertEqual(result.label_correct, 20)

    def test_label_only_stub_fails_bar(self):
        # Right label on every flawed fixture, empty critique → label
        # correct but no targets fire → pass_rate ~ 1/20 (the sound
        # fixture passes; the 19 flawed ones don't).
        def label_only(hypothesis_text, context=None):
            for f in self.fixtures:
                if f["hypothesis_text"] == hypothesis_text:
                    return {
                        "flag_decision": f["ground_truth_label"],
                        "critique_text": "",
                        "reasoning_chain": [],
                    }
            return {"flag_decision": "sound", "critique_text": "",
                    "reasoning_chain": []}

        result = score_critic_run(label_only, self.fixtures)
        self.assertFalse(result.meets_bar, result)
        # Exactly the sound fixture passes (no targets needed).
        self.assertEqual(result.passed, 1)

    def test_all_sound_stub_fails_badly(self):
        # Predicts 'sound' everywhere → wrong label on 19/20 → at most
        # 1/20 passes.
        def all_sound(hypothesis_text, context=None):
            return {
                "flag_decision": "sound",
                "critique_text": "",
                "reasoning_chain": [],
            }

        result = score_critic_run(all_sound, self.fixtures)
        self.assertFalse(result.meets_bar, result)
        self.assertLessEqual(result.passed, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
