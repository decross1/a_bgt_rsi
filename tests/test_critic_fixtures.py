"""Tests for the Day-39 critic-eval fixture set.

Run:
    pytest tests/test_critic_fixtures.py -v

The fixtures live under experiments/fixtures/critic_hypotheses/. The
loader and schema constants live in experiments/fixtures/loader.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.fixtures.loader import (
    CRITIC_DIR,
    DOMAINS,
    FLAW_TAXONOMY,
    LABELS,
    NOVELTY_TIERS,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    SEVERITIES,
    load_critic_fixtures,
    load_novelty_fixtures,
    validate_fixture,
    validate_novelty_fixture,
)

EXPECTED_TOTAL = 20
EXPECTED_FLAWED = 19
EXPECTED_SOUND = 1


@pytest.fixture(scope="module")
def fixtures():
    return load_critic_fixtures()


def test_fixture_count(fixtures):
    assert len(fixtures) == EXPECTED_TOTAL, (
        f"expected {EXPECTED_TOTAL} fixtures for the Day-39 critic eval, "
        f"got {len(fixtures)}"
    )


def test_ground_truth_balance(fixtures):
    flawed = [f for f in fixtures if f["ground_truth_label"] == "flawed"]
    sound = [f for f in fixtures if f["ground_truth_label"] == "sound"]
    assert len(flawed) == EXPECTED_FLAWED
    assert len(sound) == EXPECTED_SOUND


def test_all_fixtures_validate(fixtures):
    failures = []
    for f in fixtures:
        errs = validate_fixture(f)
        if errs:
            failures.append((f.get("id", "<no-id>"), errs))
    assert not failures, "fixture validation errors: " + repr(failures)


def test_required_fields_present(fixtures):
    for f in fixtures:
        missing = REQUIRED_FIELDS - f.keys()
        assert not missing, f"{f.get('id')} missing fields {missing}"


def test_ids_unique_and_match_filename(fixtures):
    ids = [f["id"] for f in fixtures]
    assert len(ids) == len(set(ids)), "fixture ids are not unique"
    for path in CRITIC_DIR.glob("*.json"):
        data = json.loads(path.read_text())
        assert data["id"] == path.stem, (
            f"file {path.name} stem != id {data['id']!r}"
        )


def test_schema_version_uniform(fixtures):
    for f in fixtures:
        assert f["schema_version"] == SCHEMA_VERSION


def test_enum_fields_in_range(fixtures):
    for f in fixtures:
        assert f["domain"] in DOMAINS, f"{f['id']}: bad domain {f['domain']!r}"
        assert f["severity"] in SEVERITIES, f"{f['id']}: bad severity"
        assert f["ground_truth_label"] in LABELS
        assert f["injected_flaw_type"] in FLAW_TAXONOMY


def test_none_flaw_iff_sound(fixtures):
    for f in fixtures:
        is_none = f["injected_flaw_type"] == "none"
        is_sound = f["ground_truth_label"] == "sound"
        assert is_none == is_sound, (
            f"{f['id']}: injected_flaw_type=='none' must match "
            f"ground_truth_label=='sound'"
        )


def test_flaw_taxonomy_coverage(fixtures):
    """Every flaw category in FLAW_TAXONOMY must have ≥ 1 fixture, and
    every used flaw type must be in FLAW_TAXONOMY. This catches both
    drift (taxonomy entry with no example) and unauthorized additions
    (fixture using a flaw type not declared in the taxonomy).
    """
    used = {f["injected_flaw_type"] for f in fixtures}
    declared = set(FLAW_TAXONOMY)
    unused = declared - used
    undeclared = used - declared
    assert not undeclared, f"undeclared flaw types in fixtures: {undeclared}"
    assert not unused, (
        f"taxonomy entries with no fixture (add one or remove from "
        f"taxonomy): {unused}"
    )


def test_expected_critique_targets_nonempty(fixtures):
    for f in fixtures:
        targets = f["expected_critique_targets"]
        assert isinstance(targets, list)
        assert len(targets) >= 3, (
            f"{f['id']}: expected_critique_targets should have ≥3 entries "
            f"so the Day-39 eval can score critique substance"
        )
        for t in targets:
            assert isinstance(t, str) and t.strip(), (
                f"{f['id']}: critique-target entries must be non-empty strings"
            )


def test_domain_coverage(fixtures):
    """All four declared domains have at least one fixture."""
    used_domains = {f["domain"] for f in fixtures}
    assert used_domains == DOMAINS, (
        f"missing domain coverage: {DOMAINS - used_domains}"
    )


def test_severity_spread(fixtures):
    """The fixture set should span subtle, moderate, and obvious so the
    Day-39 eval can distinguish a critic that only catches the easy ones."""
    used_severities = {f["domain"]: 0 for f in fixtures}
    counts = {s: 0 for s in SEVERITIES}
    for f in fixtures:
        counts[f["severity"]] += 1
    for s in SEVERITIES:
        assert counts[s] >= 2, (
            f"need ≥2 fixtures of severity {s!r}; got {counts[s]}"
        )


def test_hypothesis_text_nontrivial(fixtures):
    """Hypothesis text should be substantial enough for the critic to
    engage with — short strings or boilerplate would defeat the eval."""
    for f in fixtures:
        text = f["hypothesis_text"]
        assert isinstance(text, str)
        assert len(text) >= 80, (
            f"{f['id']}: hypothesis_text too short ({len(text)} chars) "
            f"for a meaningful critic test"
        )


def test_flaw_description_internal_only(fixtures):
    """flaw_description is internal documentation; it must exist and be
    distinct from the hypothesis_text (i.e., the WHY-flawed cannot leak
    into what the critic sees)."""
    for f in fixtures:
        assert f["flaw_description"]
        assert f["flaw_description"] != f["hypothesis_text"]


def test_sound_baseline_is_the_day7_finding(fixtures):
    """The single sound fixture must be the Day-7 cooperation-lock-in,
    per the addendum's guidance to use it as the ground-truth-positive."""
    sound = [f for f in fixtures if f["ground_truth_label"] == "sound"]
    assert len(sound) == 1
    text = sound[0]["hypothesis_text"].lower()
    assert "cooperation" in text and "lock-in" in text


