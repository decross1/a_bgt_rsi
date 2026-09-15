import copy
import hashlib
import json

import pytest

from bench.flash_next_ab.compare import ComparisonError, summarize_pair, validate_run
from bench.flash_next_ab.manifest import ROLES, SUITE_ID, policy_set


def sha(value):
    if isinstance(value, str):
        value = value.encode()
    elif not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(value).hexdigest()


def cell(cell_id, *, task_id=None, family="science", task_sha=None, condition="matched", seed=17):
    task_id = task_id or cell_id
    source = {
        "family": family,
        "suite_id": "public-development-v1",
        "manifest_path": f"bench/fixtures/{family}.json",
        "manifest_sha256": sha(f"{family}-manifest"),
        "task_sha256": task_sha or sha(task_id),
    }
    adapter = {
        "id": f"{family}-adapter",
        "source_path": f"bench/adapters/{family}.py",
        "source_sha256": sha(f"{family}-adapter"),
    }
    grader = {
        "id": f"{family}-grader",
        "contract_sha256": sha(f"{family}-contract"),
        "source_files": [{"path": f"bench/graders/{family}.py", "sha256": sha(f"{family}-grader")}],
    }
    call_plan = {
        "mode": "fixed",
        "steps": [{
            "call_index": 0,
            "call_id": f"{cell_id}-call-0",
            "role": "generator",
            "policy_id": "scientist",
            "seed": seed,
            "max_tokens": 512,
            "timeout_s": 30.0,
            "required": True,
            "messages_sha256": sha(f"{cell_id}-messages"),
            "messages_builder_sha256": None,
            "tools_sha256": sha([]),
        }],
    }
    return {
        "task_id": task_id,
        "family": family,
        "condition": condition,
        "seed": seed,
        "source": source,
        "adapter": adapter,
        "grader": grader,
        "call_plan": call_plan,
        "call_plan_sha256": sha(call_plan),
    }


def make_plan(cells=None):
    cells = cells or {"one": cell("one"), "two": cell("two")}

    def arm(cohort):
        routes = []
        for role in ROLES:
            endpoint = (
                "resident_qwen" if cohort == "resident" and role == "critic"
                else "resident_gemma" if cohort == "resident"
                else "flash_next"
            )
            policies = policy_set(endpoint)
            routes.append({
                "role": role,
                "endpoint_name": endpoint,
                "served_model": {
                    "resident_gemma": "gemma-4-26b-a4b",
                    "resident_qwen": "qwen3.8-27b-nvfp4-mtp",
                    "flash_next": "qwen3.8-flash-next",
                }[endpoint],
                "artifact_sha256": sha(f"{endpoint}-artifact"),
                "runtime_sha256": sha(f"{endpoint}-runtime"),
                "policies": policies,
                "policy_set_sha256": sha(policies),
            })
        return {
            "cohort": cohort,
            "qualification_receipt_sha256": sha(f"{cohort}-qualification"),
            "routes": routes,
        }

    sources = []
    adapters = []
    for receipt in cells.values():
        source = {key: receipt["source"][key] for key in ("family", "suite_id", "manifest_path", "manifest_sha256")}
        if source not in sources:
            sources.append(source)
        if receipt["adapter"] not in adapters:
            adapters.append(receipt["adapter"])
    return {
        "schema_version": "flash-next-ab-plan/v1",
        "suite_id": SUITE_ID,
        "cohorts": ["resident", "flash"],
        "arms": [arm("resident"), arm("flash")],
        "sources": sources,
        "adapter_bundle": adapters,
        "declared_cells": list(cells),
        "cell_receipts": cells,
        "promotion_authorized": False,
        "limitations": ["Public development fixtures."],
    }


def plan_fingerprints(plan):
    return {
        "declared_cells_sha256": sha(plan["declared_cells"]),
        "sources_sha256": sha(plan["sources"]),
        "arms_sha256": sha(plan["arms"]),
        "adapter_bundle_sha256": sha(plan["adapter_bundle"]),
    }


