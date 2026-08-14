#!/usr/bin/env python3
"""
LOOP_V1 M2 -- tests for schema/task_packet.schema.json (spawn lv1-m2-packet-schema).

Covers:
  * Self-validation under Draft 2020-12.
  * The checked-in example packet (tasks/packets/PKT-EXAMPLE.json) validates,
    and its task_id matches its filename stem.
  * Every required field, when removed, is rejected (all fields are required).
  * An extra top-level property is rejected (additionalProperties:false),
    likewise inside the nested acceptance_criteria / budgets / rollback objects.
  * Field-level constraints: task_id pattern, objective length bounds,
    must_fail_before const, budget ceilings.

NOTE (Wave 2): the dispatcher-coverage grep test -- asserting the dispatcher
reads every schema field -- lands in Wave 2 alongside the dispatcher itself.
It is deliberately NOT in this file.

Run standalone:
    python3 tests/test_task_packet_schema.py
or under pytest:
    MOCK_LLM=1 .venv-chroma/bin/python -m pytest tests/test_task_packet_schema.py -x -q
"""
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "task_packet.schema.json"
EXAMPLE_PATH = REPO_ROOT / "tasks" / "packets" / "PKT-EXAMPLE.json"

REQUIRED_FIELDS = [
    "task_id",
    "objective",
    "files_in_scope",
    "files_out_of_scope",
    "preconditions",
    "acceptance_criteria",
    "budgets",
    "forbidden_actions",
    "rollback",
]


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def _validator():
    return Draft202012Validator(_load_schema())


def _packet():
    """A fresh copy of the checked-in example packet (the canonical happy path)."""
    return json.loads(EXAMPLE_PATH.read_text())


class SchemaSelfValidationTest(unittest.TestCase):
    def test_schema_is_a_valid_draft_2020_12_schema(self):
        Draft202012Validator.check_schema(_load_schema())

    def test_all_fields_are_required(self):
        # The contract says every listed field is REQUIRED -- pin that here so
        # a future edit relaxing `required` fails loudly.
        self.assertEqual(sorted(_load_schema()["required"]), sorted(REQUIRED_FIELDS))

    def test_root_is_closed(self):
        self.assertIs(_load_schema()["additionalProperties"], False)


class ExamplePacketTest(unittest.TestCase):
    def test_example_packet_validates(self):
        self.assertEqual(list(_validator().iter_errors(_packet())), [])

    def test_example_task_id_matches_filename(self):
        self.assertEqual(_packet()["task_id"], EXAMPLE_PATH.stem)


class MissingRequiredTest(unittest.TestCase):
    def test_each_missing_required_field_fails(self):
        v = _validator()
        for field in REQUIRED_FIELDS:
            rec = _packet()
            del rec[field]
            with self.subTest(missing=field):
                self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_missing_nested_required_fails(self):
        v = _validator()
        for parent, child in [
            ("acceptance_criteria", "test_cmd"),
            ("acceptance_criteria", "must_fail_before"),
            ("budgets", "max_attempts"),
            ("budgets", "wall_clock_minutes"),
            ("budgets", "max_diff_lines"),
            ("rollback", "branch_delete"),
            ("rollback", "notes"),
        ]:
            rec = _packet()
            del rec[parent][child]
            with self.subTest(missing=f"{parent}.{child}"):
                self.assertNotEqual(list(v.iter_errors(rec)), [])


class ExtraPropertyTest(unittest.TestCase):
    def test_extra_top_level_property_fails(self):
        rec = _packet()
        rec["priority"] = "high"  # not declared anywhere
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_extra_nested_property_fails(self):
        v = _validator()
        for parent in ("acceptance_criteria", "budgets", "rollback"):
            rec = _packet()
            rec[parent]["surprise"] = 1
            with self.subTest(parent=parent):
                self.assertNotEqual(list(v.iter_errors(rec)), [])


class FieldConstraintTest(unittest.TestCase):
    def test_task_id_without_pkt_prefix_fails(self):
        rec = _packet()
        rec["task_id"] = "TASK-001"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_objective_too_short_fails(self):
        rec = _packet()
        rec["objective"] = "fix it"  # < 10 chars
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_objective_too_long_fails(self):
        rec = _packet()
        rec["objective"] = "x" * 2001
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_must_fail_before_false_fails(self):
        # const true: a packet whose acceptance test already passes is not
        # dispatchable (a vacuous validation is a coerced one -- rule 4).
        rec = _packet()
        rec["acceptance_criteria"]["must_fail_before"] = False
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_max_attempts_over_cap_fails(self):
        rec = _packet()
        rec["budgets"]["max_attempts"] = 6
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_wall_clock_over_cap_fails(self):
        rec = _packet()
        rec["budgets"]["wall_clock_minutes"] = 61
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_budget_at_caps_validates(self):
        rec = _packet()
        rec["budgets"] = {"max_attempts": 5, "wall_clock_minutes": 60, "max_diff_lines": 1}
        self.assertEqual(list(_validator().iter_errors(rec)), [])

    def test_non_integer_budget_fails(self):
        rec = _packet()
        rec["budgets"]["max_diff_lines"] = "60"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_empty_string_in_scope_list_fails(self):
        rec = _packet()
        rec["files_in_scope"].append("")
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])

    def test_branch_delete_not_bool_fails(self):
        rec = _packet()
        rec["rollback"]["branch_delete"] = "yes"
        self.assertNotEqual(list(_validator().iter_errors(rec)), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
