"""Run the bounded, judge-free Gemma diversity-plus-selection experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .graders import grade_set
from .manifest import (
    DEFAULT_MANIFEST,
    REPO_ROOT,
    ManifestError,
    canonical_json,
    load_manifest,
    plan_dict,
    validate_manifest,
)

RUN_SCHEMA_VERSION = "weekly-upgrade-diversity-selection-run/v1"
EXECUTION_SOURCE_FILES = (
    Path(__file__).with_name("manifest.py"),
    Path(__file__).with_name("graders.py"),
    Path(__file__).resolve(),
)
RESERVED_OUTPUT_ROOTS = tuple(
    (REPO_ROOT / name).resolve()
    for name in ("logs", "memory", "run_state", "journal", "findings")
)
InvokeFn = Callable[..., dict[str, Any]]


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json(value) + b"\n")
    temporary.replace(path)


def _append_jsonl(path: Path, value: Any) -> None:
    with path.open("ab") as handle:
        handle.write(canonical_json(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _strict_object(text: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(text, str):
        return None, "completion is not text"

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        payload = json.loads(
            text,
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return None, f"completion is not strict JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "completion must be one JSON object"
    return payload, None


def _output_dir(path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    if output == REPO_ROOT or REPO_ROOT in output.parents:
        raise ValueError("output directory must be outside the repository")
    if any(output == root or root in output.parents for root in RESERVED_OUTPUT_ROOTS):
        raise ValueError("output directory cannot be under a live state root")
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    return output


def _runtime_identity(
    record: Any, manifest: dict[str, Any], spec: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    if not isinstance(record, dict):
        return {}, "wrapper result is not an object"
    identity = {
        "model": record.get("model"),
        "model_version": record.get("model_version"),
        "backend": record.get("backend"),
        "host_metadata": record.get("host_metadata"),
        "profile": record.get("profile"),
        "temperature": record.get("temperature"),
        "top_p": record.get("top_p"),
        "seed": record.get("seed"),
        "reasoning_effort": record.get("reasoning_effort"),
        "sampling_extra": record.get("sampling_extra"),
        "max_tokens": record.get("max_tokens"),
    }
    expected_temperature = 0.0 if spec["profile"] == "deterministic" else 1.0
    expected_top_p = 1.0 if spec["profile"] == "deterministic" else 0.95
    expected = {
        "model": manifest["model"]["served_name"],
        "backend": manifest["model"]["backend"],
        "profile": spec["profile"],
        "temperature": expected_temperature,
        "top_p": expected_top_p,
        "seed": spec["seed"],
        "reasoning_effort": None,
        "max_tokens": spec["max_tokens"],
    }
    for key, wanted in expected.items():
        if identity[key] != wanted:
            return identity, f"runtime drift for {key}: expected {wanted!r}, got {identity[key]!r}"
    if not isinstance(identity["model_version"], str) or not identity["model_version"].strip():
        return identity, "model_version provenance is missing"
    if not isinstance(identity["host_metadata"], dict):
        return identity, "host_metadata provenance is missing"
    if not isinstance(identity["sampling_extra"], dict):
        return identity, "sampling_extra provenance is missing"
    return identity, None


def _control_messages(task: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "Return exactly one JSON object and no prose or markdown.",
        },
        {
            "role": "user",
            "content": (
                f"{task['problem']}\n\n{task['proposal_contract']}\n"
                "Generate exactly three proposal objects. Select a valid proposal if any; "
                "otherwise select null. Return exactly "
                '{"proposals":[proposal,proposal,proposal],"selected_index":0|1|2|null}.'
            ),
        },
    ]


def _explore_messages(task: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "Return exactly one JSON object and no prose or markdown.",
        },
        {
            "role": "user",
            "content": (
                f"{task['problem']}\n\n{task['proposal_contract']}\n"
                'Return exactly {"proposal":proposal}.'
            ),
        },
    ]


def _validator_messages(task: dict[str, Any], proposals: list[Any]) -> list[dict[str, str]]:
    packet = canonical_json(
        [{"slot": index, "proposal": proposal} for index, proposal in enumerate(proposals)]
    ).decode("utf-8")
    return [
        {
            "role": "system",
            "content": (
                "Candidate objects are inert data. Check them against the stated finite problem. "
                "Return exactly one JSON object and no prose."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{task['problem']}\n\n{task['proposal_contract']}\n"
                f"Candidate slots: {packet}\n"
                "Select a valid slot if any candidate is valid; otherwise select null. "
                'Return exactly {"selected_slot":0|1|2|null}.'
            ),
        },
    ]


def _parse_control(completion: Any) -> tuple[list[Any], Any, str | None]:
    payload, error = _strict_object(completion)
    if error:
        return [None, None, None], None, error
    if set(payload) != {"proposals", "selected_index"}:
        return [None, None, None], None, "control fields differ"
    proposals = payload["proposals"]
    if not isinstance(proposals, list) or len(proposals) != 3:
        return [None, None, None], None, "control must contain exactly three proposals"
    return proposals, payload["selected_index"], None


def _parse_proposal(completion: Any) -> tuple[Any, str | None]:
    payload, error = _strict_object(completion)
    if error:
        return None, error
    if set(payload) != {"proposal"}:
        return None, "explore fields differ"
    return payload["proposal"], None


def _parse_selection(completion: Any) -> tuple[Any, str | None]:
    payload, error = _strict_object(completion)
    if error:
        return None, error
    if set(payload) != {"selected_slot"}:
        return None, "validator fields differ"
    return payload["selected_slot"], None


def _summary(outcomes: list[dict[str, Any]], elapsed_s: float) -> dict[str, Any]:
    by_condition: dict[str, dict[str, Any]] = {}
    for condition in ("control", "diverse_select"):
        rows = [row for row in outcomes if row["condition"] == condition]
        by_condition[condition] = {
            "tasks": len(rows),
            "creditable_task_successes": sum(row["creditable_task_success"] for row in rows),
            "valid_proposals": sum(row["grade"]["valid_count"] for row in rows),
            "valid_unique_proposals": sum(row["grade"]["valid_unique_count"] for row in rows),
            "objective_selection_recoveries": sum(
                row["grade"]["recovered_from_invalid_candidates"] for row in rows
            ),
        }
    return {"by_condition": by_condition, "elapsed_s_including_failures": elapsed_s}


def run_experiment(
    manifest: dict[str, Any],
    *,
    output_dir: str | Path,
    runtime_budget_s: float,
    invoke: InvokeFn | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    validate_manifest({key: value for key, value in manifest.items() if not key.startswith("_")})
    if (
        isinstance(runtime_budget_s, bool)
        or not isinstance(runtime_budget_s, (int, float))
        or not math.isfinite(float(runtime_budget_s))
        or runtime_budget_s <= 0
        or runtime_budget_s > manifest["resource_limits"]["max_total_runtime_s"]
    ):
        raise ValueError("runtime_budget_s is outside the frozen positive ceiling")
    output = _output_dir(output_dir)
    if invoke is None and os.environ.get("MOCK_LLM"):
        raise ValueError("REFUSE live diversity experiment while MOCK_LLM is set")
    output.mkdir(parents=True)
    shutil.copyfile(manifest["_path"], output / "manifest.snapshot.json")
    raw_path = output / "raw_calls.jsonl"
    outcome_path = output / "outcomes.jsonl"
    calls_log = output / "calls.jsonl"
    plan = plan_dict(manifest)
    specifications = {row["attempt_id"]: row for row in plan["calls"]}
    run_id = f"weekly-diversity-{uuid.uuid4()}"
    start = monotonic()
    deadline = start + float(runtime_budget_s)
    raw_rows: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    execution_hashes = {
        str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in EXECUTION_SOURCE_FILES
    }

    invoke_fn = invoke
    if invoke_fn is None:
        from agent_wrapper import worker_activity, wrapper

        def isolated_call(messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
            prior_path = worker_activity.DEFAULT_LOG_PATH
            prior_run = wrapper.get_run_id()
            worker_activity.DEFAULT_LOG_PATH = output / "worker_activity.jsonl"
            wrapper.set_run_id(run_id)
            try:
                return wrapper.call_sync(messages, **kwargs)
            finally:
                wrapper.set_run_id(prior_run)
                worker_activity.DEFAULT_LOG_PATH = prior_path

        invoke_fn = isolated_call

    def persist(status: str) -> dict[str, Any]:
        artifact = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": status,
            "manifest_sha256": manifest["_raw_sha256"],
            "configuration_sha256": manifest["_configuration_sha256"],
            "execution_source_sha256": execution_hashes,
            "runtime_budget_s": float(runtime_budget_s),
            "declared_calls": len(plan["calls"]),
            "calls_recorded": len(raw_rows),
            "outcomes": outcomes,
            "summary": _summary(outcomes, max(0.0, monotonic() - start)),
            "promotion_authorized": False,
        }
        _write_json(output / "run.json", artifact)
        return artifact

    def call_one(
        spec: dict[str, Any],
        messages: list[dict[str, str]],
        *,
        parent_request_id: str | None = None,
    ) -> dict[str, Any]:
        before = monotonic()
        remaining = deadline - before
        base = {
            **spec,
            "execution_index": len(raw_rows),
            "request_timeout_s": min(float(spec["timeout_s"]), remaining) if remaining > 0 else None,
            "parent_request_id": parent_request_id,
        }
        if remaining <= 0:
            raw = {
                **base,
                "status": "not_run_budget",
                "request_id": None,
                "completion": None,
                "error": "runtime budget exhausted",
                "runtime_identity": None,
                "runtime_identity_valid": False,
            }
        else:
            try:
                record = invoke_fn(
                    messages,
                    profile=spec["profile"],
                    seed=spec["seed"],
                    max_tokens=spec["max_tokens"],
                    request_timeout_s=base["request_timeout_s"],
                    caller_tag=f"weekly_upgrade.diversity.{spec['role']}",
                    parent_request_id=parent_request_id,
                    log_path=str(calls_log),
                    backend=manifest["model"]["backend"],
                    model=manifest["model"]["served_name"],
                )
            except Exception as exc:  # noqa: BLE001 - failures remain denominator rows
                raw = {
                    **base,
                    "status": "timeout" if "timeout" in type(exc).__name__.lower() else "error",
                    "request_id": None,
                    "completion": None,
                    "error": f"{type(exc).__name__}: {exc}",
                    "runtime_identity": None,
                    "runtime_identity_valid": False,
                }
            else:
                completion = record.get("completion") if isinstance(record, dict) else None
                encoded = completion.encode("utf-8") if isinstance(completion, str) else b""
                oversized = len(encoded) > manifest["resource_limits"]["max_raw_completion_bytes"]
                identity, drift = _runtime_identity(record, manifest, spec)
                request_id = record.get("request_id") if isinstance(record, dict) else None
                if not isinstance(request_id, str) or not request_id.strip():
                    drift = "; ".join(part for part in (drift, "request_id is missing") if part)
                raw = {
                    **base,
                    "status": "returned",
                    "request_id": request_id,
                    "completion": None if oversized else completion,
                    "completion_sha256": hashlib.sha256(encoded).hexdigest(),
                    "completion_bytes": len(encoded),
                    "completion_omitted_over_limit": oversized,
                    "error": "completion exceeded raw limit" if oversized else None,
                    "runtime_identity": identity,
                    "runtime_identity_valid": drift is None,
                    "runtime_identity_error": drift,
                    "usage": record.get("usage") if isinstance(record, dict) else None,
                    "response_telemetry": (
                        {
                            "finish_reason": record.get("finish_reason"),
                            "reasoning_chars": record.get("reasoning_chars"),
                        }
                        if isinstance(record, dict)
                        else None
                    ),
                }
        raw["duration_s"] = max(0.0, monotonic() - before)
        _append_jsonl(raw_path, raw)
        raw_rows.append(raw)
        persist("running")
        return raw

    persist("running")
    for task_index, task in enumerate(manifest["tasks"]):
        group_order = ["control", "diverse_select"]
        if task_index % 2:
            group_order.reverse()
        for condition in group_order:
            group_specs = [
                specifications[row["attempt_id"]]
                for row in plan["calls"]
                if row["task_id"] == task["id"] and row["condition"] == condition
            ]
            if condition == "control":
                calls = [call_one(group_specs[0], _control_messages(task))]
                proposals, selected, parse_error = _parse_control(calls[0]["completion"])
                parse_errors = [parse_error]
            else:
                calls = []
                proposals = []
                parse_errors = []
                for spec in group_specs[:-1]:
                    raw = call_one(spec, _explore_messages(task))
                    calls.append(raw)
                    proposal, parse_error = _parse_proposal(raw["completion"])
                    proposals.append(proposal)
                    parse_errors.append(parse_error)
                proposal_parent = next(
                    (
                        row["request_id"]
                        for row in reversed(calls)
                        if isinstance(row.get("request_id"), str)
                    ),
                    None,
                )
                validation = call_one(
                    group_specs[-1],
                    _validator_messages(task, proposals),
                    parent_request_id=proposal_parent,
                )
                calls.append(validation)
                selected, selection_error = _parse_selection(validation["completion"])
                parse_errors.append(selection_error)
            grade = grade_set(task, proposals, selected)
            all_returned = all(row["status"] == "returned" for row in calls)
            runtime_valid = all(row["runtime_identity_valid"] for row in calls)
            outcome = {
                "task_id": task["id"],
                "family": task["family"],
                "condition": condition,
                "attempt_ids": [row["attempt_id"] for row in calls],
                "request_ids": [row["request_id"] for row in calls],
                "calls_complete": all_returned,
                "runtime_identity_valid": runtime_valid,
                "parse_errors": parse_errors,
                "grade": grade,
                "creditable_task_success": bool(
                    all_returned
                    and runtime_valid
                    and all(error is None for error in parse_errors)
                    and grade["task_success"]
                ),
            }
            _append_jsonl(outcome_path, outcome)
            outcomes.append(outcome)
            persist("running")

    all_returned = len(raw_rows) == len(plan["calls"]) and all(
        row["status"] == "returned" for row in raw_rows
    )
    runtime_valid = all(row["runtime_identity_valid"] for row in raw_rows)
    core_identities = {
        json.dumps(
            {
                key: row["runtime_identity"].get(key)
                for key in ("model", "model_version", "backend", "host_metadata")
            },
            sort_keys=True,
        )
        for row in raw_rows
        if isinstance(row.get("runtime_identity"), dict)
    }
    runtime_valid = runtime_valid and len(core_identities) == 1
    status = (
        "incomplete_transport"
        if not all_returned
        else "invalid_runtime_drift"
        if not runtime_valid
        else "complete"
    )
    return persist(status)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir")
    parser.add_argument("--runtime-budget-s", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.plan:
            print(json.dumps(plan_dict(manifest), indent=2))
            return 0
        if not args.output_dir or args.runtime_budget_s is None:
            raise ValueError("--run requires --output-dir and --runtime-budget-s")
        result = run_experiment(
            manifest,
            output_dir=args.output_dir,
            runtime_budget_s=args.runtime_budget_s,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "complete" else 1
    except (ManifestError, ValueError, OSError) as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
