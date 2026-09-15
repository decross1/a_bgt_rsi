"""CPU-only, source-shaped admission tests for registered Mia v5 profiles."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bench.flash_next_ab import harness
from bench.flash_next_ab.followon_canaries import (
    MTP_PROTOCOL_SHA256,
    _protocol,
    decoded_view,
)
from bench.flash_next_ab.followon_profiles import (
    MIA_MTP1,
    MIA_MTP3_REDUCED47K_OPT,
)
from bench.flash_next_ab.followon_qualification_admission import (
    _validate_profile_canary,
)
from bench.flash_next_ab.transport import (
    LocalEndpoint,
    StreamAccumulator,
    _sse_data,
    canonical,
    request_body,
)


def _write_json(path: Path, object_: dict) -> str:
    raw = json.dumps(object_, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _stream(model: str, response_id: str, request_id: str) -> tuple[bytes, dict]:
    if request_id == "structured_tool":
        delta = {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                 "function": {"name": "record_probe", "arguments":
                                              '{"label":"mtp-parity","value":703}'}}]}
        finish_reason = "tool_calls"
    else:
        delta = {"content": {"literal64": "ALPHA17_BETA703_GAMMA29_DELTA11",
                             "short_reasoned_answer": "1,1,1,1",
                             "code_generation": "def clamp01(value): return min(1.0, max(0.0, float(value)))"}[request_id]}
        finish_reason = "stop"
    events = [
        {"id": response_id, "model": model,
         "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]},
        {"id": response_id, "model": model, "choices": [],
         "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}},
    ]
    raw = b"".join(b"data: " + canonical(event) + b"\n\n" for event in events) + b"data: [DONE]\n\n"
    accumulator = StreamAccumulator(model)
    for line in raw.splitlines():
        data = _sse_data(line)
        if data is not None:
            accumulator.accept(data)
    return raw, accumulator.result()


def _producer_canary(tmp_path: Path, spec=MIA_MTP1) -> dict:
    protocol = _protocol()
    endpoint = LocalEndpoint(spec.endpoint_name,
                             f"http://127.0.0.1:{spec.host_port}/v1",
                             spec.served_name, spec.model_artifact_sha256())
    policy = {key: protocol["request_policy"][key]
              for key in ("temperature", "top_p", "enable_thinking")}
    seed = protocol["request_policy"]["seed"]
    private_dir = tmp_path / "private-probes"
    private_dir.mkdir()
    now = datetime.now(timezone.utc)
    rows = []
    for request in protocol["requests"]:
        for repetition in range(3):
            raw, public = _stream(spec.served_name,
                                  f"response_{request['id']}_{repetition}", request["id"])
            relative = f"private-probes/canary_{request['id']}_{repetition}.sse"
            (tmp_path / relative).write_bytes(raw)
            body = request_body(endpoint, request["messages"], policy,
                                request["max_tokens"], seed, request.get("tools"))
            digest = hashlib.sha256(raw).hexdigest()
            public.update({"endpoint": endpoint.__dict__,
                           "resolved_request": body,
                           "request_sha256": hashlib.sha256(canonical(body)).hexdigest(),
                           "response_stream_sha256": digest})
            rows.append({"request_id": request["id"], "repetition": repetition,
                         "status": "passed", "started_at": now.isoformat(),
                         "finished_at": now.isoformat(),
                         "public_response": public,
                         "decoded_view": decoded_view(public),
                         "request_sha256": public["request_sha256"],
                         "private_response": {"private_stream_relpath": relative,
                                              "response_stream_sha256": digest,
                                              "response_stream_bytes": len(raw)}})
    attempts = {"schema": "flash-next-mia-profile-canary-attempts/v1",
                "spec_id": spec.spec_id, "probe_set": spec.qualification_probe_set,
                "protocol_sha256": MTP_PROTOCOL_SHA256, "results": rows}
    summary = {"schema": "flash-next-mia-profile-canary/v1",
               "spec_id": spec.spec_id, "probe_set": spec.qualification_probe_set,
               "suite": ("reduced47k_v2full4_mtp_greedy_repeats"
                         if spec.draft_vocab_path is not None else
                         "fullvocab_mtp_greedy_repeats"),
               "protocol_sha256": MTP_PROTOCOL_SHA256,
               "status": "passed", "attempt_count": 12,
               "lossless_claim": False, "target_token_id_parity": "unavailable",
               "decoded_parity_status": "pending_repeated_mtp0_control_comparison",
               "finished_at": now.isoformat()}
    attempts_sha = _write_json(tmp_path / "profile-canary-attempts.json", attempts)
    summary_sha = _write_json(tmp_path / "profile-canary.json", summary)
    return {"started_at": (now - timedelta(seconds=1)).isoformat(),
            "restoration": {"verified_at": (now + timedelta(seconds=1)).isoformat()},
            "profile_canary_status": "passed", "profile_canary_sha256": summary_sha,
            "profile_canary_attempts_sha256": attempts_sha,
            "profile_canary_protocol_sha256": MTP_PROTOCOL_SHA256,
            "profile_canary_suite": summary["suite"],
            "profile_canary_attempt_count": 12,
            "profile_canary_timeout_seconds": spec.profile_canary_timeout_seconds}


def test_v5_canary_private_sse_and_frozen_requests_are_source_bound(tmp_path):
    result = _producer_canary(tmp_path)
    _validate_profile_canary(tmp_path, result, MIA_MTP1)
    path = tmp_path / "private-probes/canary_literal64_0.sse"
    path.write_bytes(path.read_bytes() + b"data: evil\n\n")
    with pytest.raises(harness.HarnessError, match="raw SSE"):
        _validate_profile_canary(tmp_path, result, MIA_MTP1)


def test_reduced_canary_has_distinct_suite_and_private_request_proof(tmp_path):
    result = _producer_canary(tmp_path, MIA_MTP3_REDUCED47K_OPT)
    _validate_profile_canary(tmp_path, result, MIA_MTP3_REDUCED47K_OPT)
    result["profile_canary_suite"] = "fullvocab_mtp_greedy_repeats"
    with pytest.raises(harness.HarnessError, match="identity"):
        _validate_profile_canary(tmp_path, result, MIA_MTP3_REDUCED47K_OPT)


def test_v5_canary_resealed_wrong_request_is_rejected(tmp_path):
    result = _producer_canary(tmp_path)
    attempts_path = tmp_path / "profile-canary-attempts.json"
    attempts = json.loads(attempts_path.read_bytes())
    attempts["results"][0]["public_response"]["resolved_request"]["seed"] = 999
    result["profile_canary_attempts_sha256"] = _write_json(attempts_path, attempts)
    with pytest.raises(harness.HarnessError, match="frozen protocol"):
        _validate_profile_canary(tmp_path, result, MIA_MTP1)


def test_historical_mia_v4_receipt_remains_admissible_after_v5_dispatch():
    run = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
               "qwen-flash-next-research/qualification-runs/qfn-mia-c0-20260915-0602")
    summary = harness.validate_flash_qualification_files(
        run / "result.json", run / "plan.json",
        run / "launch-contract.snapshot.json",
        contract_raw_path=run / "launch-contract.raw.json", require_passed=True)
    assert summary["schema_version"] == "flash-next-qualification-validation/v2"
    assert summary["admission_eligible"] is True


def test_shared_dispatch_rejects_an_unregistered_v5_candidate(tmp_path):
    run = tmp_path / "qfn-mia-mtp1-static-fake"
    run.mkdir()
    _write_json(run / "result.json", {
        "schema": "qwen-flash-next-qualification-result/v5", "run_id": run.name,
    })
    _write_json(run / "plan.json", {"schema": "qwen-flash-next-qualification-plan/v5"})
    _write_json(run / "launch-contract.snapshot.json", {
        "schema": "qwen-flash-next-qualification/v5", "candidate": {"id": "fabricated"},
    })
    with pytest.raises(harness.HarnessError, match="code-owned profile"):
        harness.validate_flash_qualification_files(
            run / "result.json", run / "plan.json",
            run / "launch-contract.snapshot.json", require_passed=True)
