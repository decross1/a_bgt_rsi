#!/usr/bin/env python3
"""
Day 3.5 task -- tests for schema/events.jsonl.schema.json (proposals P1+P3).

Covers:
  * Self-validation under Draft 2020-12.
  * Happy-path payloads of each branch validate (human_intervention, calibration_entry).
  * Multiple malformed payloads per branch are rejected.
  * Discriminator boundary: a human_intervention payload that ALSO carries
    calibration_entry's required fields must fail (additionalProperties:false
    on the matching branch rejects the extras, and the other branch's const
    discriminator does not match -- so oneOf falls through both members);
    the symmetric case must also fail.

Run standalone:
    python3 tests/test_events_schema.py
or under pytest:
    pytest tests/test_events_schema.py
"""
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "events.jsonl.schema.json"


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def _hi():
    """Happy-path human_intervention payload."""
    return {
        "event_type": "human_intervention",
        "timestamp": "2026-05-19T12:00:00.000000Z",
        "task_id": "day4_block2_e2e_test",
        "subtype": "edit_prompt",
        "reason": "Tightened the system prompt to forbid markdown in tool args.",
        "context_hash": "sha256:" + "a" * 64,
    }


def _ce():
    """Happy-path calibration_entry payload."""
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


def _validator():
    return Draft202012Validator(_load_schema())


class SchemaSelfValidationTest(unittest.TestCase):
    def test_schema_is_a_valid_draft_2020_12_schema(self):
        Draft202012Validator.check_schema(_load_schema())


class HumanInterventionHappyPathTest(unittest.TestCase):
    def test_canonical_payload_validates(self):
        self.assertEqual(list(_validator().iter_errors(_hi())), [])

    def test_each_subtype_validates(self):
        v = _validator()
        for sub in ("edit_prompt", "edit_code", "reject", "redirect", "manual_decision"):
            rec = _hi()
            rec["subtype"] = sub
            with self.subTest(subtype=sub):
                self.assertEqual(list(v.iter_errors(rec)), [])


class HumanInterventionMalformedTest(unittest.TestCase):
    """At least two distinct malformed cases for human_intervention."""

    def test_unknown_subtype_fails(self):
        rec = _hi()
        rec["subtype"] = "ponder"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_missing_required_field_fails(self):
        rec = _hi()
        del rec["context_hash"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_empty_reason_fails(self):
        rec = _hi()
        rec["reason"] = ""
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_unknown_top_level_field_fails(self):
        rec = _hi()
        rec["severity"] = "high"  # not declared anywhere
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_bad_event_type_fails(self):
        # No const matches and no branch will accept this -- oneOf must fall through.
        rec = _hi()
        rec["event_type"] = "human_action"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])


class CalibrationEntryHappyPathTest(unittest.TestCase):
    def test_canonical_payload_validates(self):
        self.assertEqual(list(_validator().iter_errors(_ce())), [])

    def test_within_range_false_validates(self):
        rec = _ce()
        rec["post_experiment_observed"] = 0.9
        rec["within_range"] = False
        self.assertEqual(list(_validator().iter_errors(rec)), [])


class CalibrationEntryMalformedTest(unittest.TestCase):
    """At least two distinct malformed cases for calibration_entry."""

    def test_range_wrong_length_fails(self):
        rec = _ce()
        rec["pre_experiment_expected_range"] = [0.4]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_within_range_not_bool_fails(self):
        rec = _ce()
        rec["within_range"] = "yes"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_missing_required_field_fails(self):
        rec = _ce()
        del rec["human_attestation"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_observed_not_a_number_fails(self):
        rec = _ce()
        rec["post_experiment_observed"] = "0.55"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])


def _ce_pre():
    """Happy-path PRE-VERDICT calibration_entry payload (D-055)."""
    return {
        "event_type": "calibration_entry",
        "phase": "pre_verdict",
        "timestamp": "2026-06-17T16:08:00.000000Z",
        "ref_id": "sf-iter-2026-05-26-008",
        "prediction": "Cooperation will rise with context-window size.",
        "confidence": 0.7,
        "by": "human:ui",
    }


