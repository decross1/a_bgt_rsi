"""Frozen v2 engineering panel, plan, local tools and independent final grading."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import re
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from typing import Any

from experiments.payoff_action_calculator import calculator
from experiments.payoff_action_calibration import runner as legacy
from experiments.payoff_tool_arithmetic import flash_resident as resident

from . import contract

CODE_ROOT = Path(__file__).resolve().parents[2]
PLAN_SCHEMA = "flash-payoff-action-calibration-plan/v2"
RUN_SCHEMA = "flash-payoff-action-calibration-run/v2"
PRIVATE_SCHEMA = "flash-payoff-action-calibration-private-call/v2"
VALIDATION_SCHEMA = "flash-payoff-action-calibration-validation/v2"
PROTOCOL_SCHEMA = "flash-payoff-action-calibration-private-protocol/v2"
CONTINUATION_POLICY = contract.CONTINUATION_POLICY
POLICY_ID = "calibration_v2_deterministic_no_thinking"
POLICY = {"temperature": 0, "top_p": 1, "top_k": 64, "enable_thinking": False}
MAX_TOKENS = 512
CALL_TIMEOUT_S = 30.0
EVALUATOR_BUDGET_S = 900.0
MEMORY_FLOOR_GIB = 20.0
UNITS, CONDITIONS, MAX_CALLS = 4, 12, 20
CLAIM_LIMIT = (
    "permanently excluded v2 engineering shakedown; no confirmation, admission, "
    "L2, model-quality, strategy-generalization, or market claim"
)
FINAL_INSTRUCTION = {
    "role": "user",
    "content": "Use the exact tool result. Return only the required bare JSON.",
}
SOURCE_PATHS = tuple(
    dict.fromkeys(
        (
            *legacy.SOURCE_PATHS,
            *(
                "experiments/payoff_action_calibration_v2/" + name
                for name in (
                    "__init__.py",
                    "__main__.py",
                    "contract.py",
                    "design.py",
                    "wire.py",
                    "runner.py",
                    "replay.py",
                )
            ),
        )
    )
)


class CalibrationError(ValueError):
    """The v2 design or its evidence has failed an explicit integrity check."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CalibrationError(reason)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sources() -> dict[str, str]:
    return {name: sha((CODE_ROOT / name).read_bytes()) for name in SOURCE_PATHS}


def panel() -> list[dict[str, Any]]:
    """New parameters/identities; legacy mechanisms, never legacy outcomes."""
    rows = []
    for index, original in enumerate(legacy._RAW_CELLS):
        cell = copy.deepcopy(original)
        cell.pop("task_sha256")
        cell["cell_id"] = f"excluded-native-tool-v2-{index + 1:02d}"
        cell["endowment"] = (22, 26, 30, 34)[index]
        cell["task_sha256"] = sha(canonical(cell))
        multiplier = Fraction(cell["multiplier"])
        cell.update(
            m_num=multiplier.numerator,
            m_den=multiplier.denominator,
            seed=2_026_092_200 + index,
            arm_order=list(legacy._ARM_ORDERS[index]),
        )
        cell["calculator_input"] = legacy._calculator_input(cell)
        cell["expected_probe"] = calculator.calculate(cell["calculator_input"])
        optimal, count, actions = legacy._oracle(cell)
        exhaustive = [
            (legacy._simulate(cell, seq), seq)
            for seq in itertools.product((0, 1), repeat=cell["horizon"])
        ]
        maximum = max(value for value, _ in exhaustive)
        winners = sorted(seq for value, seq in exhaustive if value == maximum)
        myopic = legacy._myopic(cell)
        myopic_value = legacy._simulate(cell, myopic)
        dependent = legacy._future_dependent_rounds(cell, actions)
        require(
            optimal == maximum
            and count == len(winners) == 1
            and actions == winners[0]
            and optimal > myopic_value
            and bool(dependent),
            "v2 cell controls are not uniquely future-dependent",
        )
        cell["controls"] = {
            "oracle_plan": list(actions),
            "oracle_plan_sha256": sha(canonical(list(actions))),
            "oracle_utility": legacy._rational(optimal),
            "myopic_plan": list(myopic),
            "myopic_utility": legacy._rational(myopic_value),
            "myopic_regret": legacy._rational(optimal - myopic_value),
            "future_dependent_rounds_1_indexed": dependent,
            "exhaustive_sequences": 2 ** cell["horizon"],
            "dp_matches_exhaustive": True,
        }
        rows.append(cell)
    require(
        len(rows) == UNITS and len({c["task_sha256"] for c in rows}) == UNITS,
        "v2 unit identities drifted",
    )
    require(
        not {c["endowment"] for c in rows}.intersection(
            {4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 20}
        ),
        "v2 panel overlaps known prior endowments",
    )
    prior_hashes = set(legacy._DEVELOPMENTAL_PRIMARY_TASK_HASHES)
    prior_hashes.update(c["task_sha256"] for c in legacy._RAW_CELLS)
    prior_hashes.update(
        c["task_sha256"]
        for cohort in ("shakedown", "confirmatory")
        for c in legacy.assistance.panel(cohort)
    )
    require(
        not {c["task_sha256"] for c in rows}.intersection(prior_hashes),
        "v2 task hashes overlap a prior panel",
    )
    return rows


