"""Frozen grader material that has no corresponding committed fix-side file."""

from __future__ import annotations

HCP008_GRADER = r'''from __future__ import annotations

import json
import sys
import types


# tool_probe imports live-driver helpers that are irrelevant to the pure
# message-builder contract.  Keep those surfaces inert and unavailable.
driver = types.ModuleType("bench.fp8_ab.driver")
driver.RUNS_DIR = None
driver.TEMPERATURE = 0.2
driver.TOP_P = 0.95
driver._default_http = lambda *args, **kwargs: (_ for _ in ()).throw(
    AssertionError("network helper must not run")
)
driver.write_artifact = lambda *args, **kwargs: (_ for _ in ()).throw(
    AssertionError("artifact writer must not run")
)
sys.modules["bench.fp8_ab.driver"] = driver

workers = types.ModuleType("workers")
skeptic = types.ModuleType("workers.novelty_skeptic")
skeptic._extract_json_object = lambda _text: None
workers.novelty_skeptic = skeptic
sys.modules["workers"] = workers
sys.modules["workers.novelty_skeptic"] = skeptic

from bench.fp8_ab import tool_probe


def test_message_replay_wire_types_and_trap_are_exact():
    assert len(tool_probe.TURNS) == 10
    assert tool_probe.script_sha256() == tool_probe.script_sha256()

    def dictionary_arguments(messages):
        return [
            call["function"]["arguments"]
            for message in messages
            if message.get("role") == "assistant"
            for call in (message.get("tool_calls") or [])
            if isinstance(call["function"]["arguments"], dict)
        ]

    for turn in range(10):
        first = tool_probe.build_messages(turn)
        assert first == tool_probe.build_messages(turn)
        dictionaries = dictionary_arguments(first)
        if turn == tool_probe.TRAP_REQUEST_TURN:
            assert dictionaries == [{"text": "\u03ba\u03b1\u03bb\u03b7\u03bc\u03ad\u03c1\u03b1 \u03ba\u03cc\u03c3\u03bc\u03b5 \u2713"}]
        else:
            assert dictionaries == []
        for message in first:
            for call in message.get("tool_calls") or []:
                arguments = call["function"]["arguments"]
                if isinstance(arguments, str):
                    assert isinstance(json.loads(arguments), dict)

    multi = [
        message
        for message in tool_probe.build_messages(8)
        if message.get("role") == "assistant"
        and len(message.get("tool_calls") or []) == 2
    ]
    assert len(multi) == 1
'''


GRADER_ASSETS = {"HCP-008": HCP008_GRADER}


__all__ = ["GRADER_ASSETS", "HCP008_GRADER"]
