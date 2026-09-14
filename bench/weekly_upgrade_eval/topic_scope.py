"""Frozen paired diagnostic for the game-theory topic prompt repair.

The manifest contains the literal prompts and states.  This harness never
imports either prompt implementation, reads production state, dispatches a
planner action, or assigns a semantic label itself.  Its only model boundary
is ``agent_wrapper.wrapper.call_sync``; semantic labels arrive later in a
blinded annotation file.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import shutil
import sys
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "experiments" / "topic_scope_repair_2026-09-14.json"
SCHEMA_VERSION = "topic-scope-repair/v1"
ANNOTATION_VERSION = "topic-scope-annotations/v1"
V1_SUITE_ID = "topic-scope-repair-2026-09-14"
V2_SUITE_ID = "topic-scope-repair-action-key-v2-2026-09-14"
V1_MANIFEST_SHA256 = "aab09640a9d377fc0a2a1c830223f5cd8b4e7e20299ac968d7bd01f2512b06a2"
V2_CANDIDATE_SOURCE_COMMIT = "ca39c1a512241341f25845a007097969eddf5ea4"
V2_CANDIDATE_PLANNER_SHA256 = "4cd842a95e87ab5be39d9fce1b50339e4ee28f0d5c33a310eb3a9f6b7c505754"
MAX_RUNTIME_S = 40 * 60
BASE_ATTEMPTS = 48
R0_ATTEMPTS = 32
EXECUTION_SOURCE_FILES = (
    Path(__file__).resolve(),
    REPO_ROOT / "orchestrator" / "coordinator_actions.py",
)
RESERVED_ROOTS = tuple(
    (REPO_ROOT / name).resolve()
    for name in ("logs", "run_state", "memory", "journal", "findings")
)


class ManifestError(ValueError):
    """The frozen diagnostic input is ambiguous or malformed."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"value is not canonical JSON: {exc}") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ManifestError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _keys(obj: Any, required: set[str], allowed: set[str], where: str) -> None:
    if not isinstance(obj, dict):
        raise ManifestError(f"{where} must be an object")
    missing = sorted(required - set(obj))
    extra = sorted(set(obj) - allowed)
    if missing:
        raise ManifestError(f"{where} missing fields: {', '.join(missing)}")
    if extra:
        raise ManifestError(f"{where} unknown fields: {', '.join(extra)}")


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where} must be a non-empty string")
    return value


