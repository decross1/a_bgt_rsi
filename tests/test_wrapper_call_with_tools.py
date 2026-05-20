#!/usr/bin/env python3
"""
Day 4 unit tests for agent_wrapper.wrapper.call_with_tools.

Mocks the OpenAI sync client so we exercise the loop semantics, validation,
and logging without GPU. Tests cover:

  * Single-turn (no tool_calls) -> chain of length 1, no role:"tool" turn.
  * Two-turn (one tool_call) -> chain of length 2 linked by parent_request_id,
    second prompt_messages carries the role:"tool" result, completion of the
    first record is the JSON-serialized tool_calls.
  * Malformed JSON in tool_calls.arguments -> ToolCallError (NOT silently
    retried).
  * Schema-invalid args (json parses, but fails the parameters schema) ->
    ToolCallError.
  * Hallucinated tool name -> ToolCallError.
  * max_depth bound: model that keeps calling tools forever raises
    ToolCallError once max_depth is reached, but records up to that point
    are logged.
  * retrieval_context kwarg threads into every chain record.

Run standalone:
    python3 tests/test_wrapper_call_with_tools.py
"""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jsonschema import Draft202012Validator

from agent_wrapper import wrapper as W  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "calls.jsonl.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def _mk_resp(*, content=None, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    tcs = tool_calls or []
    msg = SimpleNamespace(content=content, tool_calls=tcs or None)
    return SimpleNamespace(
        model="gemma-4-26b-a4b",
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens,
                              completion_tokens=completion_tokens),
    )


def _mk_tool_call(*, id_="call_1", name="get_payoff_matrix",
                  arguments='{"game_name": "prisoners_dilemma"}'):
    return SimpleNamespace(
        id=id_,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "get_payoff_matrix",
        "description": "Return payoff matrix.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "game_name": {"type": "string",
                              "enum": ["prisoners_dilemma", "stag_hunt",
                                       "matching_pennies"]}
            },
            "required": ["game_name"],
        },
    },
}


def _impl(game_name):
    if game_name == "prisoners_dilemma":
        return {"matrix": [[[3, 3], [0, 5]], [[5, 0], [1, 1]]]}
    raise ValueError(game_name)


def _tools():
    return [{"spec": _TOOL_SPEC, "impl": _impl}]


PD_MESSAGES = [
    {"role": "system", "content": "Use the tool."},
    {"role": "user", "content": "What is the PD payoff matrix?"},
]


class SingleTurnTest(unittest.TestCase):
    def test_no_tool_calls_returns_one_record(self):
        with patch.object(W, "_sync_client", MagicMock()) as mc:
            mc.chat.completions.create.return_value = _mk_resp(
                content="The PD matrix is (3,3),(0,5),(5,0),(1,1).")
            W.MEMORY_LOG.clear()
            chain = W.call_with_tools(PD_MESSAGES, _tools(),
                                      caller_tag="t/single")
        self.assertEqual(len(chain), 1)
        rec = chain[0]
        _VALIDATOR.validate(rec)
        self.assertIsNone(rec["parent_request_id"])
        self.assertIn("3,3", rec["completion"])
        # The OpenAI request must have been issued exactly once.
        self.assertEqual(mc.chat.completions.create.call_count, 1)


