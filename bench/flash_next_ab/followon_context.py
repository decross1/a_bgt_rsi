"""Optional, controller-gated long-context evidence sweep over frozen packets.

This module never launches or changes a model. A qualified controller supplies
an admission ticket, a continuously armed safety check, and an absolute work
cutoff. The public run contains counts, hashes, and objective grades only;
requests, completions, reasoning, and SSE streams live in private evidence.
The 60 packets are byte-identical between model arms. Token lengths are counted
with each arm's actual local tokenizer and registered chat template.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.flash_next_ab import adapters as flash_adapters
from bench.flash_next_ab import harness
from bench.flash_next_ab.adapters import CallSpec
from bench.flash_next_ab.followon_timing import TimingRecorder, validate_timings
from bench.flash_next_ab.manifest import canonical_json, sha256_file, sha256_json
from bench.flash_next_ab.transport import LocalEndpoint, complete
from bench.weekly_upgrade_eval import manifest as objective_manifest
from bench.weekly_upgrade_eval import runner as objective_runner
from bench.weekly_upgrade_eval.manifest import Task

from . import followon_context_packs as context_packs

PACK_PATH = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation/context-packs-draft-v2.json"
)
PACK_SHA256 = "f7e0619be42ca770c39728a51b3a73a92562780be7797662c4f63139ba5c7876"
BUILDER_SHA256 = "ff1d613b50c7fd3c8d55f462adaea4fddc5f02843234f5967fced5c2e0d62693"
SOURCE_SHA256 = "7a65db923631d01c296ba8e65e924e646c9134082bb2a600c099eeb66eb6f735"
PACK_SCHEMA = "flash-context-pack-manifest/v2"
PLAN_SCHEMA = "flash-context-placement-plan/v1"
RUN_SCHEMA = "flash-context-placement-run/v1"
OUTPUT_RESERVE = 2048
TARGETS = (2048, 8192, 16384, 32768, 65536)
PLACEMENTS = ("early", "middle", "late")
TIMEOUTS_S = {2048: 120.0, 8192: 180.0, 16384: 240.0, 32768: 360.0, 65536: 480.0}
ROLE = "evidence"
POLICY_ID = "deterministic_context_off"
SEED = 71
ENDPOINTS = {
    "resident_gemma": {
        "url": "http://127.0.0.1:8000/v1",
        "model": "gemma-4-26b-a4b",
        "tokenizer_path": "/mnt/models/gemma-4-26b-a4b-nvfp4",
        "template_sha256": "94899c0f917d93f6fe81c95744d1e8ddab2d21d39228d2e4aec1fb2a25bff413",
        "top_k": 64,
    },
    "resident_qwen": {
        "url": "http://127.0.0.1:8001/v1",
        "model": "qwen3.8-27b-nvfp4-mtp",
        "tokenizer_path": "/mnt/models/qwen3.8-27b-nvfp4-mtp",
        "template_sha256": "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041",
        "top_k": 20,
    },
    "flash_next": {
        "url": "http://127.0.0.1:8012/v1",
        "model": "qwen3.8-flash-next",
        "tokenizer_path": "/mnt/models/qwen3.8-flash-next-nvfp4-fc694b54",
        "template_sha256": "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041",
        "top_k": 20,
    },
    "flash_next_mia": {
        "url": "http://127.0.0.1:8012/v1",
        "model": "qwen3.8-flash-next-mia",
        "tokenizer_path": "/mnt/models/qwen3.8-flash-next-mia-925d7be6",
        "template_sha256": "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041",
        "top_k": 20,
    },
}
MAX_PACK_BYTES = 8_000_000
TOKENIZATION_PATH = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation/context-arm-tokenization-v1-20260915.json"
)
TOKENIZATION_SHA256 = "e28cd45e6e23a256b4f6b49ca2779173ec93bc018beb31a59f3a904e930ee110"
TOKENIZER_PROBE_SHA256 = "bf19a5927da0c6dd800c0d63532cf8535576a86ca42738aedc628c55680ffeaa"
TOKENIZER_PROBE_PATH = TOKENIZATION_PATH.with_name("context_tokenizer_probe.py")
CPU_IMAGE_ID = "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72"
EXECUTION_PATH = TOKENIZATION_PATH.with_name("context-arm-tokenization-execution-20260915.json")
EXECUTION_SHA256 = "d75395d76a2dbbd980024085e396bf96be88f42072b38f5e79152c6c65b3d2cb"


class ContextWindowAbort(RuntimeError):
    """A closed monitor/cutoff reason; underlying errors stay private."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class TokenizedCell:
    cell_id: str
    input_tokens: int
    supported: bool
    required_context_tokens: int


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _pack() -> dict[str, Any]:
    raw, _ = harness._read_regular_file(PACK_PATH, label="frozen context pack", max_bytes=MAX_PACK_BYTES)
    if hashlib.sha256(raw).hexdigest() != PACK_SHA256:
        raise ValueError("frozen context pack bytes drifted")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != PACK_SCHEMA:
        raise ValueError("frozen context pack schema differs")
    if (value.get("suite_id") != context_packs.SUITE_ID
            or value.get("source_sha256") != SOURCE_SHA256
            or value.get("builder_sha256") != BUILDER_SHA256
            or value.get("thinking") != "off"):
        raise ValueError("frozen context source/template controls differ")
    if sha256_file(Path(context_packs.__file__)) != BUILDER_SHA256:
        raise ValueError("context helper source drifted")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 60:
        raise ValueError("frozen context matrix must contain 60 cells")
    ids, matrix, source_ids = set(), set(), set()
    source_focal: dict[str, tuple[str, str]] = {}
    for row in tasks:
        if not isinstance(row, dict):
            raise TypeError("context cell is malformed")
        cell_id = row.get("id")
        source_id = row.get("source_task_id")
        target = row.get("target_input_tokens")
        placement = row.get("placement")
        if (not isinstance(cell_id, str) or not isinstance(source_id, str)
                or target not in TARGETS or placement not in PLACEMENTS
                or cell_id != f"{source_id}-c{target}-{placement}"):
            raise ValueError("context cell identity differs from fixed matrix")
        if cell_id in ids or (source_id, target, placement) in matrix:
            raise ValueError("duplicate context cell")
        ids.add(cell_id)
        matrix.add((source_id, target, placement))
        source_ids.add(source_id)
        messages = row.get("messages")
        if (not isinstance(messages, list) or len(messages) != 2
                or [m.get("role") for m in messages if isinstance(m, dict)] != ["system", "user"]
                or any(not isinstance(m.get("content"), str) for m in messages)):
            raise ValueError("context packet messages are malformed")
        if _digest(row.get("messages_sha256"), "messages") != sha256_json(messages):
            raise ValueError("frozen packet message digest differs")
        if row.get("max_output_tokens") != OUTPUT_RESERVE or row.get("grader", {}).get("kind") != "evidence_attribution":
            raise ValueError("context output/grader differs")
        for key in ("source_task_sha256", "focal_records_sha256"):
            _digest(row.get(key), key)
        fixed = (row["source_task_sha256"], row["focal_records_sha256"])
        if source_id in source_focal and source_focal[source_id] != fixed:
            raise ValueError("focal evidence changed across contexts")
        source_focal[source_id] = fixed
    if len(source_ids) != 4 or matrix != {(s, t, p) for s in source_ids for t in TARGETS for p in PLACEMENTS}:
        raise ValueError("context task/target/placement matrix is incomplete")
    return value


