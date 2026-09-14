"""Strict, side-effect-free manifest loader for the development portfolio."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    REPO_ROOT / "experiments" / "weekly_upgrade_game_science_dev_v0_2026-09-14.json"
)
SCHEMA_VERSION = "weekly-upgrade-game-science-development/v1"
PUBLICATION_CLASS = "public_synthetic_development"
EXPECTED_TASK_IDS = (
    "SCI-D075-LD-POWER-001",
    "SCI-D075-SORTITION-001",
    "SCI-D075-SOCIAL-CHOICE-001",
    "SCI-GT-COORDINATION-001",
    "EVID-D075-CYCLE-BOUNDARY-001",
    "EVID-GT-SIMPSON-001",
    "CODE-D075-DELEGATION-001",
    "CODE-GT-REGRET-001",
)
GRADER_KINDS = {
    "delegation_hhi",
    "sortition_representation",
    "social_choice",
    "coordination_equilibrium",
    "evidence_cycle_boundary",
    "evidence_simpson",
    "code_function",
}

_TOP_KEYS = {
    "schema_version",
    "suite_id",
    "description",
    "publication_class",
    "claim_limits",
    "ordering",
    "source_snapshot",
    "arms",
    "tasks",
    "resource_limits",
    "sandbox_runtime",
    "frozen_hashes",
}
_ARM_KEYS = {
    "id", "label", "backend", "model", "profile", "seed", "expected_policy",
}
_TASK_KEYS = {
    "id",
    "family",
    "mode",
    "system",
    "prompt",
    "max_tokens",
    "request_timeout_s",
    "grader",
    "starter",
    "provenance",
}
_PROVENANCE_KEYS = {"origin", "concept", "derivation", "source_refs", "claim_limit"}
_SANDBOX_KEYS = {
    "contract",
    "bubblewrap_path",
    "bubblewrap_sha256",
    "bubblewrap_version",
    "python_path",
    "python_sha256",
    "python_version",
}


class ManifestError(ValueError):
    """Raised when a portfolio input is ambiguous, mutable, or unsupported."""


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
        raise ManifestError(f"value is not canonical JSON: {exc}") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _keys(value: Any, expected: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{where} must be an object")
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise ManifestError(f"{where} fields differ: missing={missing}, extra={extra}")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where} must be a non-empty string")
    return value


def _integer(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ManifestError(f"{where} must be an integer >= {minimum}")
    return value


def _number(value: Any, where: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{where} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        suffix = " > 0" if positive else ""
        raise ManifestError(f"{where} must be finite{suffix}")
    return result


def _safe_repo_file(raw_path: Any, expected_sha: Any, where: str) -> Path:
    relative = Path(_text(raw_path, f"{where}.path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ManifestError(f"{where}.path must be a repository-relative path")
    resolved = (REPO_ROOT / relative).resolve()
    if REPO_ROOT not in resolved.parents:
        raise ManifestError(f"{where}.path escapes the repository")
    try:
        observed = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        raise ManifestError(f"cannot read {where}.path: {exc}") from exc
    if observed != _text(expected_sha, f"{where}.sha256"):
        raise ManifestError(f"{where}.sha256 does not match {relative}")
    return resolved


def _validate_arm(raw: Any, index: int) -> None:
    arm = _keys(raw, _ARM_KEYS, f"arms[{index}]")
    for key in ("id", "label", "backend", "model", "profile"):
        _text(arm[key], f"arms[{index}].{key}")
    seed = arm["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ManifestError(f"arms[{index}].seed must be an integer")
    expected = _keys(
        arm["expected_policy"],
        {"temperature", "top_p", "reasoning_effort"},
        f"arms[{index}].expected_policy",
    )
    _number(expected["temperature"], f"arms[{index}].expected_policy.temperature")
    _number(expected["top_p"], f"arms[{index}].expected_policy.top_p")
    if expected["reasoning_effort"] not in {"low", "medium", "xhigh", None}:
        raise ManifestError(f"arms[{index}].expected_policy.reasoning_effort is invalid")


def _validate_provenance(raw: Any, where: str) -> None:
    provenance = _keys(raw, _PROVENANCE_KEYS, where)
    if provenance["origin"] != "synthetic_authored_for_eval":
        raise ManifestError(f"{where}.origin must identify synthetic development data")
    for key in ("concept", "derivation", "claim_limit"):
        _text(provenance[key], f"{where}.{key}")
    refs = provenance["source_refs"]
    if not isinstance(refs, list) or not refs or any(
        not isinstance(item, str) or not item.strip() for item in refs
    ):
        raise ManifestError(f"{where}.source_refs must be non-empty strings")


def _validate_grader(raw: Any, mode: str, where: str) -> None:
    grader = _keys(raw, {"kind", "version", "inputs", "absolute_tolerance"}, where)
    kind = _text(grader["kind"], f"{where}.kind")
    if kind not in GRADER_KINDS:
        raise ManifestError(f"{where}.kind is unsupported: {kind!r}")
    if grader["version"] != "1":
        raise ManifestError(f"{where}.version must be '1'")
    if not isinstance(grader["inputs"], dict):
        raise ManifestError(f"{where}.inputs must be an object")
    _number(grader["absolute_tolerance"], f"{where}.absolute_tolerance")
    if (mode == "code") != (kind == "code_function"):
        raise ManifestError(f"{where}.kind does not match task mode")
    inputs = grader["inputs"]
    expected_input_keys = {
        "delegation_hhi": {"baseline_weights", "delegated_weights"},
        "sortition_representation": {"population", "eligible", "seats"},
        "social_choice": {"candidates", "ballots"},
        "coordination_equilibrium": {"actions", "row_payoffs", "column_payoffs"},
        "evidence_cycle_boundary": {"required_citations", "documents"},
        "evidence_simpson": {"required_citations", "strata"},
        "code_function": {"cases"},
    }
    _keys(inputs, expected_input_keys[kind], f"{where}.inputs")
    canonical_json(inputs)
    if kind == "code_function":
        cases = inputs["cases"]
        if not isinstance(cases, list) or not cases:
            raise ManifestError(f"{where}.inputs.cases must be a non-empty array")
        ids: list[str] = []
        for index, case in enumerate(cases):
            case_where = f"{where}.inputs.cases[{index}]"
            if not isinstance(case, dict):
                raise ManifestError(f"{case_where} must be an object")
            variant = {"id", "arguments", "timeout_s", "expected_return"}
            exception_variant = {"id", "arguments", "timeout_s", "expected_exception"}
            if frozenset(case) not in {frozenset(variant), frozenset(exception_variant)}:
                raise ManifestError(f"{case_where} must define one return or exception oracle")
            ids.append(_text(case["id"], f"{case_where}.id"))
            if not isinstance(case["arguments"], list):
                raise ManifestError(f"{case_where}.arguments must be an array")
            _number(case["timeout_s"], f"{case_where}.timeout_s", positive=True)
            if "expected_exception" in case:
                _text(case["expected_exception"], f"{case_where}.expected_exception")
        if len(ids) != len(set(ids)):
            raise ManifestError(f"{where}.inputs.cases IDs must be unique")


def _validate_task(raw: Any, index: int) -> None:
    task = _keys(raw, _TASK_KEYS, f"tasks[{index}]")
    for key in ("id", "family", "mode", "system", "prompt"):
        _text(task[key], f"tasks[{index}].{key}")
    if task["family"] not in {"scientific", "evidence", "coding"}:
        raise ManifestError(f"tasks[{index}].family is unsupported")
    if task["mode"] not in {"structured", "code"}:
        raise ManifestError(f"tasks[{index}].mode is unsupported")
    _integer(task["max_tokens"], f"tasks[{index}].max_tokens", minimum=1)
    _number(task["request_timeout_s"], f"tasks[{index}].request_timeout_s", positive=True)
    _validate_grader(task["grader"], task["mode"], f"tasks[{index}].grader")
    _validate_provenance(task["provenance"], f"tasks[{index}].provenance")

    starter = task["starter"]
    if task["mode"] == "structured":
        if starter is not None:
            raise ManifestError(f"tasks[{index}].starter must be null")
    else:
        starter = _keys(starter, {"path", "sha256", "function"}, f"tasks[{index}].starter")
        _text(starter["function"], f"tasks[{index}].starter.function")
        _safe_repo_file(starter["path"], starter["sha256"], f"tasks[{index}].starter")


def _validate_sandbox_runtime(raw: Any) -> None:
    runtime = _keys(raw, _SANDBOX_KEYS, "sandbox_runtime")
    if runtime["contract"] != "bubblewrap-python-function/v1":
        raise ManifestError("sandbox_runtime.contract is unsupported")
    for key in ("bubblewrap_path", "bubblewrap_version", "python_path", "python_version"):
        _text(runtime[key], f"sandbox_runtime.{key}")
    for key in ("bubblewrap_sha256", "python_sha256"):
        value = _text(runtime[key], f"sandbox_runtime.{key}")
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ManifestError(f"sandbox_runtime.{key} must be a lowercase SHA-256")
    if not Path(runtime["bubblewrap_path"]).is_absolute():
        raise ManifestError("sandbox_runtime.bubblewrap_path must be absolute")
    if not Path(runtime["python_path"]).is_absolute():
        raise ManifestError("sandbox_runtime.python_path must be absolute")


def validate_manifest(doc: Any) -> None:
    manifest = _keys(doc, _TOP_KEYS, "manifest")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ManifestError(f"schema_version must be {SCHEMA_VERSION!r}")
    _text(manifest["suite_id"], "suite_id")
    _text(manifest["description"], "description")
    if manifest["publication_class"] != PUBLICATION_CLASS:
        raise ManifestError(f"publication_class must be {PUBLICATION_CLASS!r}")
    limits = manifest["claim_limits"]
    if not isinstance(limits, list) or not limits or any(
        not isinstance(item, str) or not item.strip() for item in limits
    ):
        raise ManifestError("claim_limits must be a non-empty array of strings")
    if manifest["ordering"] != "alternating_ab_ba":
        raise ManifestError("ordering must be alternating_ab_ba")

    source = _keys(manifest["source_snapshot"], {"path", "sha256"}, "source_snapshot")
    _safe_repo_file(source["path"], source["sha256"], "source_snapshot")

    arms = manifest["arms"]
    if not isinstance(arms, list) or len(arms) != 2:
        raise ManifestError("arms must contain exactly two entries")
    for index, arm in enumerate(arms):
        _validate_arm(arm, index)
    if [arm["id"] for arm in arms] != ["A", "B"]:
        raise ManifestError("arms must be ordered A, B")

    tasks = manifest["tasks"]
    if not isinstance(tasks, list):
        raise ManifestError("tasks must be an array")
    for index, task in enumerate(tasks):
        _validate_task(task, index)
    if tuple(task["id"] for task in tasks) != EXPECTED_TASK_IDS:
        raise ManifestError("tasks must be the eight preregistered IDs in order")

    resources = _keys(
        manifest["resource_limits"],
        {
            "max_total_runtime_s",
            "max_grading_runtime_s",
            "planned_calls",
            "calls_serial",
            "max_raw_completion_bytes",
        },
        "resource_limits",
    )
    if resources != {
        "max_total_runtime_s": 2280,
        "max_grading_runtime_s": 120,
        "planned_calls": 16,
        "calls_serial": True,
        "max_raw_completion_bytes": 131072,
    }:
        raise ManifestError("resource_limits drifted from the development preregistration")
    _validate_sandbox_runtime(manifest["sandbox_runtime"])

    expected_hashes = {
        "arms": sha256_json(arms),
        "tasks": {task["id"]: sha256_json(task) for task in tasks},
        "starter_files": {
            task["id"]: task["starter"]["sha256"]
            for task in tasks
            if task["starter"] is not None
        },
    }
    if manifest["frozen_hashes"] != expected_hashes:
        raise ManifestError("frozen_hashes do not match the literal portfolio inputs")


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    try:
        raw = manifest_path.read_bytes()
        doc = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load manifest {manifest_path}: {exc}") from exc
    validate_manifest(doc)
    result = dict(doc)
    result["_path"] = str(manifest_path)
    result["_raw_sha256"] = hashlib.sha256(raw).hexdigest()
    result["_configuration_sha256"] = sha256_json(doc)
    return result


def plan_dict(manifest: dict[str, Any]) -> dict[str, Any]:
    order: list[dict[str, Any]] = []
    arm_ids = [arm["id"] for arm in manifest["arms"]]
    for index, task in enumerate(manifest["tasks"]):
        ordered = arm_ids if index % 2 == 0 else list(reversed(arm_ids))
        for arm_id in ordered:
            order.append(
                {
                    "attempt_id": f"{task['id']}:{arm_id}",
                    "task_id": task["id"],
                    "family": task["family"],
                    "arm": arm_id,
                    "task_sha256": manifest["frozen_hashes"]["tasks"][task["id"]],
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "suite_id": manifest["suite_id"],
        "manifest_path": manifest["_path"],
        "manifest_sha256": manifest["_raw_sha256"],
        "configuration_sha256": manifest["_configuration_sha256"],
        "planned_calls": len(order),
        "runtime_ceiling_s": manifest["resource_limits"]["max_total_runtime_s"],
        "sandbox_runtime": manifest["sandbox_runtime"],
        "order": order,
        "notice": (
            "Public synthetic development evaluation only; no hidden-set, "
            "promotion, dispatch, service, or scheduler authority."
        ),
    }