class TwoTurnTest(unittest.TestCase):
    def test_one_tool_call_chains_two_records(self):
        with patch.object(W, "_sync_client", MagicMock()) as mc:
            mc.chat.completions.create.side_effect = [
                _mk_resp(content=None, tool_calls=[_mk_tool_call()]),
                _mk_resp(content="(3,3),(0,5),(5,0),(1,1)."),
            ]
            W.MEMORY_LOG.clear()
            chain = W.call_with_tools(PD_MESSAGES, _tools(),
                                      caller_tag="t/two_turn")
        self.assertEqual(len(chain), 2)
        first, second = chain
        _VALIDATOR.validate(first)
        _VALIDATOR.validate(second)
        # Chain linkage.
        self.assertIsNone(first["parent_request_id"])
        self.assertEqual(second["parent_request_id"], first["request_id"])
        # First completion is the JSON-serialized tool_calls (per the schema
        # contract -- completion is string).
        tc_payload = json.loads(first["completion"])
        self.assertEqual(tc_payload[0]["function"]["name"], "get_payoff_matrix")
        self.assertEqual(json.loads(tc_payload[0]["function"]["arguments"]),
                         {"game_name": "prisoners_dilemma"})
        # Second prompt_messages must include the tool turn carrying the impl's
        # result (matrix payoffs).
        tool_msgs = [m for m in second["prompt_messages"]
                     if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertIn("3", tool_msgs[0]["content"])

    def test_retrieval_context_threads_through_chain(self):
        ctx = [{"doc_id": "arxiv:1", "content_hash": "sha256:x",
                "chunk_offset": 0, "chunk_length": 1}]
        with patch.object(W, "_sync_client", MagicMock()) as mc:
            mc.chat.completions.create.side_effect = [
                _mk_resp(content=None, tool_calls=[_mk_tool_call()]),
                _mk_resp(content="done."),
            ]
            W.MEMORY_LOG.clear()
            chain = W.call_with_tools(PD_MESSAGES, _tools(),
                                      caller_tag="t/ctx",
                                      retrieval_context=ctx)
        for rec in chain:
            self.assertEqual(rec["retrieval_context"], ctx)
            _VALIDATOR.validate(rec)


class MalformedJsonTest(unittest.TestCase):
    def test_malformed_arguments_raises(self):
        with patch.object(W, "_sync_client", MagicMock()) as mc:
            mc.chat.completions.create.return_value = _mk_resp(
                tool_calls=[_mk_tool_call(arguments='{game_name: prisoners}')])
            W.MEMORY_LOG.clear()
            with self.assertRaises(W.ToolCallError) as cm:
                W.call_with_tools(PD_MESSAGES, _tools(),
                                  caller_tag="t/bad_json")
        self.assertIn("malformed JSON", str(cm.exception))
        # The failing first-turn record was still logged (we want SEE the failure).
        self.assertEqual(len(W.MEMORY_LOG), 1)


class SchemaViolationTest(unittest.TestCase):
    def test_args_violating_schema_raises(self):
        with patch.object(W, "_sync_client", MagicMock()) as mc:
            mc.chat.completions.create.return_value = _mk_resp(
                tool_calls=[_mk_tool_call(arguments='{"game_name": "chicken"}')])
            W.MEMORY_LOG.clear()
            with self.assertRaises(W.ToolCallError) as cm:
                W.call_with_tools(PD_MESSAGES, _tools(),
                                  caller_tag="t/bad_args")
        self.assertIn("failed schema validation", str(cm.exception))


class HallucinatedToolNameTest(unittest.TestCase):
    def test_unknown_tool_name_raises(self):
        with patch.object(W, "_sync_client", MagicMock()) as mc:
            mc.chat.completions.create.return_value = _mk_resp(
                tool_calls=[_mk_tool_call(name="who_dis")])
            W.MEMORY_LOG.clear()
            with self.assertRaises(W.ToolCallError) as cm:
                W.call_with_tools(PD_MESSAGES, _tools(),
                                  caller_tag="t/hallucinated")
        self.assertIn("hallucinated tool name", str(cm.exception))


class MaxDepthTest(unittest.TestCase):
    def test_unbounded_tool_loop_raises_after_max_depth(self):
        # Mock always returns a tool_call: never settles into a final answer.
        with patch.object(W, "_sync_client", MagicMock()) as mc:
            mc.chat.completions.create.return_value = _mk_resp(
                tool_calls=[_mk_tool_call()])
            W.MEMORY_LOG.clear()
            with self.assertRaises(W.ToolCallError) as cm:
                W.call_with_tools(PD_MESSAGES, _tools(),
                                  caller_tag="t/max_depth", max_depth=2)
        self.assertIn("max_depth", str(cm.exception))
        # Logged records up to max_depth+1 attempts before the raise.
        self.assertEqual(len(W.MEMORY_LOG), 3)
        # Every logged record is schema-valid (don't let chain-aborts emit junk).
        for rec in W.MEMORY_LOG:
            _VALIDATOR.validate(rec)

    def test_zero_max_depth_rejected(self):
        with self.assertRaises(ValueError):
            W.call_with_tools(PD_MESSAGES, _tools(), max_depth=0)


class FileRoundTripTest(unittest.TestCase):
    def test_chain_persists_to_file_and_round_trips(self):
        import tempfile
        with patch.object(W, "_sync_client", MagicMock()) as mc:
            mc.chat.completions.create.side_effect = [
                _mk_resp(content=None, tool_calls=[_mk_tool_call()]),
                _mk_resp(content="ok."),
            ]
            with tempfile.NamedTemporaryFile("w+", suffix=".jsonl",
                                              delete=False) as f:
                path = f.name
            try:
                chain = W.call_with_tools(PD_MESSAGES, _tools(),
                                          caller_tag="t/file",
                                          log_path=path)
                self.assertEqual(len(chain), 2)
                lines = [json.loads(l) for l in Path(path).read_text().splitlines() if l]
                self.assertEqual(len(lines), 2)
                self.assertEqual(lines[1]["parent_request_id"],
                                 lines[0]["request_id"])
                self.assertEqual(W.verify_log_integrity(path), 0)
            finally:
                Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
