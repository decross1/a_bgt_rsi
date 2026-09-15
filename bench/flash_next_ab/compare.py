"""Strict paired summaries for the public Flash-Next development panel.

Receipts must independently prove one canonical plan. Comparisons are
descriptive and never authorize a production promotion.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from .manifest import PlanError
from .manifest import validate_plan as validate_manifest_plan

RUN_SCHEMA = "flash-next-ab-run/v1"
PLAN_SCHEMA = "flash-next-ab-plan/v1"
COMPARISON_SCHEMA = "flash-next-ab-comparison/v1"
COHORTS = ("resident", "flash")
RUN_STATUSES = frozenset({"complete", "aborted"})
OUTCOME_STATUSES = frozenset({"returned", "timeout", "cancelled", "error", "not_run"})
CALL_STATUSES = frozenset({"returned", "timeout", "cancelled", "error"})
HEX = frozenset("0123456789abcdef")
TOLERANCE = 1e-9

RUN_KEYS = frozenset({
    "schema_version", "run_id", "cohort", "status", "manifest_sha256",
    "plan", "plan_fingerprints", "arms", "declared_cells", "elapsed_s",
    "outcomes", "promotion_authorized",
})
PLAN_KEYS = frozenset({
    "schema_version", "suite_id", "cohorts", "arms", "sources",
    "adapter_bundle", "declared_cells", "cell_receipts",
    "promotion_authorized", "limitations",
})
FINGERPRINT_KEYS = frozenset({
    "declared_cells_sha256", "sources_sha256", "arms_sha256",
    "adapter_bundle_sha256",
})
ARM_KEYS = frozenset({"cohort", "qualification_receipt_sha256", "routes"})
ROUTE_KEYS = frozenset({
    "role", "endpoint_name", "served_model", "artifact_sha256",
    "runtime_sha256", "policies", "policy_set_sha256",
})
SOURCE_KEYS = frozenset({"family", "suite_id", "manifest_path", "manifest_sha256"})
CELL_SOURCE_KEYS = SOURCE_KEYS | {"task_sha256"}
ADAPTER_KEYS = frozenset({"id", "source_path", "source_sha256"})
GRADER_KEYS = frozenset({"id", "contract_sha256", "source_files"})
GRADER_FILE_KEYS = frozenset({"path", "sha256"})
CELL_KEYS = frozenset({
    "task_id", "family", "condition", "seed", "source", "adapter",
    "grader", "call_plan", "call_plan_sha256",
})
CALL_PLAN_KEYS = frozenset({"mode", "steps"})
STEP_KEYS = frozenset({
    "call_index", "call_id", "role", "policy_id", "seed", "max_tokens",
    "timeout_s", "required", "messages_sha256", "messages_builder_sha256",
    "tools_sha256",
})
OUTCOME_KEYS = frozenset({
    "cell_id", "cohort", "task_id", "family", "condition", "seed",
    "status", "passed", "wall_s", "source", "adapter", "grader", "calls",
    "grade", "failure_code", "error",
})
CALL_KEYS = frozenset({
    "call_index", "call_id", "role", "status", "wall_s", "endpoint_name",
    "served_model", "artifact_sha256", "policy_id",
    "resolved_policy_sha256", "seed", "max_tokens", "timeout_s",
    "messages_sha256", "tools_sha256", "request_sha256",
    "response_stream_sha256", "response_id", "response_model",
    "finish_reason", "usage", "failure_code", "error",
})
GRADE_KEYS = frozenset({"grader_id", "passed", "failure_code", "details"})


class ComparisonError(ValueError):
    """The supplied receipts cannot support a paired comparison."""


def _exact(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        actual = set(value) if isinstance(value, dict) else set()
        raise ComparisonError(
            f"{name} has an unexpected shape "
            f"(missing={sorted(set(keys) - actual)}, extra={sorted(actual - set(keys))})"
        )
    return value


def _text(value, name):
    if not isinstance(value, str) or not value:
        raise ComparisonError(f"{name} must be a nonempty string")
    return value


def _nullable_text(value, name):
    if value is not None:
        _text(value, name)
    return value


def _hash(value, name, *, nullable=False):
    if value is None and nullable:
        return value
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX for char in value):
        raise ComparisonError(f"{name} must be a lowercase SHA-256")
    return value


def _finite(value, name, *, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 or (positive and value <= 0)):
        qualifier = "positive" if positive else "nonnegative"
        raise ComparisonError(f"{name} must be finite and {qualifier}")
    return value


def _integer(value, name, *, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ComparisonError(f"{name} must be an integer >= {minimum}")
    return value


def _path(value, name):
    _text(value, name)
    path = PurePosixPath(value)
    if (path.is_absolute() or "\\" in value or value != path.as_posix()
            or any(part == ".." for part in path.parts)):
        raise ComparisonError(f"{name} must be a normalized relative POSIX path")
    return value


def _canonical(value):
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ComparisonError("receipt is not canonical-JSON serializable") from exc


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_source(source, name, *, cell=False):
    _exact(source, CELL_SOURCE_KEYS if cell else SOURCE_KEYS, name)
    _text(source["family"], f"{name}.family")
    _text(source["suite_id"], f"{name}.suite_id")
    _path(source["manifest_path"], f"{name}.manifest_path")
    _hash(source["manifest_sha256"], f"{name}.manifest_sha256")
    if cell:
        _hash(source["task_sha256"], f"{name}.task_sha256")


def _validate_adapter(adapter, name):
    _exact(adapter, ADAPTER_KEYS, name)
    _text(adapter["id"], f"{name}.id")
    _path(adapter["source_path"], f"{name}.source_path")
    _hash(adapter["source_sha256"], f"{name}.source_sha256")


def _validate_grader(grader, name):
    _exact(grader, GRADER_KEYS, name)
    _text(grader["id"], f"{name}.id")
    _hash(grader["contract_sha256"], f"{name}.contract_sha256")
    files = grader["source_files"]
    if not isinstance(files, list) or not files:
        raise ComparisonError(f"{name}.source_files must be a nonempty list")
    paths = []
    for index, item in enumerate(files):
        item_name = f"{name}.source_files[{index}]"
        _exact(item, GRADER_FILE_KEYS, item_name)
        paths.append(_path(item["path"], f"{item_name}.path"))
        _hash(item["sha256"], f"{item_name}.sha256")
    if len(paths) != len(set(paths)):
        raise ComparisonError(f"{name}.source_files contains duplicate paths")


def _validate_route(route, name):
    _exact(route, ROUTE_KEYS, name)
    for key in ("role", "endpoint_name", "served_model"):
        _text(route[key], f"{name}.{key}")
    for key in ("artifact_sha256", "runtime_sha256", "policy_set_sha256"):
        _hash(route[key], f"{name}.{key}")
    policies = route["policies"]
    if not isinstance(policies, dict) or not policies:
        raise ComparisonError(f"{name}.policies must be a nonempty object")
    for policy_id, policy in policies.items():
        _text(policy_id, f"{name}.policy_id")
        if not isinstance(policy, dict) or not policy:
            raise ComparisonError(f"{name}.policies[{policy_id!r}] must be a nonempty object")
        _canonical(policy)
    if route["policy_set_sha256"] != _sha(policies):
        raise ComparisonError(f"{name}.policy_set_sha256 does not bind policies")


def _validate_arm(arm, name):
    _exact(arm, ARM_KEYS, name)
    if arm["cohort"] not in COHORTS:
        raise ComparisonError(f"{name}.cohort is unknown")
    _hash(arm["qualification_receipt_sha256"], f"{name}.qualification_receipt_sha256")
    routes = arm["routes"]
    if not isinstance(routes, list) or not routes:
        raise ComparisonError(f"{name}.routes must be a nonempty list")
    roles = []
    for index, route in enumerate(routes):
        _validate_route(route, f"{name}.routes[{index}]")
        roles.append(route["role"])
    if len(roles) != len(set(roles)):
        raise ComparisonError(f"{name}.routes contains duplicate roles")


def _validate_call_plan(call_plan, name, global_call_ids):
    _exact(call_plan, CALL_PLAN_KEYS, name)
    if call_plan["mode"] not in {"fixed", "conditional"}:
        raise ComparisonError(f"{name}.mode is unknown")
    steps = call_plan["steps"]
    if not isinstance(steps, list) or not steps:
        raise ComparisonError(f"{name}.steps must be a nonempty list")
    optional_seen = False
    for index, step in enumerate(steps):
        step_name = f"{name}.steps[{index}]"
        _exact(step, STEP_KEYS, step_name)
        if _integer(step["call_index"], f"{step_name}.call_index") != index:
            raise ComparisonError(f"{name}.steps indices must be contiguous from zero")
        call_id = _text(step["call_id"], f"{step_name}.call_id")
        if call_id in global_call_ids:
            raise ComparisonError("plan call IDs must be globally unique")
        global_call_ids.add(call_id)
        for key in ("role", "policy_id"):
            _text(step[key], f"{step_name}.{key}")
        _integer(step["seed"], f"{step_name}.seed")
        _integer(step["max_tokens"], f"{step_name}.max_tokens", minimum=1)
        _finite(step["timeout_s"], f"{step_name}.timeout_s", positive=True)
        if not isinstance(step["required"], bool):
            raise ComparisonError(f"{step_name}.required must be boolean")
        optional_seen = optional_seen or not step["required"]
        if optional_seen and step["required"]:
            raise ComparisonError(f"{name}.steps cannot require a step after an optional step")
        static_hash = _hash(step["messages_sha256"], f"{step_name}.messages_sha256", nullable=True)
        builder_hash = _hash(step["messages_builder_sha256"], f"{step_name}.messages_builder_sha256", nullable=True)
        if (static_hash is None) == (builder_hash is None):
            raise ComparisonError(f"{step_name} must bind exactly one static message or message builder")
        _hash(step["tools_sha256"], f"{step_name}.tools_sha256")
    if call_plan["mode"] == "fixed" and any(not step["required"] for step in steps):
        raise ComparisonError(f"{name}.fixed steps must all be required")


def _validate_plan(plan):
    _exact(plan, PLAN_KEYS, "plan")
    try:
        validate_manifest_plan(plan)
    except PlanError as exc:
        raise ComparisonError(f"plan fails the frozen harness contract: {exc}") from exc
    if plan["schema_version"] != PLAN_SCHEMA:
        raise ComparisonError("unexpected plan schema")
    _text(plan["suite_id"], "plan.suite_id")
    if plan["cohorts"] != list(COHORTS):
        raise ComparisonError("plan.cohorts must be exactly resident then flash")
    if plan["promotion_authorized"] is not False:
        raise ComparisonError("comparison plan cannot authorize promotion")
    if (not isinstance(plan["limitations"], list) or not plan["limitations"]
            or any(not isinstance(item, str) or not item for item in plan["limitations"])):
        raise ComparisonError("plan.limitations must be nonempty strings")

    arms = plan["arms"]
    if not isinstance(arms, list) or len(arms) != len(COHORTS):
        raise ComparisonError("plan must contain exactly two arms")
    for index, arm in enumerate(arms):
        _validate_arm(arm, f"plan.arms[{index}]")
    if [arm["cohort"] for arm in arms] != list(COHORTS):
        raise ComparisonError("plan arms must be ordered resident then flash")

    sources = plan["sources"]
    if not isinstance(sources, list) or not sources:
        raise ComparisonError("plan.sources must be a nonempty list")
    source_identities = set()
    for index, source in enumerate(sources):
        _validate_source(source, f"plan.sources[{index}]")
        source_identities.add(_canonical(source))
    if len(source_identities) != len(sources):
        raise ComparisonError("plan.sources contains a duplicate identity")

    adapters = plan["adapter_bundle"]
    if not isinstance(adapters, list) or not adapters:
        raise ComparisonError("plan.adapter_bundle must be a nonempty list")
    adapter_identities = set()
    for index, adapter in enumerate(adapters):
        _validate_adapter(adapter, f"plan.adapter_bundle[{index}]")
        adapter_identities.add(_canonical(adapter))
    if len(adapter_identities) != len(adapters):
        raise ComparisonError("plan.adapter_bundle contains a duplicate identity")

    declared = plan["declared_cells"]
    if (not isinstance(declared, list) or not declared
            or any(not isinstance(cell, str) or not cell for cell in declared)
            or len(set(declared)) != len(declared)):
        raise ComparisonError("plan.declared_cells is invalid")
    receipts = plan["cell_receipts"]
    if not isinstance(receipts, dict) or set(receipts) != set(declared):
        raise ComparisonError("plan.cell_receipts must exactly cover declared cells")

    global_call_ids = set()
    task_families = {}
    for cell_id in declared:
        receipt = receipts[cell_id]
        name = f"plan.cell_receipts[{cell_id!r}]"
        _exact(receipt, CELL_KEYS, name)
        for key in ("task_id", "family", "condition"):
            _text(receipt[key], f"{name}.{key}")
        _integer(receipt["seed"], f"{name}.seed")
        _validate_source(receipt["source"], f"{name}.source", cell=True)
        if receipt["source"]["family"] != receipt["family"]:
            raise ComparisonError(f"{name}.source family differs from the cell")
        source_base = {key: receipt["source"][key] for key in SOURCE_KEYS}
        if _canonical(source_base) not in source_identities:
            raise ComparisonError(f"{name}.source is absent from plan.sources")
        _validate_adapter(receipt["adapter"], f"{name}.adapter")
        if _canonical(receipt["adapter"]) not in adapter_identities:
            raise ComparisonError(f"{name}.adapter is absent from plan.adapter_bundle")
        _validate_grader(receipt["grader"], f"{name}.grader")
        _validate_call_plan(receipt["call_plan"], f"{name}.call_plan", global_call_ids)
        _hash(receipt["call_plan_sha256"], f"{name}.call_plan_sha256")
        if receipt["call_plan_sha256"] != _sha(receipt["call_plan"]):
            raise ComparisonError(f"{name}.call_plan_sha256 does not bind call_plan")
        source_task = (
            receipt["source"]["suite_id"], receipt["source"]["manifest_sha256"],
            receipt["source"]["task_sha256"],
        )
        if task_families.setdefault(source_task, receipt["family"]) != receipt["family"]:
            raise ComparisonError("one immutable source task cannot span multiple families")
    return {"arms": {arm["cohort"]: arm for arm in arms}, "receipts": receipts}


def _validate_fingerprints(fingerprints, plan):
    _exact(fingerprints, FINGERPRINT_KEYS, "plan_fingerprints")
    expected = {
        "declared_cells_sha256": _sha(plan["declared_cells"]),
        "sources_sha256": _sha(plan["sources"]),
        "arms_sha256": _sha(plan["arms"]),
        "adapter_bundle_sha256": _sha(plan["adapter_bundle"]),
    }
    for key, value in fingerprints.items():
        _hash(value, f"plan_fingerprints.{key}")
    if fingerprints != expected:
        raise ComparisonError("plan_fingerprints do not bind the canonical plan")


def _validate_usage(usage, name):
    if not isinstance(usage, dict):
        raise ComparisonError(f"{name} must be an object")
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key not in usage:
            raise ComparisonError(f"{name}.{key} is missing")
        _integer(usage[key], f"{name}.{key}")
    if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
        raise ComparisonError(f"{name} token totals are inconsistent")
    _canonical(usage)


def _validate_call(call, step, route, name):
    _exact(call, CALL_KEYS, name)
    for key in ("call_index", "call_id", "role", "policy_id", "seed", "tools_sha256"):
        if call[key] != step[key]:
            raise ComparisonError(f"{name}.{key} differs from the call plan")
    _integer(call["max_tokens"], f"{name}.max_tokens", minimum=1)
    if step["required"]:
        if call["max_tokens"] != step["max_tokens"]:
            raise ComparisonError(f"{name}.max_tokens differs from the required call plan")
    elif call["max_tokens"] > step["max_tokens"]:
        raise ComparisonError(f"{name}.max_tokens exceeds the optional call-plan ceiling")
    _finite(call["timeout_s"], f"{name}.timeout_s", positive=True)
    if call["timeout_s"] > step["timeout_s"] + TOLERANCE:
        raise ComparisonError(f"{name}.timeout_s exceeds the planned ceiling")
    _text(call["call_id"], f"{name}.call_id")
    _text(call["role"], f"{name}.role")
    if call["status"] not in CALL_STATUSES:
        raise ComparisonError(f"{name}.status is unknown")
    _finite(call["wall_s"], f"{name}.wall_s")
    for key in ("endpoint_name", "served_model"):
        _text(call[key], f"{name}.{key}")
        if call[key] != route[key]:
            raise ComparisonError(f"{name}.{key} differs from the selected arm route")
    _hash(call["artifact_sha256"], f"{name}.artifact_sha256")
    if call["artifact_sha256"] != route["artifact_sha256"]:
        raise ComparisonError(f"{name}.artifact_sha256 differs from the selected arm route")
    policy_id = _text(call["policy_id"], f"{name}.policy_id")
    if policy_id not in route["policies"]:
        raise ComparisonError(f"{name}.policy_id is absent from the selected route")
    _hash(call["resolved_policy_sha256"], f"{name}.resolved_policy_sha256")
    if call["resolved_policy_sha256"] != _sha(route["policies"][policy_id]):
        raise ComparisonError(f"{name}.resolved_policy_sha256 differs from the selected policy")
    _integer(call["seed"], f"{name}.seed")
    _integer(call["max_tokens"], f"{name}.max_tokens", minimum=1)
    _hash(call["messages_sha256"], f"{name}.messages_sha256")
    if step["messages_sha256"] is not None and call["messages_sha256"] != step["messages_sha256"]:
        raise ComparisonError(f"{name}.messages_sha256 differs from the static call plan")
    _hash(call["tools_sha256"], f"{name}.tools_sha256")
    _hash(call["request_sha256"], f"{name}.request_sha256")
    _hash(call["response_stream_sha256"], f"{name}.response_stream_sha256", nullable=True)
    for key in ("response_id", "response_model", "finish_reason", "failure_code", "error"):
        _nullable_text(call[key], f"{name}.{key}")
    if call["status"] == "returned":
        for key in ("response_stream_sha256", "response_id", "response_model", "finish_reason"):
            if call[key] is None:
                raise ComparisonError(f"{name}.{key} is required for a returned call")
        if call["response_model"] != call["served_model"]:
            raise ComparisonError(f"{name}.response_model differs from served_model")
        _validate_usage(call["usage"], f"{name}.usage")
        if call["failure_code"] is not None or call["error"] is not None:
            raise ComparisonError(f"{name} returned but carries a call failure")
    else:
        for key in ("response_stream_sha256", "response_id", "response_model", "finish_reason", "usage"):
            if call[key] is not None:
                raise ComparisonError(f"{name}.{key} must be null for a failed call")
        if call["failure_code"] is None and call["error"] is None:
            raise ComparisonError(f"{name} must explain a failed call")


def _derived_outcome_status(calls):
    if not calls:
        return "not_run"
    statuses = {call["status"] for call in calls}
    for status in ("cancelled", "timeout", "error"):
        if status in statuses:
            return status
    return "returned"


def _validate_grade(grade, outcome, planned, name):
    _exact(grade, GRADE_KEYS, name)
    if grade["grader_id"] != planned["grader"]["id"]:
        raise ComparisonError(f"{name}.grader_id differs from the cell grader")
    if not isinstance(grade["passed"], bool) or grade["passed"] != outcome["passed"]:
        raise ComparisonError(f"{name}.passed differs from outcome.passed")
    _nullable_text(grade["failure_code"], f"{name}.failure_code")
    if grade["failure_code"] != outcome["failure_code"]:
        raise ComparisonError(f"{name}.failure_code differs from outcome.failure_code")
    if not isinstance(grade["details"], dict):
        raise ComparisonError(f"{name}.details must be an object")
    _canonical(grade["details"])


def validate_run(run, cohort):
    """Validate one self-contained cohort receipt and index its outcomes."""
    _exact(run, RUN_KEYS, "run")
    if run["schema_version"] != RUN_SCHEMA or cohort not in COHORTS or run["cohort"] != cohort:
        raise ComparisonError("unexpected run schema/cohort")
    _text(run["run_id"], "run.run_id")
    if run["status"] not in RUN_STATUSES:
        raise ComparisonError("run must be complete or aborted")
    _hash(run["manifest_sha256"], "run.manifest_sha256")
    plan_state = _validate_plan(run["plan"])
    if run["manifest_sha256"] != _sha(run["plan"]):
        raise ComparisonError("manifest_sha256 does not bind the canonical plan")
    _validate_fingerprints(run["plan_fingerprints"], run["plan"])
    if run["arms"] != run["plan"]["arms"]:
        raise ComparisonError("top-level arms differ from the canonical plan")
    if run["declared_cells"] != run["plan"]["declared_cells"]:
        raise ComparisonError("top-level declared cells differ from the canonical plan")
    if run["promotion_authorized"] is not False:
        raise ComparisonError("run cannot authorize promotion")
    elapsed = _finite(run["elapsed_s"], "run.elapsed_s")
    if not isinstance(run["outcomes"], list):
        raise ComparisonError("run.outcomes must be a list")

    indexed = {}
    observed_call_ids = set()
    route_by_role = {
        route["role"]: route
        for route in plan_state["arms"][cohort]["routes"]
    }
    for row_index, outcome in enumerate(run["outcomes"]):
        name = f"run.outcomes[{row_index}]"
        _exact(outcome, OUTCOME_KEYS, name)
        cell_id = outcome["cell_id"]
        if cell_id not in plan_state["receipts"] or cell_id in indexed:
            raise ComparisonError("unexpected or duplicate outcome")
        planned = plan_state["receipts"][cell_id]
        if outcome["cohort"] != cohort:
            raise ComparisonError(f"{name}.cohort differs from the run")
        for key in ("task_id", "family", "condition", "seed", "source", "adapter", "grader"):
            if outcome[key] != planned[key]:
                raise ComparisonError(f"{name}.{key} differs from the canonical cell receipt")
        if outcome["status"] not in OUTCOME_STATUSES:
            raise ComparisonError(f"{name}.status is unknown")
        if not isinstance(outcome["passed"], bool):
            raise ComparisonError(f"{name}.passed must be boolean")
        wall = _finite(outcome["wall_s"], f"{name}.wall_s")
        _nullable_text(outcome["failure_code"], f"{name}.failure_code")
        _nullable_text(outcome["error"], f"{name}.error")
        calls = outcome["calls"]
        if not isinstance(calls, list):
            raise ComparisonError(f"{name}.calls must be a list")
        call_plan = planned["call_plan"]
        steps = call_plan["steps"]
        if outcome["status"] == "not_run":
            if calls:
                raise ComparisonError(f"{name}.not_run cannot contain calls")
        elif not calls:
            raise ComparisonError(f"{name} is attempted but contains no calls")
        elif call_plan["mode"] == "fixed" and len(calls) != len(steps):
            raise ComparisonError(f"{name}.calls do not complete the fixed call plan")
        elif call_plan["mode"] == "conditional" and len(calls) > len(steps):
            raise ComparisonError(f"{name}.calls exceed the conditional call plan")

        call_wall = 0.0
        for call_index, call in enumerate(calls):
            step = steps[call_index]
            role = step["role"]
            if role not in route_by_role:
                raise ComparisonError(f"{name}.calls[{call_index}] uses an undeclared role")
            _validate_call(call, step, route_by_role[role], f"{name}.calls[{call_index}]")
            if call["call_id"] in observed_call_ids:
                raise ComparisonError("run contains a duplicate call ID")
            observed_call_ids.add(call["call_id"])
            call_wall += call["wall_s"]
        if wall + TOLERANCE < call_wall:
            raise ComparisonError(f"{name}.wall_s is shorter than its recorded calls")
        derived_status = _derived_outcome_status(calls)
        adapter_error = (
            derived_status == "returned"
            and outcome["status"] == "error"
            and outcome["failure_code"] is not None
            and outcome["error"] is not None
            and not outcome["passed"]
        )
        if outcome["status"] != derived_status and not adapter_error:
            raise ComparisonError(f"{name}.status contradicts its calls")
        required_calls = sum(step["required"] for step in steps)
        if (call_plan["mode"] == "conditional" and len(calls) < required_calls
                and all(call["status"] == "returned" for call in calls)):
            raise ComparisonError(f"{name}.calls omit a required conditional step")
        if outcome["passed"] and outcome["status"] != "returned":
            raise ComparisonError(f"{name} cannot pass without a returned outcome")
        _validate_grade(outcome["grade"], outcome, planned, f"{name}.grade")
        indexed[cell_id] = outcome

    if set(indexed) != set(run["declared_cells"]):
        raise ComparisonError("every declared cell needs an explicit terminal outcome")
    if [row["cell_id"] for row in run["outcomes"]] != run["declared_cells"]:
        raise ComparisonError("outcomes do not preserve declared cell execution order")
    if run["status"] == "complete" and any(row["status"] == "not_run" for row in run["outcomes"]):
        raise ComparisonError("an incomplete matrix cannot be complete")
    if run["status"] == "complete" and any(row["status"] == "cancelled" for row in run["outcomes"]):
        raise ComparisonError("a run with a cancelled outcome must be aborted")
    total_wall = sum(row["wall_s"] for row in run["outcomes"])
    if elapsed + TOLERANCE < total_wall:
        raise ComparisonError("run.elapsed_s is shorter than serial cell wall time")
    if elapsed == 0 and any(row["status"] != "not_run" for row in run["outcomes"]):
        raise ComparisonError("an attempted run cannot have zero elapsed time")
    return indexed


def _quantile(values, quantile):
    values = sorted(values)
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    return values[lower] + (values[math.ceil(position)] - values[lower]) * (position - lower)


def _family_rng(seed, family):
    digest = hashlib.sha256(_canonical([seed, family])).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))


def _source_task_key(outcome):
    source = outcome["source"]
    return source["suite_id"], source["manifest_sha256"], source["task_sha256"]


def _cohort_summary(indexed, cell_ids, *, eligible):
    selected = [indexed[cell] for cell in cell_ids]
    wall = sum(row["wall_s"] for row in selected)
    calls = [call for row in selected for call in row["calls"]]
    passed = sum(row["passed"] for row in selected)
    rate = passed / len(selected) if eligible else None
    throughput = passed * 3600 / wall if eligible and wall > 0 else None
    return {
        # Stable dashboard fields. Their units are declared task runs and
        # recorded end-to-end cell wall, rather than unique tasks/GPU time.
        "declared": len(selected),
        "attempted": sum(row["status"] != "not_run" for row in selected),
        "passed": passed,
        "success_rate": rate,
        "wall_s_including_failures": wall,
        "successful_task_runs_per_hour": throughput,
        "returned_task_runs": sum(row["status"] == "returned" for row in selected),
        "unique_source_tasks": len({_source_task_key(row) for row in selected}),
        "model_calls": len(calls),
        "recorded_model_call_wall_s": sum(call["wall_s"] for call in calls),
        "outcome_status_counts": {
            status: sum(row["status"] == status for row in selected)
            for status in sorted(OUTCOME_STATUSES)
        },
        "call_status_counts": {
            status: sum(call["status"] == status for call in calls)
            for status in sorted(CALL_STATUSES)
        },
    }


def summarize_pair(resident, flash, *, bootstrap_samples=2000, bootstrap_seed=1701):
    """Return failure-inclusive, development-panel descriptive evidence."""
    if (isinstance(bootstrap_samples, bool) or not isinstance(bootstrap_samples, int)
            or not 100 <= bootstrap_samples <= 100000):
        raise ComparisonError("bootstrap_samples outside 100..100000")
    if isinstance(bootstrap_seed, bool) or not isinstance(bootstrap_seed, int):
        raise ComparisonError("bootstrap_seed must be an integer")

    resident_index = validate_run(resident, "resident")
    flash_index = validate_run(flash, "flash")
    if resident["run_id"] == flash["run_id"]:
        raise ComparisonError("paired cohorts require distinct run IDs")
    if (resident["manifest_sha256"] != flash["manifest_sha256"]
            or resident["plan"] != flash["plan"]
            or resident["plan_fingerprints"] != flash["plan_fingerprints"]
            or resident["arms"] != flash["arms"]
            or resident["declared_cells"] != flash["declared_cells"]):
        raise ComparisonError("cohorts do not share one canonical preregistered matrix")
    for cell_id in resident_index:
        for key in ("task_id", "family", "condition", "seed", "source", "adapter", "grader"):
            if resident_index[cell_id][key] != flash_index[cell_id][key]:
                raise ComparisonError(f"paired cell identity drift: {cell_id}.{key}")

    eligible = resident["status"] == flash["status"] == "complete"
    families = sorted({row["family"] for row in resident_index.values()})
    result = {}
    for family in families:
        cell_ids = [cell for cell in resident["declared_cells"] if resident_index[cell]["family"] == family]
        groups = defaultdict(list)
        for cell_id in cell_ids:
            groups[_source_task_key(resident_index[cell_id])].append(
                int(flash_index[cell_id]["passed"]) - int(resident_index[cell_id]["passed"])
            )
        source_task_means = [sum(values) / len(values) for values in groups.values()]
        bootstrap = []
        if eligible and len(source_task_means) >= 2:
            rng = _family_rng(bootstrap_seed, family)
            for _ in range(bootstrap_samples):
                draw = [rng.choice(source_task_means) for _ in source_task_means]
                bootstrap.append(sum(draw) / len(draw))

        if eligible:
            resident_only = sum(resident_index[cell]["passed"] and not flash_index[cell]["passed"] for cell in cell_ids)
            flash_only = sum(not resident_index[cell]["passed"] and flash_index[cell]["passed"] for cell in cell_ids)
            both = sum(resident_index[cell]["passed"] and flash_index[cell]["passed"] for cell in cell_ids)
            neither = len(cell_ids) - resident_only - flash_only - both
            cell_delta = sum(
                int(flash_index[cell]["passed"]) - int(resident_index[cell]["passed"])
                for cell in cell_ids
            ) / len(cell_ids)
            source_delta = sum(source_task_means) / len(source_task_means)
            interval = [_quantile(bootstrap, 0.025), _quantile(bootstrap, 0.975)] if bootstrap else None
        else:
            resident_only = flash_only = both = neither = None
            cell_delta = source_delta = interval = None

        result[family] = {
            "comparison_eligible": eligible,
            "ineligibility_reason": None if eligible else "one or both cohort runs are incomplete",
            "cohorts": {
                "resident": _cohort_summary(resident_index, cell_ids, eligible=eligible),
                "flash": _cohort_summary(flash_index, cell_ids, eligible=eligible),
            },
            "resampling_units": len(groups),
            "task_runs": len(cell_ids),
            "paired_success_delta": cell_delta,
            "paired_cell_weighted_success_delta": cell_delta,
            "equal_source_task_success_delta": source_delta,
            "task_cluster_bootstrap_95ci": interval,
            "source_task_cluster_resampling_95_interval": interval,
            "both_passed_task_runs": both,
            "resident_only_passed_task_runs": resident_only,
            "flash_only_passed_task_runs": flash_only,
            "neither_passed_task_runs": neither,
            "task_run_count_by_source": sorted(Counter(
                "|".join(_source_task_key(resident_index[cell])) for cell in cell_ids
            ).values()),
        }

    return {
        "schema_version": COMPARISON_SCHEMA,
        "manifest_sha256": resident["manifest_sha256"],
        "plan_fingerprints": resident["plan_fingerprints"],
        "status": "complete" if eligible else "incomplete",
        "comparison_eligible": eligible,
        "families": result,
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": bootstrap_seed,
        "elapsed_s": {"resident": resident["elapsed_s"], "flash": flash["elapsed_s"]},
        "verdict": "DESCRIPTIVE_DEVELOPMENT_PANEL_EVIDENCE" if eligible else "INCOMPLETE_NO_COMPARATIVE_CLAIM",
        "causal_attribution": None,
        "promotion_authorized": False,
        "limitations": [
            "Public development fixtures; no hidden-set confirmation.",
            "Whole role-bundle differences can mix model, weights, quantization, runtime, policy and cache effects.",
            "Resampling units are immutable source tasks, not a random population sample.",
            "Dynamic messages are trusted through the pinned adapter builder; their derivation is not replayed here.",
            "Per-family rate uses recorded serial cell wall including grading; run elapsed additionally includes setup and persistence.",
            "This comparison never authorizes promotion.",
        ],
    }
