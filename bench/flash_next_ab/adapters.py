"""Adapters from frozen benchmark families to one paired A/B cell protocol.

All model I/O is injected by :mod:`bench.flash_next_ab.harness`.  This module
loads existing manifests and calls their existing parsers and objective graders;
it does not edit the source manifests or project their old scores forward.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .manifest import REPO_ROOT, sha256_file, sha256_json

FAMILIES = (
    "objective",
    "topic",
    "context",
    "portfolio",
    "diversity",
    "role_effort",
    "historical",
)
ADAPTER_SOURCE = "bench/flash_next_ab/adapters.py"


@dataclass(frozen=True)
class CallSpec:
    call_index: int
    call_id: str
    role: str
    policy_id: str
    seed: int
    max_tokens: int
    timeout_s: float
    required: bool
    messages: tuple[dict[str, Any], ...] | None
    tools: tuple[dict[str, Any], ...] = ()
    messages_builder: str | None = None

    def plan_step(self) -> dict[str, Any]:
        return {
            "call_index": self.call_index,
            "call_id": self.call_id,
            "role": self.role,
            "policy_id": self.policy_id,
            "seed": self.seed,
            "max_tokens": self.max_tokens,
            "timeout_s": self.timeout_s,
            "required": self.required,
            "messages_sha256": (
                sha256_json(list(self.messages)) if self.messages is not None else None
            ),
            "messages_builder_sha256": (
                sha256_json({"adapter": ADAPTER_SOURCE, "builder": self.messages_builder})
                if self.messages_builder is not None
                else None
            ),
            "tools_sha256": sha256_json(list(self.tools)),
        }


@dataclass(frozen=True)
class CallResult:
    spec: CallSpec
    status: str
    content: str | None
    tool_calls: tuple[dict[str, Any], ...]
    receipt: dict[str, Any]


@dataclass(frozen=True)
class AdapterResult:
    calls: tuple[CallResult, ...]
    passed: bool
    failure_code: str | None
    details: dict[str, Any]


InvokeFn = Callable[[CallSpec], CallResult]


@dataclass(frozen=True)
class CellDefinition:
    cell_id: str
    task_id: str
    family: str
    condition: str
    seed: int
    source: dict[str, Any]
    adapter: dict[str, Any]
    grader: dict[str, Any]
    call_mode: str
    calls: tuple[CallSpec, ...]
    payload: dict[str, Any] = field(repr=False, compare=False)

    def receipt(self) -> dict[str, Any]:
        call_plan = {
            "mode": self.call_mode,
            "steps": [call.plan_step() for call in self.calls],
        }
        return {
            "task_id": self.task_id,
            "family": self.family,
            "condition": self.condition,
            "seed": self.seed,
            "source": self.source,
            "adapter": self.adapter,
            "grader": self.grader,
            "call_plan": call_plan,
            "call_plan_sha256": sha256_json(call_plan),
        }


def _relative(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError as exc:
        raise ValueError(f"source is outside repository: {resolved}") from exc


def _source(
    family: str,
    suite_id: str,
    manifest_path: str | Path,
    task_sha256: str,
) -> dict[str, Any]:
    path = Path(manifest_path).resolve()
    return {
        "family": family,
        "suite_id": suite_id,
        "manifest_path": _relative(path),
        "manifest_sha256": sha256_file(path),
        "task_sha256": task_sha256,
    }


def _adapter(adapter_id: str) -> dict[str, Any]:
    path = REPO_ROOT / ADAPTER_SOURCE
    return {
        "id": adapter_id,
        "source_path": ADAPTER_SOURCE,
        "source_sha256": sha256_file(path),
    }


def _grader(
    grader_id: str,
    contract: Any,
    source_paths: Iterable[str],
) -> dict[str, Any]:
    files = [
        {"path": path, "sha256": sha256_file(REPO_ROOT / path)}
        for path in source_paths
    ]
    return {
        "id": grader_id,
        "contract_sha256": sha256_json(contract),
        "source_files": files,
    }


def _call(
    cell_id: str,
    index: int,
    *,
    role: str,
    policy_id: str,
    seed: int,
    max_tokens: int,
    timeout_s: float,
    messages: list[dict[str, Any]] | None,
    tools: list[dict[str, Any]] | None = None,
    required: bool = True,
    messages_builder: str | None = None,
) -> CallSpec:
    return CallSpec(
        call_index=index,
        call_id=f"{cell_id}#{index}",
        role=role,
        policy_id=policy_id,
        seed=seed,
        max_tokens=max_tokens,
        timeout_s=float(timeout_s),
        required=required,
        messages=tuple(messages) if messages is not None else None,
        tools=tuple(tools or ()),
        messages_builder=messages_builder,
    )


def _openai_tools(task: Any) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in task.tools
    ]


def _objective_cells(*, context: bool = False) -> list[CellDefinition]:
    from bench.weekly_upgrade_eval.manifest import load_manifest

    path = (
        REPO_ROOT / "experiments/weekly_context_capability_v1_2026-09-14.json"
        if context
        else REPO_ROOT / "bench/weekly_upgrade_eval/fixtures.json"
    )
    manifest = load_manifest(path)
    family = "context" if context else "objective"
    adapter_id = f"{family}/v1"
    cells: list[CellDefinition] = []
    arm_by_id = {arm.id: arm for arm in manifest.arms}
    for index, task in enumerate(manifest.tasks):
        if context:
            arm_ids = (manifest.arms[0].id,)
        else:
            arm_ids = manifest.arm_ids if index % 2 == 0 else tuple(reversed(manifest.arm_ids))
        for arm_id in arm_ids:
            arm = arm_by_id[arm_id]
            condition = "matched" if context else f"policy-{arm.id}-{arm.profile}"
            seed = arm.seed if arm.seed is not None else 0
            cell_id = f"{family}/{task.id}/{condition}/seed-{seed}"
            role = {
                "critic": "critic",
                "evidence": "evidence",
                "tool": "execution",
                "game_theory": "generator",
            }.get(task.family, "evidence" if context else "generator")
            policy_id = "deterministic" if context else arm.profile
            messages = [
                {"role": "system", "content": task.system},
                {"role": "user", "content": task.prompt},
            ]
            tools = _openai_tools(task)
            spec = _call(
                cell_id,
                0,
                role=role,
                policy_id=policy_id,
                seed=seed,
                max_tokens=arm.max_tokens,
                timeout_s=arm.request_timeout_s,
                messages=messages,
                tools=tools,
            )
            task_contract = task.as_dict()
            cells.append(
                CellDefinition(
                    cell_id=cell_id,
                    task_id=task.id,
                    family=family,
                    condition=condition,
                    seed=seed,
                    source=_source(family, manifest.suite_id, path, sha256_json(task_contract)),
                    adapter=_adapter(adapter_id),
                    grader=_grader(
                        f"weekly_upgrade_eval:{task.grader['kind']}",
                        {"grader": task.grader, "grader_sha256": task.grader_sha256},
                        (
                            "bench/weekly_upgrade_eval/runner.py",
                            "bench/weekly_upgrade_eval/structured_output.py",
                        ),
                    ),
                    call_mode="fixed",
                    calls=(spec,),
                    payload={"kind": "objective", "task": task},
                )
            )
    return cells


def _topic_cells() -> list[CellDefinition]:
    from bench.weekly_upgrade_eval import topic_scope

    path = REPO_ROOT / "experiments/topic_scope_repair_v2_2026-09-14.json"
    manifest = topic_scope.load_manifest(path)
    cells: list[CellDefinition] = []
    for attempt in topic_scope.build_attempts(manifest):
        messages, case = topic_scope._messages(manifest, attempt)
        config = manifest["settings"][attempt["stage"]]
        policy_id = "scientist" if attempt["stage"] == "hypothesis" else "planner"
        role = "generator" if attempt["stage"] == "hypothesis" else "planner"
        condition = f"{attempt['stage']}:{attempt['arm']}"
        cell_id = f"topic/{attempt['case_id']}/{condition}/seed-{attempt['seed']}"
        arm = next(item for item in manifest["arms"] if item["id"] == attempt["arm"])
        task_contract = {
            "attempt": attempt,
            "case": case,
            "system": arm[f"{attempt['stage']}_system"],
            "settings": config,
        }
        spec = _call(
            cell_id,
            0,
            role=role,
            policy_id=policy_id,
            seed=attempt["seed"],
            max_tokens=config["max_tokens"],
            timeout_s=config["request_timeout_s"],
            messages=messages,
        )
        cells.append(
            CellDefinition(
                cell_id=cell_id,
                task_id=attempt["case_id"],
                family="topic",
                condition=condition,
                seed=attempt["seed"],
                source=_source("topic", manifest["suite_id"], path, sha256_json(task_contract)),
                adapter=_adapter("topic-scope/v2-protocol"),
                grader=_grader(
                    f"topic_scope:{attempt['stage']}:protocol",
                    {
                        "stage": attempt["stage"],
                        "case_expected": case.get("expected"),
                        "planner_menu": manifest.get("planner_menu") if attempt["stage"] == "planner" else None,
                    },
                    ("bench/weekly_upgrade_eval/topic_scope.py",),
                ),
                call_mode="fixed",
                calls=(spec,),
                payload={
                    "kind": "topic",
                    "manifest": manifest,
                    "attempt": attempt,
                    "case": case,
                },
            )
        )
    return cells


def _portfolio_cells() -> list[CellDefinition]:
    from bench.weekly_upgrade_portfolio import manifest as portfolio_manifest
    from bench.weekly_upgrade_portfolio import runner as portfolio_runner

    path = portfolio_manifest.DEFAULT_MANIFEST
    manifest = portfolio_manifest.load_manifest(path)
    tasks = {task["id"]: task for task in manifest["tasks"]}
    arms = {arm["id"]: arm for arm in manifest["arms"]}
    cells = []
    for planned in portfolio_manifest.plan_dict(manifest)["order"]:
        task = tasks[planned["task_id"]]
        arm = arms[planned["arm"]]
        condition = f"policy-{arm['id']}-{arm['profile']}"
        cell_id = f"portfolio/{task['id']}/{condition}/seed-{arm['seed']}"
        role = {
            "scientific": "generator",
            "evidence": "evidence",
            "coding": "coding",
        }[task["family"]]
        spec = _call(
            cell_id,
            0,
            role=role,
            policy_id=arm["profile"],
            seed=arm["seed"],
            max_tokens=task["max_tokens"],
            timeout_s=task["request_timeout_s"],
            messages=portfolio_runner._messages(task),
        )
        grader_sources = ["bench/weekly_upgrade_portfolio/graders.py"]
        if task["mode"] == "code":
            grader_sources.append("bench/weekly_upgrade_portfolio/code_sandbox.py")
        cells.append(
            CellDefinition(
                cell_id=cell_id,
                task_id=task["id"],
                family="portfolio",
                condition=condition,
                seed=arm["seed"],
                source=_source(
                    "portfolio",
                    manifest["suite_id"],
                    path,
                    manifest["frozen_hashes"]["tasks"][task["id"]],
                ),
                adapter=_adapter("portfolio/v1"),
                grader=_grader(
                    f"portfolio:{task['grader']['kind']}",
                    task["grader"],
                    grader_sources,
                ),
                call_mode="fixed",
                calls=(spec,),
                payload={"kind": "portfolio", "task": task, "manifest": manifest},
            )
        )
    return cells


def _diversity_cells() -> list[CellDefinition]:
    from bench.weekly_upgrade_diversity import manifest as diversity_manifest
    from bench.weekly_upgrade_diversity import runner as diversity_runner

    path = diversity_manifest.V1_MANIFEST
    manifest = diversity_manifest.load_manifest(path)
    planned = diversity_manifest.plan_dict(manifest)["calls"]
    cells = []
    for task_index, task in enumerate(manifest["tasks"]):
        conditions = ["control", "diverse_select"]
        if task_index % 2:
            conditions.reverse()
        for condition in conditions:
            rows = [
                row for row in planned
                if row["task_id"] == task["id"] and row["condition"] == condition
            ]
            outcome_seed = rows[-1]["seed"] if condition == "diverse_select" else rows[0]["seed"]
            cell_id = f"diversity/{task['id']}/{condition}/seed-{outcome_seed}"
            calls = []
            for index, row in enumerate(rows):
                if condition == "control":
                    messages = diversity_runner._control_messages(task, scaffold_v1=True)
                    builder = None
                elif row["role"] == "generate":
                    messages = diversity_runner._explore_messages(task, directive_index=index)
                    builder = None
                else:
                    messages = None
                    builder = "diversity_validator_messages/v1"
                calls.append(
                    _call(
                        cell_id,
                        index,
                        role="validator" if row["role"] == "validate" else "generator",
                        policy_id=row["profile"],
                        seed=row["seed"],
                        max_tokens=row["max_tokens"],
                        timeout_s=row["timeout_s"],
                        messages=messages,
                        messages_builder=builder,
                    )
                )
            cells.append(
                CellDefinition(
                    cell_id=cell_id,
                    task_id=task["id"],
                    family="diversity",
                    condition=condition,
                    seed=outcome_seed,
                    source=_source(
                        "diversity",
                        manifest["suite_id"],
                        path,
                        manifest["frozen_hashes"]["tasks"][task["id"]],
                    ),
                    adapter=_adapter("diversity-selection/v1-followthrough"),
                    grader=_grader(
                        f"diversity:{task['grader']['kind']}:v1",
                        task["grader"],
                        (
                            "bench/weekly_upgrade_diversity/graders.py",
                            "bench/weekly_upgrade_diversity/runner.py",
                            "bench/weekly_upgrade_eval/structured_output.py",
                        ),
                    ),
                    # The validator prompt is rendered from preceding proposals.
                    # All calls are required absent cancellation, but a cancelled
                    # staged group must retain an honest issued-call prefix.
                    call_mode="conditional",
                    calls=tuple(calls),
                    payload={
                        "kind": "diversity",
                        "task": task,
                        "condition": condition,
                    },
                )
            )
    return cells


def _effort_cells() -> list[CellDefinition]:
    from bench.weekly_upgrade_effort import manifest as effort_manifest
    from bench.weekly_upgrade_effort import runner as effort_runner

    path = REPO_ROOT / "experiments/weekly_role_effort_v1_2026-09-14.json"
    manifest = effort_manifest.load_manifest(path)
    tasks = {task["id"]: task for task in manifest["tasks"]}
    plan = effort_manifest.plan_dict(manifest)
    cells = []
    for planned in plan["order"]:
        task = tasks[planned["task_id"]]
        arm = planned["arm"]
        cell_id = f"role_effort/{task['id']}/{arm}/seed-{manifest['seed']}"
        first_effort = effort_runner.route(task["role"], arm)
        assert first_effort in {"xhigh", "medium"}
        policies = {"xhigh": "critic_current", "medium": "critic_medium"}
        initial_adaptive = arm == "adaptive" and task["role"] != "critic"
        first_max = manifest["max_tokens"] // 2 if initial_adaptive else manifest["max_tokens"]
        first_timeout = manifest["attempt_timeout_s"] / 2 if initial_adaptive else manifest["attempt_timeout_s"]
        calls = [
            _call(
                cell_id,
                0,
                role=task["role"],
                policy_id=policies[first_effort],
                seed=manifest["seed"],
                max_tokens=first_max,
                timeout_s=first_timeout,
                messages=effort_runner.messages(task, retry=False),
            )
        ]
        if initial_adaptive:
            calls.append(
                _call(
                    cell_id,
                    1,
                    role=task["role"],
                    policy_id="critic_current",
                    seed=manifest["seed"] + 1,
                    max_tokens=manifest["max_tokens"],
                    timeout_s=manifest["attempt_timeout_s"],
                    messages=effort_runner.messages(task, retry=True),
                    required=False,
                )
            )
        cells.append(
            CellDefinition(
                cell_id=cell_id,
                task_id=task["id"],
                family="role_effort",
                condition=arm,
                seed=manifest["seed"],
                source=_source(
                    "role_effort", manifest["suite_id"], path,
                    plan["input_sha256"][task["id"]],
                ),
                adapter=_adapter("role-effort/v1"),
                grader=_grader(
                    "role-effort:exact-schema-answer/v1",
                    {
                        "output_schema": task["output_schema"],
                        "expected": task["expected"],
                        "grader_sha256": plan["grader_sha256"][task["id"]],
                    },
                    (
                        "bench/weekly_upgrade_effort/runner.py",
                        "bench/weekly_upgrade_eval/structured_output.py",
                    ),
                ),
                call_mode="conditional" if len(calls) > 1 else "fixed",
                calls=tuple(calls),
                payload={
                    "kind": "role_effort",
                    "manifest": manifest,
                    "task": task,
                    "planned": planned,
                },
            )
        )
    return cells


def _historical_cells() -> list[CellDefinition]:
    from bench.weekly_upgrade_historical import manifest as historical_manifest

    path = REPO_ROOT / "experiments/weekly_historical_coding_patch_wire_v1_2026-09-14.json"
    manifest = historical_manifest.load_manifest(path)
    plan = historical_manifest.plan_dict(manifest)
    cells = []
    for planned, task in zip(plan["order"], manifest["tasks"], strict=True):
        base_source = historical_manifest.git_blob(
            task["base"]["commit"], task["base"]["repair_path"]
        ).decode("utf-8")
        messages = historical_manifest.messages_for(
            task, base_source, schema_version=manifest["schema_version"]
        )
        seed = manifest["arm"]["seed"]
        cell_id = f"historical/{task['id']}/matched/seed-{seed}"
        spec = _call(
            cell_id,
            0,
            role="coding",
            policy_id=manifest["arm"]["profile"],
            seed=seed,
            max_tokens=task["max_tokens"],
            timeout_s=task["request_timeout_s"],
            messages=messages,
        )
        cells.append(
            CellDefinition(
                cell_id=cell_id,
                task_id=task["id"],
                family="historical",
                condition="matched",
                seed=seed,
                source=_source(
                    "historical", manifest["suite_id"], path,
                    planned["input_sha256"],
                ),
                adapter=_adapter("historical-patch-wire/v1"),
                grader=_grader(
                    f"historical:{task['grader']['kind']}",
                    {
                        "grader_sha256": planned["grader_sha256"],
                        "grader": task["grader"],
                        "sandbox_runtime": manifest["sandbox_runtime"],
                    },
                    (
                        "bench/weekly_upgrade_historical/manifest.py",
                        "bench/weekly_upgrade_historical/grader_assets.py",
                        "bench/weekly_upgrade_historical/sandbox.py",
                        "bench/weekly_upgrade_historical/runner.py",
                    ),
                ),
                call_mode="fixed",
                calls=(spec,),
                payload={
                    "kind": "historical",
                    "manifest": manifest,
                    "task": task,
                    "planned": planned,
                },
            )
        )
    return cells


def load_cells(*, families: Iterable[str] | None = None) -> list[CellDefinition]:
    selected = tuple(families) if families is not None else FAMILIES
    if not selected or len(selected) != len(set(selected)) or any(item not in FAMILIES for item in selected):
        raise ValueError(f"families must be unique members of {FAMILIES}")
    loaders = {
        "objective": lambda: _objective_cells(context=False),
        "topic": _topic_cells,
        "context": lambda: _objective_cells(context=True),
        "portfolio": _portfolio_cells,
        "diversity": _diversity_cells,
        "role_effort": _effort_cells,
        "historical": _historical_cells,
    }
    result = []
    for family in selected:
        result.extend(loaders[family]())
    return result


def _first_transport_failure(calls: list[CallResult]) -> str | None:
    for call in calls:
        if call.status != "returned":
            return f"transport_{call.status}"
    return None


def _decode_transport_tools(
    calls: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    decoded = []
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"__malformed_arguments__": arguments}
        else:
            arguments = {"__malformed_arguments__": arguments}
        decoded.append({"name": function["name"], "arguments": arguments})
    return tuple(decoded)


def _execute_objective(cell: CellDefinition, invoke: InvokeFn) -> AdapterResult:
    from bench.weekly_upgrade_eval.runner import InvocationResult, grade_task

    call = invoke(cell.calls[0])
    failure = _first_transport_failure([call])
    result = InvocationResult(
        completion=call.content or "",
        tool_calls=_decode_transport_tools(call.tool_calls),
        failure_code=failure,
    )
    grade = grade_task(cell.payload["task"], result)
    return AdapterResult(
        (call,),
        grade.passed,
        None if grade.passed else grade.reason,
        {
            "existing_grade": dataclasses.asdict(grade),
            "metric_scope": "objective_correctness",
        },
    )


def _execute_topic(cell: CellDefinition, invoke: InvokeFn) -> AdapterResult:
    from bench.weekly_upgrade_eval import topic_scope

    call = invoke(cell.calls[0])
    failure = _first_transport_failure([call])
    if failure is not None:
        parsed = {"protocol_valid": False, "protocol_error": failure}
    elif cell.payload["attempt"]["stage"] == "hypothesis":
        parsed = topic_scope._parse_hypothesis(call.content)
    else:
        parsed = topic_scope._parse_planner(
            call.content,
            cell.payload["case"],
            cell.payload["manifest"],
        )
    passed = bool(parsed.get("protocol_valid"))
    return AdapterResult(
        (call,),
        passed,
        None if passed else str(parsed.get("protocol_error") or "protocol_invalid"),
        {
            "existing_protocol_grade": parsed,
            "metric_scope": "protocol_compliance_only",
            "semantic_status": (
                "awaiting_separate_blinded_annotation"
                if cell.payload["attempt"]["stage"] == "hypothesis"
                else "not_a_semantic_hypothesis_judgment"
            ),
        },
    )


def _execute_portfolio(cell: CellDefinition, invoke: InvokeFn) -> AdapterResult:
    from bench.weekly_upgrade_portfolio.graders import grade_task
    from bench.weekly_upgrade_portfolio.runner import _strict_object

    call = invoke(cell.calls[0])
    failure = _first_transport_failure([call])
    payload, parse_error = _strict_object(call.content) if failure is None else (None, failure)
    if parse_error is not None:
        return AdapterResult(
            (call,),
            False,
            parse_error,
            {"existing_grade": None, "parse_error": parse_error},
        )
    grade = grade_task(cell.payload["task"], payload)
    return AdapterResult(
        (call,),
        grade.passed,
        grade.failure_code if not grade.passed else None,
        {"existing_grade": dataclasses.asdict(grade)},
    )


def _execute_diversity(cell: CellDefinition, invoke: InvokeFn) -> AdapterResult:
    from bench.weekly_upgrade_diversity import runner as diversity_runner
    from bench.weekly_upgrade_diversity.graders import grade_set_v1

    task = cell.payload["task"]
    calls: list[CallResult] = []
    diagnostics: list[dict[str, str] | None] = []
    proposal_protocol_valid: list[bool] = []
    if cell.payload["condition"] == "control":
        call = invoke(cell.calls[0])
        calls.append(call)
        proposals, selected, diagnostic, proposal_protocol_valid = (
            diversity_runner._parse_control_v1(task, call.content)
            if call.status == "returned"
            else ([None, None, None], None, {
                "failure_code": f"transport_{call.status}",
                "failure_detail": call.receipt.get("error") or call.status,
            }, [False, False, False])
        )
        diagnostics.append(diagnostic)
    else:
        proposals = []
        for spec in cell.calls[:-1]:
            call = invoke(spec)
            calls.append(call)
            if call.status == "cancelled":
                break
            if call.status == "returned":
                proposal, diagnostic, protocol_valid = diversity_runner._parse_proposal_v1(
                    task, call.content
                )
            else:
                proposal, protocol_valid = None, False
                diagnostic = {
                    "failure_code": f"transport_{call.status}",
                    "failure_detail": call.receipt.get("error") or call.status,
                }
            proposals.append(proposal)
            proposal_protocol_valid.append(protocol_valid)
            diagnostics.append(diagnostic)
        if len(calls) < len(cell.calls) - 1 or calls[-1].status == "cancelled":
            selected = None
        else:
            validator_messages = diversity_runner._validator_messages(
                task, proposals, scaffold_v1=True
            )
            validator = dataclasses.replace(
                cell.calls[-1], messages=tuple(validator_messages)
            )
            call = invoke(validator)
            calls.append(call)
            if call.status == "returned":
                selected, diagnostic = diversity_runner._parse_selection_v1(call.content)
            else:
                selected = None
                diagnostic = {
                    "failure_code": f"transport_{call.status}",
                    "failure_detail": call.receipt.get("error") or call.status,
                }
            diagnostics.append(diagnostic)
    while len(proposals) < 3:
        proposals.append(None)
        proposal_protocol_valid.append(False)
    grade = grade_set_v1(task, proposals, selected)
    transport_failure = _first_transport_failure(calls)
    passed = bool(
        transport_failure is None
        and len(calls) == len(cell.calls)
        and all(diagnostic is None for diagnostic in diagnostics)
        and grade["task_success"]
    )
    failure = None
    if not passed:
        failure = transport_failure or (
            next(
                (diagnostic["failure_code"] for diagnostic in diagnostics if diagnostic),
                None,
            )
            or "substantive_mistake"
        )
    return AdapterResult(
        tuple(calls),
        passed,
        failure,
        {
            "existing_grade": grade,
            "structured_output_diagnostics": diagnostics,
            "proposal_protocol_valid": proposal_protocol_valid,
            "dynamic_validator_messages": cell.payload["condition"] == "diverse_select",
        },
    )


def _effort_step(
    call: CallResult,
    *,
    effort: str,
    retry: bool,
    task: dict[str, Any],
) -> dict[str, Any]:
    from bench.weekly_upgrade_effort.runner import protocol

    payload, protocol_failure = (
        protocol(call.content, task["output_schema"])
        if call.status == "returned"
        else (None, "transport")
    )
    usage = call.receipt.get("usage")
    output_tokens = (
        usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
    )
    return {
        "effort": effort,
        "seed": call.spec.seed,
        "max_tokens": call.spec.max_tokens,
        "request_timeout_s": call.spec.timeout_s,
        "retry": retry,
        "parent_request_id": None,
        "request_id": call.receipt.get("response_id"),
        "output_tokens": output_tokens,
        "completion": call.content,
        "protocol_failure": protocol_failure,
        "needs_review": payload.get("needs_review") if payload else None,
        "runtime_valid": call.status == "returned",
        "runtime_identity": {
            "endpoint_name": call.receipt["endpoint_name"],
            "model": call.receipt["response_model"],
        },
        "status": call.status,
        "duration_s": call.receipt["wall_s"],
    }


def _execute_effort(cell: CellDefinition, invoke: InvokeFn) -> AdapterResult:
    from bench.weekly_upgrade_effort import runner as effort_runner

    task = cell.payload["task"]
    arm = cell.payload["planned"]["arm"]
    calls: list[CallResult] = []
    steps = []
    first = invoke(cell.calls[0])
    calls.append(first)
    first_effort = "xhigh" if first.spec.policy_id == "critic_current" else "medium"
    steps.append(_effort_step(first, effort=first_effort, retry=False, task=task))
    if len(cell.calls) > 1 and first.status != "cancelled":
        next_effort = effort_runner.route(task["role"], arm, steps[-1])
        if next_effort is not None:
            second_spec = cell.calls[1]
            remaining_tokens = max(1, cell.payload["manifest"]["max_tokens"] - steps[0]["output_tokens"])
            second_spec = dataclasses.replace(second_spec, max_tokens=remaining_tokens)
            second = invoke(second_spec)
            calls.append(second)
            steps.append(_effort_step(second, effort=next_effort, retry=True, task=task))
    duration = sum(call.receipt["wall_s"] for call in calls)
    grade = effort_runner.grade_outcome(
        cell.payload["manifest"],
        task,
        cell.payload["planned"],
        steps,
        duration,
    )
    return AdapterResult(
        tuple(calls),
        bool(grade["passed"]),
        None if grade["passed"] else str(grade.get("failure_code") or "substantive_mistake"),
        {
            "existing_grade": grade,
            "conditional_escalation_triggered": len(calls) > 1,
            "gemma_reasoning_effort_supported": not (
                calls and calls[0].receipt["endpoint_name"] == "resident_gemma"
            ),
        },
    )


def _historical_grade(cell: CellDefinition, completion: str | None) -> tuple[bool, str | None, dict[str, Any]]:
    from bench.weekly_upgrade_historical.runner import _parse_patch_completion
    from bench.weekly_upgrade_historical.sandbox import (
        SandboxUnavailable,
        apply_candidate_patch,
        grader_receipt_sha256,
        install_grader,
        materialize_workspace,
        run_grader,
        sandbox_runtime_identity,
    )

    manifest = cell.payload["manifest"]
    task = cell.payload["task"]
    planned = cell.payload["planned"]
    payload, parse_error = _parse_patch_completion(
        completion,
        task["base"]["repair_path"],
        manifest["schema_version"],
    )
    details: dict[str, Any] = {
        "patch_status": "invalid" if parse_error else "not_attempted",
        "patch_error": parse_error,
        "grader": None,
        "grader_receipt_sha256": None,
    }
    if parse_error is not None:
        return False, parse_error, details
    expected_sandbox = manifest["sandbox_runtime"]
    try:
        observed = sandbox_runtime_identity(
            bwrap_path=expected_sandbox["bubblewrap_path"],
            python_path=expected_sandbox["python_path"],
        )
    except SandboxUnavailable:
        return False, "sandbox_runtime_unavailable", details
    if observed != expected_sandbox:
        return False, "sandbox_runtime_drift", {**details, "sandbox_observed": observed}
    with tempfile.TemporaryDirectory(prefix=f"flash-ab-{task['id'].lower()}-") as raw:
        workspace = Path(raw) / "workspace"
        try:
            materialize_workspace(
                task,
                workspace,
                max_archive_bytes=manifest["resource_limits"]["max_workspace_archive_bytes"],
                max_files=manifest["resource_limits"]["max_workspace_files"],
            )
            patch_result = apply_candidate_patch(
                workspace,
                allowed_path=task["base"]["repair_path"],
                patch=payload["patch"],
                max_patch_bytes=manifest["resource_limits"]["max_patch_bytes"],
            )
        except SandboxUnavailable:
            return False, "workspace_unavailable", details
        details.update(
            {
                "patch_status": "valid" if patch_result.valid else "invalid",
                "patch_error": patch_result.code,
                "patch_sha256": patch_result.patch_sha256,
                "patch_bytes": patch_result.patch_bytes,
                "repaired_file_sha256": patch_result.repaired_file_sha256,
            }
        )
        if not patch_result.valid:
            return False, patch_result.code or "invalid_patch", details
        try:
            install_grader(task, workspace)
            grade = run_grader(
                task,
                workspace,
                bwrap_path=expected_sandbox["bubblewrap_path"],
                python_path=expected_sandbox["python_path"],
                timeout_s=task["grader_timeout_s"],
                max_output_bytes=manifest["resource_limits"]["max_grader_output_bytes"],
            )
        except SandboxUnavailable:
            return False, "grader_unavailable", details
        details["grader"] = dataclasses.asdict(grade)
        details["grader_receipt_sha256"] = grader_receipt_sha256(
            attempt_id=planned["attempt_id"],
            input_sha256=planned["input_sha256"],
            patch_sha256=patch_result.patch_sha256,
            grader_sha256=planned["grader_sha256"],
            sandbox_identity=expected_sandbox,
            result=grade,
        )
        return grade.passed, None if grade.passed else "grader_failed", details


def _execute_historical(cell: CellDefinition, invoke: InvokeFn) -> AdapterResult:
    call = invoke(cell.calls[0])
    failure = _first_transport_failure([call])
    if failure is not None:
        return AdapterResult((call,), False, failure, {"existing_grade": None})
    passed, failure, details = _historical_grade(cell, call.content)
    return AdapterResult((call,), passed, failure, {"existing_grade": details})


def execute_cell(cell: CellDefinition, invoke: InvokeFn) -> AdapterResult:
    """Execute one definition through its existing parser/objective grader."""
    kind = cell.payload["kind"]
    if kind == "objective":
        return _execute_objective(cell, invoke)
    if kind == "topic":
        return _execute_topic(cell, invoke)
    if kind == "portfolio":
        return _execute_portfolio(cell, invoke)
    if kind == "diversity":
        return _execute_diversity(cell, invoke)
    if kind == "role_effort":
        return _execute_effort(cell, invoke)
    if kind == "historical":
        return _execute_historical(cell, invoke)
    raise ValueError(f"unsupported adapter payload kind {kind!r}")


__all__ = [
    "ADAPTER_SOURCE",
    "FAMILIES",
    "AdapterResult",
    "CallResult",
    "CallSpec",
    "CellDefinition",
    "execute_cell",
    "load_cells",
]
