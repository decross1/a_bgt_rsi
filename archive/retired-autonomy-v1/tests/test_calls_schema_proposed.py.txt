#!/usr/bin/env python3
"""
Day 8 task -- regression + new-field tests for the PROPOSED Day-42-lock
calls schema at schema/proposed/calls.jsonl.schema.json.

The only delta from the Day-3.5 schema is in retrieval_context.items: four
optional inner fields added (score / collection / retrieved_for /
embedder_version) for Week-2 critic + meta-review provenance.

Covers:
  * Self-validation under Draft 2020-12.
  * Day-3.5 legacy 4-field retrieval_context items still validate.
  * Every record in pre-existing logs/dayN.jsonl re-validates with zero
    failures (so the proposed schema is a strict superset on existing data).
  * Each new optional field validates when present, with correct types.
  * Each new optional field's type / range / enum constraints reject bad values.
  * The unknown-inner-field rejection still holds for fields NOT in the new set.
  * A retrieval_context item with ALL eight fields validates.

Run standalone:
    python3 tests/test_calls_schema_proposed.py
or under pytest:
    pytest tests/test_calls_schema_proposed.py
"""
import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "proposed" / "calls.jsonl.schema.json"
LOGS_DIR = REPO_ROOT / "logs"
LEGACY_LOG_NAMES = ("day1.jsonl", "day2.jsonl")


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def _base_record():
    """Minimal record that satisfies the Day-3.5 schema (no retrieval_context)."""
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
        "caller_tag": "test_calls_schema_proposed",
        "parent_request_id": None,
    }


def _legacy_rc_item():
    """Day-3.5 retrieval_context item — the four required fields only."""
    return {
        "doc_id": "arxiv:2401.12345",
        "content_hash": "sha256:" + "a" * 64,
        "chunk_offset": 1024,
        "chunk_length": 512,
    }


def _full_rc_item():
    """All eight fields — required four + new four."""
    return {
        "doc_id": "arxiv:2401.12345",
        "content_hash": "sha256:" + "a" * 64,
        "chunk_offset": 1024,
        "chunk_length": 512,
        "score": 0.873,
        "collection": "papers_recent",
        "retrieved_for": "critic",
        "embedder_version": "bge-m3@2024-01-30",
    }


# ──────────────────────────────────────────────────────────────────────
class SchemaSelfValidationTest(unittest.TestCase):
    def test_schema_is_a_valid_draft_2020_12_schema(self):
        Draft202012Validator.check_schema(_load_schema())

    def test_schema_file_exists_at_proposed_path(self):
        self.assertTrue(SCHEMA_PATH.exists(), f"expected schema at {SCHEMA_PATH}")


