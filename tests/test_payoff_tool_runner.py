from __future__ import annotations

import copy
import hashlib
import json
import threading
import time

import pytest

from bench.flash_next_ab import transport
from bench.payoff_tool_study import runner

CERT = {
    "endpoint_name": "resident_gemma",
    "served_model": "gemma-4-26b-a4b",
    "artifact_sha256": "a" * 64,
    "runtime_sha256": "b" * 64,
}


class FakeInvoke:
    def __init__(self, mode="valid"):
        self.mode = mode
        self.requests = []

    def __call__(self, endpoint, messages, *, policy, max_tokens, timeout_s, seed, tools, cancel_event):
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        fixture = next(
            f for f in runner._fixtures()
            if messages == runner._messages(f, tool_first=False)
            or messages == runner._messages(f, tool_first=True)
            or (len(messages) == 5 and messages[:2] == runner._messages(f, tool_first=True))
        )
        is_first = bool(tools)
        if self.mode == "timeout" and is_first and fixture["pair_id"] == "G1-seat0":
            exc = TimeoutError("fake finite transport timeout")
            acc = transport.StreamAccumulator(endpoint.served_model)
            exc.private_evidence = transport._private_response_evidence(acc, b"", response_bytes=0)
            raise exc
        if is_first:
            args = {k: fixture[k] for k in ("actions", "E", "m_num", "m_den")}
            if self.mode == "wrong_args" and fixture["pair_id"] == "G1-seat0":
                args["actions"] = [1, 0, 0, 0]  # same k, different action identity
            if self.mode in {"inline", "inline_marker"} and fixture["pair_id"] == "G1-seat0":
                content = json.dumps({"focal": fixture["focal"], "total": fixture["total"]})
                if self.mode == "inline_marker":
                    content = '<|tool_call|>{"name":"shared_return"}'
                tool_calls = []
                finish = "stop"
            else:
                content = "I will call the shared-return calculator." if self.mode == "narration" else ""
                tool_calls = [{
                    "index": 0, "id": "call-" + fixture["pair_id"], "type": "function",
                    "function": {
                        "name": "shared_return",
                        "arguments": json.dumps(args, sort_keys=True, separators=(",", ":")),
                    },
                }]
                finish = "tool_calls"
                if self.mode == "length" and fixture["pair_id"] == "G1-seat0":
                    finish = "length"
        else:
            content = json.dumps({"focal": fixture["focal"], "total": fixture["total"]}, separators=(",", ":"))
            tool_calls = []
            finish = "stop"
        response_id = "response-" + str(len(self.requests))
        obj = {
            "id": response_id, "model": endpoint.served_model,
            "choices": [{"index": 0, "delta": {"content": content, "tool_calls": tool_calls},
                         "finish_reason": finish}],
        }
        usage = {
            "id": response_id, "model": endpoint.served_model,
            "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        raw = (
            b"data: " + json.dumps(obj, separators=(",", ":")).encode() + b"\n\n"
            + b"data: " + json.dumps(usage, separators=(",", ":")).encode() + b"\n\n"
            + b"data: [DONE]\n\n"
        )
        acc = transport.StreamAccumulator(endpoint.served_model)
        for line in raw.splitlines():
            payload = transport._sse_data(line)
            if payload is not None:
                acc.accept(payload)
        result = acc.result()
        body = transport.request_body(endpoint, messages, policy, max_tokens, seed, tools)
        result.update({
            "request_sha256": hashlib.sha256(transport.canonical(body)).hexdigest(),
            "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
            "endpoint": endpoint.__dict__, "resolved_request": body,
            "response_bytes": len(raw), "retries": 0,
            "private_evidence": transport._private_response_evidence(acc, raw, response_bytes=len(raw)),
        })
        return result


def _run(tmp_path, mode="valid"):
    plan_path = tmp_path / "plan.json"
    runner.make_plan(CERT, plan_path)
    plan, _ = runner.load_plan(plan_path)
    fake = FakeInvoke(mode)
    gate = {
        "admitted": True, "runtime_certificate": CERT,
        "window_id": "test-window", "window_sha256": "c" * 64,
        "ready_proof_sha256": "d" * 64, "monitor_arm_sha256": "e" * 64,
    }
    output = tmp_path / "output"
    result = runner.run(
        plan_path=plan_path, output_dir=output, admission_gate=gate,
        cancel_event=threading.Event(), absolute_cutoff_monotonic=time.monotonic() + 1000,
        invoke_fn=fake,
    )
    return plan, plan_path, output, result, fake


def test_native_tool_calls_and_raw_replay_are_required(tmp_path):
    _, plan_path, output, result, fake = _run(tmp_path)
    assert result["status"] == "complete"
    assert result["issued_calls"] == 18
    assert len(result["declared_slots"]) == 18
    assert len(result["outcomes"]) == 12
    assert all(o["grade"]["details"]["both_correct"] for o in result["outcomes"])
    assert all(tools == [runner.TOOL_SPEC] for _, tools in fake.requests if tools)
    replay = runner.replay_run(plan_path, output)
    assert replay["admitted"] is True and replay["private_calls_verified"]
    streams = list((output / "private" / "streams").glob("*.sse"))
    assert streams
    streams[0].write_bytes(streams[0].read_bytes() + b"\n")
    with pytest.raises(runner.private_evidence.PrivateEvidenceError):
        runner.replay_run(plan_path, output)


@pytest.mark.parametrize("mode,code", [
    ("inline", "bypass_no_tool"),
    ("inline_marker", "parser_miss"),
    ("wrong_args", "wrong_args"),
    ("length", "tool_incomplete"),
    ("timeout", "timeout"),
])
def test_failed_native_invocation_skips_final_without_losing_denominator(tmp_path, mode, code):
    _, plan_path, output, result, fake = _run(tmp_path, mode)
    assert result["status"] == "complete"
    assert result["issued_calls"] == 17
    assert len(result["declared_slots"]) == 18
    by_slot = {s["slot_id"]: s for s in result["slots"]}
    assert by_slot["G1-seat0/tool_final"]["status"] == "skipped"
    assert by_slot["G1-seat0/tool_final"]["failure_code"] == code
    assert runner.replay_run(plan_path, output)["issued_calls"] == 17
    assert sum(1 for _, tools in fake.requests if tools) == 6


def test_equivalent_unreduced_fraction_does_not_pass_strict_shape():
    f = runner._fixtures()[0]
    assert runner._grade_final('{"focal":"66/16","total":"27/2"}', "returned", f)["strict_shape"] is False


def test_native_tool_narration_is_preserved_in_final_history(tmp_path):
    _, plan_path, output, result, fake = _run(tmp_path, "narration")
    assert result["issued_calls"] == 18
    final_messages = [messages for messages, tools in fake.requests if len(messages) == 5 and not tools]
    assert final_messages and all(messages[2]["content"] == "I will call the shared-return calculator."
                                  for messages in final_messages)
    assert runner.replay_run(plan_path, output)["admitted"] is True


def test_resealed_order_or_slot_receipt_cannot_pass_replay(tmp_path):
    _, plan_path, output, result, _ = _run(tmp_path)
    run_path = output / "run.json"
    result["outcomes"][0], result["outcomes"][1] = result["outcomes"][1], result["outcomes"][0]
    run_path.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(runner.ToolStudyError, match="order drift"):
        runner.replay_run(plan_path, output)
    result["outcomes"][0], result["outcomes"][1] = result["outcomes"][1], result["outcomes"][0]
    result["slots"][0]["failure_code"] = "forged_failure"
    run_path.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(runner.ToolStudyError, match="slot/receipt"):
        runner.replay_run(plan_path, output)