def _tokenizer_receipt(endpoint_name: str) -> dict[str, Any]:
    registration = ENDPOINTS[endpoint_name]
    model_dir = Path(registration["tokenizer_path"])
    files = {}
    for name in ("chat_template.jinja", "tokenizer.json", "tokenizer_config.json"):
        raw, _ = harness._read_regular_file(model_dir / name, label=f"{endpoint_name}.{name}", max_bytes=40_000_000)
        files[name] = hashlib.sha256(raw).hexdigest()
    if files["chat_template.jinja"] != registration["template_sha256"]:
        raise ValueError("registered arm chat template differs")
    return {"path": str(model_dir), "file_sha256": files}


def _verified_tokenization(pack: dict[str, Any], endpoint_name: str) -> tuple[dict[str, Any], list[TokenizedCell]]:
    """Bind every precomputed count to one frozen packet and local tokenizer.

    The count producer used the pinned CPU-only image, builder helper, exact
    registered template, and offline AutoTokenizer. This reader is bounded and
    does no tokenizer/model work inside a serving window.
    """
    raw, _ = harness._read_regular_file(TOKENIZATION_PATH, label="context tokenizer preflight", max_bytes=200_000)
    if hashlib.sha256(raw).hexdigest() != TOKENIZATION_SHA256:
        raise ValueError("context tokenizer preflight bytes drifted")
    receipt = json.loads(raw)
    if (not isinstance(receipt, dict) or receipt.get("schema_version") != "flash-context-arm-tokenization/v1"
            or receipt.get("pack_sha256") != PACK_SHA256
            or receipt.get("builder_sha256") != BUILDER_SHA256
            or receipt.get("image_id") != CPU_IMAGE_ID
            or receipt.get("transformers_version") != "5.15.1"
            or receipt.get("tokenization_kwargs") != {
                "tokenize": True, "add_generation_prompt": True,
                "enable_thinking": False, "return_dict": False,
            } or not isinstance(receipt.get("arms"), dict)
            or set(receipt["arms"]) != set(ENDPOINTS)):
        raise ValueError("context tokenizer preflight source/controls differ")
    producer_raw, _ = harness._read_regular_file(TOKENIZER_PROBE_PATH, label="context tokenizer producer", max_bytes=20_000)
    if hashlib.sha256(producer_raw).hexdigest() != TOKENIZER_PROBE_SHA256:
        raise ValueError("context tokenizer preflight producer source drifted")
    execution_raw, _ = harness._read_regular_file(EXECUTION_PATH, label="context tokenizer execution", max_bytes=10_000)
    if hashlib.sha256(execution_raw).hexdigest() != EXECUTION_SHA256:
        raise ValueError("context tokenizer execution proof drifted")
    execution = json.loads(execution_raw)
    if not isinstance(execution, dict):
        raise TypeError("context tokenizer execution proof is malformed")
    controls = execution.get("container_controls", {})
    if (execution.get("result") != "completed" or execution.get("observed_exit_code") != 0
            or execution.get("image", {}).get("id") != CPU_IMAGE_ID
            or execution.get("image", {}).get("architecture") != "arm64"
            or execution.get("receipt", {}).get("sha256") != TOKENIZATION_SHA256
            or execution.get("source", {}).get("producer_sha256") != TOKENIZER_PROBE_SHA256
            or controls.get("runtime") != "runc" or controls.get("network") != "none"
            or controls.get("gpu_device_flags") != []
            or controls.get("nvidia_visible_devices") != "void"
            or controls.get("cuda_visible_devices") != ""
            or controls.get("rootfs_read_only") is not True
            or controls.get("model_and_pack_mounts") != "read_only"):
        raise ValueError("context tokenizer execution controls differ")
    arm = receipt["arms"][endpoint_name]
    files = _tokenizer_receipt(endpoint_name)["file_sha256"]
    if (not isinstance(arm, dict) or arm.get("tokenizer_path") != ENDPOINTS[endpoint_name]["tokenizer_path"]
            or arm.get("template_sha256") != files["chat_template.jinja"]
            or arm.get("tokenizer_json_sha256") != files["tokenizer.json"]
            or arm.get("tokenizer_config_sha256") != files["tokenizer_config.json"]):
        raise ValueError("precomputed arm tokenizer differs from registered local files")
    counts = arm.get("counts")
    if not isinstance(counts, list) or len(counts) != 60:
        raise ValueError("precomputed arm must cover all sixty packets")
    results = []
    for pack_row, count in zip(pack["tasks"], counts, strict=True):
        if (not isinstance(count, dict) or count.get("cell_id") != pack_row["id"]
                or count.get("source_task_id") != pack_row["source_task_id"]
                or count.get("target_input_tokens") != pack_row["target_input_tokens"]
                or count.get("placement") != pack_row["placement"]
                or count.get("source_messages_sha256") != pack_row["messages_sha256"]):
            raise ValueError("precomputed packet identity or message hash differs")
        actual = count.get("actual_input_tokens")
        required = count.get("minimum_server_context_tokens")
        if (type(actual) is not int or not 1 <= actual <= 131072
                or type(required) is not int or required != actual + OUTPUT_RESERVE):
            raise ValueError("precomputed count/reserve is invalid")
        results.append(TokenizedCell(pack_row["id"], actual, False, required))
    return receipt, results


