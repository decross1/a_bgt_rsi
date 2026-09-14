"""Verify the public development portfolio's artifact graph without model calls.

Generated code is never executed during receipt validation. Its recorded
observations are checked against the trusted parent's frozen behavioral oracle.
This is provenance for an isolated development run, not a hidden-set guarantee.
The committed runner and dispatcher are the authenticity boundary; hashes do
not defend against an operator rewriting the entire canonical evidence graph.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def validate_portfolio_receipt(
    plan: dict, artifact: dict, snapshot_path: Path, *, regular, json_lines,
    validate_calls, validate_activity, finite_nonnegative,
) -> bool:
    from bench.weekly_upgrade_portfolio.code_sandbox import SandboxResult
    from bench.weekly_upgrade_portfolio.graders import GradeResult, grade_task
    from bench.weekly_upgrade_portfolio.manifest import (
        load_manifest,
        plan_dict,
        sha256_json,
    )
    from bench.weekly_upgrade_portfolio.runner import (
        RUN_SCHEMA_VERSION,
        _messages,
        _runtime_identity,
        _strict_object,
        _summarize,
    )
    from orchestrator.weekly_upgrade_trial import TrialError

    def require(condition, message):
        if not condition:
            raise TrialError(f"portfolio {message}")

    manifest = load_manifest(snapshot_path)
    ordered = plan_dict(manifest)["order"]
    tasks = {row["id"]: row for row in manifest["tasks"]}
    arms = {row["id"]: row for row in manifest["arms"]}
    expected_ids = [row["attempt_id"] for row in ordered]
    require(
        manifest["_raw_sha256"] == plan["manifest_sha256"]
        and manifest["_configuration_sha256"] == plan["manifest_configuration_sha256"]
        and list(arms) == plan["arm_ids"]
        and expected_ids == plan["expected_attempt_ids"]
        and manifest["frozen_hashes"]["tasks"] == plan["expected_input_sha256"]
        and {key: sha256_json(row["grader"]) for key, row in tasks.items()}
        == plan["expected_grader_sha256"],
        "plan does not bind its exact manifest",
    )
    require(artifact.get("schema_version") == RUN_SCHEMA_VERSION, "run schema differs")
    require(set(artifact) == {
        "schema_version", "run_id", "status", "manifest_sha256", "configuration_sha256",
        "execution_source_sha256", "sandbox_runtime_expected", "sandbox_runtime_observed",
        "sandbox_runtime_valid", "sandbox_runtime_error", "runtime_budget_s",
        "grading_elapsed_s", "declared_attempts", "attempts_recorded", "outcomes",
        "summary", "promotion_authorized",
    }, "run fields differ from the closed schema")
    require(artifact.get("promotion_authorized") is False, "promotion guard is absent")
    require(
        artifact.get("manifest_sha256") == plan["manifest_sha256"]
        and artifact.get("configuration_sha256") == plan["manifest_configuration_sha256"]
        and artifact.get("runtime_budget_s") == plan["payload_budget_s"],
        "run configuration drifted",
    )
    expected_sources = {
        f"bench/weekly_upgrade_portfolio/{name}.py": plan["execution_dependencies"].get(
            f"bench/weekly_upgrade_portfolio/{name}.py"
        ) for name in ("manifest", "graders", "code_sandbox", "runner")
    }
    require(all(expected_sources.values()) and artifact.get("execution_source_sha256") == expected_sources,
            "execution source hashes differ")
    finite_nonnegative(artifact.get("grading_elapsed_s"), "portfolio grading elapsed")
    require(artifact.get("sandbox_runtime_expected") == manifest["sandbox_runtime"],
            "sandbox runtime contract differs")
    sandbox_equal = artifact.get("sandbox_runtime_observed") == manifest["sandbox_runtime"]
    require(artifact.get("sandbox_runtime_valid") is sandbox_equal,
            "sandbox runtime validity contradicts observed identity")
    require((artifact.get("sandbox_runtime_error") is None) if sandbox_equal else
            isinstance(artifact.get("sandbox_runtime_error"), str),
            "sandbox runtime error contradicts observed identity")
    raw = json_lines("raw_attempts.jsonl")
    outcomes = json_lines("outcomes.jsonl")
    require(
        artifact.get("outcomes") == outcomes
        and artifact.get("declared_attempts") == len(ordered)
        and artifact.get("attempts_recorded") == len(ordered)
        and [row.get("attempt_id") for row in raw] == expected_ids
        and [row.get("attempt_id") for row in outcomes] == expected_ids,
        "attempt coverage/order differs",
    )
    calls = json_lines("calls.jsonl", required=False)
    validate_calls(calls, run_id=artifact.get("run_id"))
    by_request = {row["request_id"]: row for row in calls}
    used = []
    identities = set()
    runtime_valid = True
    grader_valid = True
    all_returned = True

    def replay_grade(task, payload, details):
        observations = details.get("cases", []) if isinstance(details, dict) else []
        require(isinstance(observations, list), "code observations must be an array")
        position = 0

        def recorded_case(source, function_name, arguments, *, timeout_s):
            nonlocal position
            cases = task["grader"]["inputs"]["cases"]
            require(position < len(cases) and position < len(observations),
                    "code observation missing")
            case, row = cases[position], observations[position]
            position += 1
            oracle = ({"status": "exception", "exception_type": case["expected_exception"]}
                      if "expected_exception" in case
                      else {"status": "returned", "value": case["expected_return"]})
            observation = row.get("observation")
            require(isinstance(observation, dict), "code observation is not an object")
            require(
                source == payload["source"] and function_name == task["starter"]["function"]
                and arguments == case["arguments"] and timeout_s == case["timeout_s"]
                and row.get("case_id") == case["id"]
                and row.get("arguments_sha256") == sha256_json(arguments)
                and row.get("observation_sha256") == sha256_json(observation)
                and row.get("oracle_sha256") == sha256_json(oracle)
                and row.get("status") == observation.get("status"),
                "code case binding differs",
            )
            require(row.get("input_mutated") is None or type(row.get("input_mutated")) is bool,
                    "code mutation receipt invalid")
            return SandboxResult(
                observation["status"], value=observation.get("value"),
                exception_type=observation.get("exception_type"),
                input_mutated=row.get("input_mutated"), detail=observation.get("detail"),
            )

        grade = grade_task(task, payload, code_runner=recorded_case)
        require(position == len(observations), "code has unconsumed observations")
        return grade

    for index, (planned, original, outcome) in enumerate(zip(ordered, raw, outcomes, strict=True)):
        task, arm = tasks[planned["task_id"]], arms[planned["arm"]]
        for row in (original, outcome):
            require(
                all(row.get(key) == value for key, value in {
                    "attempt_id": planned["attempt_id"], "execution_index": index,
                    "task_id": task["id"], "family": task["family"],
                    "mode": task["mode"], "arm": arm["id"],
                }.items()), "attempt provenance differs",
            )
        status = original.get("status")
        require(status == outcome.get("status") and status in {
            "returned", "timeout", "error", "not_run_budget",
        }, "attempt terminal status differs")
        finite_nonnegative(outcome.get("duration_s"), "portfolio attempt duration")
        require(original.get("request_timeout_s") == outcome.get("request_timeout_s"),
                "attempt deadline differs")
        if status != "not_run_budget":
            deadline = finite_nonnegative(outcome.get("request_timeout_s"), "portfolio request deadline")
            require(0 < deadline <= task["request_timeout_s"], "request exceeded fixed cap")
        if status != "returned":
            all_returned = False
            require(outcome.get("passed") is False, "non-returned attempt claims success")
            require(outcome.get("failure_code") == ("budget" if status == "not_run_budget" else "transport"),
                    "non-returned failure classification differs")
            continue
        request_id = original.get("request_id")
        require(isinstance(request_id, str) and request_id in by_request and request_id not in used,
                "returned attempt has no unique raw call")
        require(outcome.get("request_id") == request_id, "parsed request_id differs from its raw call")
        used.append(request_id)
        call = by_request[request_id]
        require(outcome["duration_s"] + 0.001 >= call["latency_ms"] / 1000,
                "attempt duration is shorter than its durable call latency")
        require(
            call.get("prompt_messages") == _messages(task)
            and call.get("parent_request_id") is None
            and call.get("caller_tag") == f"weekly_upgrade.portfolio.{task['family']}"
            and call.get("max_tokens") == task["max_tokens"],
            "call request differs from its task",
        )
        identity, drift = _runtime_identity(call, arm, task)
        require(outcome.get("runtime_identity") == identity
                and outcome.get("runtime_identity_valid") is (drift is None),
                "runtime outcome differs from the raw call")
        runtime_valid = runtime_valid and drift is None
        identities.add(sha256_json({key: identity.get(key) for key in (
            "model", "model_version", "backend", "host_metadata",
        )}))
        completion = call.get("completion")
        require(isinstance(completion, str), "call completion is not text")
        encoded = completion.encode("utf-8")
        oversized = len(encoded) > manifest["resource_limits"]["max_raw_completion_bytes"]
        require(
            original.get("completion_sha256") == hashlib.sha256(encoded).hexdigest()
            and original.get("completion_bytes") == len(encoded)
            and original.get("completion_omitted_over_limit") is oversized
            and original.get("completion") == (None if oversized else completion)
            and original.get("usage") == call.get("usage"),
            "raw completion differs from its call",
        )
        payload, parse_error = _strict_object(None if oversized else completion)
        if oversized:
            grade = GradeResult(False, "completion exceeded the raw-output limit", failure_code="output_limit")
        elif drift:
            grade = GradeResult(False, drift, failure_code="runtime_drift")
        elif parse_error:
            grade = GradeResult(False, parse_error, failure_code="schema")
        elif outcome.get("failure_code") == "inconclusive_grader":
            # An unavailable sandbox or exhausted grading budget cannot earn
            # success or make an otherwise returned run complete.
            grader_valid = False
            require(outcome.get("passed") is False, "unavailable grader claims success")
            continue
        elif task["mode"] == "code":
            require(sandbox_equal, "code grade has no matching sandbox runtime")
            grade = replay_grade(task, payload, outcome.get("grade_details"))
        else:
            grade = grade_task(task, payload)
        require(
            outcome.get("passed") is grade.passed
            and outcome.get("failure_code") == grade.failure_code
            and outcome.get("reason") == grade.reason
            and outcome.get("grade_details") == grade.details,
            "grade cannot be reproduced from its frozen oracle",
        )
    require(used == [row["request_id"] for row in calls], "raw call log has extra/reordered requests")
    activity = json_lines("worker_activity.jsonl", required=bool(calls))
    validate_activity(activity, calls, run_id=artifact.get("run_id"))
    runtime_valid = runtime_valid and len(identities) <= 1
    expected_status = ("incomplete_transport" if not all_returned else
                       "invalid_runtime_drift" if not runtime_valid else
                       "invalid_grader" if not grader_valid else "complete")
    require(artifact.get("status") == expected_status, "aggregate terminal status differs")
    summary = artifact.get("summary")
    require(isinstance(summary, dict), "summary is not an object")
    elapsed = finite_nonnegative(summary.get("elapsed_s_including_failures"), "portfolio elapsed time")
    require(sum(row["duration_s"] for row in outcomes) <= elapsed + 0.001,
            "serial elapsed time omits attempted work")
    require(elapsed <= plan["payload_budget_s"] + 1,
            "elapsed time exceeds the independent payload supervisor")
    require(summary == _summarize(outcomes, elapsed), "summary differs from retained outcomes")
    return expected_status == "complete"
