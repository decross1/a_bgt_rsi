"""Prospective capability canaries for registered Mia follow-on profiles.

Draft for a NEW worktree. It is not imported by the frozen Mia C0 controller.
The caller owns the existing monitor, lifecycle, private SSE writer and finally
restoration. This module neither starts nor stops any container or service.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bench.flash_next_ab.candidate_registry import CandidateSpec
from bench.flash_next_ab.manifest import sha256_json
from bench.flash_next_ab.followon_profiles import (
    MIA_CTX69632, requires_profile_canary,
)
from bench.flash_next_ab.transport import LocalEndpoint

MTP_PROTOCOL_SHA256 = "a5d76657a386569724326c151e6f8c85981452b03ba328c756f3afea8add6289"
CONTEXT_PACKET_SHA256 = "f7e0619be42ca770c39728a51b3a73a92562780be7797662c4f63139ba5c7876"
CONTEXT_PACKET_PATH = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation/context-packs-draft-v2.json"
)
CONTEXT_MINIMUM_TOKENS = 67_629
CONTEXT_SELECTED_CELL_ID = "long_context_8k_grim_threshold-c65536-late"
CONTEXT_SELECTED_MESSAGES_SHA256 = "90584d5d55d665c262be09d2828b0f857a8449924405a6a29f2a46b762cf7186"
CONTEXT_EXPECTED_TEXT = ('{"answer_code":"claim_contradicted_threshold_0_5",'
                         '"citations":["GT8A-CLAIM-0017","GT8A-PAYOFF-0073",'
                         '"GT8A-THRESHOLD-0132"]}')


class FollowonCanaryError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _protocol() -> dict[str, Any]:
    path = Path(__file__).with_name("MTP_PARITY_PROTOCOL.json")
    raw = path.read_bytes()
    if not (0 < len(raw) <= 20_000) or hashlib.sha256(raw).hexdigest() != MTP_PROTOCOL_SHA256:
        raise FollowonCanaryError("MTP protocol differs from the preregistered bytes")
    value = json.loads(raw)
    if value.get("schema") != "flash-next-mia-fullvocab-mtp-parity-protocol/v1":
        raise FollowonCanaryError("MTP protocol schema differs")
    return value


def decoded_view(call: dict[str, Any]) -> dict[str, Any]:
    """Compare only fields the current text/SSE transport actually exposes.

    Tool-call IDs and raw SSE framing are transport artifacts. A decoded view
    is not target-token-ID evidence or a token-level losslessness proof.
    """
    if not isinstance(call, dict):
        raise FollowonCanaryError("canary response is not an object")
    content = call.get("content")
    reasoning = call.get("reasoning_content")
    if content is not None and not isinstance(content, str):
        raise FollowonCanaryError("decoded content is malformed")
    if reasoning is not None and not isinstance(reasoning, str):
        raise FollowonCanaryError("decoded reasoning content is malformed")
    tools = call.get("tool_calls")
    if tools is None:
        tools = []
    if not isinstance(tools, list):
        raise FollowonCanaryError("decoded tool calls are malformed")
    projected: list[dict[str, str]] = []
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("function"), dict):
            raise FollowonCanaryError("decoded tool function is malformed")
        fn = tool["function"]
        if not isinstance(fn.get("name"), str) or not isinstance(fn.get("arguments"), str):
            raise FollowonCanaryError("decoded tool name/arguments are malformed")
        projected.append({"name": fn["name"], "arguments": fn["arguments"]})
    return {
        "content": content, "reasoning_content": reasoning,
        "tool_calls": projected, "finish_reason": call.get("finish_reason"),
    }


def compare_mtp_decoded_controls(
    controls: dict[str, list[dict[str, Any]]],
    candidate: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    """Pure prospective comparison; repeated MTP0 controls precede attribution.

    Only decoded API fields are compared. Any candidate difference blocks a
    lossless claim; varying MTP0 controls block speculation-causal attribution.
    """
    requests = _protocol()["requests"]
    expected = {row["id"] for row in requests}
    if set(controls) != expected or set(candidate) != expected:
        raise FollowonCanaryError("control/candidate request coverage differs")
    outcomes: dict[str, str] = {}
    for request_id in sorted(expected):
        a = controls[request_id]
        b = candidate[request_id]
        if len(a) != 3 or len(b) != 3:
            raise FollowonCanaryError("each request needs three MTP0 and three candidate repeats")
        matched_requests = [row.get("request_sha256") for row in a + b]
        matched_bodies = [row.get("resolved_request") for row in a + b]
        matched_endpoints = [row.get("endpoint") for row in a + b]
        matched_models = [row.get("response_model") for row in a + b]
        if (not all(isinstance(digest, str) and len(digest) == 64 for digest in matched_requests)
                or len(set(matched_requests)) != 1
                or not isinstance(matched_bodies[0], dict)
                or any(body != matched_bodies[0] for body in matched_bodies)
                or not isinstance(matched_endpoints[0], dict)
                or any(endpoint != matched_endpoints[0] for endpoint in matched_endpoints)
                or not isinstance(matched_models[0], str)
                or any(model != matched_models[0] for model in matched_models)):
            raise FollowonCanaryError("MTP0/candidate request, endpoint or model provenance differs")
        a_view = [decoded_view(row) for row in a]
        b_view = [decoded_view(row) for row in b]
        if len({json.dumps(row, sort_keys=True, allow_nan=False) for row in a_view}) != 1:
            outcomes[request_id] = "control_nondeterminism_confounded"
        elif any(row != a_view[0] for row in b_view):
            outcomes[request_id] = "decoded_output_parity_failed"
        else:
            outcomes[request_id] = "decoded_output_parity_observed_token_ids_unavailable"
    return outcomes


def run_profile_canary(
    ops: Any, monitor: Any, *, spec: CandidateSpec, output: Path,
    timeout_s: int, work_deadline: float,
    atomic_write: Callable[[Path, dict[str, Any]], None],
    record_private: Callable[[Path, str, dict[str, Any]], dict[str, Any]],
    native_context_packet_factory: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run only the selected non-C0 Mia canary under the parent lifecycle.

    Every request is durably marked started and completed/failed before raising.
    The summary is a capability receipt. MTP decoded/lossless interpretation
    requires the separately frozen three-repeat MTP0 control receipt.
    """
    if not requires_profile_canary(spec):
        raise FollowonCanaryError("no follow-on canary for unregistered/C0 spec")
    if (type(timeout_s) is not int
        or timeout_s != spec.profile_canary_timeout_seconds
        or timeout_s not in (120, 300)):
        raise FollowonCanaryError("canary timeout differs from the registered profile")
    endpoint = LocalEndpoint(spec.endpoint_name,
                             f"http://127.0.0.1:{spec.host_port}/v1",
                             spec.served_name, spec.model_artifact_sha256())
    rows: list[dict[str, Any]] = []
    attempts_path = output / "profile-canary-attempts.json"
    summary_path = output / "profile-canary.json"
    if spec.mtp_speculative_tokens:
        protocol = _protocol()
        policy = {k: protocol["request_policy"][k] for k in
                  ("temperature", "top_p", "enable_thinking")}
        seed = protocol["request_policy"]["seed"]
        requests = protocol["requests"]
        protocol_sha = MTP_PROTOCOL_SHA256
        request_count = 3 * len(requests)
        suite = ("reduced47k_v2full4_mtp_greedy_repeats"
                 if spec.draft_vocab_path is not None else
                 "fullvocab_mtp_greedy_repeats")
    elif spec is MIA_CTX69632:
        if native_context_packet_factory is None:
            raise FollowonCanaryError("native context packet builder was not supplied")
        packet = native_context_packet_factory()
        if not isinstance(packet, dict) or packet.get("pack_sha256") != CONTEXT_PACKET_SHA256:
            raise FollowonCanaryError("native context packet differs from frozen pack")
        if packet.get("cell_id") != CONTEXT_SELECTED_CELL_ID:
            raise FollowonCanaryError("native context packet cell differs from selection")
        input_tokens = packet.get("actual_input_tokens")
        output_tokens = packet.get("max_tokens")
        if (type(input_tokens) is not int or type(output_tokens) is not int
                or input_tokens < 65_536 or output_tokens < 1 or output_tokens > 2048
                or input_tokens + output_tokens < CONTEXT_MINIMUM_TOKENS
                or input_tokens + output_tokens > spec.max_model_len):
            raise FollowonCanaryError("native context packet does not cover near-ceiling capacity")
        if not isinstance(packet.get("messages"), list) or not isinstance(packet.get("expected"), str):
            raise FollowonCanaryError("native context packet lacks exact answer/messages")
        source_messages_sha256 = packet.get("source_messages_sha256")
        if (not isinstance(source_messages_sha256, str)
                or len(source_messages_sha256) != 64
                or source_messages_sha256 != CONTEXT_SELECTED_MESSAGES_SHA256
                or sha256_json(packet["messages"]) != source_messages_sha256):
            raise FollowonCanaryError("native context messages differ from frozen source SHA")
        if packet["expected"] != CONTEXT_EXPECTED_TEXT:
            raise FollowonCanaryError("native context expected answer differs from frozen task")
        policy = {"temperature": 0, "top_p": 1, "enable_thinking": False}
        seed = 17
        requests = [{"id": "native69632_near_ceiling", "messages": packet["messages"],
                     "max_tokens": output_tokens, "tools": None,
                     "expected": packet["expected"]}]
        protocol_sha = CONTEXT_PACKET_SHA256
        request_count = 1
        suite = "native69632_near_ceiling"
    else:
        raise FollowonCanaryError("registered follow-on profile has no canary route")

    def persist() -> None:
        atomic_write(attempts_path, {
            "schema": "flash-next-mia-profile-canary-attempts/v1",
            "spec_id": spec.spec_id, "probe_set": spec.qualification_probe_set,
            "protocol_sha256": protocol_sha, "results": rows,
        })

    def invoke(request: dict[str, Any], repetition: int) -> None:
        request_id = request["id"]
        probe_id = f"canary_{request_id}_{repetition}"
        row: dict[str, Any] = {"request_id": request_id, "repetition": repetition,
                               "status": "started", "started_at": _now()}
        if request_id == "native69632_near_ceiling":
            row.update({"cell_id": CONTEXT_SELECTED_CELL_ID,
                        "source_messages_sha256": source_messages_sha256,
                        "actual_input_tokens": input_tokens,
                        "reserved_output_tokens": output_tokens})
        rows.append(row)
        persist()
        try:
            monitor.check()
            if time.monotonic() >= work_deadline:
                raise FollowonCanaryError("canary work deadline reached")
            returned = ops.complete(
                endpoint, request["messages"], policy=policy,
                max_tokens=request["max_tokens"], timeout_s=timeout_s,
                seed=seed, tools=request.get("tools"),
                cancel_event=monitor.cancel_event,
            )
            monitor.check()
            if time.monotonic() >= work_deadline:
                raise FollowonCanaryError("canary work deadline reached after response")
            if not isinstance(returned, dict) or not isinstance(returned.get("private_evidence"), dict):
                raise FollowonCanaryError("canary transport omitted real-shaped private evidence")
            row["private_response"] = record_private(
                output, probe_id, returned["private_evidence"])
            if returned.get("response_stream_sha256") != row["private_response"]["response_stream_sha256"]:
                raise FollowonCanaryError("public/private canary SSE digest differs")
            public = {key: value for key, value in returned.items() if key != "private_evidence"}
            if request_id == "native69632_near_ceiling":
                # The frozen pack/source hash and request SHA preserve provenance.
                # A long source packet does not belong in a public status row.
                public.pop("resolved_request", None)
            if public.get("response_model") != spec.served_name:
                raise FollowonCanaryError("canary response served-model identity differs")
            view = decoded_view(public)
            row["public_response"] = public
            row["decoded_view"] = view
            row["request_sha256"] = public.get("request_sha256")
            if request_id == "structured_tool":
                if view["finish_reason"] != "tool_calls":
                    raise FollowonCanaryError("MTP tool response finish reason is incorrect")
            elif view["finish_reason"] != "stop":
                raise FollowonCanaryError("canary response did not terminate normally")
            if request_id == "native69632_near_ceiling":
                usage = public.get("usage")
                if not isinstance(usage, dict) or usage.get("prompt_tokens") != input_tokens:
                    raise FollowonCanaryError("server prompt-token count differs from frozen near-ceiling count")
                try:
                    parsed_answer = json.loads(view["content"] or "")
                except (TypeError, json.JSONDecodeError):
                    parsed_answer = None
                if (parsed_answer != json.loads(CONTEXT_EXPECTED_TEXT)
                        or view["tool_calls"] or view["finish_reason"] != "stop"):
                    raise FollowonCanaryError("near-ceiling context answer is incorrect")
            elif request_id == "literal64":
                if view["content"] != "ALPHA17_BETA703_GAMMA29_DELTA11":
                    raise FollowonCanaryError("MTP literal objective is incorrect")
            elif request_id == "short_reasoned_answer":
                if view["content"] != "1,1,1,1":
                    raise FollowonCanaryError("MTP arithmetic objective is incorrect")
            elif request_id == "structured_tool":
                if len(view["tool_calls"]) != 1 or view["tool_calls"][0]["name"] != "record_probe":
                    raise FollowonCanaryError("MTP tool objective is incorrect")
                if json.loads(view["tool_calls"][0]["arguments"]) != {"label": "mtp-parity", "value": 703}:
                    raise FollowonCanaryError("MTP tool arguments are incorrect")
            row["status"] = "passed"
            row["finished_at"] = _now()
            persist()
        except Exception as exc:  # noqa: BLE001 - durable failed attempt before lifecycle restoration
            attached = getattr(exc, "private_evidence", None)
            if isinstance(attached, dict):
                row["private_response"] = record_private(output, probe_id, attached)
            row["status"] = "failed"
            row["error_type"] = type(exc).__name__
            row["finished_at"] = _now()
            persist()
            raise

    try:
        for request in requests:
            for repetition in range(3 if spec.mtp_speculative_tokens else 1):
                invoke(request, repetition)
        if len(rows) != request_count or any(row["status"] != "passed" for row in rows):
            raise FollowonCanaryError("selected canary coverage is incomplete")
        status = "passed"
    except Exception:  # noqa: BLE001 - summarize failure, preserve caller's exact restoration
        status = "failed"
        summary = {"schema": "flash-next-mia-profile-canary/v1",
                   "spec_id": spec.spec_id, "probe_set": spec.qualification_probe_set,
                   "suite": suite, "protocol_sha256": protocol_sha,
                   "status": status, "attempt_count": len(rows),
                   "lossless_claim": False, "target_token_id_parity": "unavailable",
                   "finished_at": _now()}
        atomic_write(summary_path, summary)
        raise
    summary = {"schema": "flash-next-mia-profile-canary/v1",
               "spec_id": spec.spec_id, "probe_set": spec.qualification_probe_set,
               "suite": suite, "protocol_sha256": protocol_sha,
               "status": status, "attempt_count": len(rows),
               "lossless_claim": False, "target_token_id_parity": "unavailable",
               "decoded_parity_status": "pending_repeated_mtp0_control_comparison"
                                        if spec.mtp_speculative_tokens else None,
               "finished_at": _now()}
    if spec is MIA_CTX69632:
        summary.update({"cell_id": CONTEXT_SELECTED_CELL_ID,
                        "source_messages_sha256": source_messages_sha256,
                        "actual_input_tokens": input_tokens,
                        "reserved_output_tokens": output_tokens})
    atomic_write(summary_path, summary)
    return summary
