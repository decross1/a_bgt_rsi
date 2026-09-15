"""Immutable plan receipts for the resident-bundle versus Flash evaluation.

The plan wraps existing frozen development fixtures.  It does not rewrite an
older manifest's model names or claim that a new run extends an old series.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_SCHEMA = "flash-next-ab-plan/v1"
RUN_SCHEMA = "flash-next-ab-run/v1"
SUITE_ID = "flash-next-role-bundle-development-ab-v1-2026-09-15"
COHORTS = ("resident", "flash")
ROLES = (
    "generator",
    "planner",
    "critic",
    "evidence",
    "execution",
    "coding",
    "validator",
)
HASH_FIELDS = (
    "declared_cells_sha256",
    "sources_sha256",
    "arms_sha256",
    "adapter_bundle_sha256",
)

_ENDPOINTS = {
    "resident_gemma": "gemma-4-26b-a4b",
    "resident_qwen": "qwen3.8-27b-nvfp4-mtp",
    "flash_next": "qwen3.8-flash-next",
}


class PlanError(ValueError):
    """The A/B plan is ambiguous, mutable, or internally inconsistent."""


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PlanError(f"value is not canonical JSON: {exc}") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Any, where: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PlanError(f"{where} must be a lowercase SHA-256")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{where} must be a non-empty string")
    return value


def _number(value: Any, where: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError(f"{where} must be finite")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise PlanError(f"{where} must be finite{' and positive' if positive else ''}")
    return result


def resolved_policy(policy_id: str, endpoint_name: str) -> dict[str, Any]:
    """Resolve one logical policy without pretending Gemma has Qwen effort."""
    bases: dict[str, dict[str, Any]] = {
        "deterministic": {"temperature": 0.0, "top_p": 1.0},
        "planner": {"temperature": 0.1, "top_p": 0.9},
        "scientist": {"temperature": 0.7, "top_p": 0.95},
        "precise": {"temperature": 0.2, "top_p": 0.95},
        "coding_precise": {"temperature": 0.2, "top_p": 0.9},
        "critic_current": {
            "temperature": 0.2,
            "top_p": 0.95,
            "reasoning_effort": "xhigh",
        },
        "critic_medium": {
            "temperature": 0.2,
            "top_p": 0.95,
            "reasoning_effort": "medium",
        },
        "explore": {
            "temperature": 1.0,
            "top_p": 0.95,
            "reasoning_effort": "medium",
        },
    }
    if policy_id not in bases:
        raise PlanError(f"unknown logical policy {policy_id!r}")
    policy = dict(bases[policy_id])
    # Qwen/Flash model defaults use top_k=20 while resident Gemma defaults to
    # 64.  Send one explicit value so sampled cells do not silently measure
    # that generation-config difference.
    policy["top_k"] = 20
    if endpoint_name == "resident_gemma":
        policy.pop("reasoning_effort", None)
    elif endpoint_name not in {"resident_qwen", "flash_next"}:
        raise PlanError(f"unknown endpoint {endpoint_name!r}")
    return policy


def policy_set(endpoint_name: str) -> dict[str, dict[str, Any]]:
    return {
        policy_id: resolved_policy(policy_id, endpoint_name)
        for policy_id in (
            "coding_precise",
            "critic_current",
            "critic_medium",
            "deterministic",
            "explore",
            "planner",
            "precise",
            "scientist",
        )
    }


def _validate_route(route: Any, cohort: str, index: int) -> dict[str, Any]:
    where = f"arms[{cohort}].routes[{index}]"
    expected = {
        "role",
        "endpoint_name",
        "served_model",
        "artifact_sha256",
        "runtime_sha256",
        "policies",
        "policy_set_sha256",
    }
    if not isinstance(route, dict) or set(route) != expected:
        raise PlanError(f"{where} fields differ")
    role = _text(route["role"], f"{where}.role")
    if role not in ROLES:
        raise PlanError(f"{where}.role is unsupported")
    endpoint_name = _text(route["endpoint_name"], f"{where}.endpoint_name")
    if endpoint_name not in _ENDPOINTS:
        raise PlanError(f"{where}.endpoint_name is unsupported")
    if route["served_model"] != _ENDPOINTS[endpoint_name]:
        raise PlanError(f"{where} served model differs from endpoint allowlist")
    expected_endpoint = (
        "resident_qwen" if cohort == "resident" and role == "critic"
        else "resident_gemma" if cohort == "resident"
        else "flash_next"
    )
    if endpoint_name != expected_endpoint:
        raise PlanError(f"{where} violates the fixed role bundle")
    _digest(route["artifact_sha256"], f"{where}.artifact_sha256")
    _digest(route["runtime_sha256"], f"{where}.runtime_sha256")
    expected_policies = policy_set(endpoint_name)
    if route["policies"] != expected_policies:
        raise PlanError(f"{where}.policies differ from the adapter policy set")
    if route["policy_set_sha256"] != sha256_json(expected_policies):
        raise PlanError(f"{where}.policy_set_sha256 does not match policies")
    return route


def make_arm_receipt(
    cohort: str,
    *,
    qualification_receipt_sha256: str,
    artifact_sha256_by_endpoint: dict[str, str],
    runtime_sha256_by_endpoint: dict[str, str],
) -> dict[str, Any]:
    """Construct a complete arm receipt; callers supply measured identities."""
    if cohort not in COHORTS:
        raise PlanError("cohort must be resident or flash")
    routes = []
    for role in ROLES:
        endpoint_name = (
            "resident_qwen" if cohort == "resident" and role == "critic"
            else "resident_gemma" if cohort == "resident"
            else "flash_next"
        )
        policies = policy_set(endpoint_name)
        routes.append(
            {
                "role": role,
                "endpoint_name": endpoint_name,
                "served_model": _ENDPOINTS[endpoint_name],
                "artifact_sha256": artifact_sha256_by_endpoint[endpoint_name],
                "runtime_sha256": runtime_sha256_by_endpoint[endpoint_name],
                "policies": policies,
                "policy_set_sha256": sha256_json(policies),
            }
        )
    arm = {
        "cohort": cohort,
        "qualification_receipt_sha256": qualification_receipt_sha256,
        "routes": routes,
    }
    validate_arms([arm], partial=True)
    return arm


def validate_arms(arms: Any, *, partial: bool = False) -> list[dict[str, Any]]:
    if not isinstance(arms, list) or not arms:
        raise PlanError("arms must be a non-empty array")
    expected_count = 1 if partial else 2
    if len(arms) != expected_count or any(not isinstance(arm, dict) for arm in arms):
        raise PlanError(f"arms must contain exactly {expected_count} entries")
    cohorts = []
    for arm in arms:
        if set(arm) != {"cohort", "qualification_receipt_sha256", "routes"}:
            raise PlanError("arm fields differ")
        cohort = arm["cohort"]
        if cohort not in COHORTS:
            raise PlanError("arm cohort is unsupported")
        cohorts.append(cohort)
        _digest(arm["qualification_receipt_sha256"], "qualification receipt")
        routes = arm["routes"]
        if not isinstance(routes, list) or len(routes) != len(ROLES):
            raise PlanError("each arm must bind every role exactly once")
        for index, route in enumerate(routes):
            _validate_route(route, cohort, index)
        if [route["role"] for route in routes] != list(ROLES):
            raise PlanError("arm routes must follow the canonical role order")
    if len(cohorts) != len(set(cohorts)):
        raise PlanError("arm cohorts must be unique")
    if not partial and cohorts != list(COHORTS):
        raise PlanError("arms must be ordered resident, flash")
    return arms


def plan_fingerprints(plan: dict[str, Any]) -> dict[str, str]:
    return {
        "declared_cells_sha256": sha256_json(plan["declared_cells"]),
        "sources_sha256": sha256_json(plan["sources"]),
        "arms_sha256": sha256_json(plan["arms"]),
        "adapter_bundle_sha256": sha256_json(plan["adapter_bundle"]),
    }


def build_plan(
    arms: list[dict[str, Any]],
    *,
    families: Iterable[str] | None = None,
    cell_ids: Iterable[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the canonical public plan and private loaded cell definitions."""
    validate_arms(arms)
    from .adapters import load_cells

    definitions = load_cells(families=families)
    if cell_ids is not None:
        requested = tuple(cell_ids)
        if not requested or len(requested) != len(set(requested)):
            raise PlanError("cell_ids must be a non-empty unique sequence")
        available = {cell.cell_id: cell for cell in definitions}
        missing = [cell_id for cell_id in requested if cell_id not in available]
        if missing:
            raise PlanError(f"requested cells are unavailable: {missing}")
        definitions = [available[cell_id] for cell_id in requested]
    if not definitions:
        raise PlanError("evaluation plan has no cells")
    declared = [cell.cell_id for cell in definitions]
    if len(declared) != len(set(declared)):
        raise PlanError("cell IDs are not globally unique")
    receipts = {cell.cell_id: cell.receipt() for cell in definitions}
    sources_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    adapters_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for cell in definitions:
        source = {key: cell.source[key] for key in (
            "family", "suite_id", "manifest_path", "manifest_sha256"
        )}
        sources_by_key[(source["family"], source["manifest_path"])] = source
        adapter = dict(cell.adapter)
        adapters_by_key[(adapter["id"], adapter["source_path"])] = adapter
    for adapter_id, source_path in (
        ("flash-next-plan/v1", "bench/flash_next_ab/manifest.py"),
        ("flash-next-harness/v1", "bench/flash_next_ab/harness.py"),
        ("flash-next-transport/v1", "bench/flash_next_ab/transport.py"),
    ):
        source = REPO_ROOT / source_path
        adapters_by_key[(adapter_id, source_path)] = {
            "id": adapter_id,
            "source_path": source_path,
            "source_sha256": sha256_file(source),
        }
    plan = {
        "schema_version": PLAN_SCHEMA,
        "suite_id": SUITE_ID,
        "cohorts": list(COHORTS),
        "arms": arms,
        "sources": list(sources_by_key.values()),
        "adapter_bundle": list(adapters_by_key.values()),
        "declared_cells": declared,
        "cell_receipts": receipts,
        "promotion_authorized": False,
        "limitations": [
            "Public development fixtures; no hidden-set confirmation.",
            "Legacy prompt and policy variants are diagnostics, not an extension of their old score series.",
            "Gemma has no Qwen reasoning_effort control; its effective policy omits that field and cannot estimate a reasoning-effort effect.",
            "Topic-scope hypothesis success is protocol compliance only until separate blinded semantic annotations exist.",
            "Same-checkpoint Flash generator and critic calls are correlated rather than independent review.",
        ],
    }
    validate_plan(plan)
    return plan, {cell.cell_id: cell for cell in definitions}