class PreVerdictCalibrationTest(unittest.TestCase):
    """D-055: the cockpit's pre-verdict calibration_entry coexists with the
    post-experiment one under the same event_type, disambiguated by `phase`."""

    def test_pre_verdict_payload_validates(self):
        self.assertEqual(list(_validator().iter_errors(_ce_pre())), [])

    def test_pre_verdict_and_post_experiment_both_validate_disjointly(self):
        # Each canonical payload matches exactly ONE oneOf branch (no overlap).
        v = _validator()
        self.assertEqual(list(v.iter_errors(_ce_pre())), [])
        self.assertEqual(list(v.iter_errors(_ce())), [])

    def test_pre_verdict_missing_phase_fails(self):
        # Without phase it can't match the pre_verdict branch, and it lacks the
        # post-experiment branch's required fields -> oneOf falls through.
        rec = _ce_pre()
        del rec["phase"]
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_pre_verdict_confidence_out_of_range_fails(self):
        rec = _ce_pre()
        rec["confidence"] = 1.5
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_pre_verdict_unknown_field_fails(self):
        rec = _ce_pre()
        rec["verdict"] = "valid"  # additionalProperties:false
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_unknown_top_level_field_fails(self):
        rec = _ce()
        rec["notes"] = "extra"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])


class DiscriminatorBoundaryTest(unittest.TestCase):
    """A payload that carries the *other* branch's required fields must FAIL.

    Mechanism: each branch sets additionalProperties:false, so the matching
    branch rejects the foreign fields; the other branch's `event_type` const
    does not match, so it rejects too. oneOf therefore validates against
    neither member."""

    def test_human_intervention_with_calibration_fields_fails(self):
        v = _validator()
        rec = _hi()
        ce_extras = {k: v_ for k, v_ in _ce().items() if k != "event_type"}
        rec.update(ce_extras)
        # Make sure we actually overlaid the calibration fields and kept the
        # human_intervention discriminator -- if either assumption breaks,
        # the test is no longer testing what it claims.
        self.assertEqual(rec["event_type"], "human_intervention")
        self.assertIn("experiment_id", rec)
        self.assertNotEqual(list(v.iter_errors(rec)), [],
                            "human_intervention carrying calibration fields must fail")

    def test_calibration_with_human_intervention_fields_fails(self):
        v = _validator()
        rec = _ce()
        hi_extras = {k: v_ for k, v_ in _hi().items() if k != "event_type"}
        rec.update(hi_extras)
        self.assertEqual(rec["event_type"], "calibration_entry")
        self.assertIn("task_id", rec)
        self.assertNotEqual(list(v.iter_errors(rec)), [],
                            "calibration_entry carrying human_intervention fields must fail")

    def test_two_discriminators_at_once_fails(self):
        # If a future edit weakened the const into an enum and a record set
        # event_type to a value that matched both branches, oneOf would still
        # fail because both members would validate (oneOf == exactly one).
        # Today the const guarantees this cannot happen, but we encode the
        # invariant: a record with both discriminator values is not a thing.
        v = _validator()
        rec = _hi()
        rec["event_type"] = "calibration_entry"  # discriminator now points to wrong branch
        self.assertNotEqual(list(v.iter_errors(rec)), [])


class SchemaInvariantsTest(unittest.TestCase):
    """Structural guarantees the schema must keep -- documenting the contract."""

    def test_root_is_oneOf_with_three_members(self):
        # D-055: human_intervention + post-experiment calibration_entry +
        # pre-verdict calibration_entry (the latter two share the
        # 'calibration_entry' const, disambiguated by the 'phase' discriminator).
        schema = _load_schema()
        self.assertIn("oneOf", schema)
        self.assertEqual(len(schema["oneOf"]), 3)

    def test_two_calibration_branches_share_const_disambiguated_by_phase(self):
        schema = _load_schema()
        cal = [b for b in schema["oneOf"]
               if b["properties"]["event_type"].get("const") == "calibration_entry"]
        self.assertEqual(len(cal), 2)
        phases = {b["properties"].get("phase", {}).get("const") for b in cal}
        self.assertEqual(phases, {None, "pre_verdict"})

    def test_both_branches_have_additional_properties_false(self):
        schema = _load_schema()
        for branch in schema["oneOf"]:
            self.assertIs(branch.get("additionalProperties"), False, branch.get("title"))

    def test_each_branch_uses_const_discriminator(self):
        schema = _load_schema()
        consts = {b["properties"]["event_type"].get("const") for b in schema["oneOf"]}
        self.assertEqual(consts, {"human_intervention", "calibration_entry"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
