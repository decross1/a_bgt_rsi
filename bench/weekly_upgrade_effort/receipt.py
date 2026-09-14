"""Replay role-effort routing, costs, and scores from durable call evidence."""

from __future__ import annotations

from pathlib import Path

from bench.weekly_upgrade_eval.manifest import sha256_json
from bench.weekly_upgrade_eval.runner import _runtime_provenance

from .manifest import load_manifest, plan_dict
from .runner import (
    RUN_SCHEMA,
    SOURCE_PATHS,
    grade_outcome,
    identity_valid,
    messages,
    protocol,
    route,
    summarize,
)

_BASE_STEP_FIELDS = {
    "effort",
    "seed",
    "max_tokens",
    "request_timeout_s",
    "retry",
    "parent_request_id",
    "request_id",
    "output_tokens",
    "completion",
    "protocol_failure",
    "needs_review",
    "runtime_valid",
    "runtime_identity",
    "status",
    "duration_s",
}
_RETURNED_STEP_FIELDS = _BASE_STEP_FIELDS
_FAILED_STEP_FIELDS = _BASE_STEP_FIELDS | {"error"}


def validate_effort_receipt(
    plan,
    artifact,
    snapshot_path: Path,
    *,
    regular,
    json_lines,
    validate_calls,
    validate_activity,
    finite_nonnegative,
):
    """Validate a complete, oracle-blind, cumulative-budget evidence graph."""

    from orchestrator.weekly_upgrade_trial import TrialError

    def require(ok, message):
        if not ok:
            raise TrialError("role effort " + message)

    manifest = load_manifest(snapshot_path)
    frozen = plan_dict(manifest)
    expected_ids = [row["attempt_id"] for row in frozen["order"]]
    require(
        manifest["_raw_sha256"] == plan["manifest_sha256"]
        and manifest["_configuration_sha256"]
        == plan["manifest_configuration_sha256"]
        and frozen["arm_ids"] == plan["arm_ids"]
        and expected_ids == plan["expected_attempt_ids"]
        and frozen["input_sha256"] == plan["expected_input_sha256"]
        and frozen["grader_sha256"] == plan["expected_grader_sha256"],
        "manifest binding differs",
    )
    require(
        set(artifact)
        == {
            "schema_version",
            "run_id",
            "status",
            "manifest_sha256",
            "configuration_sha256",
            "execution_source_sha256",
            "runtime_budget_s",
            "declared_attempts",
            "outcomes",
            "summary",
            "promotion_authorized",
        },
        "run fields differ",
    )
    require(
        artifact["schema_version"] == RUN_SCHEMA
        and artifact["promotion_authorized"] is False
        and artifact["manifest_sha256"] == plan["manifest_sha256"]
        and artifact["configuration_sha256"]
        == plan["manifest_configuration_sha256"]
        and artifact["runtime_budget_s"] == plan["payload_budget_s"]
        and artifact["declared_attempts"] == len(expected_ids),
        "run identity differs",
    )
    expected_sources = {
        path: plan["execution_dependencies"].get(path) for path in SOURCE_PATHS
    }
    require(
        all(expected_sources.values())
        and artifact["execution_source_sha256"] == expected_sources,
        "source binding differs",
    )

    raw = json_lines("raw_attempts.jsonl")
    outcomes = json_lines("outcomes.jsonl")
    require(
        [row.get("attempt_id") for row in raw] == expected_ids
        and [row.get("attempt_id") for row in outcomes] == expected_ids
        and artifact["outcomes"] == outcomes,
        "attempt coverage differs",
    )
    calls = json_lines("calls.jsonl", required=False)
    validate_calls(calls, run_id=artifact["run_id"])
    validate_activity(
        json_lines("worker_activity.jsonl", required=False),
        calls,
        run_id=artifact["run_id"],
    )
    by_id = {call["request_id"]: call for call in calls}
    require(len(by_id) == len(calls), "durable request IDs are duplicated")
    used: list[str] = []
    identities: set[str] = set()
    tasks = {task["id"]: task for task in manifest["tasks"]}
    summed_attempt_duration = 0.0

    for planned, original, outcome in zip(frozen["order"], raw, outcomes, strict=True):
        require(
            isinstance(original, dict)
            and set(original)
            == {"attempt_id", "task_id", "arm", "steps", "duration_s"}
            and all(original[key] == value for key, value in planned.items()),
            "raw attempt differs",
        )
        task = tasks[planned["task_id"]]
        duration = finite_nonnegative(
            original["duration_s"], "role effort duration"
        )
        require(
            duration <= manifest["attempt_timeout_s"] + 0.25,
            "attempt duration exceeds its cumulative cap",
        )
        summed_attempt_duration += duration
        steps = original["steps"]
        require(
            isinstance(steps, list) and len(steps) <= 2,
            "escalation exceeds fixed maximum",
        )
        remaining_tokens = manifest["max_tokens"]
        spent = 0.0
        for index, step in enumerate(steps):
            require(isinstance(step, dict), "step is not an object")
            status = step.get("status")
            expected_fields = (
                _RETURNED_STEP_FIELDS if status == "returned" else _FAILED_STEP_FIELDS
            )
            require(set(step) == expected_fields, "step fields differ")
            if index:
                require(
                    steps[index - 1]["runtime_valid"] is True,
                    "continued after invalid runtime provenance",
                )
            wanted = route(
                task["role"], planned["arm"], steps[index - 1] if index else None
            )
            expected_parent = steps[index - 1]["request_id"] if index else None
            require(
                wanted is not None
                and step["effort"] == wanted
                and step["retry"] is bool(index)
                and step["seed"] == manifest["seed"] + index
                and step["parent_request_id"] == expected_parent,
                "routing or parent chain used an undeclared condition",
            )
            elapsed = finite_nonnegative(
                step["duration_s"], "role effort step duration"
            )
            deadline = finite_nonnegative(
                step["request_timeout_s"], "role effort deadline"
            )
            initial = (
                planned["arm"] == "adaptive"
                and task["role"] != "critic"
                and index == 0
            )
            require(
                0
                < deadline
                <= min(
                    manifest["attempt_timeout_s"] - spent + 0.02,
                    manifest["attempt_timeout_s"] / 2
                    if initial
                    else manifest["attempt_timeout_s"],
                ),
                "step deadline exceeds attempt budget",
            )
            require(
                elapsed <= deadline + 0.25,
                "step duration exceeds its request deadline",
            )
            expected_max_tokens = min(
                remaining_tokens,
                manifest["max_tokens"] // 2 if initial else remaining_tokens,
            )
            require(
                step["max_tokens"] == expected_max_tokens,
                "step output budget differs",
            )
            require(
                status in {"returned", "timeout", "error"},
                "invalid transport status",
            )
            if status == "returned":
                request_id = step["request_id"]
                require(
                    isinstance(request_id, str)
                    and request_id in by_id
                    and request_id not in used,
                    "no unique durable call",
                )
                used.append(request_id)
                call = by_id[request_id]
                output_tokens = call["usage"]["output_tokens"]
                require(
                    isinstance(output_tokens, int)
                    and not isinstance(output_tokens, bool)
                    and 0 <= output_tokens <= step["max_tokens"]
                    and output_tokens <= remaining_tokens
                    and step["output_tokens"] == output_tokens,
                    "call exceeds its cumulative output-token budget",
                )
                require(
                    call["completion"] == step["completion"]
                    and call.get("prompt_messages") == messages(task, bool(index))
                    and call.get("caller_tag")
                    == f"weekly_upgrade.role_effort.{task['role']}"
                    and call.get("parent_request_id") == expected_parent
                    and elapsed + 0.01 >= call["latency_ms"] / 1000,
                    "call request, parent, or cost differs",
                )
                require(
                    step["runtime_valid"] is identity_valid(call, manifest, step)
                    and step["runtime_identity"] == _runtime_provenance((call,)),
                    "runtime identity differs",
                )
                identities.add(
                    sha256_json(
                        {
                            "model_version": call.get("model_version"),
                            "host_metadata": call.get("host_metadata"),
                        }
                    )
                )
                payload, error = protocol(
                    step["completion"], task["output_schema"]
                )
                require(
                    step["protocol_failure"] == error
                    and step["needs_review"]
                    == (payload["needs_review"] if payload else None),
                    "protocol diagnostics differ",
                )
                remaining_tokens -= output_tokens
            else:
                require(
                    step["request_id"] is None
                    and step["completion"] is None
                    and step["runtime_valid"] is False
                    and step["runtime_identity"] == {}
                    and step["output_tokens"] == 0
                    and step["protocol_failure"] is None
                    and step["needs_review"] is None
                    and isinstance(step["error"], str)
                    and bool(step["error"]),
                    "failed transport claims a response",
                )
            spent += elapsed
        require(
            spent <= manifest["attempt_timeout_s"] + 0.25,
            "step costs exceed the cumulative attempt cap",
        )
        require(
            duration + 0.01 >= spent,
            "attempt duration excludes call costs",
        )
        require(
            outcome == grade_outcome(manifest, task, planned, steps, duration),
            "objective result differs",
        )

    require(
        summed_attempt_duration <= plan["payload_budget_s"] + 0.5,
        "summed attempt costs exceed the trial payload budget",
    )
    require(
        used == [call["request_id"] for call in calls],
        "unconsumed or reordered call evidence",
    )
    require(len(identities) <= 1, "runtime changed within trial")
    require(artifact["summary"] == summarize(outcomes), "summary differs")
    complete = all(
        row["status"] == "returned" and row["runtime_valid"]
        for row in outcomes
    )
    require(
        artifact["status"] == ("completed" if complete else "incomplete"),
        "completion differs",
    )
    return complete
