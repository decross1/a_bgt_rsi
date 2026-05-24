#!/usr/bin/env python3
"""
Day 8 task -- regression + new-shape tests for the PROPOSED Day-42-lock
events schema at schema/proposed/events.jsonl.schema.json.

Covers:
  * Self-validation under Draft 2020-12.
  * Every Day-3.5 happy-path payload still validates (backwards compat).
  * NEW human_intervention 'gate_clear' subtype with full D-028 shape validates.
  * NEW 'gate_clear' subtype is rejected when any D-028 field is missing.
  * legacy subtypes do NOT require D-028 fields (those fields stay optional).
  * NEW calibration_entry auto_evaluator variant validates with κ/Spearman/threshold/ground_truth_ref.
  * auto_evaluator variant is rejected when any of those fields is missing.
  * human_range_check (default / absent calibration_type) still requires the original 5 fields.
  * Discriminator boundary holds across both branches and across the new sub-variants.
  * Schema structural invariants (oneOf arity, additionalProperties:false, const discriminators).

Run standalone:
    python3 tests/test_events_schema_proposed.py
or under pytest:
    pytest tests/test_events_schema_proposed.py
"""
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "proposed" / "events.jsonl.schema.json"


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def _validator():
    return Draft202012Validator(_load_schema())


# ──────────────────────────────────────────────────────────────────────
# Day-3.5 happy-path payloads (copied verbatim from
# tests/test_events_schema.py so any change there must be mirrored here).
# ──────────────────────────────────────────────────────────────────────
def _hi_legacy():
    """Day-3.5 human_intervention payload (edit_prompt subtype)."""
    return {
        "event_type": "human_intervention",
        "timestamp": "2026-05-19T12:00:00.000000Z",
        "task_id": "day4_block2_e2e_test",
        "subtype": "edit_prompt",
        "reason": "Tightened the system prompt to forbid markdown in tool args.",
        "context_hash": "sha256:" + "a" * 64,
    }


def _ce_legacy():
    """Day-3.5 calibration_entry payload (human_range_check, calibration_type absent)."""
    return {
        "event_type": "calibration_entry",
        "timestamp": "2026-05-22T17:30:00.000000Z",
        "experiment_id": "exp001_repeated_pd",
        "metric_name": "coop_rate_vs_tft",
        "pre_experiment_expected_range": [0.4, 0.7],
        "post_experiment_observed": 0.55,
        "within_range": True,
        "human_attestation": "Range chosen from Axelrod 1984 tournament priors.",
    }


# ──────────────────────────────────────────────────────────────────────
# NEW Day-8 payloads (gate_clear / auto_evaluator).
# ──────────────────────────────────────────────────────────────────────
def _hi_gate_clear():
    """Day-8 human_intervention payload with subtype='gate_clear' (D-028 shape)."""
    return {
        "event_type": "human_intervention",
        "timestamp": "2026-05-24T17:00:00.000000Z",
        "task_id": "day7_block2_publication_review",
        "subtype": "gate_clear",
        "reason": "Aggregating Day-7 into a broader future publication; one-game / one-model / one-week-of-apparatus too thin for a standalone behavioral claim.",
        "context_hash": "sha256:" + "b" * 64,
        "decision_id": "D-028",
        "human_identity": "decross1",
        "disposition": "no-publish-standalone",
        "decisions_ref": "DECISIONS.md#D-028",
        "gate_name": "day7_publication_review",
    }


def _ce_auto():
    """Day-8 calibration_entry payload with calibration_type='auto_evaluator' (Day-41 shape)."""
    return {
        "event_type": "calibration_entry",
        "timestamp": "2026-06-04T15:00:00.000000Z",
        "experiment_id": "day41_auto_evaluator_calibration",
        "calibration_type": "auto_evaluator",
        "kappa": 0.72,
        "spearman": 0.81,
        "threshold": 0.65,
        "ground_truth_ref": "experiments/critic_calibration/fixtures.py#KNOWN_FLAWED_20",
        "human_attestation": "Calibration done against the 20-known-flawed-hypotheses fixture; κ comfortably above the 0.6 Day-41 success bar.",
    }


# ──────────────────────────────────────────────────────────────────────
class SchemaSelfValidationTest(unittest.TestCase):
    def test_schema_is_a_valid_draft_2020_12_schema(self):
        Draft202012Validator.check_schema(_load_schema())

    def test_schema_file_exists_at_proposed_path(self):
        # If Track A renames the file as part of the merge, this test
        # is the first thing to update — it pins the file location.
        self.assertTrue(SCHEMA_PATH.exists(), f"expected schema at {SCHEMA_PATH}")


