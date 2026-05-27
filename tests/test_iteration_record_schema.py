"""Tests for schema/iteration_record.schema.json — focused on the
experiment_outcome field added for Phase 2 / Slice 1 (Vickrey bridge).

Covers:
  - existing iteration_records (no experiment_outcome) continue to validate
  - records WITH experiment_outcome validate when the required fields are
    present and well-typed (scalar value + structured value both work)
  - missing required experiment_outcome fields fail
  - typed constraints (trials >= 1, value scalar-or-object) fail when violated
"""
import json
import unittest
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "iteration_record.schema.json"


def _validator():
    return jsonschema.Draft7Validator(json.loads(SCHEMA_PATH.read_text()))


def _baseline_record():
    """A fully-populated iteration_record matching what nara.run_iteration
    produces today (pre-experiment_outcome). Anchored to a real shape from
    `memory/loop_memory.jsonl`."""
    return {
        "iteration_id": "iter-2026-05-27-099",
        "started_at": "2026-05-27T12:00:00Z",
        "ended_at":   "2026-05-27T12:00:30Z",
        "seed": {
            "topic":  "Vickrey-shaped query for testing.",
            "source": "human_cli",
        },
        "nara_summary": "Test summary.",
        "tool_calls_made": ["hypothesize", "journal_writer"],
        "journal_entry_path": "journal/iterations/099.md",
        "model_version": "vllm-gemma:gemma-4-26b-a4b-nvfp4:v0.21.0",
        "wrapper_call_ids": ["req-1"],
    }


class BaselineStillValidates(unittest.TestCase):
    """The schema extension must be backwards-compatible: any record that
    validated before still validates."""

    def test_record_without_experiment_outcome_validates(self):
        errors = list(_validator().iter_errors(_baseline_record()))
        self.assertEqual(errors, [], msg=f"unexpected errors: {errors}")


class ExperimentOutcomeHappyPath(unittest.TestCase):
    def test_scalar_value_validates(self):
        rec = _baseline_record()
        rec["experiment_outcome"] = {
            "experiment_id": "exp003_vickrey_rediscovery",
            "metric": "truthful_bid_fraction",
            "value": 0.84,
            "trials": 50,
            "summary": "42/50 trials had >=3/4 bidders within eps=5 of truthful.",
            "results_path": "experiments/exp003_vickrey_rediscovery/results/summary.md",
        }
        errors = list(_validator().iter_errors(rec))
        self.assertEqual(errors, [], msg=f"unexpected errors: {errors}")

    def test_object_value_validates(self):
        """Multi-metric outcomes: value can be a structured object."""
        rec = _baseline_record()
        rec["experiment_outcome"] = {
            "experiment_id": "exp003_vickrey_rediscovery",
            "metric": "bidder_residuals",
            "value": {
                "mean_abs_residual": 4.2,
                "median_abs_residual": 2.1,
                "max_abs_residual": 18.7,
            },
        }
        errors = list(_validator().iter_errors(rec))
        self.assertEqual(errors, [], msg=f"unexpected errors: {errors}")

    def test_minimal_required_fields_validate(self):
        """experiment_id + metric + value are the only required fields."""
        rec = _baseline_record()
        rec["experiment_outcome"] = {
            "experiment_id": "exp003_vickrey_rediscovery",
            "metric": "truthful_bid_fraction",
            "value": 0.84,
        }
        errors = list(_validator().iter_errors(rec))
        self.assertEqual(errors, [], msg=f"unexpected errors: {errors}")


class ExperimentOutcomeRejects(unittest.TestCase):
    def test_missing_experiment_id_fails(self):
        rec = _baseline_record()
        rec["experiment_outcome"] = {"metric": "m", "value": 0.5}
        errors = list(_validator().iter_errors(rec))
        self.assertTrue(errors, msg="expected validation failure for missing experiment_id")
        self.assertTrue(any("experiment_id" in str(e.message) for e in errors))

    def test_missing_metric_fails(self):
        rec = _baseline_record()
        rec["experiment_outcome"] = {"experiment_id": "e", "value": 0.5}
        errors = list(_validator().iter_errors(rec))
        self.assertTrue(errors)
        self.assertTrue(any("metric" in str(e.message) for e in errors))

    def test_missing_value_fails(self):
        rec = _baseline_record()
        rec["experiment_outcome"] = {"experiment_id": "e", "metric": "m"}
        errors = list(_validator().iter_errors(rec))
        self.assertTrue(errors)
        self.assertTrue(any("value" in str(e.message) for e in errors))

    def test_trials_zero_fails(self):
        rec = _baseline_record()
        rec["experiment_outcome"] = {
            "experiment_id": "e",
            "metric": "m",
            "value": 0.5,
            "trials": 0,
        }
        errors = list(_validator().iter_errors(rec))
        self.assertTrue(errors)
        self.assertTrue(any("trials" in str(e.absolute_path) for e in errors),
                        msg=f"expected trials-related error, got: {[(e.message, list(e.absolute_path)) for e in errors]}")

    def test_value_as_string_fails(self):
        """value must be number or object — not a string."""
        rec = _baseline_record()
        rec["experiment_outcome"] = {
            "experiment_id": "e",
            "metric": "m",
            "value": "0.5",
        }
        errors = list(_validator().iter_errors(rec))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