def outcome(plan, cohort, cell_id, passed=False, *, status="returned", wall_s=2.0):
    receipt = plan["cell_receipts"][cell_id]
    step = receipt["call_plan"]["steps"][0]
    arm = next(arm for arm in plan["arms"] if arm["cohort"] == cohort)
    route = next(route for route in arm["routes"] if route["role"] == step["role"])
    failure_code = None if passed else "objective_failed"
    if status == "not_run":
        calls = []
        wall_s = 0
        failure_code = "not_run"
    else:
        call_failure = status if status != "returned" else None
        calls = [{
            "call_index": step["call_index"],
            "call_id": step["call_id"],
            "role": step["role"],
            "status": status,
            "wall_s": 1.0,
            "endpoint_name": route["endpoint_name"],
            "served_model": route["served_model"],
            "artifact_sha256": route["artifact_sha256"],
            "policy_id": step["policy_id"],
            "resolved_policy_sha256": sha(route["policies"][step["policy_id"]]),
            "seed": step["seed"],
            "max_tokens": step["max_tokens"],
            "timeout_s": step["timeout_s"],
            "messages_sha256": step["messages_sha256"],
            "tools_sha256": step["tools_sha256"],
            "request_sha256": sha(f"{cohort}-{cell_id}-request"),
            "response_stream_sha256": sha(f"{cohort}-{cell_id}-response") if status == "returned" else None,
            "response_id": f"response-{cohort}-{cell_id}" if status == "returned" else None,
            "response_model": route["served_model"] if status == "returned" else None,
            "finish_reason": "stop" if status == "returned" else None,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15} if status == "returned" else None,
            "failure_code": call_failure,
            "error": None,
        }]
        if status != "returned":
            failure_code = status
            passed = False
    return {
        "cell_id": cell_id,
        "cohort": cohort,
        "task_id": receipt["task_id"],
        "family": receipt["family"],
        "condition": receipt["condition"],
        "seed": receipt["seed"],
        "status": status,
        "passed": passed,
        "wall_s": wall_s,
        "source": copy.deepcopy(receipt["source"]),
        "adapter": copy.deepcopy(receipt["adapter"]),
        "grader": copy.deepcopy(receipt["grader"]),
        "calls": calls,
        "grade": {
            "grader_id": receipt["grader"]["id"],
            "passed": passed,
            "failure_code": failure_code,
            "details": {},
        },
        "failure_code": failure_code,
        "error": None,
    }


def run(cohort, *, plan=None, passed=(True, False), status="complete"):
    plan = copy.deepcopy(plan or make_plan())
    rows = [outcome(plan, cohort, cell_id, ok) for cell_id, ok in zip(plan["declared_cells"], passed, strict=True)]
    return {
        "schema_version": "flash-next-ab-run/v1",
        "run_id": f"{cohort}-run",
        "cohort": cohort,
        "status": status,
        "manifest_sha256": sha(plan),
        "plan": plan,
        "plan_fingerprints": plan_fingerprints(plan),
        "arms": copy.deepcopy(plan["arms"]),
        "declared_cells": list(plan["declared_cells"]),
        "elapsed_s": sum(row["wall_s"] for row in rows) + 10,
        "outcomes": rows,
        "promotion_authorized": False,
    }


def paired(plan=None, resident_passed=(True, False), flash_passed=(True, True)):
    plan = plan or make_plan()
    return run("resident", plan=plan, passed=resident_passed), run("flash", plan=plan, passed=flash_passed)


def test_complete_pair_reports_failure_inclusive_units_without_causal_claim():
    resident, flash = paired()
    result = summarize_pair(resident, flash, bootstrap_samples=100)
    family = result["families"]["science"]
    assert result["comparison_eligible"] is True
    assert result["causal_attribution"] is None
    assert result["promotion_authorized"] is False
    assert family["cohorts"]["resident"] == {
        "declared": 2,
        "attempted": 2,
        "passed": 1,
        "success_rate": 0.5,
        "wall_s_including_failures": 4.0,
        "successful_task_runs_per_hour": 900.0,
        "returned_task_runs": 2,
        "unique_source_tasks": 2,
        "model_calls": 2,
        "recorded_model_call_wall_s": 2.0,
        "outcome_status_counts": {"cancelled": 0, "error": 0, "not_run": 0, "returned": 2, "timeout": 0},
        "call_status_counts": {"cancelled": 0, "error": 0, "returned": 2, "timeout": 0},
    }
    assert family["paired_success_delta"] == 0.5
    assert family["flash_only_passed_task_runs"] == 1


def test_aborted_favorable_prefix_cannot_emit_a_comparative_win():
    resident, flash = paired(resident_passed=(False, False), flash_passed=(True, False))
    flash["status"] = "aborted"
    flash["outcomes"][1] = outcome(flash["plan"], "flash", "two", status="not_run")
    result = summarize_pair(resident, flash, bootstrap_samples=100)
    family = result["families"]["science"]
    assert result["comparison_eligible"] is False
    assert result["verdict"] == "INCOMPLETE_NO_COMPARATIVE_CLAIM"
    assert family["paired_success_delta"] is None
    assert family["task_cluster_bootstrap_95ci"] is None
    assert family["flash_only_passed_task_runs"] is None
    assert family["cohorts"]["flash"]["success_rate"] is None
    assert family["cohorts"]["flash"]["successful_task_runs_per_hour"] is None
    assert family["cohorts"]["flash"]["passed"] == 1