def test_no_json_parse_errors():
    """Every *.json file in the fixture dir must parse — guards against
    a corrupt commit landing a malformed fixture."""
    for path in CRITIC_DIR.glob("*.json"):
        try:
            json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            pytest.fail(f"{path.name} did not parse as JSON: {exc}")


def test_fixture_dir_has_no_extra_files():
    """Only *.json files are expected — anything else (stray .py, .bak,
    .swp) signals an accidental commit. README.md lives one level up."""
    extras = [p.name for p in CRITIC_DIR.iterdir() if p.suffix != ".json"]
    assert not extras, f"unexpected non-JSON files in fixture dir: {extras}"


# ─── Day-41 novelty-calibration fixtures (stretch deliverable) ────────


@pytest.fixture(scope="module")
def novelty_fixtures():
    return load_novelty_fixtures()


def test_novelty_fixture_count(novelty_fixtures):
    assert len(novelty_fixtures) == 10, (
        f"Day-41 W2-05 specifies 10 synthetic outcomes; got {len(novelty_fixtures)}"
    )


def test_novelty_fixtures_validate(novelty_fixtures):
    failures = []
    for f in novelty_fixtures:
        errs = validate_novelty_fixture(f)
        if errs:
            failures.append((f.get("id"), errs))
    assert not failures, repr(failures)


def test_novelty_tier_coverage(novelty_fixtures):
    """All four tiers represented so κ has off-diagonal mass."""
    tiers = {f["ground_truth_tier"] for f in novelty_fixtures}
    assert tiers == NOVELTY_TIERS, f"missing tiers: {NOVELTY_TIERS - tiers}"


def test_novelty_scores_align_with_tiers(novelty_fixtures):
    """Sanity check that ground_truth_novelty_score is monotone with tier
    so Spearman correlates with κ; otherwise the two metrics disagree
    and the calibration test loses interpretability."""
    tier_order = {"well_known": 0, "incremental": 1, "novel": 2, "surprising": 3}
    pairs = sorted(
        ((tier_order[f["ground_truth_tier"]], f["ground_truth_novelty_score"], f["id"])
         for f in novelty_fixtures),
        key=lambda p: p[1],
    )
    for i in range(len(pairs) - 1):
        lo_tier, lo_score, lo_id = pairs[i]
        hi_tier, hi_score, hi_id = pairs[i + 1]
        if lo_score == hi_score:
            continue
        assert lo_tier <= hi_tier, (
            f"score-order/tier-order violation: {lo_id} (tier={lo_tier}, "
            f"score={lo_score}) ranked below {hi_id} (tier={hi_tier}, "
            f"score={hi_score})"
        )