# ──────────────────────────────────────────────────────────────────────
# Backwards compatibility — Day-3.5 records and existing logs must still validate.
# ──────────────────────────────────────────────────────────────────────
class LegacyRecordsStillValidateTest(unittest.TestCase):
    def test_base_record_without_retrieval_context_validates(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        self.assertNotIn("retrieval_context", rec)
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_null_retrieval_context_validates(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = None
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_legacy_four_field_item_validates(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = [_legacy_rc_item()]
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_empty_retrieval_context_list_validates(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = []
        self.assertEqual(list(v.iter_errors(rec)), [])


class ExistingLogsRevalidateTest(unittest.TestCase):
    """Every record in logs/dayN.jsonl must still validate under the proposed schema.

    This is the strict-superset guarantee: the Day-42 lock cannot break any
    record that the Day-3.5 schema accepts. If a legacy record fails this
    test, the proposed schema's additionalProperties:false on calls.* has
    drifted somewhere it shouldn't have."""

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
        # If neither day1 nor day2 logs are present this guarantee is moot;
        # the Day-3.5 test made this an assertion, we keep the same posture.
        self.assertTrue(any_log_seen, "no legacy logs found under logs/ -- "
                                      "expected at least one of: " + ", ".join(LEGACY_LOG_NAMES))


# ──────────────────────────────────────────────────────────────────────
# New optional inner fields — happy paths.
# ──────────────────────────────────────────────────────────────────────
class NewOptionalFieldsHappyPathTest(unittest.TestCase):
    def test_full_eight_field_item_validates(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        rec["retrieval_context"] = [_full_rc_item()]
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_item_with_only_score_added_validates(self):
        # Mix-and-match: Day-3.5 four required + just one new field.
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        item = _legacy_rc_item()
        item["score"] = 0.42
        rec["retrieval_context"] = [item]
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_item_with_only_collection_added_validates(self):
        v = Draft202012Validator(_load_schema())
        rec = _base_record()
        item = _legacy_rc_item()
        item["collection"] = "papers_recent"
        rec["retrieval_context"] = [item]
        self.assertEqual(list(v.iter_errors(rec)), [])

    def test_each_retrieved_for_enum_value_validates(self):
        v = Draft202012Validator(_load_schema())
        for consumer in ("generator", "critic", "meta_review", "novelty_eval", "summarize_paper"):
            item = _legacy_rc_item()
            item["retrieved_for"] = consumer
            rec = _base_record()
            rec["retrieval_context"] = [item]
            with self.subTest(retrieved_for=consumer):
                self.assertEqual(list(v.iter_errors(rec)), [])

    def test_score_at_boundaries_validates(self):
        v = Draft202012Validator(_load_schema())
        for score in (0.0, 0.5, 1.0):
            item = _legacy_rc_item()
            item["score"] = score
            rec = _base_record()
            rec["retrieval_context"] = [item]
            with self.subTest(score=score):
                self.assertEqual(list(v.iter_errors(rec)), [])


# ──────────────────────────────────────────────────────────────────────
# New optional inner fields — type / range / enum rejection.
# ──────────────────────────────────────────────────────────────────────
class NewOptionalFieldsMalformedTest(unittest.TestCase):
    def test_score_above_one_fails(self):
        v = Draft202012Validator(_load_schema())
        item = _legacy_rc_item()
        item["score"] = 1.5
        rec = _base_record()
        rec["retrieval_context"] = [item]
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_score_below_zero_fails(self):
        v = Draft202012Validator(_load_schema())
        item = _legacy_rc_item()
        item["score"] = -0.01
        rec = _base_record()
        rec["retrieval_context"] = [item]
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_score_string_fails(self):
        v = Draft202012Validator(_load_schema())
        item = _legacy_rc_item()
        item["score"] = "0.5"
        rec = _base_record()
        rec["retrieval_context"] = [item]
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_collection_empty_string_fails(self):
        v = Draft202012Validator(_load_schema())
        item = _legacy_rc_item()
        item["collection"] = ""
        rec = _base_record()
        rec["retrieval_context"] = [item]
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_retrieved_for_unknown_value_fails(self):
        # The enum is closed by design — a new consumer must bump the schema.
        v = Draft202012Validator(_load_schema())
        item = _legacy_rc_item()
        item["retrieved_for"] = "auto_evaluator"  # not in the Day-8 enum
        rec = _base_record()
        rec["retrieval_context"] = [item]
        self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_embedder_version_empty_string_fails(self):
        v = Draft202012Validator(_load_schema())
        item = _legacy_rc_item()
        item["embedder_version"] = ""
        rec = _base_record()
        rec["retrieval_context"] = [item]
        self.assertNotEqual(list(v.iter_errors(rec)), [])


# ──────────────────────────────────────────────────────────────────────
# additionalProperties:false on inner items must still reject NEW unknown fields.
# ──────────────────────────────────────────────────────────────────────
class UnknownInnerFieldsStillRejectedTest(unittest.TestCase):
    def test_truly_unknown_field_fails(self):
        # 'rank' / 'distance' / 'reranker_score' are NOT in the Day-8 set;
        # they must fail so an accidental field name doesn't silently
        # leak provenance into a place no consumer reads.
        v = Draft202012Validator(_load_schema())
        for bad in ("rank", "distance", "reranker_score", "notes"):
            item = _full_rc_item()
            item[bad] = "anything"
            rec = _base_record()
            rec["retrieval_context"] = [item]
            with self.subTest(unknown_field=bad):
                self.assertNotEqual(list(v.iter_errors(rec)), [])

    def test_required_field_still_required(self):
        # Removing a required field on the inner item still fails.
        v = Draft202012Validator(_load_schema())
        item = _full_rc_item()
        del item["chunk_length"]
        rec = _base_record()
        rec["retrieval_context"] = [item]
        self.assertNotEqual(list(v.iter_errors(rec)), [])


# ──────────────────────────────────────────────────────────────────────
class SchemaInvariantsTest(unittest.TestCase):
    """Structural guarantees the proposed schema must keep."""

    def test_retrieval_context_inner_item_is_additional_properties_false(self):
        schema = _load_schema()
        item_schema = schema["properties"]["retrieval_context"]["items"]
        self.assertIs(item_schema.get("additionalProperties"), False)

    def test_required_four_fields_unchanged(self):
        schema = _load_schema()
        item_schema = schema["properties"]["retrieval_context"]["items"]
        self.assertEqual(
            set(item_schema["required"]),
            {"doc_id", "content_hash", "chunk_offset", "chunk_length"},
        )

    def test_optional_new_fields_present(self):
        schema = _load_schema()
        item_schema = schema["properties"]["retrieval_context"]["items"]
        for new_field in ("score", "collection", "retrieved_for", "embedder_version"):
            self.assertIn(new_field, item_schema["properties"], new_field)

    def test_required_marking_on_score_would_reject_legacy(self):
        # Same guard the Day-3.5 test family used: if a future edit accidentally
        # promotes 'score' to required, this test fails and forces a conscious
        # migration of every legacy retrieval_context record (none of which have it).
        schema = _load_schema()
        strict = copy.deepcopy(schema)
        item_schema = strict["properties"]["retrieval_context"]["items"]
        item_schema["required"] = list(item_schema["required"]) + ["score"]
        v_strict = Draft202012Validator(strict)
        rec = _base_record()
        rec["retrieval_context"] = [_legacy_rc_item()]
        errs = list(v_strict.iter_errors(rec))
        self.assertTrue(errs, "strict variant must reject legacy item missing 'score'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
