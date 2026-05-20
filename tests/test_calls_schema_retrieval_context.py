#!/usr/bin/env python3
"""
Day 3.5 task -- regression tests for the optional `retrieval_context`
field added to schema/calls.jsonl.schema.json (proposal P2).

Covers:
  * The schema self-validates under Draft 2020-12.
  * Every record in any pre-existing logs/dayN.jsonl re-validates with
    zero failures (the field is OPTIONAL; absent on legacy records).
  * A record with a populated retrieval_context list validates.
  * A record with retrieval_context: null validates.
  * Marking retrieval_context as `required` rejects legacy records --
    proves the field is not silently load-bearing.

Run standalone:
    python3 tests/test_calls_schema_retrieval_context.py
or under pytest:
    pytest tests/test_calls_schema_retrieval_context.py
"""
import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "calls.jsonl.schema.json"
LOGS_DIR = REPO_ROOT / "logs"
LEGACY_LOG_NAMES = ("day1.jsonl", "day2.jsonl")


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def _base_record():
    """Minimal record that satisfies the pre-P2 schema (no retrieval_context)."""
    return {
        "timestamp": "2026-05-19T12:00:00.000000Z",
        "request_id": "11111111-2222-4333-8444-555555555555",
        "model": "gemma-4-26b-a4b-nvfp4",
        "model_version": "sha256:deadbeef",
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": None,
        "prompt_messages": [{"role": "user", "content": "ping"}],
        "completion": "pong",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "latency_ms": 12.3,
        "host_metadata": {
            "cuda_driver": "13.0",
            "vllm_image_tag": "vllm/vllm-openai:v0.21.0",
        },
        "caller_tag": "test_calls_schema_retrieval_context",
        "parent_request_id": None,
    }


class SchemaSelfValidationTest(unittest.TestCase):
    def test_schema_is_a_valid_draft_2020_12_schema(self):
        Draft202012Validator.check_schema(_load_schema())


class ExistingLogsRevalidateTest(unittest.TestCase):
    """Every record in logs/dayN.jsonl must still validate after the P2 addition."""

    def test_all_legacy_logs_validate(self):
        v = Draft202012Validator(_load_schema())
        any_log_seen = False
        for name in LEGACY_LOG_NAMES:
            log = LOGS_DIR / name
            if not log.exists():
                continue
            any_log_seen = True
            failures = []
            with log.open() as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    errs = list(v.iter_errors(rec))
                    if errs:
                        failures.append((name, lineno, errs[0].message))
            self.assertEqual(failures, [], f"legacy log {name} re-validation: {failures}")
        # The Day 2 sweep is the Track A artifact that motivates this guarantee;
        # we don't fabricate a pass when no log is present.
        self.assertTrue(any_log_seen, "no legacy logs found under logs/ -- "
                                      "expected at least one of: " + ", ".join(LEGACY_LOG_NAMES))


class PopulatedRetrievalContextTest(unittest.TestCase):
    def test_populated_list_validates(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = [
            {
                "doc_id": "arxiv:2401.12345",
                "content_hash": "sha256:" + "a" * 64,
                "chunk_offset": 1024,
                "chunk_length": 512,
            },
            {
                "doc_id": "arxiv:2403.67890",
                "content_hash": "sha256:" + "b" * 64,
                "chunk_offset": 0,
                "chunk_length": 256,
            },
        ]
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_empty_list_validates(self):
        # A retrieval call that returned zero hits is distinct from "no retrieval".
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = []
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_missing_inner_field_fails(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = [
            {"doc_id": "arxiv:2401.12345", "content_hash": "sha256:x",
             "chunk_offset": 0}  # chunk_length missing
        ]
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_unknown_inner_field_fails(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = [
            {"doc_id": "arxiv:2401.12345", "content_hash": "sha256:x",
             "chunk_offset": 0, "chunk_length": 1, "score": 0.42}
        ]
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_negative_offset_fails(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = [
            {"doc_id": "arxiv:2401.12345", "content_hash": "sha256:x",
             "chunk_offset": -1, "chunk_length": 1}
        ]
        self.assertNotEqual(list(v.iter_errors(rec)), [])


class NullRetrievalContextTest(unittest.TestCase):
    def test_null_validates(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = None
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_absent_validates(self):
        # Field is OPTIONAL: omitting it is identical to "no retrieval ran".
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        self.assertNotIn("retrieval_context", rec)
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_wrong_type_fails(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = "not-a-list"
        self.assertNotEqual(list(v.iter_errors(rec)), [])


class RequiredMarkingWouldFailTest(unittest.TestCase):
    """If retrieval_context were marked required, legacy records would fail.

    This guards the design intent: P2 is additive, not load-bearing. If a
    future edit promotes the field to required, this test fails and forces
    a conscious migration of legacy logs."""

    def test_required_marking_rejects_legacy_record(self):
        schema = _load_schema()
        # Hypothetical strict variant.
        strict = copy.deepcopy(schema)
        strict["required"] = list(strict["required"]) + ["retrieval_context"]
        v_strict = Draft202012Validator(strict)
        rec = _base_record()  # no retrieval_context key
        errs = list(v_strict.iter_errors(rec))
        self.assertTrue(errs, "strict variant must reject records missing retrieval_context")
        self.assertIn("retrieval_context", errs[0].message)

        # And the actual (non-strict) schema must still accept the same record.
        v_actual = Draft202012Validator(schema)
        self.assertEqual(list(v_actual.iter_errors(rec)), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
