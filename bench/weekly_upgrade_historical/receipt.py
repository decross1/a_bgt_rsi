"""Validate the historical-repair evidence graph without executing model code."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path


def validate_historical_receipt(
    plan: dict, artifact: dict, snapshot_path: Path, *, regular, json_lines,
    validate_calls, validate_activity, finite_nonnegative,
) -> bool:
    """Reconstruct prompts, patch scope, identities, counts, hashes, and summary.

    The grader subprocess is not replayed because receipt validation runs inside
    the controller's 30-second supervision margin. The committed runner and
    content-addressed sandbox are the trust boundary for its bounded pytest
    observation, as they are for other locally executed benchmark code. The
    grader receipt hash is a consistency checksum, not an authentication tag.
    """
    from bench.weekly_upgrade_historical.manifest import (
        git_blob,
        load_manifest,
        messages_for,
        plan_dict,
        sha256_json,
    )
    from bench.weekly_upgrade_historical.runner import (
        RUN_SCHEMA_VERSION,
        _runtime_identity,
        _strict_patch_object,
        _summary,
    )
    from bench.weekly_upgrade_historical.sandbox import (
        GraderResult,
        apply_candidate_patch,
        grader_receipt_sha256,
        materialize_workspace,
    )
    from orchestrator.weekly_upgrade_trial import TrialError

    def require(condition, message):
        if not condition:
            raise TrialError(f"historical repair {message}")

    def require_no_grade(
        outcome: dict,
        *,
        patch_status: str,
        patch_error: str | None,
        patch_sha256: str | None = None,
        patch_bytes: int = 0,
        repaired_file_sha256: str | None = None,
    ) -> None:
        """Bind every downstream field when a branch cannot produce a grade."""
        require(
            outcome.get("patch_status") == patch_status
            and outcome.get("patch_error") == patch_error
            and outcome.get("patch_sha256") == patch_sha256
            and outcome.get("patch_bytes") == patch_bytes
            and outcome.get("repaired_file_sha256") == repaired_file_sha256
            and outcome.get("grader") is None
            and outcome.get("grader_receipt_sha256") is None
            and outcome.get("creditable_success") is False,
            "non-graded attempt claims downstream evidence",
        )

    manifest = load_manifest(snapshot_path)
    frozen = plan_dict(manifest)
    ordered = frozen["order"]
    expected_ids = frozen["expected_attempt_ids"]
    tasks = {task["id"]: task for task in manifest["tasks"]}
    arm = manifest["arm"]
    require(
        manifest["_raw_sha256"] == plan.get("manifest_sha256")
        and manifest["_configuration_sha256"] == plan.get("manifest_configuration_sha256")
        and frozen["fixture_ids"] == plan.get("fixture_ids")
        and frozen["arm_ids"] == plan.get("arm_ids")
        and frozen["seeds"] == plan.get("seeds")
        and expected_ids == plan.get("expected_attempt_ids")
        and frozen["expected_input_sha256"] == plan.get("expected_input_sha256")
        and frozen["expected_grader_sha256"] == plan.get("expected_grader_sha256"),
        "plan does not bind the exact manifest",
    )
    require(artifact.get("schema_version") == RUN_SCHEMA_VERSION, "run schema differs")
    require(set(artifact) == {
        "schema_version", "run_id", "status", "manifest_sha256", "configuration_sha256",
        "execution_source_sha256", "sandbox_runtime_expected", "sandbox_runtime_observed",
        "sandbox_runtime_valid", "sandbox_runtime_error", "runtime_budget_s",
        "grading_elapsed_s", "declared_attempts", "attempts_recorded", "outcomes",
        "summary", "provenance", "promotion_authorized",
    }, "run fields differ from the closed schema")
    require(artifact.get("promotion_authorized") is False, "promotion guard is absent")
    require(
        artifact.get("manifest_sha256") == plan.get("manifest_sha256")
        and artifact.get("configuration_sha256") == plan.get("manifest_configuration_sha256")
        and artifact.get("runtime_budget_s") == plan.get("payload_budget_s"),
        "run configuration differs from the controller reservation",
    )
    expected_sources = {
        f"bench/weekly_upgrade_historical/{name}.py": plan.get("execution_dependencies", {}).get(
            f"bench/weekly_upgrade_historical/{name}.py"
        )
        for name in ("manifest", "grader_assets", "sandbox", "runner", "receipt")
    }
    require(
        all(expected_sources.values()) and artifact.get("execution_source_sha256") == expected_sources,
        "execution source hashes differ",
    )
    provenance = artifact.get("provenance")
    require(provenance == {
        "class": "public_historical", "contamination_resistant": False,
        "source_proof_sha256": manifest["source_proof"]["sha256"], "single_arm": True,
    }, "public-history provenance differs")
    sandbox_equal = artifact.get("sandbox_runtime_observed") == manifest["sandbox_runtime"]
    require(
        artifact.get("sandbox_runtime_expected") == manifest["sandbox_runtime"]
        and artifact.get("sandbox_runtime_valid") is sandbox_equal
        and ((artifact.get("sandbox_runtime_error") is None) if sandbox_equal else isinstance(artifact.get("sandbox_runtime_error"), str)),
        "sandbox identity receipt is inconsistent",
    )

    raw = json_lines("raw_attempts.jsonl")
    outcomes = json_lines("outcomes.jsonl")
    require(
        artifact.get("outcomes") == outcomes
        and artifact.get("declared_attempts") == len(ordered)
        and artifact.get("attempts_recorded") == len(ordered)
        and [row.get("attempt_id") for row in raw] == expected_ids
        and [row.get("attempt_id") for row in outcomes] == expected_ids,
        "attempt coverage or order differs",
    )
    calls = json_lines("calls.jsonl", required=False)
    validate_calls(calls, run_id=artifact.get("run_id"))
    calls_by_request = {row["request_id"]: row for row in calls}
    require(len(calls_by_request) == len(calls), "durable request IDs are duplicated")
    used_request_ids: list[str] = []
    all_returned = True
    runtime_valid = True
    grader_valid = sandbox_equal
    core_identities: set[str] = set()
    grader_duration_sum = 0.0

    raw_fields = {
        "attempt_id", "execution_index", "task_id", "arm_id", "input_sha256",
        "grader_sha256", "request_timeout_s", "status", "request_id", "completion",
        "completion_sha256", "completion_bytes", "completion_omitted_over_limit",
        "usage", "response_telemetry", "error", "duration_s",
    }
    outcome_fields = {
        "attempt_id", "execution_index", "task_id", "arm_id", "input_sha256",
        "grader_sha256", "request_timeout_s", "status", "request_id",
        "runtime_identity", "runtime_identity_valid", "runtime_identity_error",
        "patch_status", "patch_error", "patch_sha256", "patch_bytes",
        "repaired_file_sha256", "grader", "grader_receipt_sha256",
        "creditable_success", "duration_s",
    }
    allowed_patch_errors = {
        None, "completion_output_limit", "completion_not_text",
        "completion_not_strict_json", "completion_schema", "completion_path",
        "completion_patch_not_text", "patch_missing", "patch_too_large",
        "patch_binary_or_nul", "patch_operation_forbidden", "patch_path_or_header",
        "patch_does_not_apply", "patch_apply_error", "patch_scope_violation",
        "workspace_unavailable", "grader_unavailable", "sandbox_runtime_unavailable",
        "sandbox_runtime_drift",
    }

    for index, (planned, original, outcome) in enumerate(zip(ordered, raw, outcomes, strict=True)):
        task = tasks[planned["task_id"]]
        expected_common = {
            "attempt_id": planned["attempt_id"], "execution_index": index,
            "task_id": task["id"], "arm_id": arm["id"],
            "input_sha256": planned["input_sha256"],
            "grader_sha256": planned["grader_sha256"],
        }
        require(set(original) == raw_fields and set(outcome) == outcome_fields, "attempt fields differ")
        require(
            all(original.get(key) == value and outcome.get(key) == value for key, value in expected_common.items()),
            "attempt provenance differs",
        )
        status = original.get("status")
        require(status == outcome.get("status") and status in {"returned", "timeout", "error", "not_run_budget"}, "attempt status differs")
        raw_duration = finite_nonnegative(original.get("duration_s"), "historical raw duration")
        outcome_duration = finite_nonnegative(outcome.get("duration_s"), "historical outcome duration")
        require(outcome_duration + 0.001 >= raw_duration, "outcome duration omits transport")
        require(original.get("request_timeout_s") == outcome.get("request_timeout_s"), "request timeout differs")
        if status == "not_run_budget":
            require(original.get("request_timeout_s") is None, "unrun attempt claims a timeout allowance")
            require(outcome_duration <= 5.0, "unrun attempt claims an excessive duration")
        else:
            timeout = finite_nonnegative(original.get("request_timeout_s"), "historical request timeout")
            require(0 < timeout <= task["request_timeout_s"], "request timeout exceeds its cap")
            require(raw_duration <= timeout + 2.0, "transport duration exceeds its request allowance")
            require(
                outcome_duration <= timeout + task["grader_timeout_s"] + 5.0,
                "attempt duration exceeds its transport and grading allowance",
            )
        if status != "returned":
            all_returned = False
            runtime_valid = False
            error = original.get("error")
            require(
                original.get("request_id") is None
                and original.get("completion") is None
                and original.get("completion_sha256") is None and original.get("completion_bytes") is None
                and original.get("completion_omitted_over_limit") is False
                and original.get("usage") is None
                and original.get("response_telemetry") is None
                and isinstance(error, str) and 0 < len(error) <= 128
                and (status != "not_run_budget" or error == "runtime_budget_exhausted")
                and outcome.get("request_id") is None
                and outcome.get("runtime_identity") is None
                and outcome.get("runtime_identity_valid") is False
                and outcome.get("runtime_identity_error") is None,
                "non-returned attempt claims repair evidence",
            )
            require_no_grade(outcome, patch_status="not_attempted", patch_error=None)
            continue

        request_id = original.get("request_id")
        require(
            isinstance(request_id, str) and request_id in calls_by_request
            and request_id not in used_request_ids and outcome.get("request_id") == request_id,
            "returned attempt has no unique durable call",
        )
        used_request_ids.append(request_id)
        call = calls_by_request[request_id]
        require(
            raw_duration + 0.001 >= call["latency_ms"] / 1000,
            "raw duration is below the durable call latency",
        )
        base_source = git_blob(task["base"]["commit"], task["base"]["repair_path"]).decode("utf-8")
        require(
            call.get("prompt_messages") == messages_for(task, base_source)
            and call.get("caller_tag") == "weekly_upgrade.historical_repair"
            and call.get("parent_request_id") is None
            and call.get("max_tokens") == task["max_tokens"],
            "durable call differs from its scrubbed task packet",
        )
        require(
            type(call["usage"]["output_tokens"]) is int
            and call["usage"]["output_tokens"] <= task["max_tokens"],
            "durable call exceeds its output-token cap",
        )
        identity, drift = _runtime_identity(call, arm, task)
        require(
            outcome.get("runtime_identity") == identity
            and outcome.get("runtime_identity_valid") is (drift is None)
            and outcome.get("runtime_identity_error") == drift,
            "runtime identity cannot be reconstructed",
        )
        runtime_valid = runtime_valid and drift is None
        core_identities.add(sha256_json({
            key: identity.get(key) for key in ("model", "model_version", "backend", "host_metadata")
        }))
        completion = call.get("completion")
        require(isinstance(completion, str), "durable completion is not text")
        encoded = completion.encode("utf-8")
        oversized = len(encoded) > manifest["resource_limits"]["max_raw_completion_bytes"]
        require(
            original.get("completion_sha256") == hashlib.sha256(encoded).hexdigest()
            and original.get("completion_bytes") == len(encoded)
            and original.get("completion_omitted_over_limit") is oversized
            and original.get("completion") == (None if oversized else completion)
            and original.get("usage") == call.get("usage")
            and original.get("response_telemetry") == {
                "finish_reason": call.get("finish_reason"),
                "reasoning_chars": call.get("reasoning_chars"),
            },
            "raw completion differs from its durable call",
        )
        require(
            original.get("error") == ("completion_output_limit" if oversized else None),
            "raw completion error differs",
        )

        payload, parse_error = _strict_patch_object(None if oversized else completion, task["base"]["repair_path"])
        if oversized:
            parse_error = "completion_output_limit"
        if drift is not None:
            require_no_grade(outcome, patch_status="not_attempted", patch_error=drift)
            continue
        if parse_error is not None:
            require_no_grade(outcome, patch_status="invalid", patch_error=parse_error)
            continue
        if not sandbox_equal:
            require_no_grade(
                outcome,
                patch_status="not_attempted",
                patch_error=artifact.get("sandbox_runtime_error"),
            )
            continue

        with tempfile.TemporaryDirectory(prefix="historical-receipt-") as raw_workspace:
            workspace = Path(raw_workspace) / "workspace"
            materialize_workspace(
                task, workspace,
                max_archive_bytes=manifest["resource_limits"]["max_workspace_archive_bytes"],
                max_files=manifest["resource_limits"]["max_workspace_files"],
            )
            replay = apply_candidate_patch(
                workspace, allowed_path=task["base"]["repair_path"], patch=payload["patch"],
                max_patch_bytes=manifest["resource_limits"]["max_patch_bytes"],
            )
        require(
            outcome.get("patch_status") == ("valid" if replay.valid else "invalid")
            and outcome.get("patch_error") == replay.code
            and outcome.get("patch_sha256") == replay.patch_sha256
            and outcome.get("patch_bytes") == replay.patch_bytes
            and outcome.get("repaired_file_sha256") == replay.repaired_file_sha256,
            "patch receipt cannot be reconstructed",
        )
        require(outcome.get("patch_error") in allowed_patch_errors, "patch error code is unsupported")
        if not replay.valid:
            require_no_grade(
                outcome,
                patch_status="invalid",
                patch_error=replay.code,
                patch_sha256=replay.patch_sha256,
                patch_bytes=replay.patch_bytes,
                repaired_file_sha256=replay.repaired_file_sha256,
            )
            continue

        grade = outcome.get("grader")
        if not isinstance(grade, dict):
            grader_valid = False
            require_no_grade(
                outcome,
                patch_status="valid",
                patch_error="grader_unavailable",
                patch_sha256=replay.patch_sha256,
                patch_bytes=replay.patch_bytes,
                repaired_file_sha256=replay.repaired_file_sha256,
            )
            continue
        require(outcome.get("patch_error") is None, "graded patch retains an error")
        require(set(grade) == {
            "status", "passed", "returncode", "timed_out", "counts", "duration_s",
            "output_sha256", "output_bytes", "output_truncated", "guard_event_count",
        }, "grader fields differ")
        require(grade.get("status") in {"passed", "failed", "timeout", "output_limit", "guard_denial", "error"}, "grader status differs")
        require(type(grade.get("passed")) is bool and grade["passed"] is (grade["status"] == "passed"), "grader success contradicts status")
        require(type(grade.get("timed_out")) is bool, "grader timeout flag is absent")
        require(type(grade.get("returncode")) is int, "grader returncode is absent")
        duration = finite_nonnegative(grade.get("duration_s"), "historical grader duration")
        require(duration <= task["grader_timeout_s"] + 1.0, "grader duration exceeds its task cap")
        grader_duration_sum += duration
        counts = grade.get("counts")
        require(isinstance(counts, dict) and set(counts) == {"passed", "failed", "errors", "skipped"}, "grader counts differ")
        require(all(type(value) is int and value >= 0 for value in counts.values()), "grader count is invalid")
        expected_cases = task["grader"]["expected_cases"]
        require(sum(counts.values()) <= expected_cases, "grader counts exceed the fixed cases")
        require(
            isinstance(grade.get("output_sha256"), str)
            and len(grade["output_sha256"]) == 64
            and all(char in "0123456789abcdef" for char in grade["output_sha256"])
            and type(grade.get("output_bytes")) is int
            and 0 <= grade["output_bytes"] <= manifest["resource_limits"]["max_grader_output_bytes"] + 1
            and type(grade.get("output_truncated")) is bool
            and type(grade.get("guard_event_count")) is int and grade["guard_event_count"] >= 0,
            "grader bounded-output receipt differs",
        )
        max_output = manifest["resource_limits"]["max_grader_output_bytes"]
        require(
            grade["output_truncated"] is (grade["output_bytes"] > max_output),
            "grader truncation flag contradicts its bounded output",
        )
        complete_pass = (
            grade["returncode"] == 0
            and counts == {"passed": expected_cases, "failed": 0, "errors": 0, "skipped": 0}
        )
        expected_grade_status = (
            "timeout" if grade["timed_out"] else
            "output_limit" if grade["output_truncated"] else
            "guard_denial" if grade["guard_event_count"] > 0 else
            "passed" if complete_pass else
            "failed" if grade["returncode"] in {0, 1, 2, 3, 4, 5} else
            "error"
        )
        require(grade["status"] == expected_grade_status, "grader status contradicts its receipt")
        grade_result = GraderResult(**grade)
        require(
            outcome.get("grader_receipt_sha256") == grader_receipt_sha256(
                attempt_id=planned["attempt_id"], input_sha256=planned["input_sha256"],
                patch_sha256=replay.patch_sha256, grader_sha256=planned["grader_sha256"],
                sandbox_identity=manifest["sandbox_runtime"], result=grade_result,
            )
            and outcome.get("creditable_success") is grade_result.passed,
            "grader receipt or task credit differs",
        )
        require(outcome_duration + 0.01 >= raw_duration + duration, "attempt duration omits grading")

    require(used_request_ids == [row["request_id"] for row in calls], "call log has extras or reordered requests")
    activity = json_lines("worker_activity.jsonl", required=bool(calls))
    validate_activity(activity, calls, run_id=artifact.get("run_id"))
    runtime_valid = runtime_valid and len(core_identities) == 1
    expected_status = (
        "incomplete_transport" if not all_returned else
        "invalid_runtime_drift" if not runtime_valid else
        "invalid_grader" if not grader_valid else "complete"
    )
    require(artifact.get("status") == expected_status, "terminal status differs")
    grading_elapsed = finite_nonnegative(artifact.get("grading_elapsed_s"), "historical grading elapsed")
    require(grader_duration_sum <= grading_elapsed + 0.01, "grading elapsed omits grader work")
    require(
        grading_elapsed <= manifest["resource_limits"]["max_grading_runtime_s"] + 2.0,
        "grading elapsed exceeds its run cap",
    )
    summary = artifact.get("summary")
    require(isinstance(summary, dict), "summary is not an object")
    elapsed = finite_nonnegative(summary.get("elapsed_s_including_failures"), "historical elapsed")
    require(grading_elapsed <= elapsed + 0.01, "grading elapsed exceeds total elapsed")
    require(sum(row["duration_s"] for row in outcomes) <= elapsed + 0.01, "serial elapsed omits attempts")
    require(elapsed <= plan.get("payload_budget_s") + 1, "elapsed exceeds the independent supervisor")
    require(summary == _summary(outcomes, elapsed), "summary differs from retained outcomes")
    return expected_status == "complete"


__all__ = ["validate_historical_receipt"]