def _cells(pack: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "cell_id": row["id"],
            "source_task_id": row["source_task_id"],
            "family": "context_evidence",
            "target_input_tokens": row["target_input_tokens"],
            "placement": row["placement"],
            "messages_sha256": row["messages_sha256"],
            "grader_sha256": sha256_json(row["grader"]),
            "focal_records_sha256": row["focal_records_sha256"],
            "timeout_s": TIMEOUTS_S[row["target_input_tokens"]],
        }
        for row in pack["tasks"]
    ]


def freeze_plan(endpoint_name: str, route: dict[str, Any]) -> dict[str, Any]:
    """Freeze one qualified, fixed local route; no messages enter this plan."""
    if endpoint_name not in ENDPOINTS or not isinstance(route, dict):
        raise ValueError("route must be a registered local model")
    required = {"served_model", "artifact_sha256", "runtime_sha256", "qualification_receipt_sha256", "max_model_len"}
    if set(route) != required or route["served_model"] != ENDPOINTS[endpoint_name]["model"]:
        raise ValueError("route identity fields differ")
    if type(route["max_model_len"]) is not int or not 4096 <= route["max_model_len"] <= 131072:
        raise ValueError("server max context is absent or out of bounds")
    for key in required - {"served_model", "max_model_len"}:
        _digest(route[key], f"route.{key}")
    LocalEndpoint(endpoint_name, ENDPOINTS[endpoint_name]["url"], route["served_model"], route["artifact_sha256"]).validate()
    pack = _pack()
    tokenization, _ = _verified_tokenization(pack, endpoint_name)
    source_files = {
        "bench/weekly_upgrade_eval/runner.py": sha256_file(objective_runner.__file__),
        "bench/weekly_upgrade_eval/manifest.py": sha256_file(objective_manifest.__file__),
        "bench/flash_next_ab/adapters.py": sha256_file(flash_adapters.__file__),
        "bench/flash_next_ab/transport.py": sha256_file(Path(harness.__file__).with_name("transport.py")),
        "bench/flash_next_ab/harness.py": sha256_file(harness.__file__),
        "context_sweep.py": sha256_file(__file__),
        str(TOKENIZER_PROBE_PATH): TOKENIZER_PROBE_SHA256,
    }
    policy = {"temperature": 0.0, "top_p": 1.0, "top_k": ENDPOINTS[endpoint_name]["top_k"]}
    if endpoint_name != "resident_gemma":
        policy["enable_thinking"] = False
    plan = {
        "schema_version": PLAN_SCHEMA,
        "suite_id": pack["suite_id"],
        "endpoint_name": endpoint_name,
        "route": copy.deepcopy(route),
        "tokenizer": _tokenizer_receipt(endpoint_name),
        "source": {"pack_path": str(PACK_PATH), "pack_sha256": PACK_SHA256,
                   "builder_sha256": BUILDER_SHA256, "source_sha256": SOURCE_SHA256,
                   "tokenization_path": str(TOKENIZATION_PATH),
                   "tokenization_sha256": TOKENIZATION_SHA256,
                   "tokenization_image_id": CPU_IMAGE_ID,
                   "tokenization_execution_path": str(EXECUTION_PATH),
                   "tokenization_execution_sha256": EXECUTION_SHA256,
                   "source_files": source_files},
        "tokenization_arm_sha256": sha256_json(tokenization["arms"][endpoint_name]),
        "declared_cells": _cells(pack),
        "policy": policy,
        "output_reserve_tokens": OUTPUT_RESERVE,
        "caps": {"timeouts_s_by_target": {str(k): v for k, v in TIMEOUTS_S.items()},
                 "maximum_wall_s_all_cells": sum(TIMEOUTS_S[c["target_input_tokens"]] for c in _cells(pack))},
        "promotion_authorized": False,
        "claim_limit": "PUBLIC_SYNTHETIC_CONTEXT_DIAGNOSTIC",
    }
    plan["plan_sha256"] = sha256_json(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("endpoint_name") not in ENDPOINTS:
        raise ValueError("context plan is absent or uses an unknown endpoint")
    expected = freeze_plan(plan["endpoint_name"], plan.get("route"))
    if plan != expected:
        raise ValueError("frozen packets, tokenizer, policy, route, or source drifted")
    return _pack()


def _retokenize(plan: dict[str, Any], pack: dict[str, Any]) -> list[TokenizedCell]:
    receipt, verified = _verified_tokenization(pack, plan["endpoint_name"])
    if sha256_json(receipt["arms"][plan["endpoint_name"]]) != plan["tokenization_arm_sha256"]:
        raise ValueError("precomputed arm tokenization differs from frozen plan")
    result = []
    max_context = plan["route"]["max_model_len"]
    for row in verified:
        result.append(TokenizedCell(row.cell_id, row.input_tokens,
                                    row.required_context_tokens <= max_context,
                                    row.required_context_tokens))
    return result


def _grade(row: dict[str, Any], call) -> dict[str, Any]:
    """Use the existing strict JSON/evidence grader, adding role order."""
    messages = row["messages"]
    task = Task(
        id=row["id"], family="context_evidence", mode="chat",
        system=messages[0]["content"], prompt=messages[1]["content"],
        grader=row["grader"], tools=(),
        input_sha256=row["messages_sha256"], grader_sha256=sha256_json(row["grader"]),
    )
    result = objective_runner.InvocationResult(
        completion=call.content or "", failure_code=None if call.status == "returned" else call.receipt.get("failure_code") or call.status
    )
    graded = objective_runner.grade_task(task, result)
    passed, reason_code = bool(graded.passed), "objective_grade"
    if passed:
        parsed, error = objective_runner._strict_object(call.content or "")
        if error or parsed is None or parsed.get("citations") != row["grader"]["expected"]["citations"]:
            passed, reason_code = False, "citation_role_order"
    return {"passed": passed, "reason_code": reason_code if passed or reason_code != "objective_grade" else "objective_mismatch",
            "grader_sha256": task.grader_sha256}


def _atomic_json(path: Path, value: Any) -> None:
    raw = canonical_json(value) + b"\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    os.replace(temporary, path)


def _public_call(receipt: dict[str, Any]) -> dict[str, Any]:
    """Keep hashes, timing and protocol identity; errors/content remain private."""
    return {k: copy.deepcopy(v) for k, v in receipt.items() if k != "error"}


def run_model(
    plan: dict[str, Any], *, output_dir: str | Path, runtime_budget_s: float,
    admission_gate: Callable[[dict[str, Any]], dict[str, Any]],
    safety_check: Callable[[dict[str, Any]], dict[str, Any]],
    work_cutoff_s: float, target_block: int | None = None,
    invoke_fn: Callable[..., dict[str, Any]] = complete,
    cancel_event: Any = None, monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run one serial local arm inside a controller-owned qualification lease.

    The admission ticket is a trusted controller output, not an input from a
    model. It must bind the active lease and exact prior qualification receipt.
    An export consumer still needs final controller restoration proof.
    """
    pack = validate_plan(plan)
    if target_block is not None and target_block not in TARGETS:
        raise ValueError("target block is not in the registered five-context matrix")
    if (not callable(admission_gate) or not callable(safety_check)
            or not callable(invoke_fn)):
        raise TypeError("controller admission, monitor and local transport are required")
    if (type(runtime_budget_s) not in (int, float) or not math.isfinite(runtime_budget_s)
            or runtime_budget_s <= 0 or type(work_cutoff_s) not in (int, float)
            or not math.isfinite(work_cutoff_s)):
        raise ValueError("finite runtime budget and absolute monotonic cutoff required")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise ValueError("cancel_event must expose is_set()")
    ticket = admission_gate(plan)  # Must validate controller lease, receipt and active model.
    if not isinstance(ticket, dict) or set(ticket) != {
        "status", "endpoint_name", "qualification_receipt_sha256", "served_model",
        "artifact_sha256", "runtime_sha256", "max_model_len", "lease_sha256", "work_cutoff_s",
    } or ticket["status"] != "admitted":
        raise ValueError("qualified controller admission ticket is absent")
    route = plan["route"]
    for key in ("served_model", "artifact_sha256", "runtime_sha256", "max_model_len", "qualification_receipt_sha256"):
        if ticket[key] != route[key]:
            raise ValueError("controller ticket differs from selected route")
    if ticket["endpoint_name"] != plan["endpoint_name"] or ticket["work_cutoff_s"] != work_cutoff_s:
        raise ValueError("controller lease endpoint/deadline differs")
    _digest(ticket["lease_sha256"], "controller lease")

    def guarded() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise ContextWindowAbort("cancelled")
        if monotonic() >= work_cutoff_s:
            raise ContextWindowAbort("work_cutoff")
        try:
            sample = safety_check(ticket)
        except Exception as exc:
            raise ContextWindowAbort("monitor_check_failed") from exc
        if (not isinstance(sample, dict) or set(sample) != {"status", "lease_sha256"}
                or sample["status"] != "safe" or sample["lease_sha256"] != ticket["lease_sha256"]):
            raise ContextWindowAbort("monitor_check_contract")
        if cancel_event is not None and cancel_event.is_set():
            raise ContextWindowAbort("cancelled")

    guarded()  # Before tokenizer work, output creation or model requests.
    tokenized = _retokenize(plan, pack)
    selected = [cell for cell in plan["declared_cells"] if target_block is None or cell["target_input_tokens"] == target_block]
    token_by_id = {cell.cell_id: cell for cell in tokenized}
    supported = [cell for cell in selected if token_by_id[cell["cell_id"]].supported]
    if not supported:
        raise ValueError("no packet in the selected block fits the qualified server context")
    ceiling = sum(cell["timeout_s"] for cell in supported)
    if runtime_budget_s != ceiling or work_cutoff_s - monotonic() < ceiling:
        raise ValueError("whole supported block must fit before controller restoration cutoff")
    guarded()  # Tokenization could outlive a safe lease.
    output = harness._output_dir(output_dir)
    output.mkdir(mode=0o700, parents=True)
    output.chmod(0o700)
    _atomic_json(output / "plan.json", plan)
    _atomic_json(output / "tokenization.json", {
        "schema_version": "flash-context-arm-tokenization/v1", "plan_sha256": plan["plan_sha256"],
        "endpoint_name": plan["endpoint_name"], "max_model_len": route["max_model_len"],
        "output_reserve_tokens": OUTPUT_RESERVE,
        "cells": [{"cell_id": x.cell_id, "actual_input_tokens": x.input_tokens,
                   "minimum_server_context_tokens": x.required_context_tokens,
                   "supported": x.supported} for x in tokenized],
    })
    start, started_at = monotonic(), _utc()
    deadline = min(start + runtime_budget_s, work_cutoff_s)
    run_id = f"{plan['suite_id']}-{plan['endpoint_name']}-{target_block or 'all'}-{uuid.uuid4().hex}"
    arm = {"routes": [{"role": ROLE, "endpoint_name": plan["endpoint_name"],
                       "served_model": route["served_model"],
                       "artifact_sha256": route["artifact_sha256"],
                       "runtime_sha256": route["runtime_sha256"],
                       "policies": {POLICY_ID: copy.deepcopy(plan["policy"])}}]}
    pack_by_id = {row["id"]: row for row in pack["tasks"]}
    outcomes: list[dict[str, Any]] = []
    timing = TimingRecorder()
    observed_invoke = timing.wrap(invoke_fn)
    abort_reason = None
    evidence_ordinal = 0
    for cell in selected:
        row = pack_by_id[cell["cell_id"]]
        tokens = token_by_id[cell["cell_id"]]
        if not tokens.supported:
            outcome = {"cell_id": cell["cell_id"], "source_task_id": cell["source_task_id"],
                       "target_input_tokens": cell["target_input_tokens"], "placement": cell["placement"],
                       "messages_sha256": cell["messages_sha256"], "actual_input_tokens": tokens.input_tokens,
                       "minimum_server_context_tokens": tokens.required_context_tokens,
                       "supported": False, "status": "not_run", "reason_code": "qualified_context_unsupported",
                       "passed": None, "wall_s": 0.0, "calls": [], "private_call_evidence": [], "grade": None}
        elif abort_reason is not None:
            outcome = {"cell_id": cell["cell_id"], "source_task_id": cell["source_task_id"],
                       "target_input_tokens": cell["target_input_tokens"], "placement": cell["placement"],
                       "messages_sha256": cell["messages_sha256"], "actual_input_tokens": tokens.input_tokens,
                       "minimum_server_context_tokens": tokens.required_context_tokens,
                       "supported": True, "status": "not_run", "reason_code": abort_reason,
                       "passed": None, "wall_s": 0.0, "calls": [], "private_call_evidence": [], "grade": None}
        else:
            cell_start = monotonic()
            call = None
            private: list[dict[str, Any]] = []
            descriptor = None
            runner_error_type = None
            try:
                guarded()
                spec = CallSpec(
                    call_index=0, call_id=f"{run_id}/{cell['cell_id']}#0", role=ROLE,
                    policy_id=POLICY_ID, seed=SEED, max_tokens=OUTPUT_RESERVE,
                    timeout_s=cell["timeout_s"], required=True,
                    messages=tuple(copy.deepcopy(row["messages"])),
                )
                call = harness._invoke_call(
                    spec, arm=arm, deadline=min(deadline, cell_start + cell["timeout_s"]),
                    invoke_fn=observed_invoke, cancel_event=cancel_event, monotonic=monotonic,
                    evidence_sink=private.append,
                )
                evidence = {**private[-1], "run_id": run_id,
                            "endpoint_name": plan["endpoint_name"], "cell_id": cell["cell_id"]}
                descriptor = harness._persist_private_call(output, ordinal=evidence_ordinal, evidence=evidence)
                evidence_ordinal += 1
                guarded()
                grade = _grade(row, call)
                guarded()
            except ContextWindowAbort as exc:
                abort_reason = exc.reason
                grade = None
            except Exception as exc:  # noqa: BLE001 - durable attempted evidence is never a win
                abort_reason = "runner_error"
                grade = None
                runner_error_type = type(exc).__name__
            else:
                runner_error_type = None
            status = ("not_run" if call is None else "error" if abort_reason else call.status)
            outcome = {
                "cell_id": cell["cell_id"], "source_task_id": cell["source_task_id"],
                "target_input_tokens": cell["target_input_tokens"], "placement": cell["placement"],
                "messages_sha256": cell["messages_sha256"], "actual_input_tokens": tokens.input_tokens,
                "minimum_server_context_tokens": tokens.required_context_tokens,
                "supported": True, "status": status,
                "reason_code": abort_reason if abort_reason else grade["reason_code"] if grade else "unattempted",
                "passed": grade["passed"] if grade and status == "returned" else False if call else None,
                "wall_s": max(0.0, monotonic() - cell_start) if call else 0.0,
                "calls": [_public_call(call.receipt)] if call else [],
                "transport_timings": timing.for_calls([call.receipt] if call else []),
                "private_call_evidence": [descriptor] if descriptor else [],
                "grade": grade if status == "returned" else None,
                "runner_error_type": runner_error_type if abort_reason == "runner_error" else None,
            }
        outcome.setdefault("transport_timings", [])
        _atomic_json(output / f"outcome-{len(outcomes):03d}.json", outcome)
        outcomes.append(outcome)
    attempted = [row for row in outcomes if row["supported"] and row["calls"]]
    support_complete = (
        abort_reason is None
        and all((not row["supported"] and row["status"] == "not_run")
                or (row["supported"] and row["calls"] and len(row["private_call_evidence"]) == 1
                    and row["status"] in {"returned", "timeout", "error"})
                for row in outcomes)
        and not (cancel_event is not None and cancel_event.is_set())
    )
    status = ("aborted" if not support_complete else "block_complete" if target_block is not None
              else "complete_supported_subset" if len(supported) < len(selected) else "complete")
    summary = {"declared": len(selected), "supported": len(supported),
               "unsupported_not_run": sum(not row["supported"] for row in outcomes),
               "attempted": len(attempted), "returned": sum(row["status"] == "returned" for row in attempted),
               "timeout": sum(row["status"] == "timeout" for row in attempted),
               "error": sum(row["status"] == "error" for row in attempted),
               "passed": sum(row["passed"] is True for row in attempted),
               "wall_s_including_failures": sum(row["wall_s"] for row in attempted),
               "paired_comparison_eligible": support_complete}
    result = {"schema_version": RUN_SCHEMA, "run_id": run_id,
              "suite_id": plan["suite_id"], "endpoint_name": plan["endpoint_name"],
              "status": status, "aborted_reason": abort_reason,
              "target_block": target_block, "plan_sha256": plan["plan_sha256"],
              "plan": copy.deepcopy(plan), "lease_sha256": ticket["lease_sha256"],
              "qualification_receipt_sha256": route["qualification_receipt_sha256"],
              "started_at": started_at, "finished_at": _utc(),
              "elapsed_s": max(0.0, monotonic() - start),
              "declared_cells": [cell["cell_id"] for cell in selected],
              "outcomes": outcomes, "summary": summary,
              "promotion_authorized": False,
              "claim_limit": "PUBLIC_SYNTHETIC_CONTEXT_DIAGNOSTIC_REQUIRES_RESTORATION_PROOF"}
    _atomic_json(output / "run.json", result)
    return result


def paired_supported(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Descriptive matched support only; exclude unsupported and partial runs."""
    eligible = {"complete", "complete_supported_subset", "block_complete"}
    for run in (left, right):
        validate_run(run)
        if run["status"] not in eligible:
            raise ValueError("a paired context run is incomplete")
    if left["declared_cells"] != right["declared_cells"]:
        raise ValueError("context block pair differs")
    pair = []
    for a, b in zip(left["outcomes"], right["outcomes"], strict=True):
        if (a["cell_id"] != b["cell_id"] or a["messages_sha256"] != b["messages_sha256"]):
            raise ValueError("paired packets are not byte-identical")
        if a["supported"] and b["supported"]:
            pair.append((a, b))
    return {"schema_version": "flash-context-paired-supported-summary/v1",
            "left_endpoint": left["endpoint_name"], "right_endpoint": right["endpoint_name"],
            "declared": len(left["declared_cells"]), "paired_supported": len(pair),
            "excluded_unsupported": len(left["declared_cells"]) - len(pair),
            "left_passed": sum(a["passed"] is True for a, _ in pair),
            "right_passed": sum(b["passed"] is True for _, b in pair),
            "left_attempted": sum(bool(a["calls"]) for a, _ in pair),
            "right_attempted": sum(bool(b["calls"]) for _, b in pair),
            "left_timeout": sum(a["status"] == "timeout" for a, _ in pair),
            "right_timeout": sum(b["status"] == "timeout" for _, b in pair),
            "left_error": sum(a["status"] == "error" for a, _ in pair),
            "right_error": sum(b["status"] == "error" for _, b in pair),
            "claim_limit": "DESCRIPTIVE_PUBLIC_RECEIPTS_REQUIRES_PRIVATE_EVIDENCE_AND_RESTORATION_PROOF",
            "promotion_authorized": False}


def validate_run(run: dict[str, Any]) -> None:
    """Reject missing, duplicated, unsupported-donated, or incomplete cells.

    This validates public structure only. An external admission consumer must
    also verify every private evidence digest and final controller restoration.
    """
    if not isinstance(run, dict) or run.get("schema_version") != RUN_SCHEMA:
        raise ValueError("context run schema differs")
    plan = run.get("plan")
    pack = validate_plan(plan)
    if (run.get("plan_sha256") != plan["plan_sha256"]
            or run.get("endpoint_name") != plan["endpoint_name"]
            or run.get("qualification_receipt_sha256") != plan["route"]["qualification_receipt_sha256"]
            or run.get("promotion_authorized") is not False):
        raise ValueError("context run identity differs from frozen plan")
    block = run.get("target_block")
    if block is not None and block not in TARGETS:
        raise ValueError("context target block differs")
    expected = [cell for cell in plan["declared_cells"] if block is None or cell["target_input_tokens"] == block]
    outcomes = run.get("outcomes")
    if (not isinstance(outcomes, list) or len(outcomes) != len(expected)
            or run.get("declared_cells") != [cell["cell_id"] for cell in expected]):
        raise ValueError("context run cell membership differs")
    pack_rows = {row["id"]: row for row in pack["tasks"]}
    attempted = []
    unsupported = 0
    for declared, outcome in zip(expected, outcomes, strict=True):
        if not isinstance(outcome, dict):
            raise TypeError("context outcome is malformed")
        cell_id = declared["cell_id"]
        if (outcome.get("cell_id") != cell_id
                or outcome.get("source_task_id") != declared["source_task_id"]
                or outcome.get("target_input_tokens") != declared["target_input_tokens"]
                or outcome.get("placement") != declared["placement"]
                or outcome.get("messages_sha256") != pack_rows[cell_id]["messages_sha256"]):
            raise ValueError("context outcome source/cell differs")
        tokens = outcome.get("actual_input_tokens")
        required = outcome.get("minimum_server_context_tokens")
        if (type(tokens) is not int or tokens <= 0 or type(required) is not int
                or required != tokens + OUTPUT_RESERVE):
            raise ValueError("context actual token count/reserve differs")
        supported = required <= plan["route"]["max_model_len"]
        if outcome.get("supported") is not supported:
            raise ValueError("context support claim differs from qualified capacity")
        calls = outcome.get("calls")
        evidence = outcome.get("private_call_evidence")
        if not isinstance(calls, list) or not isinstance(evidence, list):
            raise TypeError("context call/evidence row is malformed")
        validate_timings(calls, outcome.get("transport_timings"))
        if not supported:
            unsupported += 1
            if (outcome.get("status") != "not_run" or outcome.get("reason_code") != "qualified_context_unsupported"
                    or calls or evidence or outcome.get("passed") is not None
                    or outcome.get("wall_s") != 0.0 or outcome.get("grade") is not None):
                raise ValueError("unsupported context donated a score")
            continue
        if not calls:
            if (run.get("status") != "aborted" or outcome.get("status") != "not_run"
                    or evidence or outcome.get("passed") is not None):
                raise ValueError("supported context was silently omitted")
            continue
        if len(calls) != 1 or len(evidence) != 1:
            raise ValueError("attempted context lacks one call and one private receipt")
        call = calls[0]
        if not isinstance(call, dict) or not isinstance(evidence[0], dict):
            raise TypeError("context call/descriptor is malformed")
        if (call.get("call_index") != 0 or call.get("role") != ROLE
                or call.get("endpoint_name") != plan["endpoint_name"]
                or call.get("served_model") != plan["route"]["served_model"]
                or call.get("artifact_sha256") != plan["route"]["artifact_sha256"]
                or call.get("messages_sha256") != declared["messages_sha256"]
                or call.get("max_tokens") != OUTPUT_RESERVE
                or call.get("seed") != SEED
                or call.get("policy_id") != POLICY_ID
                or call.get("resolved_policy_sha256") != sha256_json(plan["policy"])
                or evidence[0].get("call_id") != call.get("call_id")
                or evidence[0].get("status") != call.get("status")
                or call.get("status") not in {"returned", "timeout", "error"}
                or type(call.get("timeout_s")) not in (int, float)
                or not 0 < call["timeout_s"] <= declared["timeout_s"]):
            raise ValueError("context transport/provenance receipt differs")
        if call["status"] == "returned" and call.get("response_model") != plan["route"]["served_model"]:
            raise ValueError("returned context model identity differs")
        if type(outcome.get("wall_s")) not in (int, float) or not math.isfinite(outcome["wall_s"]) or outcome["wall_s"] < 0:
            raise ValueError("context attempted wall duration is invalid")
        if run.get("status") != "aborted" and outcome.get("status") != call["status"]:
            raise ValueError("completed context status differs from attempted call")
        if outcome.get("passed") is True and (call["status"] != "returned" or outcome.get("grade", {}).get("passed") is not True):
            raise ValueError("failed call donated a context pass")
        attempted.append(outcome)
    status = run.get("status")
    if status not in {"complete", "complete_supported_subset", "block_complete", "aborted"}:
        raise ValueError("context run terminal status differs")
    all_supported_attempted = all(not row["supported"] or bool(row["calls"]) for row in outcomes)
    if status != "aborted" and (not all_supported_attempted or run.get("aborted_reason") is not None):
        raise ValueError("partial context run was called complete")
    expected_status = ("block_complete" if block is not None else
                       "complete_supported_subset" if unsupported else "complete")
    if status != "aborted" and status != expected_status:
        raise ValueError("context support subset was mislabeled complete")
    summary = run.get("summary")
    if not isinstance(summary, dict) or any(summary.get(k) != v for k, v in {
        "declared": len(expected), "supported": len(expected) - unsupported,
        "unsupported_not_run": unsupported, "attempted": len(attempted),
        "returned": sum(r["status"] == "returned" for r in attempted),
        "timeout": sum(r["status"] == "timeout" for r in attempted),
        "error": sum(r["status"] == "error" for r in attempted),
        "passed": sum(r["passed"] is True for r in attempted),
    }.items()):
        raise ValueError("context denominator/count summary differs")
