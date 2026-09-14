"""Matched role-effort arms with oracle-blind, budget-bound escalation.

Only this opt-in experiment routes effort. Production calls are unchanged.
The adaptive arm sees a public response schema and explicit uncertainty, never
the hidden expected answer. Semantic mistakes without those signals stay wrong.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator

from bench.weekly_upgrade_eval.manifest import canonical_json
from bench.weekly_upgrade_eval.runner import _runtime_provenance, validate_output_dir
from bench.weekly_upgrade_eval.structured_output import parse_strict_json_object

from .manifest import ARMS, load_manifest, plan_dict

RUN_SCHEMA = "weekly-upgrade-role-effort-run/v1"
ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = tuple(
    f"bench/weekly_upgrade_effort/{name}.py"
    for name in ("manifest", "runner", "receipt")
) + ("bench/weekly_upgrade_eval/structured_output.py",)


def write_json(path, obj):
    path.write_bytes(canonical_json(obj) + b"\n")


def append(path, obj):
    with path.open("ab") as stream:
        stream.write(canonical_json(obj) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def protocol(content, schema):
    parsed = parse_strict_json_object(content, expected_keys=schema["properties"])
    if not parsed.valid:
        return None, parsed.failure_code
    if any(Draft202012Validator(schema).iter_errors(parsed.payload)):
        return None, "value_schema"
    return parsed.payload, None


def route(role, arm, previous=None):
    """Deliberately accepts no expected answer or grading result."""
    if previous is None:
        return "xhigh" if arm == "xhigh" or (arm == "adaptive" and role == "critic") else "medium"
    if arm != "adaptive" or role == "critic" or previous["effort"] != "medium" or previous["status"] != "returned":
        return None
    if previous["protocol_failure"] or previous["needs_review"]:
        return "xhigh"
    return None


def messages(task, retry=False):
    # Explicit allowlist: expected answer and historical outputs never enter.
    prompt = task["prompt"] + "\nOutput schema: " + canonical_json(task["output_schema"]).decode()
    if retry:
        prompt += "\nThe first attempt failed its public output contract or requested review. Reassess independently and return a complete valid answer."
    return [{"role": "system", "content": "Return exactly one JSON object. No Markdown or reasoning text in the final answer. Set needs_review=true if uncertainty warrants independent checking."},
            {"role": "user", "content": prompt}]


def invoke(
    manifest,
    task,
    effort,
    seed,
    max_tokens,
    timeout_s,
    retry,
    output,
    run_id,
    parent_request_id,
):
    from agent_wrapper import worker_activity
    from agent_wrapper.wrapper import call_sync, get_run_id, set_run_id
    old_run, old_path = get_run_id(), worker_activity.DEFAULT_LOG_PATH
    set_run_id(run_id)
    worker_activity.DEFAULT_LOG_PATH = output / "worker_activity.jsonl"
    try:
        return call_sync(
            messages(task, retry),
            backend=manifest["backend"],
            model=manifest["model"],
            profile="critic_current" if effort == "xhigh" else "critic_medium",
            seed=seed,
            max_tokens=max_tokens,
            request_timeout_s=timeout_s,
            caller_tag=f"weekly_upgrade.role_effort.{task['role']}",
            parent_request_id=parent_request_id,
            log_path=str(output / "calls.jsonl"),
        )
    finally:
        set_run_id(old_run)
        worker_activity.DEFAULT_LOG_PATH = old_path


def identity_valid(record, manifest, step):
    expected = {"model": manifest["model"], "backend": manifest["backend"],
                "profile": "critic_current" if step["effort"] == "xhigh" else "critic_medium",
                "reasoning_effort": step["effort"], "temperature": 0.2, "top_p": 0.95,
                "seed": step["seed"], "max_tokens": step["max_tokens"]}
    return (
        all(record.get(key) == value for key, value in expected.items())
        and isinstance(record.get("request_id"), str)
        and bool(record["request_id"])
        and bool(record.get("model_version"))
        and isinstance(record.get("host_metadata"), dict)
        and record.get("sampling_extra") == {}
    )


def summarize(rows):
    result = {}
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        protocol_failures = {}
        transport_failures = {}
        for row in selected:
            for code in row["step_protocol_failures"]:
                protocol_failures[code] = protocol_failures.get(code, 0) + 1
            for status in row["step_transport_statuses"]:
                if status != "returned":
                    transport_failures[status] = transport_failures.get(status, 0) + 1
        result[arm] = {
            "passed": sum(row["passed"] for row in selected),
            "total": len(selected),
            "returned": sum(row["status"] == "returned" for row in selected),
            "wall_s": sum(row["duration_s"] for row in selected),
            "escalations": sum(row["escalated"] for row in selected),
            "calls": sum(row["steps"] for row in selected),
            "output_tokens": sum(row["output_tokens"] for row in selected),
            "needs_review_signals": sum(
                row["needs_review_signals"] for row in selected
            ),
            "protocol_failure_counts": dict(sorted(protocol_failures.items())),
            "transport_failure_counts": dict(sorted(transport_failures.items())),
            "by_role": {
                role: {
                    "passed": sum(
                        row["passed"] for row in selected if row["role"] == role
                    ),
                    "total": sum(row["role"] == role for row in selected),
                }
                for role in ("critic", "evidence", "execution")
            },
        }
    return {"arms": result, "verdict": "DESCRIPTIVE_PILOT_NO_PROMOTION",
            "limitations": ["Two fresh tasks per role; one seed; not a confirmation panel.",
                            "Adaptive escalation uses public protocol/uncertainty signals, not hidden correctness.",
                            "Execution fixtures measure tool selection/arguments, not full tool chains."]}


def grade_outcome(manifest, task, planned, steps, duration):
    final = steps[-1] if steps else None
    payload, failure = protocol(final["completion"], task["output_schema"]) if final and final["status"] == "returned" else (None, "transport")
    valid_runtime = bool(final and final["status"] == "returned") and all(s.get("runtime_valid", False) for s in steps)
    actual = {k: v for k, v in payload.items() if k != "needs_review"} if payload else None
    expected = dict(task["expected"])
    if actual is not None and "citations" in actual:
        actual["citations"] = sorted(actual["citations"])
        expected["citations"] = sorted(expected["citations"])
    semantic = actual is not None and actual == expected
    if not steps:
        failure = "not_run_budget"
    elif final["status"] != "returned":
        failure = f"transport_{final['status']}"
    elif not valid_runtime:
        failure = "runtime_identity"
    elif payload is not None and not semantic:
        failure = "substantive_mistake"
    return {
        **planned,
        "role": task["role"],
        "status": final["status"] if final else "not_run_budget",
        "passed": bool(semantic and valid_runtime),
        "failure_code": failure,
        "protocol_valid": payload is not None,
        "runtime_valid": valid_runtime,
        "duration_s": duration,
        "output_tokens": sum(step.get("output_tokens", 0) for step in steps),
        "escalated": len(steps) > 1,
        "steps": len(steps),
        "step_protocol_failures": [
            step["protocol_failure"]
            for step in steps
            if step.get("protocol_failure") is not None
        ],
        "step_transport_statuses": [step["status"] for step in steps],
        "needs_review_signals": sum(
            step.get("needs_review") is True for step in steps
        ),
        "request_ids": [step["request_id"] for step in steps if step.get("request_id")],
        "input_sha256": plan_dict(manifest)["input_sha256"][task["id"]],
        "grader_sha256": plan_dict(manifest)["grader_sha256"][task["id"]],
    }


def run(manifest_path, output_dir, runtime_budget_s, *, invoke_fn=invoke, clock=time.monotonic):
    if not math.isfinite(runtime_budget_s) or not 1 <= runtime_budget_s <= 1630:
        raise ValueError("invalid role-effort runtime budget")
    manifest = load_manifest(manifest_path)
    output = validate_output_dir(output_dir)
    output.mkdir(parents=True)
    (output / "manifest.snapshot.json").write_bytes(Path(manifest_path).read_bytes())
    for name in ("raw_attempts.jsonl", "outcomes.jsonl"):
        (output / name).touch()
    run_id = "role-effort-" + uuid.uuid4().hex
    stop = clock() + runtime_budget_s - 5
    rows = []
    tasks = {t["id"]: t for t in manifest["tasks"]}
    for planned in plan_dict(manifest)["order"]:
        task, arm = tasks[planned["task_id"]], planned["arm"]
        start = clock()
        deadline = min(stop, start + manifest["attempt_timeout_s"])
        steps = []
        remaining_tokens = manifest["max_tokens"]
        while clock() < deadline - 0.05 and remaining_tokens > 0:
            effort = route(task["role"], arm, steps[-1] if steps else None)
            if effort is None or len(steps) == 2:
                break
            initial_adaptive = arm == "adaptive" and task["role"] != "critic" and not steps
            timeout_s = min(deadline - clock(), manifest["attempt_timeout_s"] / 2 if initial_adaptive else manifest["attempt_timeout_s"])
            max_tokens = min(remaining_tokens, manifest["max_tokens"] // 2 if initial_adaptive else remaining_tokens)
            parent_request_id = steps[-1]["request_id"] if steps else None
            step = {
                "effort": effort,
                "seed": manifest["seed"] + len(steps),
                "max_tokens": max_tokens,
                "request_timeout_s": timeout_s,
                "retry": bool(steps),
                "parent_request_id": parent_request_id,
                "request_id": None,
                "output_tokens": 0,
                "completion": None,
                "protocol_failure": None,
                "needs_review": None,
                "runtime_valid": False,
                "runtime_identity": {},
            }
            step_start = clock()
            try:
                record = invoke_fn(
                    manifest,
                    task,
                    effort,
                    step["seed"],
                    max_tokens,
                    timeout_s,
                    bool(steps),
                    output,
                    run_id,
                    parent_request_id,
                )
                used_tokens = record["usage"]["output_tokens"]
                if (
                    isinstance(used_tokens, bool)
                    or not isinstance(used_tokens, int)
                    or not 0 <= used_tokens <= max_tokens
                ):
                    raise ValueError("wrapper output token usage exceeds call cap")
                step.update(status="returned", completion=record.get("completion"), request_id=record.get("request_id"),
                            output_tokens=used_tokens, runtime_valid=identity_valid(record, manifest, step),
                            runtime_identity=_runtime_provenance((record,)))
                payload, error = protocol(step["completion"], task["output_schema"])
                step.update(protocol_failure=error, needs_review=payload["needs_review"] if payload else None)
                remaining_tokens -= step["output_tokens"]
            except Exception as exc:  # noqa: BLE001 - transport failures are evidence
                step.update(status="timeout" if "timeout" in type(exc).__name__.lower() else "error", error=type(exc).__name__)
            step["duration_s"] = max(0, clock() - step_start)
            steps.append(step)
            if not step["runtime_valid"]:
                break
        duration = max(0, clock() - start)
        row = grade_outcome(manifest, task, planned, steps, duration)
        append(output / "raw_attempts.jsonl", {**planned, "steps": steps, "duration_s": duration})
        append(output / "outcomes.jsonl", row)
        rows.append(row)
    complete = all(r["status"] == "returned" and r["runtime_valid"] for r in rows)
    result = {"schema_version": RUN_SCHEMA, "run_id": run_id, "status": "completed" if complete else "incomplete",
              "manifest_sha256": manifest["_raw_sha256"], "configuration_sha256": manifest["_configuration_sha256"],
              "execution_source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCE_PATHS},
              "runtime_budget_s": runtime_budget_s, "declared_attempts": 18, "outcomes": rows,
              "summary": summarize(rows), "promotion_authorized": False}
    write_json(output / "run.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--runtime-budget-s", type=float, required=True)
    args = parser.parse_args()
    if os.environ.get("MOCK_LLM"):
        raise SystemExit("Live experiment requires env -u MOCK_LLM")
    result = run(args.manifest, args.output_dir, args.runtime_budget_s)
    print(json.dumps({"status": result["status"], "summary": result["summary"]}, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