def validate_plan(plan: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "suite_id",
        "cohorts",
        "arms",
        "sources",
        "adapter_bundle",
        "declared_cells",
        "cell_receipts",
        "promotion_authorized",
        "limitations",
    }
    if not isinstance(plan, dict) or set(plan) != expected:
        raise PlanError("plan fields differ")
    if plan["schema_version"] != PLAN_SCHEMA or plan["suite_id"] != SUITE_ID:
        raise PlanError("plan schema or suite differs")
    if plan["cohorts"] != list(COHORTS):
        raise PlanError("plan cohorts differ")
    validate_arms(plan["arms"])
    if plan["promotion_authorized"] is not False:
        raise PlanError("plan cannot authorize promotion")
    declared = plan["declared_cells"]
    receipts = plan["cell_receipts"]
    for key, required in (("sources", {"family", "suite_id", "manifest_path", "manifest_sha256"}),
                          ("adapter_bundle", {"id", "source_path", "source_sha256"})):
        rows = plan[key]
        if not isinstance(rows, list) or not rows or any(
            not isinstance(row, dict) or set(row) != required for row in rows
        ):
            raise PlanError(f"plan {key} fields differ")
        for index, row in enumerate(rows):
            for field in required - {"manifest_sha256", "source_sha256"}:
                _text(row[field], f"{key}[{index}].{field}")
            hash_field = "manifest_sha256" if key == "sources" else "source_sha256"
            _digest(row[hash_field], f"{key}[{index}].{hash_field}")
    if not isinstance(plan["limitations"], list) or not plan["limitations"] or any(
        not isinstance(item, str) or not item.strip() for item in plan["limitations"]
    ):
        raise PlanError("plan limitations must be non-empty text")
    if (
        not isinstance(declared, list)
        or not declared
        or any(not isinstance(item, str) or not item for item in declared)
        or len(declared) != len(set(declared))
        or not isinstance(receipts, dict)
        or list(receipts) != declared
    ):
        raise PlanError("declared cells and receipts differ")
    call_ids: list[str] = []
    for cell_id, receipt in receipts.items():
        call_ids.extend(_validate_cell_receipt(cell_id, receipt))
    if len(call_ids) != len(set(call_ids)):
        raise PlanError("planned call IDs are not globally unique")
    canonical_json(plan)
    return plan