def messages(cell: dict, arm: str) -> list[dict]:
    return legacy._messages(cell, arm)


def tool_spec(arm: str) -> dict:
    require(arm in {"table", "calculator"}, "unsupported tool arm")
    return copy.deepcopy(legacy._tool_spec(arm))


def expectation(cell: dict, arm: str) -> contract.ToolExpectation:
    return contract.ToolExpectation(
        tool_spec(arm)["function"]["name"], arm, legacy._tool_arguments(cell, arm)
    )


def _table_arguments_valid(arguments: Any) -> bool:
    return (
        type(arguments) is dict
        and set(arguments) == {"E", "m_num", "m_den", "players"}
        and all(type(v) is int for v in arguments.values())
        and arguments["players"] == 4
        and all(arguments[k] > 0 for k in ("E", "m_num", "m_den"))
    )


def table_executor(arguments: dict) -> dict:
    """Compute from accepted parsed arguments, never from a scenario shortcut."""
    require(_table_arguments_valid(arguments), "table arguments invalid")
    return legacy.assistance._tool_payload(
        {
            "endowment": arguments["E"],
            "m_num": arguments["m_num"],
            "m_den": arguments["m_den"],
        }
    )


def table_result_valid(result: Any, arguments: dict) -> bool:
    """Schema/internal consistency only; no second executor invocation."""
    if (
        not _table_arguments_valid(arguments)
        or type(result) is not dict
        or set(result) != {"formula", "rows", "strategy_or_recommendation_included"}
    ):
        return False
    formula = {
        "k": "other_contributors+focal_action",
        "shared_per_player": "m*E*(other_contributors+focal_action)/4",
        "focal_payoff": "E*(1-focal_action)+shared_per_player",
        "group_payoff": "E*(4-k)+4*shared_per_player",
    }
    rows = result["rows"]
    if (
        result["formula"] != formula
        or result["strategy_or_recommendation_included"] is not False
        or type(rows) is not list
        or len(rows) != 8
    ):
        return False
    for row, (others, action) in zip(
        rows, itertools.product(range(4), (0, 1)), strict=True
    ):
        if type(row) is not dict or set(row) != {
            "other_contributors",
            "focal_action",
            "shared_per_player",
            "focal_payoff",
            "group_payoff",
        }:
            return False
        if (
            type(row["other_contributors"]) is not int
            or type(row["focal_action"]) is not int
            or row["other_contributors"] != others
            or row["focal_action"] != action
        ):
            return False
        try:
            values = [
                row[k] for k in ("shared_per_player", "focal_payoff", "group_payoff")
            ]
            if not all(
                type(v) is str
                and len(v) <= 128
                and re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?", v)
                for v in values
            ):
                return False
            shared, focal, group = map(Fraction, values)
            if any(
                legacy._rational(v) != s
                for v, s in zip((shared, focal, group), values, strict=True)
            ):
                return False
            if (
                shared
                != Fraction(arguments["m_num"], arguments["m_den"])
                * arguments["E"]
                * (others + action)
                / 4
                or focal != arguments["E"] * (1 - action) + shared
                or group != arguments["E"] * (4 - others - action) + 4 * shared
            ):
                return False
        except (ValueError, ZeroDivisionError, TypeError):
            return False
    return True


