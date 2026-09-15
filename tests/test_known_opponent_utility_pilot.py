"""CPU-only producer tests for the registered known-opponent utility pilot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bench.agentic_game_theory import optimal_control
from bench.flash_next_ab import transport
from experiments.known_opponent_utility import pilot
from experiments.known_opponent_utility.admission import (
    PilotAdmissionError,
    validate_pilot,
)
from experiments.known_opponent_utility.loop_bridge import build_bridge_payload


def _manifest():
    root = Path(optimal_control.__file__).resolve().parents[2]
    endpoint = transport.LocalEndpoint(
        "flash_next_mia", "http://127.0.0.1:8012",
        "qwen3.8-flash-next-mia", transport.MIA_ARTIFACT_SHA256)
    receipt = {
        "schema_version": "flash-next-qualification-validation/v3",
        "cohort": "flash", "status": "passed", "admission_eligible": True,
        "variant_id": "unit-test-only", "endpoint_name": endpoint.name,
        "served_model": endpoint.served_model,
        "model_artifact_sha256": endpoint.artifact_sha256,
        "qualification_receipt_sha256": "a" * 64,
    }
    manifest = pilot.freeze_manifest(
        source_root=root, endpoint=endpoint, registered_admission=receipt,
        policy={"temperature": 0, "top_p": 1, "enable_thinking": False},
        seed=107, max_tokens=64, per_call_timeout_s=10)
    return manifest, receipt


def _fake(content_fn, *, drift_first=False):
    attempts = 0

    def invoke(endpoint, messages, *, policy, max_tokens, timeout_s, seed,
               cancel_event=None):
        nonlocal attempts
        attempts += 1
        body = transport.request_body(endpoint, messages, policy, max_tokens, seed)
        request_sha = hashlib.sha256(transport.canonical(body)).hexdigest()
        content = content_fn(attempts)
        raw = f"data: public-unit-test-{attempts}\n\n".encode()
        return {"content": content,
                "request_sha256": "0" * 64 if drift_first and attempts == 1 else request_sha,
                "latency_s": 0.1, "ttft_s": 0.05,
                "usage": {"prompt_tokens": 10, "completion_tokens": 1},
                "private_evidence": {"content": content, "reasoning_content": "",
                                     "tool_calls": [], "raw_response_stream": raw}}

    return invoke


def _real_sse_fake(*, invalid_actions: bool = False):
    def invoke(endpoint, messages, *, policy, max_tokens, timeout_s, seed,
               cancel_event=None):
        body = transport.request_body(endpoint, messages, policy, max_tokens, seed)
        request_sha = hashlib.sha256(transport.canonical(body)).hexdigest()
        if messages[-1]["content"].startswith("Arithmetic check"):
            content = ("focal=10;sum=30" if "focal seat 3" in messages[-1]["content"]
                       else "focal=5;sum=30")
        else:
            content = "maybe" if invalid_actions else "0"
        chunk = {
            "id": f"local-{seed}", "model": endpoint.served_model,
            "choices": [{"index": 0, "delta": {"content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1,
                      "total_tokens": 11},
        }
        payload = json.dumps(chunk, separators=(",", ":"))
        raw = f"data: {payload}\n\ndata: [DONE]\n\n".encode()
        accumulator = transport.StreamAccumulator(endpoint.served_model)
        accumulator.accept(payload)
        accumulator.accept("[DONE]")
        evidence = transport._private_response_evidence(
            accumulator, raw, response_bytes=len(raw))
        return {
            "content": content, "request_sha256": request_sha,
            "latency_s": 0.1, "ttft_s": 0.05,
            "usage": chunk["usage"], "private_evidence": evidence,
        }

    return invoke


def test_exact_schedule_and_matched_comprehension():
    manifest, _ = _manifest()
    assert len(manifest["schedule"]) == 12
    assert len({row["id"] for row in manifest["schedule"]}) == 12
    for mix in pilot.MIXES:
        for seat in pilot.SEATS:
            rows = [row for row in manifest["schedule"]
                    if row["mix"] == mix and row["seat"] == seat]
            assert {row["objective"] for row in rows} == set(pilot.OBJECTIVES)
            assert {row["rule_label"] for row in rows} == {"A", "B"}
            tasks = [task for task in manifest["tasks"]
                     if task["cell"]["mix"] == mix and task["cell"]["seat"] == seat]
            assert tasks[0]["comprehension_messages"] == tasks[1]["comprehension_messages"]


def test_invalid_action_remains_unknown_full_horizon(tmp_path):
    manifest, receipt = _manifest()
    result = pilot.run_pilot(
        manifest, output=tmp_path / "invalid", admission_gate=lambda: receipt,
        safety_check=lambda: None, cancel_event=None,
        invoke_fn=_fake(lambda n: "focal=5;sum=30" if n % 2 else "maybe"),
    )
    assert result["status"] == "completed_schedule_with_unknown_actions"
    assert result["attempted_calls"] == 24
    assert all(row["full_episode"] is None for row in result["cells"])
    assert not list((tmp_path / "invalid/private").glob("oracle-*.json"))


def test_request_drift_is_fatal_and_public_failure_closed(tmp_path):
    manifest, receipt = _manifest()
    result = pilot.run_pilot(
        manifest, output=tmp_path / "drift", admission_gate=lambda: receipt,
        safety_check=lambda: None, cancel_event=None,
        invoke_fn=_fake(lambda _: "focal=5;sum=30", drift_first=True),
    )
    assert result["status"] == "ineligible_provenance_drift"
    assert result["failure"] == "provenance_drift"
    assert result["attempted_calls"] == 1
    assert result["cells"][0]["calls"][0]["failure_code"] == "provenance_drift"
    assert "actual request" not in str(result)


def test_full_producer_to_private_dp_admission_and_public_action_tamper(tmp_path):
    manifest, receipt = _manifest()
    output = tmp_path / "complete"
    run = pilot.run_pilot(
        manifest, output=output, admission_gate=lambda: receipt,
        safety_check=lambda: None, cancel_event=None,
        invoke_fn=_real_sse_fake(),
    )
    assert run["status"] == "complete" and run["attempted_calls"] == 108
    gate = validate_pilot(output)
    assert gate["admission_eligible"] is True
    assert gate["returned_sse_verified"] == 108
    assert gate["complete_episodes"] == 12
    assert gate["valid_action_calls"] == 96
    assert gate["private_content_exported"] is False
    bridge = build_bridge_payload(
        output, topic_id="topic-known-retain-utility-001",
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert bridge["experiment_outcome"]["value"]["valid_action_calls"] == 96
    assert bridge["scientific_novelty_claimed"] is False
    run["cells"][0]["calls"][1]["action"] = 1
    (output / "run.json").write_bytes(pilot._raw_json(run) + b"\n")
    with pytest.raises(PilotAdmissionError):
        validate_pilot(output)


def test_invalid_actions_are_admitted_as_negative_complete_schedule(tmp_path):
    manifest, receipt = _manifest()
    output = tmp_path / "negative"
    run = pilot.run_pilot(
        manifest, output=output, admission_gate=lambda: receipt,
        safety_check=lambda: None, cancel_event=None,
        invoke_fn=_real_sse_fake(invalid_actions=True),
    )
    assert run["status"] == "completed_schedule_with_unknown_actions"
    assert run["attempted_calls"] == 24
    gate = validate_pilot(output)
    assert gate["admission_eligible"] is True
    assert gate["valid_action_calls"] == 0
    assert gate["complete_episodes"] == 0
    assert gate["attempted_calls"] == 24
