#!/usr/bin/env python3
"""
Day 3.5 task -- agent_wrapper retrieval_context passthrough (proposal P2).

Covers:
  * call_sync default (no kwarg)              -> record OMITS retrieval_context.
  * call_sync retrieval_context=None          -> record OMITS retrieval_context
                                                  (semantically: no retrieval ran).
  * call_sync retrieval_context=[...]         -> record CARRIES the list verbatim.
  * call_async retrieval_context=[...]        -> same, async path.
  * Both produced records validate against schema/calls.jsonl.schema.json.
  * Existing callers (no kwarg) are byte-identical for the legacy keys.

Mocks the OpenAI client to avoid needing GPU. Run standalone:
    python3 tests/test_wrapper_retrieval_context.py
or under pytest.
"""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jsonschema import Draft202012Validator

from agent_wrapper import wrapper as W  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "calls.jsonl.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def _mock_response():
    """Shape vLLM/OpenAI response well enough for _record()."""
    return SimpleNamespace(
        model="gemma-4-26b-a4b",
        choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


_SAMPLE_CTX = [
    {
        "doc_id": "arxiv:2401.12345",
        "content_hash": "sha256:" + "a" * 64,
        "chunk_offset": 1024,
        "chunk_length": 512,
    }
]


def _msgs():
    return [{"role": "user", "content": "ping"}]


class SyncDefaultOmitsFieldTest(unittest.TestCase):
    def test_no_kwarg_means_field_absent(self):
        with patch.object(W, "_sync_client", MagicMock()) as mock_client:
            mock_client.chat.completions.create.return_value = _mock_response()
            W.MEMORY_LOG.clear()
            rec = W.call_sync(_msgs(), caller_tag="t/default")
        self.assertNotIn("retrieval_context", rec)
        _VALIDATOR.validate(rec)

    def test_explicit_none_means_field_absent(self):
        with patch.object(W, "_sync_client", MagicMock()) as mock_client:
            mock_client.chat.completions.create.return_value = _mock_response()
            W.MEMORY_LOG.clear()
            rec = W.call_sync(_msgs(), caller_tag="t/none",
                              retrieval_context=None)
        self.assertNotIn("retrieval_context", rec)
        _VALIDATOR.validate(rec)


class SyncPopulatedListTest(unittest.TestCase):
    def test_populated_list_threads_through(self):
        with patch.object(W, "_sync_client", MagicMock()) as mock_client:
            mock_client.chat.completions.create.return_value = _mock_response()
            W.MEMORY_LOG.clear()
            rec = W.call_sync(_msgs(), caller_tag="t/populated",
                              retrieval_context=_SAMPLE_CTX)
        self.assertEqual(rec["retrieval_context"], _SAMPLE_CTX)
        _VALIDATOR.validate(rec)

    def test_empty_list_threads_through(self):
        # Empty list means "retrieval ran, returned zero hits" -- distinct from None.
        with patch.object(W, "_sync_client", MagicMock()) as mock_client:
            mock_client.chat.completions.create.return_value = _mock_response()
            W.MEMORY_LOG.clear()
            rec = W.call_sync(_msgs(), caller_tag="t/empty",
                              retrieval_context=[])
        self.assertEqual(rec["retrieval_context"], [])
        _VALIDATOR.validate(rec)


class AsyncPathTest(unittest.TestCase):
    def test_async_populated_list_threads_through(self):
        with patch.object(W, "_async_client", MagicMock()) as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=_mock_response())
            W.MEMORY_LOG.clear()
            rec = asyncio.run(W.call_async(_msgs(), caller_tag="t/async/populated",
                                            retrieval_context=_SAMPLE_CTX))
        self.assertEqual(rec["retrieval_context"], _SAMPLE_CTX)
        _VALIDATOR.validate(rec)

    def test_async_default_omits_field(self):
        with patch.object(W, "_async_client", MagicMock()) as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=_mock_response())
            W.MEMORY_LOG.clear()
            rec = asyncio.run(W.call_async(_msgs(), caller_tag="t/async/default"))
        self.assertNotIn("retrieval_context", rec)
        _VALIDATOR.validate(rec)


class FilePersistenceTest(unittest.TestCase):
    """Persistence path: log_path=<file> must write the field verbatim and the
    resulting JSONL must round-trip through verify_log_integrity()."""

    def test_round_trip_through_file(self):
        import tempfile
        with patch.object(W, "_sync_client", MagicMock()) as mock_client:
            mock_client.chat.completions.create.return_value = _mock_response()
            with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False) as f:
                path = f.name
            try:
                W.call_sync(_msgs(), caller_tag="t/file/none", log_path=path)
                W.call_sync(_msgs(), caller_tag="t/file/populated",
                            retrieval_context=_SAMPLE_CTX, log_path=path)
                lines = [json.loads(l) for l in Path(path).read_text().splitlines() if l]
                self.assertEqual(len(lines), 2)
                self.assertNotIn("retrieval_context", lines[0])
                self.assertEqual(lines[1]["retrieval_context"], _SAMPLE_CTX)
                self.assertEqual(W.verify_log_integrity(path), 0)
            finally:
                Path(path).unlink(missing_ok=True)


class LegacyCallersUnchangedTest(unittest.TestCase):
    """A caller that does not pass retrieval_context must not observe any new
    keys in the returned record beyond the 14 documented ones plus the
    always-stamped provenance field `backend` (2026-06-10 UI-attribution
    contract: every new record names the backend registry entry that served
    it; pre-2026-06-10 records validate without it)."""

    LEGACY_KEYS = {
        "timestamp", "request_id", "model", "model_version", "temperature",
        "top_p", "seed", "prompt_messages", "completion", "usage",
        "latency_ms", "host_metadata", "caller_tag", "parent_request_id",
        "backend",
    }

    def test_legacy_record_has_only_legacy_keys(self):
        with patch.object(W, "_sync_client", MagicMock()) as mock_client:
            mock_client.chat.completions.create.return_value = _mock_response()
            W.MEMORY_LOG.clear()
            rec = W.call_sync(_msgs(), caller_tag="t/legacy")
        self.assertEqual(set(rec.keys()), self.LEGACY_KEYS)


class Day2SweepRegressionTest(unittest.TestCase):
    """Day-2 50-call sweep fixture equivalent: every record in logs/day2.jsonl
    must re-validate against the updated schema with zero malformed records.

    This is the explicit regression gate from plan.yaml day3_5 §
    day3_5_block2_wrapper_retrieval_passthrough. Track A's wrapper change
    cannot land if a single Day-2 record now fails."""

    def test_day2_jsonl_revalidates(self):
        log = Path(__file__).resolve().parent.parent / "logs" / "day2.jsonl"
        if not log.exists():
            self.skipTest(f"{log} missing; nothing to re-validate")
        n, bad = 0, []
        with log.open() as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                n += 1
                errs = list(_VALIDATOR.iter_errors(json.loads(line)))
                if errs:
                    bad.append((i, errs[0].message))
        self.assertEqual(bad, [], f"day2.jsonl regressed: {bad}")
        self.assertGreaterEqual(n, 50,
                                 f"day2.jsonl has {n} records, expected >=50")


if __name__ == "__main__":
    unittest.main(verbosity=2)
