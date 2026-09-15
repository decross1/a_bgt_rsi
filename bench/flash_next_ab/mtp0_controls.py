"""One supervised MTP0 control block for the frozen Mia full-vocab MTP panel.

This runner owns only
12 serial model calls and isolated output; the existing qualification worker
owns model launch, monitor, UI observer, deadline, Nara/resident restoration.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bench.flash_next_ab import harness, qualification as q
from bench.flash_next_ab.adapters import CallSpec
from bench.flash_next_ab.candidate_registry import MIA
from bench.flash_next_ab.followon_canaries import (
    FollowonCanaryError, MTP_PROTOCOL_SHA256, _protocol, decoded_view,
)
from bench.flash_next_ab.followon_timing import TimingRecorder, validate_timings
from bench.flash_next_ab.manifest import canonical_json, sha256_json
from bench.flash_next_ab.transport import LocalEndpoint, canonical, complete, request_body

PLAN_SCHEMA = "flash-next-mia-mtp0-controls-plan/v1"
RUN_SCHEMA = "flash-next-mia-mtp0-controls-run/v1"
STUDY_ID = "mtp0-control-panel-v1"
BLOCK_TIMEOUT_S = 60.0
BLOCK_BUDGET_S = 12 * BLOCK_TIMEOUT_S
SEED_BLOCK = 17


class MTP0ControlWindowAbort(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex(value: Any, where: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{where} is not a lowercase SHA-256")
    return value


def _cells() -> list[dict[str, Any]]:
    protocol = _protocol()
    cells = []
    for request in protocol["requests"]:
        for repetition in range(3):
            cells.append({
                "cell_id": f"mtp0/{request['id']}/repeat-{repetition}",
                "request_id": request["id"], "repetition": repetition,
                "seed": SEED_BLOCK, "messages_sha256": sha256_json(request["messages"]),
                "tools_sha256": sha256_json(request.get("tools") or []),
                "max_tokens": request["max_tokens"],
            })
    if len(cells) != 12 or len({row["cell_id"] for row in cells}) != 12:
        raise ValueError("preregistered MTP0 control panel does not have 12 cells")
    return cells


def freeze_plan(route: dict[str, Any]) -> dict[str, Any]:
    """Bind exact passed Mia C0 route; qualification gate resolves the receipt."""
    if not isinstance(route, dict) or set(route) != {
        "served_model", "artifact_sha256", "runtime_sha256",
        "qualification_receipt_sha256",
    }:
        raise ValueError("MTP0 control route fields differ")
    if route["served_model"] != MIA.served_name or route["artifact_sha256"] != MIA.model_artifact_sha256():
        raise ValueError("MTP0 control route differs from the original Mia C0")
    LocalEndpoint(MIA.endpoint_name, f"http://127.0.0.1:{MIA.host_port}/v1",
                  MIA.served_name, route["artifact_sha256"]).validate()
    for field in ("artifact_sha256", "runtime_sha256", "qualification_receipt_sha256"):
        _hex(route[field], field)
    expected_runtime = harness._qualification_runtime_sha256(
        image_id=MIA.image_id,
        command_sha256=q.sha256(MIA.launch_argv(compilation_config=q.COMPILATION_CONFIG)),
    )
    if route["runtime_sha256"] != expected_runtime:
        raise ValueError("MTP0 route runtime differs from the authentic C0 launch")
    result = {
        "schema_version": PLAN_SCHEMA, "study_id": STUDY_ID,
        "protocol_sha256": MTP_PROTOCOL_SHA256,
        "mtp0_spec_id": MIA.spec_id, "mtp0_spec_sha256": MIA.identity_sha256(),
        "route": dict(route), "endpoint_name": MIA.endpoint_name,
        "seed_block": SEED_BLOCK, "declared_cells": _cells(),
        "request_policy": {"temperature": 0, "top_p": 1,
                           "enable_thinking": False},
        "caps": {"timeout_seconds_per_call": BLOCK_TIMEOUT_S,
                 "block_budget_seconds": BLOCK_BUDGET_S,
                 "maximum_calls": 12},
        "comparison_eligible": False, "promotion_authorized": False,
        "weekly_budget_debit": False, "paid_api_allowed": False,
    }
    result["plan_sha256"] = sha256_json(result)
    return result


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema_version") != PLAN_SCHEMA:
        raise ValueError("MTP0 control plan schema differs")
    expected = freeze_plan(plan.get("route"))
    if plan != expected:
        raise ValueError("MTP0 control plan/protocol/source/route drifted")
    return plan


def _write_json(path: Path, value: dict[str, Any]) -> None:
    raw = canonical_json(value) + b"\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _outcome(call, private: dict[str, Any], descriptor: dict[str, Any],
             request_id: str, repetition: int) -> dict[str, Any]:
    status = call.status
    if status not in {"returned", "timeout", "error"}:
        raise MTP0ControlWindowAbort("MTP0 call was canceled or unclassified")
    response = private.get("response") if isinstance(private, dict) else None
    view = decoded_view(response) if status == "returned" and isinstance(response, dict) else None
    objective = None
    if view is not None:
        if request_id == "literal64":
            objective = view["content"] == "ALPHA17_BETA703_GAMMA29_DELTA11" and view["finish_reason"] == "stop"
        elif request_id == "short_reasoned_answer":
            objective = view["content"] == "1,1,1,1" and view["finish_reason"] == "stop"
        elif request_id == "structured_tool":
            tool = view["tool_calls"]
            try:
                objective = (len(tool) == 1 and tool[0]["name"] == "record_probe"
                             and json.loads(tool[0]["arguments"]) ==
                             {"label": "mtp-parity", "value": 703}
                             and view["finish_reason"] == "tool_calls")
            except (TypeError, ValueError, json.JSONDecodeError):
                objective = False
        else:
            objective = view["finish_reason"] == "stop"
    return {
        "cell_id": f"mtp0/{request_id}/repeat-{repetition}",
        "request_id": request_id, "repetition": repetition,
        "status": status, "passed": objective,
        "request_sha256": call.receipt["request_sha256"],
        "response_stream_sha256": call.receipt.get("response_stream_sha256"),
        "decoded_view_sha256": sha256_json(view) if view is not None else None,
        "private_call_evidence": [descriptor],
        "calls": [call.receipt],
    }


def run_model(
    plan: dict[str, Any], *, endpoint_name: str, seed_block: int | None,
    output_dir: str | Path, runtime_budget_s: float,
    admission_gate: Callable[[dict[str, Any], str], None],
    safety_check: Callable[[], None], work_cutoff_s: float,
    cancel_event: Any, invoke_fn: Callable[..., dict[str, Any]] = complete,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    validate_plan(plan)
    if endpoint_name != MIA.endpoint_name or seed_block != SEED_BLOCK:
        raise ValueError("MTP0 controls require one exact Mia route/seed block")
    if not callable(admission_gate) or not callable(safety_check) or not callable(invoke_fn):
        raise ValueError("controller admission, monitor or transport callback is missing")
    if (not isinstance(runtime_budget_s, (int, float)) or isinstance(runtime_budget_s, bool)
            or not math.isfinite(runtime_budget_s) or runtime_budget_s != BLOCK_BUDGET_S):
        raise ValueError("MTP0 control budget differs from the 12-call frozen ceiling")
    if (not isinstance(work_cutoff_s, (int, float)) or isinstance(work_cutoff_s, bool)
            or not math.isfinite(work_cutoff_s) or
            not callable(getattr(cancel_event, "is_set", None))):
        raise ValueError("MTP0 controller cutoff/cancel source differs")
    output = Path(output_dir).absolute()
    parent = output.parent
    window_root = parent.parent
    if (output.exists() or output.is_symlink() or parent.name != "blocks"
            or not window_root.is_dir() or window_root.is_symlink()
            or window_root.resolve() != window_root or parent.is_symlink()
            or (parent.exists() and (not parent.is_dir() or parent.resolve() != parent))):
        raise ValueError("MTP0 output child is not new below a stable grouped window")
    admission_gate(plan, endpoint_name)  # No output/model call before external gate.
    if safety_check() is not None:
        raise MTP0ControlWindowAbort("MTP0 monitor callback contract differs")
    if monotonic() + BLOCK_BUDGET_S > work_cutoff_s:
        raise MTP0ControlWindowAbort("12 controls no longer fit before restoration")
    parent.mkdir(mode=0o700, exist_ok=True)
    if parent.is_symlink() or parent.resolve() != parent:
        raise MTP0ControlWindowAbort("MTP0 block parent redirected after creation")
    output.mkdir(mode=0o700)
    _write_json(output / "plan.json", plan)
    protocol = _protocol()
    policy = plan["request_policy"]
    arm = {"cohort": "flash", "routes": [{
        "role": "control", "endpoint_name": endpoint_name,
        "served_model": MIA.served_name,
        "artifact_sha256": MIA.model_artifact_sha256(),
        "policies": {"mtp0_greedy": policy},
    }]}
    started_at = _now()
    outcomes = []
    recorder = TimingRecorder()
    measured_invoke = recorder.wrap(invoke_fn)
    for ordinal, cell in enumerate(plan["declared_cells"]):
        if safety_check() is not None:
            raise MTP0ControlWindowAbort("MTP0 monitor callback contract differs")
        if cancel_event.is_set() or monotonic() >= work_cutoff_s:
            raise MTP0ControlWindowAbort("controller canceled MTP0 controls")
        request = next(row for row in protocol["requests"]
                       if row["id"] == cell["request_id"])
        spec = CallSpec(
            call_index=ordinal,
            call_id=cell["cell_id"], role="control", policy_id="mtp0_greedy",
            seed=SEED_BLOCK, max_tokens=request["max_tokens"],
            timeout_s=BLOCK_TIMEOUT_S, required=True,
            messages=tuple(request["messages"]),
            tools=tuple(request.get("tools") or []),
        )
        private_records: list[dict[str, Any]] = []
        call = harness._invoke_call(
            spec, arm=arm, deadline=work_cutoff_s, invoke_fn=measured_invoke,
            cancel_event=cancel_event, monotonic=monotonic,
            evidence_sink=private_records.append,
        )
        if len(private_records) != 1:
            raise MTP0ControlWindowAbort("control call lacks one private evidence record")
        private = private_records[0]
        descriptor = harness._persist_private_call(
            output, ordinal=ordinal, evidence=private,
        )
        outcome = _outcome(call, private, descriptor,
                           cell["request_id"], cell["repetition"])
        outcome["timing"] = recorder.for_calls([call.receipt])[0]
        validate_timings([call.receipt], [outcome["timing"]])
        outcomes.append(outcome)
        if safety_check() is not None:
            raise MTP0ControlWindowAbort("MTP0 monitor callback contract differs")
        _write_json(output / "progress.json", {
            "schema_version": "flash-next-mia-mtp0-controls-progress/v1",
            "attempted": len(outcomes), "declared": 12,
            "last_cell_id": cell["cell_id"],
        })
    if len(outcomes) != 12:
        raise MTP0ControlWindowAbort("MTP0 control panel has incomplete coverage")
    passed = sum(row["passed"] is True for row in outcomes)
    timeouts = sum(row["status"] == "timeout" for row in outcomes)
    result = {
        "schema_version": RUN_SCHEMA, "study_id": STUDY_ID,
        "status": "block_complete", "plan_sha256": plan["plan_sha256"],
        "protocol_sha256": MTP_PROTOCOL_SHA256,
        "endpoint_name": endpoint_name, "seed_block": seed_block,
        "route": plan["route"], "started_at": started_at,
        "finished_at": _now(), "outcomes": outcomes,
        "summary": {"attempted": 12, "returned": sum(row["status"] == "returned" for row in outcomes),
                    "passed": passed, "timeout": timeouts,
                    "error": sum(row["status"] == "error" for row in outcomes)},
        "controls_ready_for_parity": passed == 12,
        "restoration_required": True,
        "comparison_eligible": False, "promotion_authorized": False,
        "weekly_budget_debit": False, "paid_api_allowed": False,
    }
    validate_run(result, plan)
    _write_json(output / "run.json", result)
    return result


def validate_run(result: dict[str, Any], plan: dict[str, Any]) -> None:
    validate_plan(plan)
    expected_cells = [row["cell_id"] for row in plan["declared_cells"]]
    outcomes = result.get("outcomes") if isinstance(result, dict) else None
    if (result.get("schema_version") != RUN_SCHEMA
            or result.get("study_id") != STUDY_ID
            or result.get("status") != "block_complete"
            or result.get("plan_sha256") != plan["plan_sha256"]
            or result.get("protocol_sha256") != MTP_PROTOCOL_SHA256
            or result.get("endpoint_name") != MIA.endpoint_name
            or result.get("seed_block") != SEED_BLOCK
            or result.get("route") != plan["route"]
            or not isinstance(outcomes, list) or len(outcomes) != 12
            or [row.get("cell_id") for row in outcomes] != expected_cells
            or result.get("comparison_eligible") is not False
            or result.get("promotion_authorized") is not False
            or result.get("restoration_required") is not True):
        raise ValueError("MTP0 control run is not a complete frozen block")
    if result.get("paid_api_allowed") is not False or result.get("weekly_budget_debit") is not False:
        raise ValueError("MTP0 control run accounting differs")
    protocol = _protocol()
    endpoint = LocalEndpoint(MIA.endpoint_name,
                             f"http://127.0.0.1:{MIA.host_port}/v1",
                             MIA.served_name, MIA.model_artifact_sha256())
    requests = {request["id"]: request for request in protocol["requests"]}
    for cell, row in zip(plan["declared_cells"], outcomes, strict=True):
        if (not isinstance(row, dict) or row.get("request_id") != cell["request_id"]
                or row.get("repetition") != cell["repetition"]
                or row.get("status") not in {"returned", "timeout", "error"}
                or not isinstance(row.get("calls"), list) or len(row["calls"]) != 1
                or not isinstance(row["calls"][0], dict)
                or not isinstance(row.get("private_call_evidence"), list)
                or len(row["private_call_evidence"]) != 1
                or not isinstance(row["private_call_evidence"][0], dict)
                or row["calls"][0].get("call_id") != cell["cell_id"]
                or row.get("request_sha256") != row["calls"][0].get("request_sha256")
                or not isinstance(row.get("timing"), dict)
                or not isinstance(row.get("decoded_view_sha256"), (str, type(None)))):
            raise ValueError("MTP0 control cell/private descriptor chronology differs")
        validate_timings(row["calls"], [row["timing"]])
        call = row["calls"][0]
        source = requests[cell["request_id"]]
        expected_body = request_body(endpoint, source["messages"],
                                     plan["request_policy"], source["max_tokens"],
                                     SEED_BLOCK, source.get("tools"))
        expected_sha = hashlib.sha256(canonical(expected_body)).hexdigest()
        if (call.get("endpoint_name") != MIA.endpoint_name
            or call.get("served_model") != MIA.served_name
            or call.get("artifact_sha256") != MIA.model_artifact_sha256()
            or call.get("policy_id") != "mtp0_greedy"
            or call.get("resolved_policy_sha256") != sha256_json(plan["request_policy"])
            or call.get("seed") != SEED_BLOCK
            or call.get("max_tokens") != source["max_tokens"]
            or type(call.get("timeout_s")) not in (float, int)
            or not 0 < call["timeout_s"] <= BLOCK_TIMEOUT_S
            or call.get("messages_sha256") != sha256_json(source["messages"])
            or call.get("tools_sha256") != sha256_json(source.get("tools") or [])
            or call.get("request_sha256") != expected_sha
            or (row["status"] == "returned"
                and call.get("response_model") != MIA.served_name)):
            raise ValueError("MTP0 recorded call differs from its frozen cell")
        if isinstance(row["decoded_view_sha256"], str):
            _hex(row["decoded_view_sha256"], "MTP0 decoded view")
        if row["status"] != "returned" and row.get("passed") is not None:
            raise ValueError("failed MTP0 transport cannot pass an objective")
    summary = result.get("summary")
    if not isinstance(summary, dict) or summary != {
        "attempted": 12,
        "returned": sum(row["status"] == "returned" for row in outcomes),
        "passed": sum(row["passed"] is True for row in outcomes),
        "timeout": sum(row["status"] == "timeout" for row in outcomes),
        "error": sum(row["status"] == "error" for row in outcomes),
    }:
        raise ValueError("MTP0 control measured denominator differs")
    if result.get("controls_ready_for_parity") is not (summary["passed"] == 12):
        raise ValueError("MTP0 control parity readiness differs")


def validate_private_run(run: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """Replay the recorded calls/raw SSE through the existing strict gate."""
    from bench.flash_next_ab.private_evidence import validate_private_evidence

    rows = run.get("outcomes") if isinstance(run, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("diagnostic block has no private call outcomes")
    wrapper = {"status": "complete", "outcomes": [{
        "calls": row["calls"],
        "grade": {"details": {"_private_call_evidence": {
            "schema_version": harness.PRIVATE_INDEX_SCHEMA,
            "artifacts": row["private_call_evidence"],
        }}},
    } for row in rows]}
    return validate_private_evidence(wrapper, Path(output_dir).absolute())
