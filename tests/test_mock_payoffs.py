#!/usr/bin/env python3
"""Unit tests for tools/mock_payoffs.py and tools/mock_payoffs.schema.json.

The schema is the OpenAI-style tool-call descriptor — it describes the
*input* (`game_name`), not the matrix returned. Tests therefore:

  1. Validate the schema document is well-formed (function.name +
     parameters with a non-empty enum).
  2. Cross-check the schema's enum against the implementation's known
     games (no drift between schema and code).
  3. For every game in the schema's enum, call get_payoff_matrix and
     assert the returned matrix is JSON-serializable and shape-correct
     (2x2 matrix of [int, int] pairs).
  4. Exercise the input schema with jsonschema.validate for both valid
     and invalid `game_name` arguments.
  5. Confirm unknown game names raise ValueError.

Run standalone:
    python3 tests/test_mock_payoffs.py
or under pytest:
    pytest tests/test_mock_payoffs.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import mock_payoffs  # noqa: E402

SCHEMA_PATH = REPO / "tools" / "mock_payoffs.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def input_schema(schema: dict) -> dict:
    """Extract the JSON-Schema describing the function's input arguments."""
    return schema["function"]["parameters"]


class SchemaShapeTest(unittest.TestCase):
    """The schema document itself is a well-formed OpenAI tool descriptor."""

    def test_schema_file_exists(self):
        self.assertTrue(SCHEMA_PATH.is_file(),
                        f"missing {SCHEMA_PATH}")

    def test_schema_top_level_shape(self):
        schema = load_schema()
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "get_payoff_matrix")
        params = input_schema(schema)
        self.assertEqual(params["type"], "object")
        self.assertEqual(params["required"], ["game_name"])
        self.assertIn("game_name", params["properties"])

    def test_game_name_property_has_enum(self):
        schema = load_schema()
        prop = input_schema(schema)["properties"]["game_name"]
        self.assertEqual(prop["type"], "string")
        self.assertIsInstance(prop["enum"], list)
        self.assertGreater(len(prop["enum"]), 0)

    def test_parameters_disallow_additional_properties(self):
        # The tool's contract is strict on inputs; this prevents the model
        # from inventing extra fields the implementation would ignore.
        params = input_schema(load_schema())
        self.assertFalse(params["additionalProperties"])


class SchemaCodeConsistencyTest(unittest.TestCase):
    """No drift between the schema's enum and the implementation's _GAMES."""

    def test_enum_matches_implementation_games(self):
        schema = load_schema()
        schema_games = set(input_schema(schema)["properties"]["game_name"]["enum"])
        impl_games = set(mock_payoffs._GAMES)
        self.assertEqual(schema_games, impl_games,
                         f"schema enum ({sorted(schema_games)}) and "
                         f"_GAMES ({sorted(impl_games)}) diverged")


class GetPayoffMatrixTest(unittest.TestCase):
    """Every enum-listed game returns a 2x2 matrix of [int, int] pairs."""

    def _assert_well_formed(self, game_name, result):
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result.keys()),
                         {"row_actions", "col_actions", "matrix"})
        # 2-action games on both sides.
        self.assertEqual(len(result["row_actions"]), 2)
        self.assertEqual(len(result["col_actions"]), 2)
        for label in result["row_actions"] + result["col_actions"]:
            self.assertIsInstance(label, str)
        # Matrix is 2x2 of [row_payoff, col_payoff] pairs of ints.
        self.assertEqual(len(result["matrix"]), 2)
        for row in result["matrix"]:
            self.assertEqual(len(row), 2)
            for pair in row:
                self.assertEqual(len(pair), 2)
                for v in pair:
                    self.assertIsInstance(v, int)
        # And, critically, the dict survives a JSON round trip — the
        # wrapper hands it back to the model as a role:"tool" message.
        roundtrip = json.loads(json.dumps(result))
        self.assertEqual(roundtrip, result)

    def test_every_enum_game_returns_well_formed_matrix(self):
        schema = load_schema()
        for game in input_schema(schema)["properties"]["game_name"]["enum"]:
            with self.subTest(game=game):
                self._assert_well_formed(game, mock_payoffs.get_payoff_matrix(game))

    def test_prisoners_dilemma_exact_payoffs(self):
        # Pin the canonical values so a careless edit can't silently
        # rebalance the game.
        result = mock_payoffs.get_payoff_matrix("prisoners_dilemma")
        self.assertEqual(result["row_actions"], ["cooperate", "defect"])
        self.assertEqual(result["col_actions"], ["cooperate", "defect"])
        self.assertEqual(result["matrix"],
                         [[[3, 3], [0, 5]], [[5, 0], [1, 1]]])

    def test_matching_pennies_is_zero_sum(self):
        result = mock_payoffs.get_payoff_matrix("matching_pennies")
        for row in result["matrix"]:
            for pair in row:
                self.assertEqual(sum(pair), 0,
                                 f"matching_pennies must be zero-sum; got {pair}")

    def test_unknown_game_raises_value_error(self):
        with self.assertRaises(ValueError) as cm:
            mock_payoffs.get_payoff_matrix("not_a_game")
        self.assertIn("unknown game_name", str(cm.exception))
        # The error lists the known games so the caller can recover.
        for known in mock_payoffs._GAMES:
            self.assertIn(known, str(cm.exception))


class InputArgumentValidationTest(unittest.TestCase):
    """The schema is enforced on inputs via jsonschema.validate."""

    def test_each_enum_game_validates_as_input(self):
        params = input_schema(load_schema())
        for game in params["properties"]["game_name"]["enum"]:
            with self.subTest(game=game):
                jsonschema.validate({"game_name": game}, params)

    def test_unknown_game_name_fails_validation(self):
        params = input_schema(load_schema())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"game_name": "not_a_game"}, params)

    def test_missing_game_name_fails_validation(self):
        params = input_schema(load_schema())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({}, params)

    def test_extra_property_fails_validation(self):
        params = input_schema(load_schema())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(
                {"game_name": "prisoners_dilemma", "rounds": 100}, params)


if __name__ == "__main__":
    unittest.main(verbosity=2)
