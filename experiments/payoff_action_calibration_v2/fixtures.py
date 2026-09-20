"""Injected transport fixtures for the offline v2 runner tests."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from bench.flash_next_ab import transport
from experiments.payoff_tool_arithmetic import flash_resident as resident

from . import design


def runtime_binding() -> dict[str, Any]:
    image = resident.RUNTIME_IMAGE_ID
    value = {
        "endpoint": {
            "name": resident.ENDPOINT.name,
            "base_url": resident.ENDPOINT.base_url,
            "served_model": resident.ENDPOINT.served_model,
            "checkpoint_artifact_sha256": resident.ENDPOINT.artifact_sha256,
        },
        "checkpoint": {
            "model_revision": resident.MODEL_REVISION,
            "artifact_sha256": resident.ENDPOINT.artifact_sha256,
        },
        "runtime": {
            "backend": "sglang-flash",
            "image_id": image,
            "profile_sha256": resident.SERVING_PROFILE_SHA256,
            "context_length": 32768,
            "max_running_requests": 1,
            "host_reserve_gib": 20,
        },
        "deployment": {
            "path": str(resident.CANONICAL_ROOT / "config/model_deployment.json"),
            "config_sha256": "4" * 64,
            "selected_at": "2026-09-20",
        },
        "live": {
            "boot_id": "12345678-1234-1234-1234-123456789abc",
            "pid": 101,
            "process_start_ticks": 202,
            "guard_pid": 303,
            "guard_start_ticks": 404,
            "container_id": "5" * 64,
            "image_id": image,
            "artifact_dir": "/private/resident-v2-test",
        },
    }
    value["live_identity_sha256"] = hashlib.sha256(
        json.dumps(value["live"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value


def idle_observation() -> dict[str, Any]:
    return {
        "schema_version": "flash-payoff-idle-probe/v1",
        "endpoint_name": resident.ENDPOINT.name,
        "running_requests": 0.0,
        "waiting_requests": 0.0,
        "metrics_sha256": "8" * 64,
        "metrics_bytes": 123,
        "observed_idle": True,
        "cooperative_exclusion_only": True,
        "direct_http_clients_excluded": False,
        "isolated_latency_claim": False,
    }


class FakeInvoke:
    """Return deterministic SSE while exercising the real transport accumulator."""

    def __init__(
        self,
        *,
        malformed_tools: bool = False,
        wrong_finals: bool = False,
        pretool_content: str = "",
        reasoning_content: str = "fixture reasoning",
    ) -> None:
        self.requests = 0
        self.malformed_tools = malformed_tools
        self.wrong_finals = wrong_finals
        self.pretool_content = pretool_content
        self.reasoning_content = reasoning_content
        self._cells = design.panel()

    def _condition(self, messages: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
        for cell in self._cells:
            for arm in cell["arm_order"]:
                if messages[:2] == design.messages(cell, arm):
                    return cell, arm
        raise AssertionError("fixture request does not match a frozen condition")

    def __call__(
        self,
        endpoint,
        messages,
        *,
        policy,
        max_tokens,
        timeout_s,
        seed,
        tools,
        cancel_event,
    ) -> dict[str, Any]:
        del timeout_s, cancel_event
        self.requests += 1
        cell, arm = self._condition(messages)
        if tools:
            expectation = design.expectation(cell, arm)
            name = expectation.name
            arguments = dict(expectation.expected_arguments)
            if self.malformed_tools:
                name = "wrong_tool"
            content = self.pretool_content
            tool_calls = [
                {
                    "index": 0,
                    "id": f"call-{cell['cell_id']}-{arm}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, separators=(",", ":")),
                    },
                }
            ]
            finish_reason = "tool_calls"
        else:
            actions = (
                cell["controls"]["myopic_plan"]
                if self.wrong_finals
                else cell["controls"]["oracle_plan"]
            )
            content = json.dumps(
                {"probe": cell["expected_probe"], "actions": actions},
                separators=(",", ":"),
            )
            tool_calls = []
            finish_reason = "stop"

        response_id = f"fake-v2-{self.requests}"
        chunk = {
            "id": response_id,
            "model": endpoint.served_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": content,
                        "reasoning_content": self.reasoning_content,
                        "tool_calls": tool_calls,
                    },
                    "finish_reason": finish_reason,
                }
            ],
        }
        usage = {
            "id": response_id,
            "model": endpoint.served_model,
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        raw = (
            b"data: "
            + json.dumps(chunk, separators=(",", ":")).encode()
            + b"\n\n"
            + b"data: "
            + json.dumps(usage, separators=(",", ":")).encode()
            + b"\n\n"
            + b"data: [DONE]\n\n"
        )
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        for line in raw.splitlines():
            payload = transport._sse_data(line)
            if payload is not None:
                accumulator.accept(payload)
        result = accumulator.result()
        body = transport.request_body(endpoint, messages, policy, max_tokens, seed, tools)
        result.update(
            {
                "request_sha256": hashlib.sha256(transport.canonical(body)).hexdigest(),
                "response_stream_sha256": hashlib.sha256(raw).hexdigest(),
                "endpoint": endpoint.__dict__,
                "resolved_request": copy.deepcopy(body),
                "response_bytes": len(raw),
                "retries": 0,
                "private_evidence": transport._private_response_evidence(
                    accumulator, raw, response_bytes=len(raw)
                ),
            }
        )
        return result


def prepare_plan(tmp_path: Path) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    binding = runtime_binding()
    root = tmp_path / "artifacts"
    plan_path = root / "plan.json"
    plan = design.make_plan(
        plan_path,
        study_id="excluded-native-tool-v2-test",
        artifact_root=root,
        runtime_snapshot_fn=lambda: copy.deepcopy(binding),
        ready_fn=lambda: True,
        memory_fn=lambda: 21.0,
    )
    return binding, root, plan_path, plan


__all__ = ["FakeInvoke", "idle_observation", "prepare_plan", "runtime_binding"]
