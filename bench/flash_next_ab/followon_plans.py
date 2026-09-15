"""Distinct plans for the existing Flash and resident supervisors.

The old portfolio planner and source tuple remain pinned to the first pair's
checkout. This module reuses their exact qualified C0/resident receipts, then
binds a different follow-on window, output namespace and controller checkout.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.flash_next_ab import evaluation_window as ew
from bench.flash_next_ab import followon_dispatch as grouped
from bench.flash_next_ab import resident_evaluation_window as resident

FLASH_PLAN_SCHEMA = "flash-followon-flash-plan/v1"
V5_FLASH_PLAN_SCHEMA = "flash-followon-flash-plan/v2"
RESIDENT_PLAN_SCHEMA = "flash-followon-resident-plan/v1"
REGISTERED_CONTEXT_CAPS = {
    "resident_qwen": 16_384,
    "resident_gemma": 32_768,
}


class FollowonPlanError(ValueError):
    pass


@dataclass(frozen=True)
class FollowonExecution:
    frozen: grouped.FrozenWindow
    parent: ew.FrozenEvaluationWindow
    v5_parent: Any | None = None

    @property
    def document(self) -> dict:
        return self.frozen.document

    @property
    def source_path(self) -> Path:
        return self.frozen.path

    @property
    def source_sha256(self) -> str:
        return self.frozen.raw_sha256

    @property
    def pair_id(self) -> str:
        # Reuse existing sentinel/usage field names only within distinct
        # follow-on result schemas. This is a window ID, not an A/B pair.
        return self.document["window_id"]

    @property
    def cohort(self) -> str:
        return self.document["cohort"]

    @property
    def runtime_budget_seconds(self) -> int:
        return self.document["block_budget_total_seconds"]

    @property
    def qualification_summary(self) -> dict:
        return (self.v5_parent.qualification_summary if self.v5_parent is not None
                else self.parent.qualification_summary)

    @property
    def qualification_plan(self) -> dict | None:
        return (self.v5_parent.qualification_plan if self.v5_parent is not None
                else self.parent.qualification_plan)

    @property
    def benchmark_plan(self) -> dict:
        # Only q's pre-existing qualification plan adapter reads this; the
        # follow-on post-probe branch never invokes the portfolio harness.
        return self.parent.benchmark_plan

    @property
    def benchmark_plan_file_sha256(self) -> str:
        return self.parent.benchmark_plan_file_sha256


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise FollowonPlanError(reason)


def _expected_output(window: FollowonExecution, output: Path,
                     *, must_be_absent: bool) -> Path:
    expected = grouped._output_path(
        window.pair_id, window.cohort, grouped.RESEARCH_ROOT
    )
    _require(output == expected and output.parent.is_dir()
             and not output.parent.is_symlink()
             and output.parent.resolve() == output.parent
             and (not must_be_absent or not output.exists())
             and (not output.exists() or
                  output.is_dir() and not output.is_symlink()
                  and output.resolve() == output),
             "follow-on output differs from its registered direct child")
    return output


def _launcher() -> str:
    launcher = grouped.FOLLOWON_CODE_ROOT / ".venv-chroma/bin/python"
    _require(launcher.is_file() and not launcher.is_dir()
             and launcher.resolve() == Path("/usr/bin/python3.12"),
             "follow-on local Python launcher changed")
    return str(launcher)


def load_execution(source_path: Path, *, cohort: str) -> FollowonExecution:
    source = Path(source_path).absolute()
    suffix = f".{cohort}.json"
    _require(source.parent == grouped.RESEARCH_ROOT /
             "evaluation/followon-window-plans"
             and source.name.endswith(suffix),
             "follow-on source is outside the registered namespace")
    window_id = source.name[: -len(suffix)]
    frozen = grouped.load_window(window_id, cohort)
    _require(frozen.path == source, "follow-on source changed path")
    binding = frozen.document["qualified_parent_window"]
    parent = ew.load_evaluation_window(
        binding["path"], expected_cohort=cohort
    )
    _require(parent.source_sha256 == binding["sha256"],
             "qualified parent source raw bytes changed")
    summary = parent.qualification_summary
    v5_parent = None
    if frozen.document["schema_version"] == grouped.V5_WINDOW_SCHEMA:
        from .followon_v5_parent import load_parent

        v5_ref = frozen.document["v5_qualified_parent"]
        v5_parent = load_parent(Path(v5_ref["path"]))
        _require(v5_parent.source_sha256 == v5_ref["sha256"]
                 and cohort == "flash",
                 "v5 qualification source differs from the grouped window")
        summary = v5_parent.qualification_summary
    routes = frozen.document["route_bindings"]
    if cohort == "flash":
        selected = next(iter(routes.values()))
        qualified_plan = (v5_parent.qualification_plan if v5_parent is not None
                          else parent.qualification_plan)
        qualified_argv = (qualified_plan.get("docker_create_argv")
                          if isinstance(qualified_plan, dict) else None)
        _require(isinstance(qualified_argv, list)
                 and qualified_argv.count("--max-model-len") == 1,
                 "qualified Flash launch has no unique context ceiling")
        cap_index = qualified_argv.index("--max-model-len") + 1
        expected_cap = (v5_parent.spec.max_model_len if v5_parent is not None
                        else 32768)
        _require(cap_index < len(qualified_argv)
                 and qualified_argv[cap_index] == str(expected_cap)
                 and selected["max_model_len"] == expected_cap,
                 "frozen Flash route context differs from qualified launch")
        _require(summary.get("admission_eligible") is True
                 and summary.get("variant_id")
                    == frozen.document["candidate_variant_id"]
                 and selected["served_model"] == summary.get("served_model")
                 and selected["artifact_sha256"]
                    == summary.get("model_artifact_sha256")
                 and selected["runtime_sha256"]
                    == summary.get("runtime_sha256")
                 and selected["qualification_receipt_sha256"]
                    == summary.get("qualification_receipt_sha256"),
                 "Flash follow-on route differs from the prior qualified C0")
    else:
        _require(summary.get("admission_eligible") is True
                 and all(routes[endpoint]["max_model_len"] == cap
                         for endpoint, cap in REGISTERED_CONTEXT_CAPS.items())
                 and all(
                     route["artifact_sha256"]
                         == summary["artifact_sha256_by_endpoint"][endpoint]
                     and route["runtime_sha256"]
                         == summary["runtime_sha256_by_endpoint"][endpoint]
                     and route["qualification_receipt_sha256"]
                         == summary["qualification_receipt_sha256"]
                     for endpoint, route in routes.items()
                 ),
                 "resident follow-on routes differ from fixed incumbent receipts")
    return FollowonExecution(frozen, parent, v5_parent)


def flash_plan(window: FollowonExecution, output: Path,
               *, must_be_absent: bool = False) -> dict[str, Any]:
    _require(window.cohort == "flash", "follow-on Flash plan requires Flash cohort")
    output = _expected_output(window, output, must_be_absent=must_be_absent)
    original_output = (ew.WINDOW_RUN_ROOT /
                       f"{window.parent.pair_id}.flash")
    base = ew.build_extended_evaluation_plan(window.parent, original_output)
    route = next(iter(window.document["route_bindings"].values()))
    bundle = grouped.frozen_followon_source_bundle()
    _require(bundle == window.document["followon_source_bundle"],
             "follow-on Flash plan does not bind the prior C0/source tuple")
    if window.v5_parent is None:
        _require(base["candidate_variant_id"]
                     == window.document["candidate_variant_id"]
                 and base["model_artifact_sha256"] == route["artifact_sha256"]
                 and base["runtime_sha256"] == route["runtime_sha256"]
                 and base["served_model"] == route["served_model"]
                 and base["prior_qualification_receipt_sha256"]
                     == route["qualification_receipt_sha256"],
                 "C0 follow-on route differs from the qualified parent")
    plan = copy.deepcopy(base)
    plan.update(
        schema_version=(V5_FLASH_PLAN_SCHEMA if window.v5_parent is not None
                        else FLASH_PLAN_SCHEMA),
        evaluation_kind="followon",
        pair_id=window.pair_id,
        output_dir=str(output),
        window_plan_path=str(window.source_path),
        window_plan_sha256=window.source_sha256,
        benchmark_runtime_budget_seconds=window.runtime_budget_seconds,
        launcher_python_path=_launcher(),
        controller_source_bundle=bundle,
        controller_source_bundle_sha256=grouped._canonical_sha(bundle),
        qualified_parent_window=window.document["qualified_parent_window"],
        registered_code_root=str(grouped.FOLLOWON_CODE_ROOT),
        followon_blocks=copy.deepcopy(window.document["blocks"]),
        followon_block_budget_total_seconds=window.runtime_budget_seconds,
        weekly_budget_debit=False,
        paid_api_allowed=False,
        production_change_authorized=False,
    )
    if window.v5_parent is not None:
        from . import qualification as q

        spec = window.v5_parent.spec
        summary = window.v5_parent.qualification_summary
        qualified = window.v5_parent.qualification_plan
        _require(summary["admission_eligible"] is True
                 and summary["variant_id"] == spec.spec_id
                 and window.document["candidate_variant_id"] == spec.spec_id
                 and route["qualification_receipt_sha256"]
                    == summary["qualification_receipt_sha256"],
                 "v5 follow-on selected an unadmitted profile")
        plan.update(
            candidate_variant_id=spec.spec_id,
            candidate_spec_sha256=spec.identity_sha256(),
            contract_sha256=summary["contract_sha256"],
            runtime_sha256=summary["runtime_sha256"],
            model_artifact_sha256=summary["model_artifact_sha256"],
            served_model=summary["served_model"],
            image_id=spec.image_id,
            docker_create_argv=copy.deepcopy(qualified["docker_create_argv"]),
            docker_create_argv_sha256=qualified["docker_create_argv_sha256"],
            probe_set=qualified["probe_set"],
            prior_qualification_receipt_sha256=summary[
                "qualification_receipt_sha256"],
            prior_qualification_plan_sha256=summary[
                "qualification_plan_sha256"],
            paging_policy=copy.deepcopy(spec.paging_policy()),
            v5_qualified_parent=copy.deepcopy(window.document["v5_qualified_parent"]),
        )
        _require(plan["candidate_spec_sha256"] == spec.identity_sha256()
                 and plan["docker_create_argv"] == spec.launch_argv(
                     compilation_config=q.COMPILATION_CONFIG,
                 ),
                 "v5 follow-on launch is not the literal qualified argv")
    _require(plan["effective_invocation_deadline_seconds"] == 14_400
             and plan["restoration_reserve_seconds"] == 600,
             "follow-on Flash plan has a different lifecycle ceiling")
    return plan


def resident_plan(window: FollowonExecution, output: Path,
                  *, must_be_absent: bool = False) -> dict[str, Any]:
    _require(window.cohort == "resident",
             "follow-on resident plan requires resident cohort")
    output = _expected_output(window, output, must_be_absent=must_be_absent)
    original_output = (resident.WINDOW_RUN_ROOT /
                       f"{window.parent.pair_id}.resident")
    base = resident._resident_plan(window.parent, original_output)
    bundle = grouped.frozen_followon_source_bundle()
    _require(bundle == window.document["followon_source_bundle"],
             "follow-on resident code tuple differs")
    sentinel = resident._sentinel_command(window.pair_id)
    plan = copy.deepcopy(base)
    plan.update(
        schema=RESIDENT_PLAN_SCHEMA,
        evaluation_kind="followon",
        pair_id=window.pair_id,
        output_dir=str(output),
        window_plan_path=str(window.source_path),
        window_plan_sha256=window.source_sha256,
        benchmark_runtime_budget_seconds=window.runtime_budget_seconds,
        watchdog_sentinel_name=resident._sentinel_name(window.pair_id),
        watchdog_sentinel_create_argv=sentinel,
        watchdog_sentinel_create_argv_sha256=resident.sha256(sentinel),
        launcher_python_path=_launcher(),
        controller_source_bundle=bundle,
        controller_source_bundle_sha256=grouped._canonical_sha(bundle),
        qualified_parent_window=window.document["qualified_parent_window"],
        registered_code_root=str(grouped.FOLLOWON_CODE_ROOT),
        followon_blocks=copy.deepcopy(window.document["blocks"]),
        followon_block_budget_total_seconds=window.runtime_budget_seconds,
        weekly_budget_debit=False,
        paid_api_allowed=False,
        production_change_authorized=False,
    )
    _require(plan["effective_invocation_deadline_seconds"] == 14_400
             and plan["verification_reserve_seconds"] == 600,
             "follow-on resident plan has a different lifecycle ceiling")
    return plan
