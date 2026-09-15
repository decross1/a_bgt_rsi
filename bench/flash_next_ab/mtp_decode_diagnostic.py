"""Three repeated 512-token decode calls under an existing supervised window.

The parent controller owns model and resident lifecycle, monitor, deadline,
observer and exact restoration. This block only makes isolated model calls.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bench.flash_next_ab import harness, qualification as q
from bench.flash_next_ab.adapters import CallSpec
from bench.flash_next_ab.candidate_registry import MIA, CandidateSpec
from bench.flash_next_ab.followon_profiles import (
    MIA_MTP1, MIA_MTP2, MIA_MTP3, SPECS_BY_ID,
)
from bench.flash_next_ab.followon_timing import TimingRecorder, validate_timings
from bench.flash_next_ab.manifest import sha256_json
from bench.flash_next_ab.mtp0_controls import _write_json
from bench.flash_next_ab.transport import LocalEndpoint, canonical, complete, request_body

PROTOCOL_SHA256 = "2348e541a6451bcb3f68c19bb5c5e0e5a4aab110a9c9e74e1bacdbd72ce59ca0"
PLAN_SCHEMA = "flash-next-mia-mtp-decode-plan/v1"
RUN_SCHEMA = "flash-next-mia-mtp-decode-run/v1"
STUDY_ID = "mtp-fullvocab-decode-timing-v1"
CALL_TIMEOUT_S = 120.0
BLOCK_BUDGET_S = 360.0
SEED_BLOCK = 17
ALLOWED_IDS = (
    MIA.spec_id, MIA_MTP1.spec_id, MIA_MTP2.spec_id, MIA_MTP3.spec_id,
    "mia-925d7be6-mtp3-reduced47k-v2opt-v1",
)


class DecodeWindowAbort(RuntimeError):
    pass


def _protocol() -> dict[str, Any]:
    path = Path(__file__).with_name("MTP_DECODE_TIMING_PROTOCOL.json")
    raw = path.read_bytes()
    if not 0 < len(raw) <= 20_000 or hashlib.sha256(raw).hexdigest() != PROTOCOL_SHA256:
        raise ValueError("decode protocol differs from prospective raw bytes")
    value = json.loads(raw)
    if (value.get("schema") != "flash-next-mia-mtp-decode-diagnostic/v1"
        or value.get("profiles") != list(ALLOWED_IDS)
        or value.get("sampling", {}).get("repetitions") != 3
        or value.get("request", {}).get("max_tokens") != 512):
        raise ValueError("decode protocol shape or registered profile set differs")
    return value


def _spec(spec_id: str) -> CandidateSpec:
    spec = SPECS_BY_ID.get(spec_id)
    if spec is None or spec_id not in ALLOWED_IDS:
        raise ValueError("decode route is not an exact MTP0/full-vocab MTP profile")
    return spec


def freeze_plan(spec_id: str, route: dict[str, Any]) -> dict[str, Any]:
    """Freeze one exact passed profile route; the parent gate checks the receipt."""
    spec = _spec(spec_id)
    if not isinstance(route, dict) or set(route) != {
        "served_model", "artifact_sha256", "runtime_sha256",
        "qualification_receipt_sha256",
    }:
        raise ValueError("decode route fields differ")
    expected_runtime = harness._qualification_runtime_sha256(
        image_id=spec.image_id,
        command_sha256=q.sha256(spec.launch_argv(compilation_config=q.COMPILATION_CONFIG)),
    )
    if (route["served_model"] != spec.served_name
        or route["artifact_sha256"] != spec.model_artifact_sha256()
        or route["runtime_sha256"] != expected_runtime
        or any(not harness._digest(route[key]) for key in
               ("runtime_sha256", "qualification_receipt_sha256"))):
        raise ValueError("decode route differs from the code-owned passed profile")
    LocalEndpoint(spec.endpoint_name, f"http://127.0.0.1:{spec.host_port}/v1",
                  spec.served_name, spec.model_artifact_sha256()).validate()
    protocol = _protocol()
    request = protocol["request"]
    cells = [{"cell_id": f"decode512/{spec.spec_id}/repeat-{rep}",
              "repetition": rep, "messages_sha256": sha256_json(request["messages"]),
              "tools_sha256": sha256_json(request.get("tools") or []),
              "max_tokens": 512, "seed": SEED_BLOCK} for rep in range(3)]
    plan = {
        "schema_version": PLAN_SCHEMA, "study_id": STUDY_ID,
        "protocol_sha256": PROTOCOL_SHA256,
        "spec_id": spec.spec_id, "spec_sha256": spec.identity_sha256(),
        "profile": spec.profile, "mtp_speculative_tokens": spec.mtp_speculative_tokens,
        "route": dict(route), "endpoint_name": spec.endpoint_name,
        "seed_block": SEED_BLOCK, "declared_cells": cells,
        "request_policy": {"temperature": 0, "top_p": 1,
                           "enable_thinking": False},
        "caps": {"timeout_seconds_per_call": CALL_TIMEOUT_S,
                 "block_budget_seconds": BLOCK_BUDGET_S,
                 "maximum_calls": 3, "max_output_tokens": 512},
        "comparison_eligible": False, "promotion_authorized": False,
        "weekly_budget_debit": False, "paid_api_allowed": False,
    }
    plan["plan_sha256"] = sha256_json(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> CandidateSpec:
    if not isinstance(plan, dict) or plan.get("schema_version") != PLAN_SCHEMA:
        raise ValueError("decode plan schema differs")
    spec = _spec(plan.get("spec_id"))
    if plan != freeze_plan(spec.spec_id, plan.get("route")):
        raise ValueError("decode plan source, route or budget drifted")
    return spec


def run_model(
    plan: dict[str, Any], *, endpoint_name: str, seed_block: int,
    output_dir: str | Path, runtime_budget_s: float,
    admission_gate: Callable[[dict[str, Any], str], None],
    safety_check: Callable[[], None], work_cutoff_s: float,
    cancel_event: Any, invoke_fn: Callable[..., dict[str, Any]] = complete,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    spec = validate_plan(plan)
    if (endpoint_name != spec.endpoint_name or seed_block != SEED_BLOCK
        or type(runtime_budget_s) not in (float, int)
        or not math.isfinite(runtime_budget_s)
        or runtime_budget_s != BLOCK_BUDGET_S
        or type(work_cutoff_s) not in (float, int)
        or not math.isfinite(work_cutoff_s)
        or not callable(admission_gate) or not callable(safety_check)
        or not callable(getattr(cancel_event, "is_set", None))):
        raise ValueError("decode parent route, cutoff or monitor differs")
    output = Path(output_dir).absolute()
    parent = output.parent
    root = parent.parent
    if (output.exists() or output.is_symlink() or parent.name != "blocks"
        or not root.is_dir() or root.is_symlink() or root.resolve() != root
        or parent.is_symlink() or parent.exists() and parent.resolve() != parent):
        raise ValueError("decode output is not a new grouped child")
    admission_gate(plan, endpoint_name)
    if safety_check() is not None or cancel_event.is_set() or monotonic() + BLOCK_BUDGET_S > work_cutoff_s:
        raise DecodeWindowAbort("decode block no longer fits before restoration")
    parent.mkdir(mode=0o700, exist_ok=True)
    output.mkdir(mode=0o700)
    _write_json(output / "plan.json", plan)
    protocol = _protocol()
    request = protocol["request"]
    arm = {"cohort": "flash", "routes": [{
        "role": "decode", "endpoint_name": spec.endpoint_name,
        "served_model": spec.served_name,
        "artifact_sha256": spec.model_artifact_sha256(),
        "policies": {"mtp_decode_greedy": plan["request_policy"]},
    }]}
    recorder = TimingRecorder()
    measured = recorder.wrap(invoke_fn)
    outcomes = []
    started_at = datetime.now(timezone.utc).isoformat()
    for index, cell in enumerate(plan["declared_cells"]):
        if safety_check() is not None or cancel_event.is_set() or monotonic() >= work_cutoff_s:
            raise DecodeWindowAbort("decode block canceled before next call")
        call_spec = CallSpec(
            call_index=index, call_id=cell["cell_id"], role="decode",
            policy_id="mtp_decode_greedy", seed=SEED_BLOCK,
            max_tokens=512, timeout_s=CALL_TIMEOUT_S, required=True,
            messages=tuple(request["messages"]), tools=(),
        )
        private_records: list[dict[str, Any]] = []
        call = harness._invoke_call(
            call_spec, arm=arm, deadline=work_cutoff_s,
            invoke_fn=measured, cancel_event=cancel_event,
            monotonic=monotonic, evidence_sink=private_records.append,
        )
        if len(private_records) != 1 or call.status not in {"returned", "timeout", "error"}:
            raise DecodeWindowAbort("decode call/private evidence is unclassified")
        descriptor = harness._persist_private_call(
            output, ordinal=index, evidence=private_records[0],
        )
        timing = recorder.for_calls([call.receipt])[0]
        validate_timings([call.receipt], [timing])
        usage = call.receipt.get("usage")
        completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
        finish = call.receipt.get("finish_reason")
        outcomes.append({
            "cell_id": cell["cell_id"], "repetition": index,
            "status": call.status, "calls": [call.receipt],
            "private_call_evidence": [descriptor], "timing": timing,
            "completion_tokens": completion, "finish_reason": finish,
            "wall_s": call.receipt.get("wall_s"),
            "early_stop": (finish == "stop" and completion < 512)
                          if type(completion) is int else None,
        })
        if safety_check() is not None:
            raise DecodeWindowAbort("decode monitor failed after call")
        _write_json(output / "progress.json", {
            "schema_version": "flash-next-mia-mtp-decode-progress/v1",
            "attempted": len(outcomes), "declared": 3,
            "last_cell_id": cell["cell_id"],
        })
    run = {
        "schema_version": RUN_SCHEMA, "study_id": STUDY_ID,
        "status": "block_complete", "plan_sha256": plan["plan_sha256"],
        "protocol_sha256": PROTOCOL_SHA256,
        "spec_id": spec.spec_id, "spec_sha256": spec.identity_sha256(),
        "route": plan["route"], "endpoint_name": endpoint_name,
        "seed_block": SEED_BLOCK, "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "outcomes": outcomes,
        "summary": {"attempted": 3,
                    "returned": sum(row["status"] == "returned" for row in outcomes),
                    "timeout": sum(row["status"] == "timeout" for row in outcomes),
                    "error": sum(row["status"] == "error" for row in outcomes),
                    "early_stop": sum(row["early_stop"] is True for row in outcomes)},
        "diagnostic_only": True, "restoration_required": True,
        "comparison_eligible": False, "promotion_authorized": False,
        "weekly_budget_debit": False, "paid_api_allowed": False,
    }
    validate_run(run, plan)
    _write_json(output / "run.json", run)
    return run


def validate_run(run: dict[str, Any], plan: dict[str, Any]) -> None:
    spec = validate_plan(plan)
    rows = run.get("outcomes") if isinstance(run, dict) else None
    if (run.get("schema_version") != RUN_SCHEMA
        or run.get("study_id") != STUDY_ID
        or run.get("status") != "block_complete"
        or run.get("plan_sha256") != plan["plan_sha256"]
        or run.get("protocol_sha256") != PROTOCOL_SHA256
        or run.get("spec_id") != spec.spec_id
        or run.get("spec_sha256") != spec.identity_sha256()
        or run.get("route") != plan["route"]
        or run.get("endpoint_name") != spec.endpoint_name
        or run.get("seed_block") != SEED_BLOCK
        or not isinstance(rows, list) or len(rows) != 3
        or [row.get("cell_id") for row in rows] !=
           [cell["cell_id"] for cell in plan["declared_cells"]]
        or run.get("diagnostic_only") is not True
        or run.get("restoration_required") is not True
        or run.get("comparison_eligible") is not False
        or run.get("promotion_authorized") is not False
        or run.get("weekly_budget_debit") is not False
        or run.get("paid_api_allowed") is not False):
        raise ValueError("decode run is not a complete frozen diagnostic block")
    protocol = _protocol()
    request = protocol["request"]
    endpoint = LocalEndpoint(spec.endpoint_name,
                             f"http://127.0.0.1:{spec.host_port}/v1",
                             spec.served_name, spec.model_artifact_sha256())
    body = request_body(endpoint, request["messages"], plan["request_policy"],
                        512, SEED_BLOCK, None)
    request_sha = hashlib.sha256(canonical(body)).hexdigest()
    for index, (cell, row) in enumerate(zip(plan["declared_cells"], rows, strict=True)):
        if (not isinstance(row, dict) or row.get("repetition") != index
            or row.get("status") not in {"returned", "timeout", "error"}
            or not isinstance(row.get("calls"), list) or len(row["calls"]) != 1
            or not isinstance(row.get("private_call_evidence"), list)
            or len(row["private_call_evidence"]) != 1
            or not isinstance(row.get("timing"), dict)):
            raise ValueError("decode cell/private/timing coverage differs")
        call = row["calls"][0]
        if (not isinstance(call, dict) or call.get("call_id") != cell["cell_id"]
            or call.get("status") != row["status"]
            or call.get("endpoint_name") != spec.endpoint_name
            or call.get("served_model") != spec.served_name
            or call.get("artifact_sha256") != spec.model_artifact_sha256()
            or call.get("policy_id") != "mtp_decode_greedy"
            or call.get("resolved_policy_sha256") != sha256_json(plan["request_policy"])
            or call.get("seed") != SEED_BLOCK or call.get("max_tokens") != 512
            or type(call.get("timeout_s")) not in (float, int)
            or not 0 < call["timeout_s"] <= CALL_TIMEOUT_S
            or call.get("messages_sha256") != sha256_json(request["messages"])
            or call.get("tools_sha256") != sha256_json([])
            or call.get("request_sha256") != request_sha
            or row.get("completion_tokens") !=
               (call["usage"].get("completion_tokens")
                if isinstance(call.get("usage"), dict) else None)
            or row.get("finish_reason") != call.get("finish_reason")
            or row.get("wall_s") != call.get("wall_s")
            or row.get("early_stop") is not
               (call.get("finish_reason") == "stop"
                and call["usage"].get("completion_tokens") < 512
                if isinstance(call.get("usage"), dict) else None)
            or row["status"] == "returned" and call.get("response_model") != spec.served_name):
            raise ValueError("decode recorded request, length or route differs")
        validate_timings([call], [row["timing"]])
    if run.get("summary") != {
        "attempted": 3,
        "returned": sum(row["status"] == "returned" for row in rows),
        "timeout": sum(row["status"] == "timeout" for row in rows),
        "error": sum(row["status"] == "error" for row in rows),
        "early_stop": sum(row["early_stop"] is True for row in rows),
    }:
        raise ValueError("decode diagnostic denominator or early-stop count differs")