# ──────────────────────────────────────────────────────────────────────
# Backwards compatibility — Day-3.5 records must still validate.
# ──────────────────────────────────────────────────────────────────────
class LegacyHumanInterventionStillValidatesTest(unittest.TestCase):
    def test_legacy_edit_prompt_validates(self):
        self.assertEqual(list(_validator().iter_errors(_hi_legacy())), [])

    def test_each_legacy_subtype_validates(self):
        v = _validator()
        for sub in ("edit_prompt", "edit_code", "reject", "redirect", "manual_decision"):
            rec = _hi_legacy()
            rec["subtype"] = sub
            with self.subTest(subtype=sub):
                self.assertEqual(list(v.iter_errors(rec)), [])

    def test_legacy_subtype_does_not_require_d028_fields(self):
        # The if/then on 'gate_clear' must NOT spill over to other subtypes.
        v = _validator()
        rec = _hi_legacy()
        rec["subtype"] = "manual_decision"
        # No decision_id, no human_identity, no disposition, no decisions_ref, no gate_name.
        self.assertEqual(list(v.iter_errors(rec)), [])


class LegacyCalibrationEntryStillValidatesTest(unittest.TestCase):
    def test_legacy_payload_validates(self):
        self.assertEqual(list(_validator().iter_errors(_ce_legacy())), [])

    def test_legacy_within_range_false_validates(self):
        rec = _ce_legacy()
        rec["post_experiment_observed"] = 0.9
        rec["within_range"] = False
        self.assertEqual(list(_validator().iter_errors(rec)), [])

    def test_legacy_payload_with_explicit_human_range_check_type_validates(self):
        # An old shape with calibration_type='human_range_check' is the
        # else-branch path; it must validate identically to no calibration_type.
        rec = _ce_legacy()
        rec["calibration_type"] = "human_range_check"
        self.assertEqual(list(_validator().iter_errors(rec)), [])


# ──────────────────────────────────────────────────────────────────────
# New shape — human_intervention 'gate_clear'.
# ──────────────────────────────────────────────────────────────────────
class GateClearHappyPathTest(unittest.TestCase):
    def test_d028_shape_validates(self):
        self.assertEqual(list(_validator().iter_errors(_hi_gate_clear())), [])

    def test_d028_with_different_disposition_validates(self):
        # The disposition field is free-form by design (D-NNN entries vary).
        rec = _hi_gate_clear()
        rec["disposition"] = "aggregate-into-future-paper"
        self.assertEqual(list(_validator().iter_errors(rec)), [])

    def test_decision_id_pattern_accepts_three_digit_ids(self):
        v = _validator()
        for did in ("D-001", "D-028", "D-999"):
            rec = _hi_gate_clear()
            rec["decision_id"] = did
            with self.subTest(decision_id=did):
                self.assertEqual(list(v.iter_errors(rec)), [])


class GateClearMissingFieldsFailTest(unittest.TestCase):
    """Each of the 5 D-028 fields is required when subtype == 'gate_clear'."""

    def test_missing_decision_id_fails(self):
        rec = _hi_gate_clear()
        del rec["decision_id"]
        errs = list(_validator().iter_errors(rec))
        self.assertNotEqual(errs, [], "gate_clear without decision_id must fail")

    def test_missing_human_identity_fails(self):
        rec = _hi_gate_clear()
        del rec["human_identity"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_missing_disposition_fails(self):
        rec = _hi_gate_clear()
        del rec["disposition"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_missing_decisions_ref_fails(self):
        rec = _hi_gate_clear()
        del rec["decisions_ref"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_missing_gate_name_fails(self):
        rec = _hi_gate_clear()
        del rec["gate_name"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])


class GateClearMalformedTest(unittest.TestCase):
    def test_bad_decision_id_pattern_fails(self):
        v = _validator()
        for bad in ("D-28", "D-0028", "D028", "d-028", "X-028", "D-abc", ""):
            rec = _hi_gate_clear()
            rec["decision_id"] = bad
            with self.subTest(bad=bad):
                self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_empty_human_identity_fails(self):
        rec = _hi_gate_clear()
        rec["human_identity"] = ""
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_empty_gate_name_fails(self):
        rec = _hi_gate_clear()
        rec["gate_name"] = ""
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_unknown_subtype_still_fails(self):
        rec = _hi_gate_clear()
        rec["subtype"] = "ponder"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_unknown_top_level_field_fails(self):
        rec = _hi_gate_clear()
        rec["severity"] = "high"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])