@pytest.mark.parametrize(
    "mutation",
    ["manifest", "fingerprint", "top_arms", "top_cells", "cohort", "source", "adapter", "grader", "call_plan"],
)
def test_refuses_plan_or_cell_identity_drift(mutation):
    resident, flash = paired()
    if mutation == "manifest":
        flash["manifest_sha256"] = "b" * 64
    elif mutation == "fingerprint":
        flash["plan_fingerprints"]["sources_sha256"] = "b" * 64
    elif mutation == "top_arms":
        flash["arms"][0]["qualification_receipt_sha256"] = "b" * 64
    elif mutation == "top_cells":
        flash["declared_cells"].reverse()
    elif mutation == "cohort":
        flash["outcomes"][0]["cohort"] = "resident"
    elif mutation == "source":
        flash["outcomes"][0]["source"]["task_sha256"] = "b" * 64
    elif mutation == "adapter":
        flash["outcomes"][0]["adapter"]["source_sha256"] = "b" * 64
    elif mutation == "grader":
        flash["outcomes"][0]["grader"]["contract_sha256"] = "b" * 64
    elif mutation == "call_plan":
        flash["plan"]["cell_receipts"]["one"]["call_plan"]["steps"][0]["seed"] = 29
    with pytest.raises(ComparisonError):
        summarize_pair(resident, flash, bootstrap_samples=100)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("endpoint_name", "wrong"),
        ("served_model", "wrong"),
        ("artifact_sha256", "b" * 64),
        ("policy_id", "wrong"),
        ("resolved_policy_sha256", "b" * 64),
        ("seed", 29),
        ("max_tokens", 999),
        ("timeout_s", 31),
        ("messages_sha256", "b" * 64),
        ("tools_sha256", "b" * 64),
        ("response_model", "wrong"),
    ],
)
def test_refuses_call_execution_identity_drift(field, value):
    candidate = run("flash")
    candidate["outcomes"][0]["calls"][0][field] = value
    with pytest.raises(ComparisonError):
        validate_run(candidate, "flash")


@pytest.mark.parametrize("status", ["timeout", "cancelled", "error"])
def test_terminal_call_failures_are_explicit_and_failure_inclusive(status):
    resident, flash = paired()
    flash["outcomes"][0] = outcome(flash["plan"], "flash", "one", status=status)
    if status == "cancelled":
        flash["status"] = "aborted"
        with pytest.raises(ComparisonError, match="cancelled outcome"):
            validate_run({**flash, "status": "complete"}, "flash")
    result = summarize_pair(resident, flash, bootstrap_samples=100)
    summary = result["families"]["science"]["cohorts"]["flash"]
    assert result["comparison_eligible"] is (status != "cancelled")
    assert summary["declared"] == 2
    assert summary["outcome_status_counts"][status] == 1
    assert summary["passed"] == 1
    assert summary["success_rate"] == (0.5 if status != "cancelled" else None)


def test_fixed_plan_requires_all_calls_and_status_matches_calls():
    candidate = run("flash")
    receipt = candidate["plan"]["cell_receipts"]["one"]
    second = copy.deepcopy(receipt["call_plan"]["steps"][0])
    second.update(call_index=1, call_id="one-call-1")
    receipt["call_plan"]["steps"].append(second)
    receipt["call_plan_sha256"] = sha(receipt["call_plan"])
    candidate["manifest_sha256"] = sha(candidate["plan"])
    candidate["plan_fingerprints"] = plan_fingerprints(candidate["plan"])
    candidate["arms"] = copy.deepcopy(candidate["plan"]["arms"])
    with pytest.raises(ComparisonError, match="fixed call plan"):
        validate_run(candidate, "flash")


def test_conditional_plan_cannot_skip_a_required_step_after_returning():
    plan = make_plan()
    receipt = plan["cell_receipts"]["one"]
    receipt["call_plan"]["mode"] = "conditional"
    second = copy.deepcopy(receipt["call_plan"]["steps"][0])
    second.update(call_index=1, call_id="one-call-1")
    receipt["call_plan"]["steps"].append(second)
    receipt["call_plan_sha256"] = sha(receipt["call_plan"])
    candidate = run("flash", plan=plan)
    with pytest.raises(ComparisonError, match="required conditional step"):
        validate_run(candidate, "flash")