def executor_for(arm: str):
    require(arm in {"table", "calculator"}, "unsupported tool executor")
    return table_executor if arm == "table" else calculator.calculate


def result_validator_for(arm: str):
    require(arm in {"table", "calculator"}, "unsupported result validator")
    return (
        table_result_valid
        if arm == "table"
        else contract.calculator_result_contract_valid
    )


def _probe_representation_valid(text: str) -> bool:
    try:
        probe = calculator._load_json_exact(text)["probe"]
        return (
            type(probe["formula_version"]) is str
            and type(probe["evaluated_joint_action"]) is list
            and len(probe["evaluated_joint_action"]) == 4
            and all(
                type(v) is int and v in (0, 1) for v in probe["evaluated_joint_action"]
            )
            and all(
                type(probe[k]) is int and 0 <= probe[k] <= ceiling
                for k, ceiling in (
                    ("focal_seat", 3),
                    ("contributor_count", 4),
                    ("other_contributor_count", 3),
                    ("focal_action", 1),
                )
            )
            and probe["strategy_advice_included"] is False
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def final_grade(
    content: Any, status: str, receipt: Any, tool_calls: Any, cell: dict
) -> dict:
    diagnostic: dict = {}

    def assess(text: str) -> contract.FinalContentAssessment:
        scored = legacy._grade_final(
            text, "returned", cell, finish_reason="stop", tool_calls=[]
        )
        score = scored["response_score"]
        # Shape/representation is distinct from arithmetic/strategic correctness.
        valid = all(
            score[key]
            for key in (
                "json_valid",
                "field_valid",
                "numeric_representation_valid",
                "action_scoreable",
            )
        ) and _probe_representation_valid(text)
        correct = (
            valid
            and score["probe_binding_valid"]
            and score["contributor_counts_correct"]
            and score["exact_arithmetic"]
            and scored["zero_regret"]
        )
        diagnostic.update(scored)
        strategy_failure = (
            ("strategy_suboptimal",)
            if score["action_scoreable"] and not scored["zero_regret"]
            else ()
        )
        return contract.FinalContentAssessment(
            bool(valid),
            bool(correct),
            tuple(score["failure_codes"])
            + strategy_failure
            + (
                ("probe_representation_invalid",)
                if score["field_valid"] and not _probe_representation_valid(text)
                else ()
            ),
        )

    grade = contract.grade_final_turn(
        status=status,
        receipt=receipt,
        tool_calls=tool_calls,
        content=content,
        content_grader=assess,
    )
    if diagnostic:
        diagnostic["response_score"].pop("actions", None)
        # The old strict flag bundles arithmetic into validity: do not export it
        # as the v2 terminal contract or primary success flag.
        diagnostic.pop("final_accepted", None)
    return json.loads(canonical({"contract": asdict(grade), "diagnostic": diagnostic}))


def _plan(study_id: str, runtime: dict, root: Path) -> dict:
    rows = panel()
    return {
        "schema_version": PLAN_SCHEMA,
        "study_id": study_id,
        "cohort": "permanently_excluded_v2_shakedown",
        "code_root": str(CODE_ROOT),
        "runtime_binding": runtime,
        "source_sha256": sources(),
        "core_contract": contract.CONTRACT_VERSION,
        "continuation_policy": CONTINUATION_POLICY,
        "scenarios": rows,
        "panel_sha256": sha(canonical(rows)),
        "declared_units": [c["cell_id"] for c in rows],
        "declared_conditions": [
            f"{c['cell_id']}/{arm}" for c in rows for arm in c["arm_order"]
        ],
        "declared_slots": legacy._declared_slots(rows),
        "policy_id": POLICY_ID,
        "policy": copy.deepcopy(POLICY),
        "tool_specs": {arm: tool_spec(arm) for arm in ("table", "calculator")},
        "limits": {
            "max_tokens": MAX_TOKENS,
            "call_timeout_s": CALL_TIMEOUT_S,
            "evaluator_budget_s": EVALUATOR_BUDGET_S,
            "memory_floor_gib": MEMORY_FLOOR_GIB,
            "max_units": UNITS,
            "conditions": CONDITIONS,
            "max_calls": MAX_CALLS,
        },
        "unit_contract": {
            "unit": "distinct_scenario_paired_across_three_arms",
            "count": UNITS,
            "requests_are_units": False,
            "rounds_are_units": False,
            "iid_population_claim": False,
            "pooled_with_any_study": False,
        },
        "coordination": {
            "mode": "exclusive_nonblocking_once",
            "cooperative_exclusion_only": True,
            "direct_http_clients_excluded": False,
            "isolated_latency_claim": False,
        },
        "budget": {
            "weekly_two_hour_debit": False,
            "authorization": "owner-authorized-current-local-research-session",
        },
        "artifact_policy": {
            "private_root": str(root),
            "outside_git_required": True,
            "directory_mode": "0700",
        },
        "claim_limit": CLAIM_LIMIT,
        "permanently_excluded": True,
        "scientific_admission_eligible": False,
        "scientific_admission_registered": False,
        "confirmation_authorized": False,
        "production_change_authorized": False,
        "promotion_authorized": False,
    }


def make_plan(
    plan_path: str | Path,
    *,
    study_id: str,
    artifact_root: str | Path,
    runtime_snapshot_fn=resident._live_runtime_binding,
    ready_fn=resident._ready,
    memory_fn=resident._available_gib,
) -> dict:
    require(
        isinstance(study_id, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", study_id) is not None,
        "study ID is malformed",
    )
    runtime = runtime_snapshot_fn()
    resident._validate_runtime_binding(runtime)
    require(ready_fn() is True, "resident Flash is not ready")
    memory = float(memory_fn())
    require(
        math.isfinite(memory) and memory >= MEMORY_FLOOR_GIB,
        "20 GiB memory floor unavailable",
    )
    root = Path(artifact_root).resolve(strict=False)
    path = resident._artifact_path(Path(plan_path), root, label="v2 shakedown plan")
    value = _plan(study_id, runtime, root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
    path.chmod(0o600)
    return value


def load_plan(plan_path: str | Path) -> tuple[dict, str]:
    value, raw = resident._read_object(
        Path(plan_path), label="v2 shakedown plan", ceiling=6_000_000
    )
    require(value.get("schema_version") == PLAN_SCHEMA, "not a v2 plan")
    artifact_policy = value.get("artifact_policy")
    require(type(artifact_policy) is dict, "invalid private artifact policy")
    root = artifact_policy.get("private_root")
    require(
        isinstance(root, str) and Path(root).is_absolute(),
        "invalid private artifact root",
    )
    resident._artifact_path(Path(plan_path), Path(root), label="v2 shakedown plan")
    study_id = value.get("study_id")
    require(
        isinstance(study_id, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", study_id) is not None,
        "study ID is malformed",
    )
    resident._validate_runtime_binding(value.get("runtime_binding"))
    expected = _plan(study_id, value["runtime_binding"], Path(root))
    require(
        canonical(value) == canonical(expected),
        "v2 plan/source/denominator/authority drift",
    )
    return value, sha(raw)