# ──────────────────────────────────────────────────────────────────────
# New shape — calibration_entry 'auto_evaluator'.
# ──────────────────────────────────────────────────────────────────────
class AutoEvaluatorHappyPathTest(unittest.TestCase):
    def test_auto_evaluator_shape_validates(self):
        self.assertEqual(list(_validator().iter_errors(_ce_auto())), [])

    def test_auto_evaluator_does_not_need_human_range_fields(self):
        # The auto_evaluator branch does not require the four fields that
        # only make sense for a human_range_check (metric_name + the range
        # triple + within_range). human_attestation is shared by both
        # shapes — a human still attests the auto-evaluator calibration —
        # so we don't assert it's absent.
        rec = _ce_auto()
        for k in ("metric_name", "pre_experiment_expected_range",
                  "post_experiment_observed", "within_range"):
            self.assertNotIn(k, rec, f"unexpected leftover key {k} in auto_evaluator fixture")
        # Re-assert validation with a fresh validator just in case.
        self.assertEqual(list(_validator().iter_errors(rec)), [])

    def test_auto_evaluator_without_human_attestation_also_validates(self):
        # human_attestation is optional in the auto_evaluator branch
        # (it's only required in the human_range_check else-branch).
        rec = _ce_auto()
        del rec["human_attestation"]
        self.assertEqual(list(_validator().iter_errors(rec)), [])

    def test_kappa_at_boundaries_validates(self):
        v = _validator()
        for kappa in (-1.0, 0.0, 0.6, 0.99, 1.0):
            rec = _ce_auto()
            rec["kappa"] = kappa
            with self.subTest(kappa=kappa):
                self.assertEqual(list(v.iter_errors(rec)), [])


class AutoEvaluatorMissingFieldsFailTest(unittest.TestCase):
    def test_missing_kappa_fails(self):
        rec = _ce_auto()
        del rec["kappa"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_missing_spearman_fails(self):
        rec = _ce_auto()
        del rec["spearman"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_missing_threshold_fails(self):
        rec = _ce_auto()
        del rec["threshold"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_missing_ground_truth_ref_fails(self):
        rec = _ce_auto()
        del rec["ground_truth_ref"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])


class AutoEvaluatorMalformedTest(unittest.TestCase):
    def test_kappa_out_of_range_fails(self):
        v = _validator()
        for k in (-1.5, 1.5, 2.0):
            rec = _ce_auto()
            rec["kappa"] = k
            with self.subTest(kappa=k):
                self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_spearman_not_a_number_fails(self):
        rec = _ce_auto()
        rec["spearman"] = "high"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_empty_ground_truth_ref_fails(self):
        rec = _ce_auto()
        rec["ground_truth_ref"] = ""
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_unknown_calibration_type_fails(self):
        rec = _ce_auto()
        rec["calibration_type"] = "vibes_check"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_unknown_top_level_field_fails(self):
        rec = _ce_auto()
        rec["notes"] = "extra"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])


# ──────────────────────────────────────────────────────────────────────
# Discriminator boundary — must still hold across all four variants.
# ──────────────────────────────────────────────────────────────────────
class DiscriminatorBoundaryTest(unittest.TestCase):
    def test_human_intervention_with_calibration_fields_fails(self):
        v = _validator()
        rec = _hi_legacy()
        rec.update({k: val for k, val in _ce_legacy().items() if k != "event_type"})
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_calibration_with_human_intervention_fields_fails(self):
        v = _validator()
        rec = _ce_legacy()
        rec.update({k: val for k, val in _hi_legacy().items() if k != "event_type"})
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_gate_clear_event_with_calibration_fields_fails(self):
        # Even the new D-028 shape must not accept foreign branch fields.
        v = _validator()
        rec = _hi_gate_clear()
        rec.update({k: val for k, val in _ce_auto().items() if k != "event_type"})
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_auto_evaluator_with_human_intervention_fields_fails(self):
        v = _validator()
        rec = _ce_auto()
        rec.update({k: val for k, val in _hi_gate_clear().items() if k != "event_type"})
        self.assertNotEqual(list(v.iter_errors(rec)), [])


# ──────────────────────────────────────────────────────────────────────
class SchemaInvariantsTest(unittest.TestCase):
    """Structural guarantees the proposed schema must keep."""

    def test_root_is_oneOf_with_two_members(self):
        schema = _load_schema()
        self.assertIn("oneOf", schema)
        self.assertEqual(len(schema["oneOf"]), 2)

    def test_both_branches_have_additional_properties_false(self):
        schema = _load_schema()
        for branch in schema["oneOf"]:
            self.assertIs(branch.get("additionalProperties"), False, branch.get("title"))

    def test_each_branch_uses_const_discriminator(self):
        schema = _load_schema()
        consts = {b["properties"]["event_type"].get("const") for b in schema["oneOf"]}
        self.assertEqual(consts, {"human_intervention", "calibration_entry"})

    def test_gate_clear_subtype_is_in_enum(self):
        schema = _load_schema()
        hi_branch = next(b for b in schema["oneOf"] if b["title"] == "human_intervention")
        self.assertIn("gate_clear", hi_branch["properties"]["subtype"]["enum"])

    def test_auto_evaluator_calibration_type_is_in_enum(self):
        schema = _load_schema()
        ce_branch = next(b for b in schema["oneOf"] if b["title"] == "calibration_entry")
        ct_enum = ce_branch["properties"]["calibration_type"]["enum"]
        self.assertEqual(set(ct_enum), {"human_range_check", "auto_evaluator"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
