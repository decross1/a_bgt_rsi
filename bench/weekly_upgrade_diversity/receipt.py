"""Reconstruct diversity-run evidence without model calls or LLM judging."""

from __future__ import annotations

import hashlib
from pathlib import Path


def validate_diversity_receipt(
    plan: dict,
    artifact: dict,
    snapshot_path: Path,
    *,
    regular,
    json_lines,
    validate_calls,
    validate_activity,
    finite_nonnegative,
) -> bool:
    """Verify the complete artifact graph and recompute every objective score."""
    from bench.weekly_upgrade_diversity.graders import grade_set
    from bench.weekly_upgrade_diversity.manifest import (
        load_manifest,
        plan_dict,
        sha256_json,
    )
    from bench.weekly_upgrade_diversity.runner import (
        RUN_SCHEMA_VERSION,
        _control_messages,
        _explore_messages,
        _parse_control,
        _parse_proposal,
        _parse_selection,
        _runtime_identity,
        _summary,
        _validator_messages,
    )
    from orchestrator.weekly_upgrade_trial import TrialError

    def require(condition, message):
        if not condition:
            raise TrialError(f"diversity {message}")

    manifest = load_manifest(snapshot_path)
    frozen_plan = plan_dict(manifest)
    expected_calls = frozen_plan["calls"]
    expected_ids = [row["attempt_id"] for row in expected_calls]
    tasks = {task["id"]: task for task in manifest["tasks"]}
    require(
        manifest["_raw_sha256"] == plan["manifest_sha256"]
        and manifest["_configuration_sha256"] == plan["manifest_configuration_sha256"]
        and [row["id"] for row in manifest["conditions"]] == plan["condition_ids"]
        and expected_ids == plan["expected_attempt_ids"]
        and manifest["frozen_hashes"]["tasks"] == plan["expected_input_sha256"]
        and {
            task_id: sha256_json(task["grader"])
            for task_id, task in tasks.items()
        }
        == plan["expected_grader_sha256"],
        "plan does not bind the literal manifest",
    )
    require(artifact.get("schema_version") == RUN_SCHEMA_VERSION, "run schema differs")
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
            "declared_calls",
            "calls_recorded",
            "outcomes",
            "summary",
            "promotion_authorized",
        },
        "run fields differ from the closed schema",
    )
    require(artifact.get("promotion_authorized") is False, "promotion guard differs")
    require(
        artifact.get("manifest_sha256") == plan["manifest_sha256"]
        and artifact.get("configuration_sha256")
        == plan["manifest_configuration_sha256"]
        and artifact.get("runtime_budget_s") == plan["payload_budget_s"],
        "run configuration differs",
    )
    expected_sources = {
        f"bench/weekly_upgrade_diversity/{name}.py": plan["execution_dependencies"].get(
            f"bench/weekly_upgrade_diversity/{name}.py"
        )
        for name in ("manifest", "graders", "runner")
    }
    require(
        all(expected_sources.values())
        and artifact.get("execution_source_sha256") == expected_sources,
        "execution source hashes differ",
    )

    raw = json_lines("raw_calls.jsonl")
    outcomes = json_lines("outcomes.jsonl")
    require(
        artifact.get("outcomes") == outcomes
        and artifact.get("declared_calls") == len(expected_calls)
        and artifact.get("calls_recorded") == len(expected_calls)
        and len(raw) == len(expected_calls)
        and [row.get("attempt_id") for row in raw] == expected_ids,
        "call matrix coverage or order differs",
    )
    calls = json_lines("calls.jsonl", required=False)
    validate_calls(calls, run_id=artifact.get("run_id"))
    by_request = {row["request_id"]: row for row in calls}
    require(len(by_request) == len(calls), "durable request IDs are duplicated")
    used_request_ids: list[str] = []
    runtime_valid = True
    all_returned = True
    core_identities: set[str] = set()

    returned_fields = {
        "attempt_id",
        "task_id",
        "condition",
        "role",
        "seed",
        "profile",
        "max_tokens",
        "timeout_s",
        "execution_index",
        "request_timeout_s",
        "parent_request_id",
        "status",
        "request_id",
        "completion",
        "completion_sha256",
        "completion_bytes",
        "completion_omitted_over_limit",
        "error",
        "runtime_identity",
        "runtime_identity_valid",
        "runtime_identity_error",
        "usage",
        "response_telemetry",
        "duration_s",
    }
    failed_fields = {
        "attempt_id",
        "task_id",
        "condition",
        "role",
        "seed",
        "profile",
        "max_tokens",
        "timeout_s",
        "execution_index",
        "request_timeout_s",
        "parent_request_id",
        "status",
        "request_id",
        "completion",
        "error",
        "runtime_identity",
        "runtime_identity_valid",
        "duration_s",
    }

    for index, (spec, row) in enumerate(zip(expected_calls, raw, strict=True)):
        require(
            all(row.get(key) == value for key, value in spec.items())
            and row.get("execution_index") == index,
            "call provenance differs",
        )
        status = row.get("status")
        require(status in {"returned", "timeout", "error", "not_run_budget"}, "status differs")
        require(
            set(row) == (returned_fields if status == "returned" else failed_fields),
            "raw call fields differ from the closed schema",
        )
        duration = finite_nonnegative(row.get("duration_s"), "diversity call duration")
        if status != "not_run_budget":
            request_timeout = finite_nonnegative(
                row.get("request_timeout_s"), "diversity request timeout"
            )
            require(0 < request_timeout <= spec["timeout_s"], "call deadline exceeds cap")
        if status != "returned":
            all_returned = False
            runtime_valid = False
            require(
                row.get("request_id") is None
                and row.get("completion") is None
                and row.get("runtime_identity") is None
                and row.get("runtime_identity_valid") is False
                and isinstance(row.get("error"), str),
                "failed call claims returned evidence",
            )
            continue
        request_id = row.get("request_id")
        require(
            isinstance(request_id, str)
            and request_id in by_request
            and request_id not in used_request_ids,
            "returned row has no unique durable call",
        )
        used_request_ids.append(request_id)
        call = by_request[request_id]
        require(duration + 0.001 >= call["latency_ms"] / 1000, "duration is below call latency")
        identity, drift = _runtime_identity(call, manifest, spec)
        require(
            row.get("runtime_identity") == identity
            and row.get("runtime_identity_valid") is (drift is None)
            and row.get("runtime_identity_error") == drift,
            "runtime identity cannot be reconstructed",
        )
        runtime_valid = runtime_valid and drift is None
        core_identities.add(
            sha256_json(
                {
                    key: identity.get(key)
                    for key in ("model", "model_version", "backend", "host_metadata")
                }
            )
        )
        require(
            call.get("profile") == spec["profile"]
            and call.get("seed") == spec["seed"]
            and call.get("max_tokens") == spec["max_tokens"]
            and call.get("caller_tag") == f"weekly_upgrade.diversity.{spec['role']}"
            and call.get("parent_request_id") == row.get("parent_request_id"),
            "durable call request differs",
        )
        completion = call.get("completion")
        require(isinstance(completion, str), "completion is not text")
        encoded = completion.encode("utf-8")
        oversized = len(encoded) > manifest["resource_limits"]["max_raw_completion_bytes"]
        require(
            row.get("completion_sha256") == hashlib.sha256(encoded).hexdigest()
            and row.get("completion_bytes") == len(encoded)
            and row.get("completion_omitted_over_limit") is oversized
            and row.get("completion") == (None if oversized else completion)
            and row.get("usage") == call.get("usage")
            and row.get("response_telemetry")
            == {
                "finish_reason": call.get("finish_reason"),
                "reasoning_chars": call.get("reasoning_chars"),
            },
            "raw completion or telemetry differs from durable call",
        )

    require(used_request_ids == [row["request_id"] for row in calls], "call log has extras or reordering")
    activity = json_lines("worker_activity.jsonl", required=bool(calls))
    validate_activity(activity, calls, run_id=artifact.get("run_id"))

    expected_outcomes: list[dict] = []
    raw_by_id = {row["attempt_id"]: row for row in raw}
    for task_index, task in enumerate(manifest["tasks"]):
        group_order = ["control", "diverse_select"]
        if task_index % 2:
            group_order.reverse()
        for condition in group_order:
            specs = [
                spec
                for spec in expected_calls
                if spec["task_id"] == task["id"] and spec["condition"] == condition
            ]
            rows = [raw_by_id[spec["attempt_id"]] for spec in specs]
            if condition == "control":
                require(rows[0].get("parent_request_id") is None, "control parent chain differs")
                require(
                    not rows[0].get("request_id")
                    or by_request[rows[0]["request_id"]].get("prompt_messages")
                    == _control_messages(task),
                    "control prompt differs",
                )
                proposals, selected, error = _parse_control(rows[0].get("completion"))
                parse_errors = [error]
            else:
                proposals = []
                parse_errors = []
                for row in rows[:-1]:
                    require(row.get("parent_request_id") is None, "explore parent chain differs")
                    require(
                        not row.get("request_id")
                        or by_request[row["request_id"]].get("prompt_messages")
                        == _explore_messages(task),
                        "explore prompt differs",
                    )
                    proposal, error = _parse_proposal(row.get("completion"))
                    proposals.append(proposal)
                    parse_errors.append(error)
                expected_parent = next(
                    (
                        row.get("request_id")
                        for row in reversed(rows[:-1])
                        if isinstance(row.get("request_id"), str)
                    ),
                    None,
                )
                validator = rows[-1]
                require(
                    validator.get("parent_request_id") == expected_parent,
                    "validator parent request differs",
                )
                require(
                    not validator.get("request_id")
                    or by_request[validator["request_id"]].get("prompt_messages")
                    == _validator_messages(task, proposals),
                    "validator prompt does not bind parsed proposals",
                )
                selected, error = _parse_selection(validator.get("completion"))
                parse_errors.append(error)
            grade = grade_set(task, proposals, selected)
            all_group_returned = all(row["status"] == "returned" for row in rows)
            group_runtime_valid = all(row["runtime_identity_valid"] for row in rows)
            expected_outcomes.append(
                {
                    "task_id": task["id"],
                    "family": task["family"],
                    "condition": condition,
                    "attempt_ids": [row["attempt_id"] for row in rows],
                    "request_ids": [row["request_id"] for row in rows],
                    "calls_complete": all_group_returned,
                    "runtime_identity_valid": group_runtime_valid,
                    "parse_errors": parse_errors,
                    "grade": grade,
                    "creditable_task_success": bool(
                        all_group_returned
                        and group_runtime_valid
                        and all(error is None for error in parse_errors)
                        and grade["task_success"]
                    ),
                }
            )
    require(outcomes == expected_outcomes, "parsed outcomes or objective grades differ")
    runtime_valid = runtime_valid and len(core_identities) == 1
    expected_status = (
        "incomplete_transport"
        if not all_returned
        else "invalid_runtime_drift"
        if not runtime_valid
        else "complete"
    )
    require(artifact.get("status") == expected_status, "terminal status differs")
    summary = artifact.get("summary")
    require(isinstance(summary, dict), "summary is not an object")
    elapsed = finite_nonnegative(
        summary.get("elapsed_s_including_failures"), "diversity elapsed"
    )
    require(
        sum(row["duration_s"] for row in raw) <= elapsed + 0.000001,
        "serial elapsed omits call work",
    )
    require(elapsed <= plan["payload_budget_s"] + 1, "elapsed exceeds supervisor budget")
    require(summary == _summary(outcomes, elapsed), "summary differs from objective outcomes")
    return expected_status == "complete"


__all__ = ["validate_diversity_receipt"]