def test_not_run_has_no_calls_even_when_adapter_time_is_recorded():
    candidate = run("flash", status="aborted")
    candidate["outcomes"][1] = outcome(candidate["plan"], "flash", "two", status="not_run")
    candidate["outcomes"][1]["wall_s"] = 1
    candidate["elapsed_s"] += 1
    validate_run(candidate, "flash")
    candidate["outcomes"][1]["calls"] = copy.deepcopy(candidate["outcomes"][0]["calls"])
    with pytest.raises(ComparisonError, match="not_run cannot contain calls"):
        validate_run(candidate, "flash")


def test_outcomes_preserve_declared_counterbalanced_order():
    candidate = run("flash")
    candidate["outcomes"].reverse()
    with pytest.raises(ComparisonError, match="execution order"):
        validate_run(candidate, "flash")


def test_timing_must_cover_calls_cells_and_serial_run():
    candidate = run("flash")
    candidate["outcomes"][0]["wall_s"] = 0.5
    with pytest.raises(ComparisonError, match="shorter than its recorded calls"):
        validate_run(candidate, "flash")
    candidate = run("flash")
    candidate["elapsed_s"] = 1
    with pytest.raises(ComparisonError, match="serial cell wall time"):
        validate_run(candidate, "flash")


def test_wrapper_plan_can_bind_multiple_original_source_suites():
    cells = {"one": cell("one"), "two": cell("two", family="tool")}
    cells["one"]["source"]["suite_id"] = "science-suite-v3"
    cells["two"]["source"]["suite_id"] = "tool-suite-v2"
    plan = make_plan(cells)
    resident, flash = paired(plan)
    result = summarize_pair(resident, flash, bootstrap_samples=100)
    assert result["comparison_eligible"] is True
    assert set(result["families"]) == {"science", "tool"}


def test_equal_source_task_estimand_does_not_let_repetitions_dominate():
    cells = {}
    shared_a = sha("source-task-a")
    for index in range(10):
        cells[f"a-{index}"] = cell(f"a-{index}", task_id="task-a", task_sha=shared_a, condition=f"repeat-{index}")
    cells["b-0"] = cell("b-0", task_id="task-b", task_sha=sha("source-task-b"))
    plan = make_plan(cells)
    resident_passed = (False,) * 10 + (True,)
    flash_passed = (True,) * 10 + (False,)
    resident, flash = paired(plan, resident_passed, flash_passed)
    family = summarize_pair(resident, flash, bootstrap_samples=100)["families"]["science"]
    assert family["paired_cell_weighted_success_delta"] == pytest.approx(9 / 11)
    assert family["equal_source_task_success_delta"] == 0
    assert family["resampling_units"] == 2
    assert family["task_run_count_by_source"] == [1, 10]


def test_family_resampling_stream_is_stable_when_an_unrelated_family_is_added():
    base_cells = {
        "s1": cell("s1"),
        "s2": cell("s2"),
        "s3": cell("s3"),
    }
    base = make_plan(base_cells)
    a, b = paired(base, (False, False, True), (True, False, False))
    original = summarize_pair(a, b, bootstrap_samples=200)["families"]["science"]["task_cluster_bootstrap_95ci"]

    expanded_cells = {
        "other-1": cell("other-1", family="alpha"),
        "other-2": cell("other-2", family="alpha"),
        **base_cells,
    }
    expanded = make_plan(expanded_cells)
    a, b = paired(expanded, (False, True, False, False, True), (True, True, True, False, False))
    observed = summarize_pair(a, b, bootstrap_samples=200)["families"]["science"]["task_cluster_bootstrap_95ci"]
    assert observed == original


def test_closed_receipts_and_invalid_bootstrap_controls_fail_closed():
    candidate = run("flash")
    candidate["outcomes"][0]["surprise"] = True
    with pytest.raises(ComparisonError, match="unexpected shape"):
        validate_run(candidate, "flash")
    resident, flash = paired()
    with pytest.raises(ComparisonError):
        summarize_pair(resident, flash, bootstrap_samples=True)
    with pytest.raises(ComparisonError):
        summarize_pair(resident, flash, bootstrap_seed=True)


def test_paired_receipts_must_be_distinct_runs():
    resident, flash = paired()
    flash["run_id"] = resident["run_id"]
    with pytest.raises(ComparisonError, match="distinct run IDs"):
        summarize_pair(resident, flash, bootstrap_samples=100)