def _validate_cell_receipt(cell_id: str, receipt: Any) -> list[str]:
    expected = {
        "task_id",
        "family",
        "condition",
        "seed",
        "source",
        "adapter",
        "grader",
        "call_plan",
        "call_plan_sha256",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected:
        raise PlanError(f"cell {cell_id} receipt fields differ")
    for key in ("task_id", "family", "condition"):
        _text(receipt[key], f"cell {cell_id}.{key}")
    if isinstance(receipt["seed"], bool) or not isinstance(receipt["seed"], int):
        raise PlanError(f"cell {cell_id}.seed must be an integer")
    call_plan = receipt["call_plan"]
    if receipt["call_plan_sha256"] != sha256_json(call_plan):
        raise PlanError(f"cell {cell_id} call plan hash differs")
    if not isinstance(call_plan, dict) or set(call_plan) != {"mode", "steps"}:
        raise PlanError(f"cell {cell_id} call plan fields differ")
    if call_plan["mode"] not in {"fixed", "conditional"}:
        raise PlanError(f"cell {cell_id} call plan mode differs")
    steps = call_plan["steps"]
    if not isinstance(steps, list) or not steps:
        raise PlanError(f"cell {cell_id} needs at least one planned call")
    if [step.get("call_index") for step in steps if isinstance(step, dict)] != list(range(len(steps))):
        raise PlanError(f"cell {cell_id} call indices differ")
    optional_seen = False
    call_ids = []
    for index, step in enumerate(steps):
        required = {
            "call_index", "call_id", "role", "policy_id", "seed",
            "max_tokens", "timeout_s", "required", "messages_sha256",
            "messages_builder_sha256", "tools_sha256",
        }
        if not isinstance(step, dict) or set(step) != required:
            raise PlanError(f"cell {cell_id} step {index} fields differ")
        if step["role"] not in ROLES:
            raise PlanError(f"cell {cell_id} step {index} role differs")
        if not isinstance(step["required"], bool):
            raise PlanError(f"cell {cell_id} step {index} required must be boolean")
        optional_seen = optional_seen or not step["required"]
        if optional_seen and step["required"]:
            raise PlanError(f"cell {cell_id} required calls must precede optional calls")
        if call_plan["mode"] == "fixed" and not step["required"]:
            raise PlanError(f"cell {cell_id} fixed call plan cannot contain optional calls")
        _text(step["call_id"], f"cell {cell_id} step {index}.call_id")
        _text(step["policy_id"], f"cell {cell_id} step {index}.policy_id")
        call_ids.append(step["call_id"])
        if isinstance(step["seed"], bool) or not isinstance(step["seed"], int):
            raise PlanError(f"cell {cell_id} step {index} seed differs")
        if isinstance(step["max_tokens"], bool) or not isinstance(step["max_tokens"], int) or step["max_tokens"] <= 0:
            raise PlanError(f"cell {cell_id} step {index} max_tokens differs")
        _number(step["timeout_s"], f"cell {cell_id} step {index} timeout", positive=True)
        for key in ("messages_sha256", "messages_builder_sha256", "tools_sha256"):
            if step[key] is not None:
                _digest(step[key], f"cell {cell_id} step {index}.{key}")
        if (step["messages_sha256"] is None) == (step["messages_builder_sha256"] is None):
            raise PlanError(f"cell {cell_id} step {index} must bind messages or a builder")
        if step["tools_sha256"] is None:
            raise PlanError(f"cell {cell_id} step {index} must bind the tools array")
    source = receipt["source"]
    if not isinstance(source, dict) or set(source) != {
        "family", "suite_id", "manifest_path", "manifest_sha256", "task_sha256"
    }:
        raise PlanError(f"cell {cell_id} source fields differ")
    if source["family"] != receipt["family"]:
        raise PlanError(f"cell {cell_id} source family differs")
    for key in ("suite_id", "manifest_path"):
        _text(source[key], f"cell {cell_id}.source.{key}")
    for key in ("manifest_sha256", "task_sha256"):
        _digest(source[key], f"cell {cell_id}.source.{key}")
    adapter = receipt["adapter"]
    if not isinstance(adapter, dict) or set(adapter) != {"id", "source_path", "source_sha256"}:
        raise PlanError(f"cell {cell_id} adapter fields differ")
    _text(adapter["id"], f"cell {cell_id}.adapter.id")
    _text(adapter["source_path"], f"cell {cell_id}.adapter.source_path")
    _digest(adapter["source_sha256"], f"cell {cell_id}.adapter.source_sha256")
    grader = receipt["grader"]
    if not isinstance(grader, dict) or set(grader) != {
        "id", "contract_sha256", "source_files"
    }:
        raise PlanError(f"cell {cell_id} grader fields differ")
    _text(grader["id"], f"cell {cell_id}.grader.id")
    _digest(grader["contract_sha256"], f"cell {cell_id}.grader.contract_sha256")
    files = grader["source_files"]
    if not isinstance(files, list) or not files or any(
        not isinstance(row, dict) or set(row) != {"path", "sha256"} for row in files
    ):
        raise PlanError(f"cell {cell_id} grader source files differ")
    for row in files:
        _text(row["path"], f"cell {cell_id}.grader.source.path")
        _digest(row["sha256"], f"cell {cell_id}.grader.source.sha256")
    return call_ids


__all__ = [
    "COHORTS",
    "HASH_FIELDS",
    "PLAN_SCHEMA",
    "ROLES",
    "RUN_SCHEMA",
    "SUITE_ID",
    "PlanError",
    "build_plan",
    "canonical_json",
    "make_arm_receipt",
    "plan_fingerprints",
    "policy_set",
    "resolved_policy",
    "sha256_file",
    "sha256_json",
    "validate_arms",
    "validate_plan",
]
