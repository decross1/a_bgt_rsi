"""Loader + schema constants for the critic-eval fixture set.

Day-39 (W2-01) consumes `load_critic_fixtures()` to run the critic
agent against 20 hypotheses (19 known-flawed + 1 sound baseline).
See `experiments/fixtures/README.md` for the schema rationale.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

SCHEMA_VERSION = "1.0"

FIXTURE_ROOT = Path(__file__).parent
CRITIC_DIR = FIXTURE_ROOT / "critic_hypotheses"
NOVELTY_DIR = FIXTURE_ROOT / "novelty_calibration"

REQUIRED_FIELDS = {
    "id",
    "hypothesis_text",
    "domain",
    "injected_flaw_type",
    "flaw_description",
    "expected_critique_targets",
    "ground_truth_label",
    "severity",
    "schema_version",
}

DOMAINS = {"game_theory", "llm_behavior", "mech_design", "methodology"}
SEVERITIES = {"subtle", "moderate", "obvious"}
LABELS = {"flawed", "sound"}

# Flaw categories present in the fixture set. `none` is reserved for the
# ground-truth-positive baseline. New categories MUST be added here AND
# get at least one fixture, or the test suite fails.
FLAW_TAXONOMY = {
    "none",
    "spurious_causation",
    "prompt_leakage",
    "misspecified_payoff",
    "sample_size_insufficient",
    "post_hoc_rationale",
    "overgeneralization",
    "selection_bias",
    "confounded_treatment",
    "measurement_artifact",
    "circular_reasoning",
    "goodhart",
    "regression_to_mean",
    "missing_baseline",
    "temperature_artifact",
    "ungrounded_extrapolation",
    "ambiguous_construct",
    "publication_threshold",
    "anthropomorphic_attribution",
    "mis_specified_construct_validity",
}


def _load_dir(directory: Path) -> List[Dict[str, Any]]:
    if not directory.exists():
        return []
    fixtures: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        with path.open() as fh:
            fixtures.append(json.load(fh))
    return fixtures


def load_critic_fixtures() -> List[Dict[str, Any]]:
    """Return the 20 critic-eval fixtures, sorted by id."""
    return _load_dir(CRITIC_DIR)


NOVELTY_REQUIRED_FIELDS = {
    "id",
    "hypothesis_text",
    "prior_art_summary",
    "ground_truth_tier",
    "ground_truth_novelty_score",
    "domain",
    "rationale",
    "schema_version",
}

NOVELTY_TIERS = {"well_known", "incremental", "novel", "surprising"}


def load_novelty_fixtures() -> List[Dict[str, Any]]:
    """Return the Day-41 novelty-calibration fixtures (may be empty)."""
    return _load_dir(NOVELTY_DIR)


def validate_novelty_fixture(fixture: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    missing = NOVELTY_REQUIRED_FIELDS - fixture.keys()
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
        return errors
    if fixture["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version mismatch: {fixture['schema_version']!r}")
    if fixture["ground_truth_tier"] not in NOVELTY_TIERS:
        errors.append(f"unknown tier: {fixture['ground_truth_tier']!r}")
    if fixture["domain"] not in DOMAINS:
        errors.append(f"unknown domain: {fixture['domain']!r}")
    score = fixture["ground_truth_novelty_score"]
    if not isinstance(score, (int, float)) or not 0.0 <= score <= 1.0:
        errors.append(f"novelty score must be in [0,1]; got {score!r}")
    return errors


def validate_fixture(fixture: Dict[str, Any]) -> List[str]:
    """Return a list of validation errors; empty list = valid."""
    errors: List[str] = []
    missing = REQUIRED_FIELDS - fixture.keys()
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
        return errors
    if fixture["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version mismatch: {fixture['schema_version']!r}")
    if fixture["domain"] not in DOMAINS:
        errors.append(f"unknown domain: {fixture['domain']!r}")
    if fixture["severity"] not in SEVERITIES:
        errors.append(f"unknown severity: {fixture['severity']!r}")
    if fixture["ground_truth_label"] not in LABELS:
        errors.append(f"unknown ground_truth_label: {fixture['ground_truth_label']!r}")
    if fixture["injected_flaw_type"] not in FLAW_TAXONOMY:
        errors.append(f"unknown injected_flaw_type: {fixture['injected_flaw_type']!r}")
    if (fixture["injected_flaw_type"] == "none") != (fixture["ground_truth_label"] == "sound"):
        errors.append("injected_flaw_type='none' iff ground_truth_label='sound'")
    if not isinstance(fixture["expected_critique_targets"], list) or not fixture["expected_critique_targets"]:
        errors.append("expected_critique_targets must be a non-empty list")
    return errors
