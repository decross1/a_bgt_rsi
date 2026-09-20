from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import threading
from pathlib import Path

import pytest

from bench.flash_next_ab import transport
from bench.payoff_tool_study import runner as legacy
from experiments.payoff_tool_arithmetic import flash_resident as diagnostic


def _binding() -> dict:
    image = diagnostic.RUNTIME_IMAGE_ID
    binding = {
        "endpoint": {
            "name": diagnostic.ENDPOINT.name,
            "base_url": diagnostic.ENDPOINT.base_url,
            "served_model": diagnostic.ENDPOINT.served_model,
            "checkpoint_artifact_sha256": diagnostic.ENDPOINT.artifact_sha256,
        },
        "checkpoint": {
            "model_revision": diagnostic.MODEL_REVISION,
            "artifact_sha256": diagnostic.ENDPOINT.artifact_sha256,
        },
        "runtime": {
            "backend": "sglang-flash",
            "image_id": image,
            "profile_sha256": diagnostic.SERVING_PROFILE_SHA256,
            "context_length": 32768,
            "max_running_requests": 1,
            "host_reserve_gib": 20,
        },
        "deployment": {
            "path": str(diagnostic.CANONICAL_ROOT / "config/model_deployment.json"),
            "config_sha256": "4" * 64,
            "selected_at": "2026-09-19",
        },
        "live": {
            "boot_id": "12345678-1234-1234-1234-123456789abc",
            "pid": 101,
            "process_start_ticks": 202,
            "guard_pid": 303,
            "guard_start_ticks": 404,
            "container_id": "5" * 64,
            "image_id": image,
            "artifact_dir": "/private/resident-test",
        },
    }
    binding["live_identity_sha256"] = hashlib.sha256(
        json.dumps(
            binding["live"], sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return binding


class FakeInvoke:
    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode
        self.requests: list[tuple[list[dict], list[dict] | None]] = []

    def __call__(
        self, endpoint, messages, *, policy, max_tokens, timeout_s, seed,
        tools, cancel_event,
    ):
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        fixture = next(
            fixture for fixture in legacy._fixtures()
            if messages == legacy._messages(fixture, tool_first=False)
            or messages == legacy._messages(fixture, tool_first=True)
            or (
                len(messages) == 5
                and messages[:2] == legacy._messages(fixture, tool_first=True)
            )
        )
        first = bool(tools)
        if self.mode == "local_error" and len(self.requests) == 1:
            raise ValueError("local request wiring failed")
        if self.mode == "all_timeout":
            exc = TimeoutError("bounded fake timeout before any SSE")
            accumulator = transport.StreamAccumulator(endpoint.served_model)
            exc.private_evidence = transport._private_response_evidence(
                accumulator, b"", response_bytes=0
            )
            raise exc
        if self.mode == "timeout" and first and fixture["pair_id"] == "G1-seat0":
            exc = TimeoutError("bounded fake timeout")
            accumulator = transport.StreamAccumulator(endpoint.served_model)
            exc.private_evidence = transport._private_response_evidence(
                accumulator, b"", response_bytes=0
            )
            raise exc
        if first:
            arguments = {
                key: fixture[key] for key in ("actions", "E", "m_num", "m_den")
            }
            if self.mode == "wrong_args" and fixture["pair_id"] == "G1-seat0":
                arguments["actions"] = [1, 0, 0, 0]
            content = ""
            tool_calls = [{
                "index": 0,
                "id": "call-" + fixture["pair_id"],
                "type": "function",
                "function": {
                    "name": "shared_return",
                    "arguments": json.dumps(
                        arguments, sort_keys=True, separators=(",", ":")
                    ),
                },
            }]
            finish = "tool_calls"
        else:
            content = json.dumps(
                {"focal": fixture["focal"], "total": fixture["total"]},
                separators=(",", ":"),
            )
            tool_calls = []
            finish = "stop"
        response_id = f"fake-{len(self.requests)}"
        chunk = {
            "id": response_id,
            "model": endpoint.served_model,
            "choices": [{
                "index": 0,
                "delta": {"content": content, "tool_calls": tool_calls},
                "finish_reason": finish,
            }],
        }
        usage = {
            "id": response_id,
            "model": endpoint.served_model,
            "choices": [],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        raw = (
            b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"
            + b"data: " + json.dumps(usage, separators=(",", ":")).encode() + b"\n\n"
            + b"data: [DONE]\n\n"
        )
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        for line in raw.splitlines():
            payload = transport._sse_data(line)
            if payload is not None:
                accumulator.accept(payload)
        result = accumulator.result()
        body = transport.request_body(
            endpoint, messages, policy, max_tokens, seed, tools
        )
        result.update({
            "request_sha256": hashlib.sha256(transport.canonical(body)).hexdigest(),
            "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
            "endpoint": endpoint.__dict__,
            "resolved_request": body,
            "response_bytes": len(raw),
            "retries": 0,
            "private_evidence": transport._private_response_evidence(
                accumulator, raw, response_bytes=len(raw)
            ),
        })
        return result


def _prepare(tmp_path):
    binding = _binding()
    artifact_root = tmp_path / "artifacts"
    plan_path = artifact_root / "plan.json"
    plan = diagnostic.make_plan(
        plan_path,
        diagnostic_id="flash-payoff-test-v1",
        artifact_root=artifact_root,
        runtime_snapshot_fn=lambda: copy.deepcopy(binding),
        ready_fn=lambda: True,
        memory_fn=lambda: 21.0,
    )
    return binding, plan_path, plan


def _idle():
    return {
        "schema_version": "flash-payoff-idle-probe/v1",
        "endpoint_name": diagnostic.ENDPOINT.name,
        "running_requests": 0.0,
        "waiting_requests": 0.0,
        "metrics_sha256": "8" * 64,
        "metrics_bytes": 123,
        "observed_idle": True,
        "cooperative_exclusion_only": True,
        "direct_http_clients_excluded": False,
        "isolated_latency_claim": False,
    }


def _run(tmp_path, *, mode="valid", memory_fn=lambda: 21.0):
    binding, plan_path, _ = _prepare(tmp_path)
    fake = FakeInvoke(mode)
    output = Path(json.loads(plan_path.read_text())["artifact_policy"]["private_root"]) / "output"
    result = diagnostic.run(
        plan_path,
        output,
        cancel_event=threading.Event(),
        invoke_fn=fake,
        runtime_snapshot_fn=lambda: copy.deepcopy(binding),
        ready_fn=lambda: True,
        memory_fn=memory_fn,
        idle_probe_fn=_idle,
        lock_factory=lambda _root: contextlib.nullcontext(),
    )
    return plan_path, output, result, fake


def test_plan_binds_flash_identity_policy_inputs_and_limits(tmp_path):
    binding, plan_path, plan = _prepare(tmp_path)
    loaded, digest = diagnostic.load_plan(plan_path)
    assert loaded == plan
    assert len(plan["declared_pairs"]) == 6
    assert len(plan["declared_conditions"]) == 12
    assert len(plan["declared_slots"]) == 18
    assert plan["runtime_binding"] == binding
    assert plan["artifact_policy"]["private_root"] == str(tmp_path / "artifacts")
    assert plan["research_context"] == {
        "source_iteration_id": "iter-2026-09-15-007",
        "source_campaign": "v2-utility-mechanism-followon-20260915",
        "relationship": "motivation_only",
        "claim_binding": False,
        "diagnostic_stage": "preparatory_interface_diagnostic",
    }
    assert plan["policy"] == {
        "temperature": 0,
        "top_p": 1,
        "top_k": 64,
        "enable_thinking": False,
    }
    assert plan["limits"] == {
        "max_tokens": 256,
        "call_timeout_s": 90.0,
        "evaluator_budget_s": 900.0,
        "memory_floor_gib": 20.0,
        "max_calls": 18,
    }
    assert digest == hashlib.sha256(plan_path.read_bytes()).hexdigest()


def test_plan_relocates_by_exact_source_hash_not_checkout_path(tmp_path):
    _, plan_path, plan = _prepare(tmp_path)
    plan["code_root"] = "/tmp/reviewed-worktree-that-was-landed"
    plan_path.write_bytes(diagnostic._canonical(plan) + b"\n")
    loaded, _ = diagnostic.load_plan(plan_path)
    assert loaded["code_root"] == "/tmp/reviewed-worktree-that-was-landed"
    plan["source_sha256"][diagnostic.SOURCE_PATHS[0]] = "0" * 64
    plan_path.write_bytes(diagnostic._canonical(plan) + b"\n")
    with pytest.raises(diagnostic.FlashPayoffError, match="source drift"):
        diagnostic.load_plan(plan_path)


def test_complete_run_has_exhaustive_denominator_and_independent_replay(tmp_path):
    plan_path, output, result, fake = _run(tmp_path)
    assert result["status"] == "complete"
    assert result["accounting"] == {
        "declared_slots": 18,
        "attempted_calls": 18,
        "confirmed_dispatched_calls": 18,
        "wire_unknown_attempts": 0,
        "prewire_failures": 0,
        "returned_calls": 18,
        "failed_calls": 0,
        "skipped_unissued": 0,
        "unissued_after_abort": 0,
    }
    assert len(result["outcomes"]) == 12 and len(fake.requests) == 18
    public = (output / "run.json").read_text()
    assert '"content"' not in public and '"reasoning_content"' not in public
    replay = diagnostic.validate(plan_path, output)
    assert replay["status"] == "passed"
    assert replay["returned_streams_replayed"] == 18
    assert replay["private_content_exported"] is False
    assert replay["objective_summary"]["direct"] == {
        "correct": 6,
        "denominator": 6,
        "missing_cells": [],
        "failed_cells": [],
        "failure_categories": {},
    }
    assert replay["objective_summary"]["tool_invocation"]["exact"] == 6
    assert replay["objective_summary"]["tool_final"]["correct"] == 6
    assert replay["objective_summary"]["missing_cells"] == []
    assert replay["objective_summary"]["ragged_conditions"] == []
    assert replay["objective_summary"]["failed_cells"] == []


def test_invalid_tool_call_is_skipped_unissued_but_still_replayable(tmp_path):
    plan_path, output, result, _ = _run(tmp_path, mode="wrong_args")
    assert result["status"] == "complete"
    assert result["accounting"]["attempted_calls"] == 17
    assert result["accounting"]["confirmed_dispatched_calls"] == 17
    assert result["accounting"]["returned_calls"] == 17
    assert result["accounting"]["skipped_unissued"] == 1
    slot = next(
        item for item in result["slots"]
        if item["slot_id"] == "G1-seat0/tool_final"
    )
    assert slot["disposition"] == "skipped_unissued"
    assert slot["failure_code"] == "wrong_args"
    replay = diagnostic.validate(plan_path, output)
    assert replay["accounting"] == result["accounting"]
    summary = replay["objective_summary"]
    assert summary["direct"]["correct"] == 6
    assert summary["tool_invocation"]["exact"] == 5
    assert summary["tool_invocation"]["failure_categories"] == {"wrong_args": 1}
    assert summary["tool_final"]["correct"] == 5
    assert summary["tool_final"]["failure_categories"] == {"skipped": 1}
    assert summary["ragged_conditions"] == ["G1-seat0/tool"]
    assert summary["failed_cells"] == [
        "G1-seat0/tool_final", "G1-seat0/tool_first"
    ]


def test_failed_transport_and_empty_raw_stream_remain_auditable(tmp_path):
    plan_path, output, result, _ = _run(tmp_path, mode="timeout")
    assert result["status"] == "complete"
    assert result["accounting"]["failed_calls"] == 1
    assert result["accounting"]["returned_calls"] == 16
    assert result["accounting"]["wire_unknown_attempts"] == 1
    assert result["accounting"]["skipped_unissued"] == 1
    replay = diagnostic.validate(plan_path, output)
    assert replay["accounting"] == result["accounting"]
    assert replay["returned_streams_replayed"] == 16


def test_local_prewire_failure_aborts_and_is_not_a_dispatched_call(tmp_path):
    _, _, result, fake = _run(tmp_path, mode="local_error")
    assert result["status"] == "aborted"
    assert result["abort_reason"].startswith("prewire_failure:")
    assert result["accounting"] == {
        "declared_slots": 18,
        "attempted_calls": 1,
        "confirmed_dispatched_calls": 0,
        "wire_unknown_attempts": 0,
        "prewire_failures": 1,
        "returned_calls": 0,
        "failed_calls": 1,
        "skipped_unissued": 0,
        "unissued_after_abort": 17,
    }
    assert len(fake.requests) == 1


def test_zero_return_wire_unknown_attempts_cannot_complete(tmp_path):
    plan_path, output, result, _ = _run(tmp_path, mode="all_timeout")
    assert result["status"] == "aborted"
    assert result["abort_reason"] == "no_returned_model_responses"
    assert result["accounting"]["attempted_calls"] == 12
    assert result["accounting"]["wire_unknown_attempts"] == 12
    assert result["accounting"]["confirmed_dispatched_calls"] == 0
    assert result["accounting"]["returned_calls"] == 0
    assert result["accounting"]["skipped_unissued"] == 6
    with pytest.raises(diagnostic.FlashPayoffError, match="not complete"):
        diagnostic.validate(plan_path, output)


def test_zero_return_run_cannot_be_admitted_by_editing_terminal_fields(tmp_path):
    plan_path, output, result, _ = _run(tmp_path, mode="all_timeout")
    result["status"] = "complete"
    result["abort_reason"] = None
    (output / "run.json").write_bytes(diagnostic._canonical(result) + b"\n")
    with pytest.raises(
        diagnostic.FlashPayoffError, match="no returned model response"
    ):
        diagnostic.validate(plan_path, output)


def test_complete_run_cannot_contain_a_derived_prewire_failure(tmp_path):
    plan_path, output, result, _ = _run(tmp_path)
    slot = result["slots"][0]
    slot["call"]["status"] = "error"
    slot["call"]["dispatch_state"] = "prewire_failure"
    slot["call"]["failure_code"] = "local_error"
    slot["call"]["error"] = "synthetic local error"
    slot["call"]["response_stream_sha256"] = None
    slot["call"]["response_id"] = None
    slot["call"]["response_model"] = None
    slot["call"]["finish_reason"] = None
    slot["call"]["usage"] = None
    slot["disposition"] = "failed"
    slot["status"] = "error"
    slot["failure_code"] = "local_error"
    result["accounting"] = diagnostic._account(result["slots"])
    (output / "run.json").write_bytes(diagnostic._canonical(result) + b"\n")
    with pytest.raises(diagnostic.FlashPayoffError, match="pre-wire failure"):
        diagnostic.validate(plan_path, output)


def test_memory_loss_aborts_before_next_call_and_preserves_denominator(tmp_path):
    samples = iter([21.0, 21.0, 19.0])
    plan_path, output, result, fake = _run(
        tmp_path, memory_fn=lambda: next(samples, 19.0)
    )
    assert result["status"] == "aborted"
    assert result["abort_reason"] == "memory_floor_before_next_call"
    assert result["accounting"]["attempted_calls"] == 1
    assert result["accounting"]["unissued_after_abort"] == 17
    assert len(fake.requests) == 1
    assert sum(result["accounting"][key] for key in (
        "returned_calls", "failed_calls", "skipped_unissued", "unissued_after_abort"
    )) == 18
    with pytest.raises(diagnostic.FlashPayoffError, match="not complete"):
        diagnostic.validate(plan_path, output)


def test_busy_cooperative_resource_lease_refuses_freshly_without_a_call(tmp_path):
    binding, plan_path, _ = _prepare(tmp_path)
    output = Path(json.loads(plan_path.read_text())["artifact_policy"]["private_root"]) / "output"
    fake = FakeInvoke()

    @contextlib.contextmanager
    def busy(_root):
        raise diagnostic.FlashPayoffError("cooperative resource lease is busy")
        yield

    with pytest.raises(diagnostic.FlashPayoffError, match="busy"):
        diagnostic.run(
            plan_path,
            output,
            cancel_event=threading.Event(),
            invoke_fn=fake,
            runtime_snapshot_fn=lambda: binding,
            ready_fn=lambda: True,
            memory_fn=lambda: 21.0,
            idle_probe_fn=_idle,
            lock_factory=busy,
        )
    assert not output.exists() and not fake.requests


def test_busy_endpoint_probe_refuses_before_artifact_or_model_call(tmp_path):
    binding, plan_path, _ = _prepare(tmp_path)
    output = Path(json.loads(plan_path.read_text())["artifact_policy"]["private_root"]) / "output"
    fake = FakeInvoke()
    busy = _idle()
    busy.update(running_requests=1.0, observed_idle=False)
    with pytest.raises(diagnostic.FlashPayoffError, match="busy before diagnostic"):
        diagnostic.run(
            plan_path,
            output,
            cancel_event=threading.Event(),
            invoke_fn=fake,
            runtime_snapshot_fn=lambda: binding,
            ready_fn=lambda: True,
            memory_fn=lambda: 21.0,
            idle_probe_fn=lambda: busy,
            lock_factory=lambda _root: contextlib.nullcontext(),
        )
    assert not output.exists() and not fake.requests


def test_live_identity_drift_aborts_before_issuing(tmp_path):
    binding, plan_path, _ = _prepare(tmp_path)
    changed = copy.deepcopy(binding)
    changed["live"]["container_id"] = "7" * 64
    changed["live_identity_sha256"] = hashlib.sha256(
        json.dumps(
            changed["live"], sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    snapshots = iter([copy.deepcopy(binding), changed])
    fake = FakeInvoke()
    output = Path(json.loads(plan_path.read_text())["artifact_policy"]["private_root"]) / "output"
    result = diagnostic.run(
        plan_path,
        output,
        cancel_event=threading.Event(),
        invoke_fn=fake,
        runtime_snapshot_fn=lambda: next(snapshots, changed),
        ready_fn=lambda: True,
        memory_fn=lambda: 21.0,
        idle_probe_fn=_idle,
        lock_factory=lambda _root: contextlib.nullcontext(),
    )
    assert result["status"] == "aborted"
    assert result["abort_reason"] == "runtime_identity_changed_before_next_call"
    assert result["accounting"]["attempted_calls"] == 0
    assert result["accounting"]["unissued_after_abort"] == 18
    assert not fake.requests


def test_raw_sse_tamper_is_rejected(tmp_path):
    plan_path, output, _, _ = _run(tmp_path)
    stream = next((output / "private/streams").glob("*.sse"))
    stream.write_bytes(stream.read_bytes() + b"\n")
    with pytest.raises(diagnostic.FlashPayoffError, match="SSE bytes differ"):
        diagnostic.validate(plan_path, output)


def test_public_schema_cannot_be_extended_with_response_content(tmp_path):
    plan_path, output, result, _ = _run(tmp_path)
    result["content"] = "must remain private"
    (output / "run.json").write_bytes(diagnostic._canonical(result) + b"\n")
    with pytest.raises(diagnostic.FlashPayoffError, match="run shape differs"):
        diagnostic.validate(plan_path, output)