def _number(value: Any, where: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{where} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ManifestError(f"{where} must be finite" + (" and > 0" if positive else ""))
    return result


def load_manifest(path: Path | str = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    try:
        raw = manifest_path.read_bytes()
        doc = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load manifest {manifest_path}: {exc}") from exc
    validate_manifest(doc)
    result = dict(doc)
    result["_path"] = str(manifest_path)
    result["_raw_sha256"] = hashlib.sha256(raw).hexdigest()
    result["_configuration_sha256"] = _sha(doc)
    return result


def validate_manifest(doc: Any) -> None:
    required = {
        "schema_version", "suite_id", "source_commits", "ordering", "seeds",
        "settings", "arms", "topics", "planner_menu", "planner_cases",
        "primary_r0", "annotation_contract", "resource_limits", "frozen_hashes",
        "source_snapshot",
    }
    _keys(doc, required, required, "manifest")
    if doc["schema_version"] != SCHEMA_VERSION:
        raise ManifestError(f"schema_version must be {SCHEMA_VERSION!r}")
    suite_id = _text(doc["suite_id"], "suite_id")
    if suite_id not in {V1_SUITE_ID, V2_SUITE_ID}:
        raise ManifestError(f"unsupported topic-scope suite_id {suite_id!r}")
    if doc["ordering"] != "alternate_ab_ba_reverse_cases_second_seed":
        raise ManifestError("unexpected ordering contract")
    if doc["seeds"] != [17, 29]:
        raise ManifestError("seeds must be exactly [17, 29]")
    _keys(doc["source_commits"], {"control", "candidate"}, {"control", "candidate"}, "source_commits")
    expected_commits = {
        "control": "d4eaeee2813ecf78b2542ed36e6428c928b98bce",
        "candidate": (
            "3a50b8c" if suite_id == V1_SUITE_ID
            else V2_CANDIDATE_SOURCE_COMMIT
        ),
    }
    for key, expected in expected_commits.items():
        observed = str(doc["source_commits"][key])
        matches = (
            observed.startswith(expected)
            if suite_id == V1_SUITE_ID
            else observed == expected
        )
        if not matches:
            raise ManifestError(f"source_commits.{key} is not the preregistered commit")

    arms = doc["arms"]
    if not isinstance(arms, list) or [arm.get("id") for arm in arms if isinstance(arm, dict)] != ["control", "candidate"]:
        raise ManifestError("arms must be ordered control, candidate")
    for index, arm in enumerate(arms):
        _keys(arm, {"id", "source_commit", "hypothesis_system", "planner_system"},
              {"id", "source_commit", "hypothesis_system", "planner_system"}, f"arms[{index}]")
        for field in ("source_commit", "hypothesis_system", "planner_system"):
            _text(arm[field], f"arms[{index}].{field}")
        if arm["source_commit"] != doc["source_commits"][arm["id"]]:
            raise ManifestError(f"arms[{index}].source_commit disagrees with source_commits")

    settings = doc["settings"]
    _keys(settings, {"backend", "model", "hypothesis", "planner"},
          {"backend", "model", "hypothesis", "planner"}, "settings")
    _text(settings["backend"], "settings.backend")
    if settings["model"] is not None:
        _text(settings["model"], "settings.model")
    for stage, expected in {
        "hypothesis": {"temperature": 0.7, "top_p": 0.95, "max_tokens": 512, "request_timeout_s": 30},
        "planner": {"temperature": 0.1, "top_p": 0.9, "max_tokens": 512, "request_timeout_s": 30, "budget": 3},
    }.items():
        config = settings[stage]
        if config != expected:
            raise ManifestError(f"settings.{stage} drifted from preregistration")

    topics = doc["topics"]
    if not isinstance(topics, list) or [item.get("id") for item in topics if isinstance(item, dict)] != [f"T{i}" for i in range(1, 9)]:
        raise ManifestError("topics must be exactly T1..T8 in order")
    for index, topic in enumerate(topics):
        _keys(topic, {"id", "text", "input_scope", "scope_anchor", "rendered_user"},
              {"id", "text", "input_scope", "scope_anchor", "rendered_user"}, f"topics[{index}]")
        _text(topic["text"], f"topics[{index}].text")
        _text(topic["scope_anchor"], f"topics[{index}].scope_anchor")
        if topic["rendered_user"] != f"Research topic: {topic['text']}":
            raise ManifestError(f"topics[{index}].rendered_user is not literal")
        if topic["input_scope"] not in {"in_scope", "repair"}:
            raise ManifestError(f"topics[{index}].input_scope is invalid")
    if topics[5]["text"] != "Test-Time Collaborative Classification over Multi-Agent Networks":
        raise ManifestError("T6 does not match the pinned recurring seed")
    if [topic["id"] for topic in topics if topic["input_scope"] == "repair"] != ["T5", "T6", "T7"]:
        raise ManifestError("repair cases must be exactly T5..T7")
    snapshot = doc["source_snapshot"]
    if snapshot != {
        "path": "memory/loop_memory.jsonl",
        "bytes": 8564469,
        "sha256": "542427d9a73f16dd840b07b21a8eebfccbe41bfa3e11516a312166a43b84b2c6",
        "note": "T6 was separately verified against this pinned private-source prefix; the harness never reads it.",
    }:
        raise ManifestError("source_snapshot drifted from the preregistered T6 provenance")

    menu = doc["planner_menu"]
    if not isinstance(menu, list) or not menu:
        raise ManifestError("planner_menu must be a non-empty array")
    menu_names: list[str] = []
    for index, item in enumerate(menu):
        _keys(item, {"name", "description", "arg_schema", "cost"},
              {"name", "description", "arg_schema", "cost"}, f"planner_menu[{index}]")
        menu_names.append(_text(item["name"], f"planner_menu[{index}].name"))
        _text(item["description"], f"planner_menu[{index}].description")
        if not isinstance(item["arg_schema"], dict):
            raise ManifestError(f"planner_menu[{index}].arg_schema must be an object")
        Draft7Validator.check_schema(item["arg_schema"])
        _number(item["cost"], f"planner_menu[{index}].cost")
    if len(menu_names) != len(set(menu_names)) or "run_loop_iteration" not in menu_names or "noop" not in menu_names:
        raise ManifestError("planner_menu names are invalid")

    states = doc["planner_cases"]
    if not isinstance(states, list) or [item.get("id") for item in states if isinstance(item, dict)] != [f"P{i}" for i in range(1, 5)]:
        raise ManifestError("planner_states must be exactly P1..P4 in order")
    for index, item in enumerate(states):
        _keys(item, {"id", "state", "rendered_user", "expected"},
              {"id", "state", "rendered_user", "expected"}, f"planner_cases[{index}]")
        expected_user = (
            "Apparatus state snapshot:\n"
            + json.dumps(item["state"], indent=2, default=str)
            + "\n\nEmit the plan as a JSON array (budget=3)."
        )
        if item["rendered_user"] != expected_user:
            raise ManifestError(f"planner_cases[{index}].rendered_user is not literal")
        suggestions = item["state"].get("topic_suggestions") if isinstance(item["state"], dict) else None
        if not isinstance(suggestions, list) or not suggestions:
            raise ManifestError(f"planner_cases[{index}] needs frozen topic_suggestions")
        _keys(item["expected"], {"preferred_topic", "exact_copy_only"},
              {"preferred_topic", "exact_copy_only"}, f"planner_cases[{index}].expected")

    r0 = doc["primary_r0"]
    _keys(r0, {"system", "temperature", "top_p", "max_tokens", "request_timeout_s"},
          {"system", "temperature", "top_p", "max_tokens", "request_timeout_s"}, "primary_r0")
    _text(r0["system"], "primary_r0.system")
    if {key: r0[key] for key in r0 if key != "system"} != {
        "temperature": 0.0, "top_p": 1.0, "max_tokens": 256, "request_timeout_s": 15,
    }:
        raise ManifestError("primary_r0 settings drifted")

    annotation = doc["annotation_contract"]
    _keys(annotation, {"schema_version", "domain", "fidelity", "required_fields"},
          {"schema_version", "domain", "fidelity", "required_fields"}, "annotation_contract")
    if annotation["schema_version"] != ANNOTATION_VERSION:
        raise ManifestError("annotation schema version drifted")
    if annotation["domain"] != ["in_scope", "out_of_scope", "unclear"]:
        raise ManifestError("annotation domain enum drifted")
    if annotation["fidelity"] != ["preserved", "grounded_transfer", "scope_safe_reset", "unrelated_redirect", "unclear"]:
        raise ManifestError("annotation fidelity enum drifted")
    if annotation["required_fields"] != [
        "candidate_index", "domain", "substantive_mechanism",
        "fidelity", "unsupported_attribution", "generic_output",
    ]:
        raise ManifestError("annotation required fields drifted")

    limits = doc["resource_limits"]
    if limits != {
        "max_total_runtime_s": 2400,
        "base_attempts": 48,
        "optional_primary_r0_attempts": 32,
        "calls_serial": True,
    }:
        raise ManifestError("resource_limits drifted from the preregistration")

    expected_hashes = {
        "arm_system_prompts": {
            arm["id"]: {
                "hypothesis": _sha(arm["hypothesis_system"]),
                "planner": _sha(arm["planner_system"]),
            }
            for arm in arms
        },
        "topic_rendered_users": {topic["id"]: _sha(topic["rendered_user"]) for topic in topics},
        "topic_grading_anchors": {topic["id"]: _sha(topic["scope_anchor"]) for topic in topics},
        "planner_case_states": {item["id"]: _sha(item["state"]) for item in states},
        "planner_rendered_users": {item["id"]: _sha(item["rendered_user"]) for item in states},
        "planner_menu": _sha(menu),
        "settings": _sha(settings),
        "primary_r0_system": _sha(r0["system"]),
    }
    if doc["frozen_hashes"] != expected_hashes:
        raise ManifestError("frozen_hashes do not match the literal manifest inputs")
    if suite_id == V2_SUITE_ID:
        _validate_v2_lineage(doc)


def _validate_v2_lineage(doc: dict[str, Any]) -> None:
    """Prove v2 changes only the candidate planner contract and its identity."""
    try:
        baseline_raw = DEFAULT_MANIFEST.read_bytes()
        baseline = json.loads(baseline_raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot validate v2 lineage against v1: {exc}") from exc
    if hashlib.sha256(baseline_raw).hexdigest() != V1_MANIFEST_SHA256:
        raise ManifestError("the frozen v1 lineage manifest has drifted")

    candidate = next(arm for arm in doc["arms"] if arm["id"] == "candidate")
    if _sha(candidate["planner_system"]) != V2_CANDIDATE_PLANNER_SHA256:
        raise ManifestError("v2 candidate planner prompt is not the preregistered repair")

    normalized = copy.deepcopy(doc)
    normalized["suite_id"] = baseline["suite_id"]
    normalized["source_commits"]["candidate"] = baseline["source_commits"]["candidate"]
    normalized_candidate = next(
        arm for arm in normalized["arms"] if arm["id"] == "candidate"
    )
    baseline_candidate = next(
        arm for arm in baseline["arms"] if arm["id"] == "candidate"
    )
    normalized_candidate["source_commit"] = baseline_candidate["source_commit"]
    normalized_candidate["planner_system"] = baseline_candidate["planner_system"]
    normalized["frozen_hashes"]["arm_system_prompts"]["candidate"]["planner"] = (
        baseline["frozen_hashes"]["arm_system_prompts"]["candidate"]["planner"]
    )
    if normalized != baseline:
        raise ManifestError(
            "v2 may change only suite identity, candidate source identity, "
            "and candidate planner prompt"
        )


def _case_order(items: list[dict[str, Any]], seed_index: int) -> Iterable[tuple[int, dict[str, Any]]]:
    indexed = list(enumerate(items))
    return indexed if seed_index == 0 else reversed(indexed)


def build_attempts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the declared 32 hypothesis and 16 planner attempts."""
    attempts: list[dict[str, Any]] = []
    arms = [arm["id"] for arm in manifest["arms"]]
    for stage, key in (("hypothesis", "topics"), ("planner", "planner_cases")):
        for seed_index, seed in enumerate(manifest["seeds"]):
            for original_index, case in _case_order(manifest[key], seed_index):
                arm_order = arms if original_index % 2 == 0 else list(reversed(arms))
                for arm in arm_order:
                    attempts.append({
                        "attempt_id": f"{stage}:{case['id']}:seed-{seed}:{arm}",
                        "stage": stage,
                        "case_id": case["id"],
                        "seed": seed,
                        "arm": arm,
                    })
    if len(attempts) != BASE_ATTEMPTS or len({item["attempt_id"] for item in attempts}) != BASE_ATTEMPTS:
        raise AssertionError("internal attempt matrix is not 48 unique cells")
    return attempts


def plan_dict(manifest: dict[str, Any], *, include_r0: bool = False) -> dict[str, Any]:
    attempts = build_attempts(manifest)
    return {
        "schema_version": manifest["schema_version"],
        "suite_id": manifest["suite_id"],
        "manifest_path": manifest["_path"],
        "manifest_sha256": manifest["_raw_sha256"],
        "configuration_sha256": manifest["_configuration_sha256"],
        "base_attempts": len(attempts),
        "hypothesis_attempts": sum(item["stage"] == "hypothesis" for item in attempts),
        "planner_attempts": sum(item["stage"] == "planner" for item in attempts),
        "optional_primary_r0_attempts": R0_ATTEMPTS if include_r0 else 0,
        "maximum_attempt_records": len(attempts) + (R0_ATTEMPTS if include_r0 else 0),
        "order": attempts,
        "notice": "Evaluation only: no action dispatch, production writes, promotion, or automatic semantic grading.",
    }


def validate_output_dir(path: Path | str) -> Path:
    output = Path(path).expanduser().resolve()
    if output == REPO_ROOT:
        raise ValueError("output directory cannot be the repository root")
    for reserved in RESERVED_ROOTS:
        if output == reserved or reserved in output.parents:
            raise ValueError(f"output directory cannot be under live artifact root {reserved}")
    if output.exists():
        raise FileExistsError(f"output directory already exists; use a fresh path: {output}")
    return output


def _append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_canonical(value).decode("utf-8") + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(_canonical(value) + b"\n")
    temp.replace(path)


def _extract_json(text: Any) -> Any:
    if not isinstance(text, str):
        return None
    starts = sorted(
        (position, opener, closer)
        for opener, closer in (("{", "}"), ("[", "]"))
        if (position := text.find(opener)) >= 0
    )
    for start, opener, closer in starts:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if escape:
                escape = False
            elif char == "\\" and in_string:
                escape = True
            elif char == '"':
                in_string = not in_string
            elif not in_string:
                if char == opener:
                    depth += 1
                elif char == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:index + 1])
                        except json.JSONDecodeError:
                            break
    return None


def _parse_hypothesis(completion: Any) -> dict[str, Any]:
    payload = _extract_json(completion)
    if not isinstance(payload, dict):
        return {"protocol_valid": False, "protocol_error": "completion is not a JSON object", "candidates": [], "chosen": None, "chosen_index": None}
    raw_candidates = payload.get("candidates")
    chosen = payload.get("chosen")
    if (
        not isinstance(raw_candidates, list)
        or not 1 <= len(raw_candidates) <= 3
        or any(not isinstance(item, str) or not item.strip() for item in raw_candidates)
        or len(set(raw_candidates)) != len(raw_candidates)
        or not isinstance(chosen, str)
        or chosen not in raw_candidates
    ):
        return {"protocol_valid": False, "protocol_error": "hypothesis schema/chosen contract failed", "candidates": [], "chosen": None, "chosen_index": None}
    return {
        "protocol_valid": True,
        "protocol_error": None,
        "candidates": raw_candidates,
        "chosen": chosen,
        "chosen_index": raw_candidates.index(chosen),
    }


def _validate_frozen_plan(plan: Any, menu: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(plan, list) or not plan:
        return {"valid": False, "errors": ["plan must be a non-empty array"], "cost": 0}
    if len(plan) > 6:
        errors.append("plan exceeds six-action cap")
    by_name = {item["name"]: item for item in menu}
    total = 0
    for index, step in enumerate(plan):
        if not isinstance(step, dict) or set(step) != {"action", "args"}:
            errors.append(f"action[{index}] must have exactly action and args")
            continue
        name = step.get("action")
        spec = by_name.get(name)
        if spec is None:
            errors.append(f"action[{index}] is off-menu")
            continue
        args = step.get("args")
        for error in Draft7Validator(spec["arg_schema"]).iter_errors(args):
            errors.append(f"action[{index}] args: {error.message}")
        total += spec["cost"]
    if total > budget:
        errors.append(f"plan costs {total}, exceeds budget {budget}")
    return {"valid": not errors, "errors": errors, "cost": total}


def _parse_planner(completion: Any, case: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    payload = _extract_json(completion)
    if isinstance(payload, dict) and isinstance(payload.get("plan"), list):
        payload = payload["plan"]
    checked = _validate_frozen_plan(payload, manifest["planner_menu"], manifest["settings"]["planner"]["budget"])
    actions = payload if isinstance(payload, list) else []
    suggestions = [item["topic"] for item in case["state"]["topic_suggestions"]]
    selected = [
        step.get("args", {}).get("topic")
        for step in actions if isinstance(step, dict) and step.get("action") == "run_loop_iteration"
    ]
    all_exact = all(topic in suggestions for topic in selected)
    preferred = case["expected"]["preferred_topic"]
    return {
        "protocol_valid": checked["valid"],
        "protocol_error": None if checked["valid"] else "; ".join(checked["errors"]),
        "plan": actions,
        "plan_cost": checked["cost"],
        "selected_topics": selected,
        "noop_count": sum(
            isinstance(step, dict) and step.get("action") == "noop" for step in actions
        ),
        "preferred_topic_selected": bool(checked["valid"] and preferred is not None and preferred in selected),
        "exact_copy_provenance": bool(checked["valid"] and selected and all_exact),
    }


def _parse_r0(completion: Any) -> dict[str, Any]:
    payload = _extract_json(completion)
    domain = payload.get("domain") if isinstance(payload, dict) else None
    reason = payload.get("reason") if isinstance(payload, dict) else None
    valid = domain in {"on", "off", "unsure"} and isinstance(reason, str) and bool(reason.strip())
    return {
        "protocol_valid": valid,
        "protocol_error": None if valid else "R0 response failed frozen schema",
        "domain": domain if valid else None,
        "reason": reason if valid else None,
    }


def _messages(manifest: dict[str, Any], attempt: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    arm = next(item for item in manifest["arms"] if item["id"] == attempt["arm"])
    if attempt["stage"] == "hypothesis":
        case = next(item for item in manifest["topics"] if item["id"] == attempt["case_id"])
        return ([
            {"role": "system", "content": arm["hypothesis_system"]},
            {"role": "user", "content": case["rendered_user"]},
        ], case)
    case = next(item for item in manifest["planner_cases"] if item["id"] == attempt["case_id"])
    return ([
        {"role": "system", "content": arm["planner_system"]},
        {"role": "user", "content": case["rendered_user"]},
    ], case)


def _call_kwargs(manifest: dict[str, Any], attempt: dict[str, Any], calls_log: Path, timeout_s: float) -> dict[str, Any]:
    config = manifest["settings"][attempt["stage"]]
    kwargs: dict[str, Any] = {
        "temperature": config["temperature"],
        "top_p": config["top_p"],
        "seed": attempt["seed"],
        "max_tokens": config["max_tokens"],
        "request_timeout_s": min(float(config["request_timeout_s"]), timeout_s),
        "caller_tag": f"weekly_upgrade.topic_scope.{attempt['stage']}",
        "parent_request_id": None,
        "log_path": str(calls_log),
        "backend": manifest["settings"]["backend"],
        "model": manifest["settings"]["model"],
    }
    return kwargs


def _error_status(exc: Exception) -> str:
    return "timeout" if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() else "error"


def _runtime_identity(record: Any, manifest: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    if not isinstance(record, dict):
        return {}, "wrapper result is not an object"
    identity = {
        "model": record.get("model"),
        "model_version": record.get("model_version"),
        "backend": record.get("backend"),
        "host_metadata": record.get("host_metadata"),
    }
    expected_model = manifest["settings"]["model"]
    expected_backend = manifest["settings"]["backend"]
    if identity["model"] != expected_model:
        return identity, f"model drift: expected {expected_model!r}, got {identity['model']!r}"
    if identity["backend"] != expected_backend:
        return identity, f"backend drift: expected {expected_backend!r}, got {identity['backend']!r}"
    if not isinstance(identity["model_version"], str) or not identity["model_version"].strip():
        return identity, "model_version provenance is missing"
    if not isinstance(identity["host_metadata"], dict):
        return identity, "host_metadata provenance is missing"
    return identity, None


def _blind_artifacts(manifest: dict[str, Any], parsed: list[dict[str, Any]], run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    labels = {"control": f"arm-{uuid.uuid4().hex[:12]}", "candidate": f"arm-{uuid.uuid4().hex[:12]}"}
    private_rows = []
    blind_rows = []
    for item in parsed:
        if item["stage"] not in {"hypothesis", "planner"}:
            continue
        blind_id = hashlib.sha256(f"{run_id}:{item['attempt_id']}".encode()).hexdigest()[:24]
        private_rows.append({"blind_id": blind_id, "attempt_id": item["attempt_id"], "arm": item["arm"], "blind_arm": labels[item["arm"]]})
        row = {
            "blind_id": blind_id,
            "blind_arm": labels[item["arm"]],
            "stage": item["stage"],
            "case_id": item["case_id"],
            "seed": item["seed"],
            "status": item["status"],
            "protocol_valid": item.get("protocol_valid", False),
            "protocol_error": item.get("protocol_error"),
        }
        if item["stage"] == "hypothesis":
            topic = next(topic for topic in manifest["topics"] if topic["id"] == item["case_id"])
            row["input_topic"] = topic["text"]
            row["scope_anchor"] = topic["scope_anchor"]
            row["candidates"] = [
                {"candidate_index": index, "text": text, "chosen": index == item.get("chosen_index")}
                for index, text in enumerate(item.get("candidates") or [])
            ]
        else:
            row["plan"] = item.get("plan") or []
            row["selected_topics"] = item.get("selected_topics") or []
        blind_rows.append(row)
    blind = {
        "schema_version": "topic-scope-blind-export/v1",
        "suite_id": manifest["suite_id"],
        "instructions": {
            "annotation_schema_version": ANNOTATION_VERSION,
            "required_candidate_fields": manifest["annotation_contract"]["required_fields"],
            "domain_enum": manifest["annotation_contract"]["domain"],
            "fidelity_enum": manifest["annotation_contract"]["fidelity"],
            "note": "Annotate semantic content only. Arm identity is intentionally withheld.",
        },
        "items": blind_rows,
    }
    private = {
        "schema_version": "topic-scope-private-map/v1",
        "run_id": run_id,
        "arm_labels": labels,
        "items": private_rows,
    }
    return blind, private


def run_experiment(
    manifest: dict[str, Any], *, output_dir: Path | str, runtime_budget_s: float,
    include_r0: bool = False, invoke: Callable[..., dict[str, Any]] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Execute serial paired calls and preserve every declared denominator cell."""
    validate_manifest({key: value for key, value in manifest.items() if not key.startswith("_")})
    runtime = _number(runtime_budget_s, "runtime_budget_s", positive=True)
    if runtime > MAX_RUNTIME_S:
        raise ValueError(f"runtime_budget_s cannot exceed {MAX_RUNTIME_S}")
    execution_source_sha256 = {
        str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in EXECUTION_SOURCE_FILES
    }
    output = validate_output_dir(output_dir)
    if invoke is None and os.environ.get("MOCK_LLM"):
        raise ValueError("REFUSE live diagnostic while MOCK_LLM is set")
    output.mkdir(parents=True)
    source_path = Path(manifest["_path"])
    shutil.copyfile(source_path, output / "manifest.snapshot.json")
    invoke_fn = invoke
    if invoke_fn is None:
        from agent_wrapper import worker_activity, wrapper

        def isolated_wrapper_call(messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
            prior_activity_path = worker_activity.DEFAULT_LOG_PATH
            prior_run_id = wrapper.get_run_id()
            worker_activity.DEFAULT_LOG_PATH = output / "worker_activity.jsonl"
            wrapper.set_run_id(run_id)
            try:
                return wrapper.call_sync(messages, **kwargs)
            finally:
                wrapper.set_run_id(prior_run_id)
                worker_activity.DEFAULT_LOG_PATH = prior_activity_path

        invoke_fn = isolated_wrapper_call

    run_id = f"topic-scope-{uuid.uuid4()}"
    start = monotonic()
    deadline = start + runtime
    raw_path = output / "raw_attempts.jsonl"
    parsed_path = output / "parsed_attempts.jsonl"
    calls_log = output / "calls.jsonl"
    parsed_rows: list[dict[str, Any]] = []

    def persist_run(status: str) -> dict[str, Any]:
        artifact = {
            "schema_version": "topic-scope-run/v1",
            "run_id": run_id,
            "status": status,
            "manifest_sha256": manifest["_raw_sha256"],
            "configuration_sha256": manifest["_configuration_sha256"],
            "execution_source_sha256": execution_source_sha256,
            "runtime_budget_s": runtime,
            "include_primary_r0": include_r0,
            "declared_base_attempts": BASE_ATTEMPTS,
            "declared_primary_r0_attempts": R0_ATTEMPTS if include_r0 else 0,
            "attempts_recorded": len(parsed_rows),
            "elapsed_s": max(0.0, monotonic() - start),
            "outcomes": parsed_rows,
            "promotion_authorized": False,
        }
        _write_json(output / "run.json", artifact)
        return artifact

    attempts = build_attempts(manifest)
    for execution_index, attempt in enumerate(attempts):
        before = monotonic()
        remaining = deadline - before
        request_timeout = (
            min(float(manifest["settings"][attempt["stage"]]["request_timeout_s"]), remaining)
            if remaining > 0 else None
        )
        base = {
            **attempt,
            "execution_index": execution_index,
            "request_timeout_s": request_timeout,
        }
        if remaining <= 0:
            raw = {**base, "status": "not_run_budget", "completion": None, "record": None, "error": "runtime budget exhausted"}
            _append_jsonl(raw_path, raw)
            parsed = {**base, "status": "not_run_budget", "protocol_valid": False, "protocol_error": "runtime budget exhausted"}
        else:
            messages, case = _messages(manifest, attempt)
            call_kwargs = _call_kwargs(manifest, attempt, calls_log, remaining)
            try:
                record = invoke_fn(messages, **call_kwargs)
            except Exception as exc:  # noqa: BLE001 - every call failure is a denominator result
                status = _error_status(exc)
                raw = {**base, "status": status, "completion": None, "record": None, "error": f"{type(exc).__name__}: {exc}"}
                _append_jsonl(raw_path, raw)
                parsed = {**base, "status": status, "protocol_valid": False, "protocol_error": raw["error"]}
            else:
                completion = record.get("completion") if isinstance(record, dict) else None
                raw = {**base, "status": "returned", "completion": completion, "record": record, "error": None}
                _append_jsonl(raw_path, raw)  # durable before parsing/grading
                try:
                    parsed_payload = _parse_hypothesis(completion) if attempt["stage"] == "hypothesis" else _parse_planner(completion, case, manifest)
                except Exception as exc:  # noqa: BLE001 - raw response remains available for repair
                    parsed_payload = {"protocol_valid": False, "protocol_error": f"harness parse error: {type(exc).__name__}: {exc}"}
                identity, drift = _runtime_identity(record, manifest)
                if drift:
                    parsed_payload["protocol_valid"] = False
                    parsed_payload["protocol_error"] = "; ".join(
                        part for part in (parsed_payload.get("protocol_error"), drift) if part
                    )
                parsed = {**base, "status": "returned", "runtime_identity": identity, "runtime_identity_valid": drift is None, **parsed_payload}
        parsed["duration_s"] = max(0.0, monotonic() - before)
        _append_jsonl(parsed_path, parsed)
        parsed_rows.append(parsed)
        persist_run("running")

    if include_r0:
        r0_config = manifest["primary_r0"]
        for r0_index, source in enumerate(item for item in parsed_rows if item["stage"] == "hypothesis"):
            attempt_id = f"primary_r0:{source['case_id']}:seed-{source['seed']}:{source['arm']}"
            before = monotonic()
            chosen = source.get("chosen") if source.get("protocol_valid") else None
            remaining = deadline - before
            base = {
                "attempt_id": attempt_id, "stage": "primary_r0", "case_id": source["case_id"],
                "seed": source["seed"], "arm": source["arm"],
                "execution_index": len(attempts) + r0_index,
                "request_timeout_s": (
                    min(float(r0_config["request_timeout_s"]), remaining)
                    if remaining > 0 and chosen else None
                ),
            }
            if not chosen:
                raw = {**base, "status": "not_run_missing_output", "completion": None, "record": None, "error": "source hypothesis missing or invalid"}
                _append_jsonl(raw_path, raw)
                parsed = {**base, "status": "not_run_missing_output", "protocol_valid": False, "protocol_error": raw["error"]}
            elif remaining <= 0:
                raw = {**base, "status": "not_run_budget", "completion": None, "record": None, "error": "runtime budget exhausted"}
                _append_jsonl(raw_path, raw)
                parsed = {**base, "status": "not_run_budget", "protocol_valid": False, "protocol_error": raw["error"]}
            else:
                kwargs = {
                    "temperature": r0_config["temperature"], "top_p": r0_config["top_p"],
                    "seed": source["seed"], "max_tokens": r0_config["max_tokens"],
                    "request_timeout_s": min(float(r0_config["request_timeout_s"]), remaining),
                    "caller_tag": "weekly_upgrade.topic_scope.primary_r0", "parent_request_id": None,
                    "log_path": str(calls_log), "backend": manifest["settings"]["backend"],
                    "model": manifest["settings"]["model"],
                }
                try:
                    record = invoke_fn([
                        {"role": "system", "content": r0_config["system"]},
                        {"role": "user", "content": chosen},
                    ], **kwargs)
                except Exception as exc:  # noqa: BLE001 - every call failure is a denominator result
                    status = _error_status(exc)
                    raw = {**base, "status": status, "completion": None, "record": None, "error": f"{type(exc).__name__}: {exc}"}
                    _append_jsonl(raw_path, raw)
                    parsed = {**base, "status": status, "protocol_valid": False, "protocol_error": raw["error"]}
                else:
                    completion = record.get("completion") if isinstance(record, dict) else None
                    raw = {**base, "status": "returned", "completion": completion, "record": record, "error": None}
                    _append_jsonl(raw_path, raw)
                    try:
                        parsed_payload = _parse_r0(completion)
                    except Exception as exc:  # noqa: BLE001 - raw response remains available
                        parsed_payload = {"protocol_valid": False, "protocol_error": f"harness parse error: {type(exc).__name__}: {exc}"}
                    identity, drift = _runtime_identity(record, manifest)
                    if drift:
                        parsed_payload["protocol_valid"] = False
                        parsed_payload["protocol_error"] = "; ".join(
                            part for part in (parsed_payload.get("protocol_error"), drift) if part
                        )
                    parsed = {**base, "status": "returned", "runtime_identity": identity, "runtime_identity_valid": drift is None, **parsed_payload}
            parsed["duration_s"] = max(0.0, monotonic() - before)
            _append_jsonl(parsed_path, parsed)
            parsed_rows.append(parsed)
            persist_run("running")

    blind, private = _blind_artifacts(manifest, parsed_rows, run_id)
    _write_json(output / "annotation_blind.json", blind)
    _write_json(output / "arm_map_private.json", private)
    expected = BASE_ATTEMPTS + (R0_ATTEMPTS if include_r0 else 0)
    identities = {
        _sha(row["runtime_identity"])
        for row in parsed_rows if isinstance(row.get("runtime_identity"), dict)
    }
    complete_transport = len(parsed_rows) == expected and all(
        row["status"] == "returned" for row in parsed_rows
    )
    identity_invalid = any(
        row.get("runtime_identity_valid") is False for row in parsed_rows
    )
    if complete_transport and (len(identities) > 1 or identity_invalid):
        status = "invalid_runtime_drift"
    else:
        status = "awaiting_annotation" if complete_transport else "incomplete_transport"
    return persist_run(status)


def _read_annotations(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load annotations: {exc}") from exc
    annotation_fields = {
        "schema_version", "reviewer", "reviewer_kind",
        "independent_of_generator", "items",
    }
    _keys(doc, annotation_fields, annotation_fields, "annotations")
    if doc["schema_version"] != ANNOTATION_VERSION:
        raise ValueError("unsupported annotation schema version")
    _text(doc["reviewer"], "annotations.reviewer")
    if doc["reviewer_kind"] not in {"human", "subscription_frontier"}:
        raise ValueError("reviewer_kind must be human or subscription_frontier")
    if doc["independent_of_generator"] is not True:
        raise ValueError("annotations must attest independence from the generator")
    if not isinstance(doc["items"], list):
        raise ValueError("annotations.items must be an array")  # noqa: TRY004
    return doc


def summarize_annotations(artifact_dir: Path | str, annotations_path: Path | str) -> dict[str, Any]:
    root = Path(artifact_dir).resolve()
    run = json.loads((root / "run.json").read_bytes())
    blind = json.loads((root / "annotation_blind.json").read_bytes())
    private = json.loads((root / "arm_map_private.json").read_bytes())
    annotations = _read_annotations(Path(annotations_path))
    blind_hyp = {item["blind_id"]: item for item in blind["items"] if item["stage"] == "hypothesis" and item["protocol_valid"]}
    mapping = {item["blind_id"]: item for item in private["items"]}
    supplied: dict[str, dict[str, Any]] = {}
    allowed_fields = {
        "blind_id", "candidate_index", "domain", "substantive_mechanism",
        "fidelity", "unsupported_attribution", "generic_output",
    }
    for index, item in enumerate(annotations["items"]):
        _keys(item, allowed_fields, allowed_fields, f"annotations.items[{index}]")
        blind_id = item["blind_id"]
        if blind_id not in blind_hyp:
            raise ValueError(f"annotation references unknown/non-gradable blind_id {blind_id!r}")
        candidate_index = item["candidate_index"]
        if isinstance(candidate_index, bool) or not isinstance(candidate_index, int):
            raise ValueError("candidate_index must be an integer")  # noqa: TRY004
        candidates = blind_hyp[blind_id]["candidates"]
        if candidate_index < 0 or candidate_index >= len(candidates):
            raise ValueError("candidate_index is outside the blinded candidate list")
        key = f"{blind_id}:{candidate_index}"
        if key in supplied:
            raise ValueError(f"duplicate annotation {key}")
        if item["domain"] not in {"in_scope", "out_of_scope", "unclear"}:
            raise ValueError("invalid domain annotation")
        if item["fidelity"] not in {"preserved", "grounded_transfer", "scope_safe_reset", "unrelated_redirect", "unclear"}:
            raise ValueError("invalid fidelity annotation")
        for boolean in ("substantive_mechanism", "unsupported_attribution", "generic_output"):
            if not isinstance(item[boolean], bool):
                raise ValueError(f"{boolean} must be boolean")  # noqa: TRY004
        supplied[key] = item
    expected = {
        f"{blind_id}:{candidate['candidate_index']}"
        for blind_id, row in blind_hyp.items() for candidate in row["candidates"]
    }
    if set(supplied) != expected:
        missing = sorted(expected - set(supplied))
        extra = sorted(set(supplied) - expected)
        raise ValueError(f"annotations must cover every candidate; missing={missing}, extra={extra}")

    by_attempt = {item["attempt_id"]: item for item in run["outcomes"]}
    metrics = {
        arm: {
            "all_candidates_in_scope": 0, "all_candidates_out_of_scope": 0,
            "all_candidates_unclear": 0, "all_candidates_substantive": 0,
            "chosen_in_scope": 0, "chosen_in_scope_substantive": 0,
            "repair_grounded_useful": 0,
            "unsupported_attribution": 0, "generic_output": 0,
            "chosen_cross_case_duplicate_outputs": 0,
            "all_candidates": 0, "chosen_annotated": 0,
            "hypothesis_protocol_failures": 0, "planner_protocol_failures": 0,
            "planner_valid_plans": 0, "planner_preferred_correct": 0, "planner_exact_copy": 0,
            "planner_noops": 0, "r0_on": 0, "r0_off": 0, "r0_unsure": 0,
            "r0_error_or_missing": 0, "r0_annotation_disagreement": 0,
        } for arm in ("control", "candidate")
    }
    case_metrics: list[dict[str, Any]] = []
    chosen_texts: dict[str, list[tuple[str, str]]] = {"control": [], "candidate": []}
    for blind_id, blind_row in blind_hyp.items():
        map_row = mapping[blind_id]
        arm = map_row["arm"]
        outcome = by_attempt[map_row["attempt_id"]]
        for candidate in blind_row["candidates"]:
            ann = supplied[f"{blind_id}:{candidate['candidate_index']}"]
            metrics[arm]["all_candidates"] += 1
            metrics[arm][f"all_candidates_{ann['domain']}"] += 1
            metrics[arm]["all_candidates_substantive"] += int(ann["substantive_mechanism"])
            metrics[arm]["unsupported_attribution"] += int(ann["unsupported_attribution"])
            metrics[arm]["generic_output"] += int(ann["generic_output"])
            if candidate["chosen"]:
                normalized = " ".join(candidate["text"].split()).casefold()
                chosen_texts[arm].append((blind_row["case_id"], normalized))
                metrics[arm]["chosen_annotated"] += 1
                metrics[arm]["chosen_in_scope"] += int(ann["domain"] == "in_scope")
                valid = ann["domain"] == "in_scope" and ann["substantive_mechanism"] and not ann["unsupported_attribution"]
                metrics[arm]["chosen_in_scope_substantive"] += int(valid)
                repair_useful = valid and ann["fidelity"] == "grounded_transfer" and outcome["case_id"] in {"T5", "T6", "T7"}
                metrics[arm]["repair_grounded_useful"] += int(repair_useful)
                case_metrics.append({"attempt_id": outcome["attempt_id"], "case_id": outcome["case_id"], "seed": outcome["seed"], "arm": arm, "chosen_valid": valid, "repair_grounded_useful": repair_useful, **{key: ann[key] for key in allowed_fields if key not in {"blind_id", "candidate_index"}}})

    for arm, rows in chosen_texts.items():
        by_text: dict[str, list[str]] = {}
        for case_id, text in rows:
            by_text.setdefault(text, []).append(case_id)
        metrics[arm]["chosen_cross_case_duplicate_outputs"] = sum(
            len(cases) for cases in by_text.values() if len(set(cases)) > 1
        )

    for outcome in run["outcomes"]:
        arm = outcome["arm"]
        if outcome["stage"] == "hypothesis" and not outcome.get("protocol_valid"):
            metrics[arm]["hypothesis_protocol_failures"] += 1
        elif outcome["stage"] == "planner":
            if not outcome.get("protocol_valid"):
                metrics[arm]["planner_protocol_failures"] += 1
            metrics[arm]["planner_valid_plans"] += int(outcome.get("protocol_valid", False))
            metrics[arm]["planner_preferred_correct"] += int(outcome.get("preferred_topic_selected", False))
            metrics[arm]["planner_exact_copy"] += int(outcome.get("exact_copy_provenance", False))
            metrics[arm]["planner_noops"] += int(outcome.get("noop_count", 0))

    chosen_by_cell = {
        (row["case_id"], row["seed"], row["arm"]): row for row in case_metrics
    }
    for outcome in run["outcomes"]:
        if outcome["stage"] != "primary_r0":
            continue
        arm = outcome["arm"]
        domain = outcome.get("domain") if outcome.get("protocol_valid") else None
        if domain in {"on", "off", "unsure"}:
            metrics[arm][f"r0_{domain}"] += 1
        else:
            metrics[arm]["r0_error_or_missing"] += 1
            continue
        annotation = chosen_by_cell.get((outcome["case_id"], outcome["seed"], arm))
        if annotation and annotation["domain"] in {"in_scope", "out_of_scope"}:
            agrees = (domain == "on" and annotation["domain"] == "in_scope") or (
                domain == "off" and annotation["domain"] == "out_of_scope"
            )
            metrics[arm]["r0_annotation_disagreement"] += int(not agrees)

    on_domain_ids = {"T1", "T2", "T3", "T4", "T8"}
    on_domain_valid = {arm: sum(row["chosen_valid"] for row in case_metrics if row["arm"] == arm and row["case_id"] in on_domain_ids) for arm in metrics}
    control, candidate = metrics["control"], metrics["candidate"]
    complete = (
        run["status"] == "awaiting_annotation"
        and all(metric["chosen_annotated"] == 16 for metric in metrics.values())
    )
    evaluate = (
        complete
        and candidate["repair_grounded_useful"] > control["repair_grounded_useful"]
        and on_domain_valid["candidate"] >= on_domain_valid["control"]
        and candidate["unsupported_attribution"] <= control["unsupported_attribution"]
        and candidate["hypothesis_protocol_failures"] <= control["hypothesis_protocol_failures"]
        and candidate["planner_protocol_failures"] <= control["planner_protocol_failures"]
        and candidate["planner_preferred_correct"] >= control["planner_preferred_correct"]
        and candidate["planner_exact_copy"] >= control["planner_exact_copy"]
    )
    decision = "EVALUATE-LARGER" if evaluate else ("NO-MATERIAL-SIGNAL" if complete else "INVALID/INCOMPLETE")
    summary = {
        "schema_version": "topic-scope-summary/v1",
        "run_id": run["run_id"],
        "annotation_reviewer": annotations["reviewer"],
        "annotation_reviewer_kind": annotations["reviewer_kind"],
        "annotation_sha256": hashlib.sha256(Path(annotations_path).read_bytes()).hexdigest(),
        "metrics_by_arm": metrics,
        "on_domain_chosen_valid": on_domain_valid,
        "case_metrics": case_metrics,
        "elapsed_s_including_failures": run["elapsed_s"],
        "decision": decision,
        "production_change_authorized": False,
        "caveat": "Development diagnostic only; no scientific-benefit or production-promotion claim.",
    }
    _write_json(root / "summary.json", summary)
    return summary


def export_grading_package(
    artifact_dir: Path | str,
    package_path: Path | str,
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Write one self-contained blind-only JSON file for an external grader.

    The package deliberately contains neither the private arm map nor a path
    to it.  Give the grader this file, rather than access to the evaluation
    directory that also holds ``arm_map_private.json``.
    """
    artifact_root = Path(artifact_dir).expanduser().resolve()
    destination = Path(package_path).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"grading package already exists: {destination}")
    if destination.is_symlink() or artifact_root == destination or artifact_root in destination.parents:
        raise ValueError("grading package must be outside the evaluation artifact directory")
    run = json.loads((artifact_root / "run.json").read_bytes(), object_pairs_hook=_unique_object)
    blind = json.loads((artifact_root / "annotation_blind.json").read_bytes(), object_pairs_hook=_unique_object)
    if run.get("schema_version") != "topic-scope-run/v1" or blind.get("schema_version") != "topic-scope-blind-export/v1":
        raise ValueError("unrecognized topic-scope run or blind export")
    if expected_manifest_sha256 is not None and run.get("manifest_sha256") != expected_manifest_sha256:
        raise ValueError("grading package source does not bind to the expected manifest")
    items = blind.get("items")
    if not isinstance(items, list) or len(items) != BASE_ATTEMPTS:
        raise ValueError("blind export must contain all 48 base attempts")
    forbidden_keys = {"arm", "attempt_id", "source_commit", "hypothesis_system", "planner_system"}

    def inspect_blind(value: Any) -> None:
        if isinstance(value, dict):
            leaked = forbidden_keys.intersection(value)
            if leaked:
                raise ValueError(f"blind export contains private key(s): {sorted(leaked)}")
            for child in value.values():
                inspect_blind(child)
        elif isinstance(value, list):
            for child in value:
                inspect_blind(child)

    inspect_blind(blind)
    template_items = [
        {
            "blind_id": row["blind_id"],
            "candidate_index": candidate["candidate_index"],
            "domain": None,
            "substantive_mechanism": None,
            "fidelity": None,
            "unsupported_attribution": None,
            "generic_output": None,
        }
        for row in items if row.get("stage") == "hypothesis"
        for candidate in row.get("candidates", [])
    ]
    package = {
        "schema_version": "topic-scope-grading-package/v1",
        "blind_input_sha256": _sha(blind),
        "blind_input": blind,
        "annotation_template": {
            "schema_version": ANNOTATION_VERSION,
            "reviewer": "<fill independent reviewer identity>",
            "reviewer_kind": "human",
            "independent_of_generator": True,
            "items": template_items,
        },
        "instructions": (
            "Fill every null candidate judgment, freeze the annotation file, "
            "and return only that file. Do not request the private arm map."
        ),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_json(destination, package)
    return {
        "path": str(destination),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "blind_input_sha256": package["blind_input_sha256"],
        "candidate_annotation_count": len(template_items),
        "contains_private_arm_map": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--summarize", action="store_true")
    mode.add_argument("--export-grading-package", action="store_true")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir")
    parser.add_argument("--artifact-dir")
    parser.add_argument("--annotations")
    parser.add_argument("--grading-package")
    parser.add_argument("--runtime-budget-s", type=float)
    parser.add_argument("--include-r0", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.plan:
            print(json.dumps(plan_dict(manifest, include_r0=args.include_r0), indent=2))
            return 0
        if args.summarize:
            if not args.artifact_dir or not args.annotations:
                raise ValueError("--summarize requires --artifact-dir and --annotations")
            print(json.dumps(summarize_annotations(args.artifact_dir, args.annotations), indent=2))
            return 0
        if args.export_grading_package:
            if not args.artifact_dir or not args.grading_package:
                raise ValueError("--export-grading-package requires --artifact-dir and --grading-package")
            print(json.dumps(export_grading_package(
                args.artifact_dir, args.grading_package,
                expected_manifest_sha256=manifest["_raw_sha256"],
            ), indent=2))
            return 0
        if not args.output_dir or args.runtime_budget_s is None:
            raise ValueError("--run requires --output-dir and --runtime-budget-s")
        if os.environ.get("MOCK_LLM"):
            raise ValueError("REFUSE live diagnostic while MOCK_LLM is set")
        result = run_experiment(
            manifest, output_dir=args.output_dir, runtime_budget_s=args.runtime_budget_s,
            include_r0=args.include_r0,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "awaiting_annotation" else 1
    except (ManifestError, ValueError, OSError) as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
