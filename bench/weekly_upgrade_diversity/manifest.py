"""Strict frozen-manifest loader for the Gemma diversity experiment."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

from .graders import grade_proposal

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "experiments" / "diversity_selection_dev_v0_2026-09-14.json"
SCHEMA_VERSION = "weekly-upgrade-diversity-selection/v1"
TASK_IDS = (
    "DIV-GT-PURE-NASH-001",
    "DIV-D075-BALLOT-001",
    "DIV-D075-DELEGATION-001",
    "DIV-GT-COORDINATION-001",
    "DIV-GT-COALITION-001",
)
GRADER_KINDS = {
    "pure_nash",
    "ballot_counterexample",
    "delegation_graph",
    "coordination_matrix",
    "minimal_winning_coalition",
}


class ManifestError(ValueError):
    """The frozen experiment description is ambiguous or has drifted."""


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"not canonical finite JSON: {exc}") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _keys(value: Any, expected: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise ManifestError(f"{where} fields differ: {actual}")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where} must be non-empty text")
    return value


def _integer(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ManifestError(f"{where} must be an integer >= {minimum}")
    return value


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{where} must be finite")
    number = float(value)
    if not math.isfinite(number):
        raise ManifestError(f"{where} must be finite")
    return number


def _candidate_space(task: dict[str, Any]):
    inputs = task["grader"]["inputs"]
    kind = task["grader"]["kind"]
    if kind == "pure_nash":
        for row, column in itertools.product(inputs["actions"], repeat=2):
            yield {"row_action": row, "column_action": column}
    elif kind == "ballot_counterexample":
        rankings = inputs["rankings"]
        for values in itertools.product(range(inputs["voters"] + 1), repeat=len(rankings)):
            if sum(values) == inputs["voters"]:
                yield dict(zip(rankings, values, strict=True))
    elif kind == "delegation_graph":
        for values in itertools.product(inputs["allowed_values"], repeat=len(inputs["voters"])):
            yield dict(zip(inputs["voters"], values, strict=True))
    elif kind == "coordination_matrix":
        for values in itertools.product(inputs["allowed_payoffs"], repeat=4):
            yield dict(zip(("a", "b", "c", "d"), values, strict=True))
    elif kind == "minimal_winning_coalition":
        players = list(inputs["weights"])
        for size in range(1, len(players) + 1):
            for coalition in itertools.combinations(players, size):
                yield {"coalition": list(coalition)}


def _validate_inputs(kind: str, inputs: Any, where: str) -> None:
    keys = {
        "pure_nash": {"actions", "row_payoffs", "column_payoffs"},
        "ballot_counterexample": {
            "candidates",
            "rankings",
            "voters",
            "target_plurality",
            "target_condorcet",
        },
        "delegation_graph": {
            "voters",
            "allowed_values",
            "target_totals",
            "target_exhausted",
        },
        "coordination_matrix": {"allowed_payoffs", "target_mixed_probability"},
        "minimal_winning_coalition": {"weights", "quota"},
    }
    row = _keys(inputs, keys[kind], where)
    canonical_json(row)
    if kind == "pure_nash":
        actions = row["actions"]
        if (
            not isinstance(actions, list)
            or len(actions) != 2
            or any(not isinstance(action, str) for action in actions)
            or len(set(actions)) != 2
        ):
            raise ManifestError(f"{where}.actions must have two unique strings")
        for name in ("row_payoffs", "column_payoffs"):
            matrix = row[name]
            if (
                not isinstance(matrix, list)
                or len(matrix) != 2
                or any(not isinstance(line, list) or len(line) != 2 for line in matrix)
            ):
                raise ManifestError(f"{where}.{name} must be 2x2")
            for line in matrix:
                for value in line:
                    _number(value, f"{where}.{name}")
    elif kind == "ballot_counterexample":
        candidates, rankings = row["candidates"], row["rankings"]
        voters = _integer(row["voters"], f"{where}.voters", minimum=1)
        if voters > 9:
            raise ManifestError(f"{where}.voters exceeds finite validation bound")
        if (
            not isinstance(candidates, list)
            or not 2 <= len(candidates) <= 4
            or any(not isinstance(value, str) for value in candidates)
            or len(set(candidates)) != len(candidates)
            or not isinstance(rankings, list)
            or not 2 <= len(rankings) <= 8
            or any(
                not isinstance(ranking, str)
                or len(ranking) != len(candidates)
                or set(ranking) != set(candidates)
                for ranking in rankings
            )
            or len(set(rankings)) != len(rankings)
        ):
            raise ManifestError(f"{where} has invalid finite rankings")
        if row["target_plurality"] not in candidates or row["target_condorcet"] not in candidates:
            raise ManifestError(f"{where} target candidate is unknown")
    elif kind == "delegation_graph":
        voters, values = row["voters"], row["allowed_values"]
        if (
            not isinstance(voters, list)
            or not 1 <= len(voters) <= 5
            or any(not isinstance(value, str) for value in voters)
            or len(set(voters)) != len(voters)
            or not isinstance(values, list)
            or not 2 <= len(values) <= 8
            or any(not isinstance(value, str) for value in values)
            or len(set(values)) != len(values)
        ):
            raise ManifestError(f"{where} has an invalid finite delegation domain")
        totals = _keys(row["target_totals"], {"A", "B"}, f"{where}.target_totals")
        for value in totals.values():
            _integer(value, f"{where}.target_totals")
        if (
            not isinstance(row["target_exhausted"], list)
            or any(
                not isinstance(value, str) or value not in voters
                for value in row["target_exhausted"]
            )
            or len(row["target_exhausted"]) != len(set(row["target_exhausted"]))
        ):
            raise ManifestError(f"{where}.target_exhausted must be an array")
    elif kind == "coordination_matrix":
        values = row["allowed_payoffs"]
        if not isinstance(values, list) or not 2 <= len(values) <= 8:
            raise ManifestError(f"{where}.allowed_payoffs is invalid")
        for value in values:
            _integer(value, f"{where}.allowed_payoffs")
        if len(set(values)) != len(values):
            raise ManifestError(f"{where}.allowed_payoffs contains duplicates")
        _number(row["target_mixed_probability"], f"{where}.target_mixed_probability")
    else:
        weights = row["weights"]
        if (
            not isinstance(weights, dict)
            or not 2 <= len(weights) <= 8
            or any(not isinstance(player, str) or not player for player in weights)
        ):
            raise ManifestError(f"{where}.weights is invalid")
        for value in weights.values():
            _integer(value, f"{where}.weights", minimum=1)
        _integer(row["quota"], f"{where}.quota", minimum=1)


def _validate_task(task: Any, index: int) -> None:
    row = _keys(
        task,
        {"id", "family", "problem", "proposal_contract", "grader", "provenance"},
        f"tasks[{index}]",
    )
    for key in ("id", "family", "problem", "proposal_contract"):
        _text(row[key], f"tasks[{index}].{key}")
    if row["family"] not in {"game_theory", "collective_choice"}:
        raise ManifestError(f"tasks[{index}].family is invalid")
    grader = _keys(row["grader"], {"kind", "version", "inputs"}, f"tasks[{index}].grader")
    if grader["kind"] not in GRADER_KINDS or grader["version"] != "1":
        raise ManifestError(f"tasks[{index}].grader is unsupported")
    _validate_inputs(grader["kind"], grader["inputs"], f"tasks[{index}].grader.inputs")
    provenance = _keys(
        row["provenance"],
        {"origin", "derivation", "source_refs", "claim_limit"},
        f"tasks[{index}].provenance",
    )
    if provenance["origin"] != "synthetic_authored_for_eval":
        raise ManifestError(f"tasks[{index}] is not labeled synthetic")
    for key in ("derivation", "claim_limit"):
        _text(provenance[key], f"tasks[{index}].provenance.{key}")
    if (
        not isinstance(provenance["source_refs"], list)
        or not provenance["source_refs"]
        or any(not isinstance(ref, str) or not ref.strip() for ref in provenance["source_refs"])
    ):
        raise ManifestError(f"tasks[{index}].provenance.source_refs is empty")
    valid_count = sum(grade_proposal(row, proposal).valid for proposal in _candidate_space(row))
    if valid_count < 2:
        raise ManifestError(f"tasks[{index}] does not have multiple enumerable solutions")


def validate_manifest(document: Any) -> None:
    manifest = _keys(
        document,
        {
            "schema_version",
            "suite_id",
            "description",
            "publication_class",
            "claim_limits",
            "model",
            "conditions",
            "ordering",
            "tasks",
            "resource_limits",
            "frozen_hashes",
        },
        "manifest",
    )
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ManifestError("schema_version is unsupported")
    _text(manifest["suite_id"], "suite_id")
    _text(manifest["description"], "description")
    if manifest["publication_class"] != "public_synthetic_development":
        raise ManifestError("publication_class is invalid")
    if (
        not isinstance(manifest["claim_limits"], list)
        or not manifest["claim_limits"]
        or any(not isinstance(claim, str) or not claim.strip() for claim in manifest["claim_limits"])
    ):
        raise ManifestError("claim_limits must be non-empty")
    model = _keys(manifest["model"], {"backend", "served_name"}, "model")
    if model != {"backend": "vllm-gemma", "served_name": "gemma-4-26b-a4b"}:
        raise ManifestError("model must be the fixed Gemma baseline")
    conditions = manifest["conditions"]
    if not isinstance(conditions, list) or len(conditions) != 2:
        raise ManifestError("conditions must contain control and diverse")
    control = _keys(
        conditions[0],
        {"id", "profile", "seeds", "generation_calls", "max_tokens_per_call", "timeout_s_per_call"},
        "conditions[0]",
    )
    diverse = _keys(
        conditions[1],
        {
            "id",
            "generation_profile",
            "generation_seeds",
            "generation_max_tokens_per_call",
            "generation_timeout_s_per_call",
            "validator_profile",
            "validator_seed",
            "validator_max_tokens",
            "validator_timeout_s",
        },
        "conditions[1]",
    )
    if control != {
        "id": "control",
        "profile": "deterministic",
        "seeds": [0],
        "generation_calls": 1,
        "max_tokens_per_call": 1280,
        "timeout_s_per_call": 80,
    }:
        raise ManifestError("control condition drifted")
    if diverse != {
        "id": "diverse_select",
        "generation_profile": "explore",
        "generation_seeds": [11, 29, 47],
        "generation_max_tokens_per_call": 384,
        "generation_timeout_s_per_call": 20,
        "validator_profile": "deterministic",
        "validator_seed": 0,
        "validator_max_tokens": 128,
        "validator_timeout_s": 20,
    }:
        raise ManifestError("diverse condition drifted")
    if control["max_tokens_per_call"] != (
        len(diverse["generation_seeds"]) * diverse["generation_max_tokens_per_call"]
        + diverse["validator_max_tokens"]
    ):
        raise ManifestError("conditions do not have matched output-token ceilings")
    if control["timeout_s_per_call"] != (
        len(diverse["generation_seeds"]) * diverse["generation_timeout_s_per_call"]
        + diverse["validator_timeout_s"]
    ):
        raise ManifestError("conditions do not have matched request-time ceilings")
    if manifest["ordering"] != "alternating_condition_groups":
        raise ManifestError("ordering is unsupported")
    tasks = manifest["tasks"]
    if not isinstance(tasks, list):
        raise ManifestError("tasks must be an array")
    for index, task in enumerate(tasks):
        _validate_task(task, index)
    if tuple(task["id"] for task in tasks) != TASK_IDS:
        raise ManifestError("task IDs or order drifted")
    resources = _keys(
        manifest["resource_limits"],
        {"planned_calls", "calls_serial", "max_total_runtime_s", "max_raw_completion_bytes"},
        "resource_limits",
    )
    if resources != {
        "planned_calls": 25,
        "calls_serial": True,
        "max_total_runtime_s": 850,
        "max_raw_completion_bytes": 131072,
    }:
        raise ManifestError("resource limits drifted")
    expected_hashes = {
        "model": sha256_json(model),
        "conditions": sha256_json(conditions),
        "tasks": {task["id"]: sha256_json(task) for task in tasks},
    }
    if manifest["frozen_hashes"] != expected_hashes:
        raise ManifestError("frozen hashes do not match literal inputs")


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    try:
        raw = manifest_path.read_bytes()
        document = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load manifest: {exc}") from exc
    validate_manifest(document)
    result = dict(document)
    result["_path"] = str(manifest_path)
    result["_raw_sha256"] = hashlib.sha256(raw).hexdigest()
    result["_configuration_sha256"] = sha256_json(document)
    return result


def plan_dict(manifest: dict[str, Any]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    for task_index, task in enumerate(manifest["tasks"]):
        groups = ["control", "diverse_select"]
        if task_index % 2:
            groups.reverse()
        for condition in groups:
            if condition == "control":
                specs = [("generate", 0, "deterministic", 1280, 80)]
            else:
                specs = [
                    ("generate", seed, "explore", 384, 20)
                    for seed in (11, 29, 47)
                ] + [("validate", 0, "deterministic", 128, 20)]
            for role, seed, profile, max_tokens, timeout_s in specs:
                sequence = sum(
                    row["task_id"] == task["id"]
                    and row["condition"] == condition
                    and row["role"] == role
                    for row in calls
                )
                calls.append(
                    {
                        "attempt_id": f"{task['id']}:{condition}:{role}:{sequence}:{seed}",
                        "task_id": task["id"],
                        "condition": condition,
                        "role": role,
                        "seed": seed,
                        "profile": profile,
                        "max_tokens": max_tokens,
                        "timeout_s": timeout_s,
                    }
                )
    return {
        "schema_version": SCHEMA_VERSION,
        "suite_id": manifest["suite_id"],
        "manifest_path": manifest["_path"],
        "manifest_sha256": manifest["_raw_sha256"],
        "configuration_sha256": manifest["_configuration_sha256"],
        "planned_calls": len(calls),
        "runtime_ceiling_s": manifest["resource_limits"]["max_total_runtime_s"],
        "calls": calls,
        "notice": "Public synthetic development evidence; no promotion or dispatch authority.",
    }
