"""Definition publication and one-arm execution binding.

Draft construction, publication, and execution binding are intentionally
separate.  A timestamp in generated source is not publication: a published
definition must carry an external Git or preregistration witness.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fixtures import REVIEW_AT, draft_definition


DEFINITION_SCHEMA = "stable-benchmark-definition/v1"
RUN_MANIFEST_SCHEMA = "stable-benchmark-run-manifest/v1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedDocument:
    document: dict[str, Any]
    raw_sha256: str
    path: Path | None = None


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
        raise ManifestError(f"document is not canonical JSON: {exc}") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ManifestError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _reject_constant(value: str) -> Any:
    raise ManifestError(f"non-finite JSON constant {value!r}")


def _read_regular(path: Path | str, *, limit: int) -> tuple[Path, bytes]:
    target = Path(path).expanduser().absolute()
    try:
        before = target.lstat()
    except OSError as exc:
        raise ManifestError(f"cannot stat {target}: {exc}") from exc
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise ManifestError(f"document is not a regular non-symlink file: {target}")
    if before.st_size > limit:
        raise ManifestError(f"document exceeds {limit} bytes: {target}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags)
        try:
            observed = os.fstat(descriptor)
            if (observed.st_dev, observed.st_ino) != (before.st_dev, before.st_ino):
                raise ManifestError("document identity changed during open")
            chunks: list[bytes] = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ManifestError(f"cannot safely read {target}: {exc}") from exc
    if len(raw) > limit or len(raw) != before.st_size:
        raise ManifestError("document size changed or exceeded its bound during read")
    return target, raw


def _bound_json_shape(value: Any, *, max_depth: int = 32, max_nodes: int = 50000) -> None:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise ManifestError("JSON document exceeds structural bounds")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ManifestError("JSON object key is not text")
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _utc(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ManifestError(f"{where} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ManifestError(f"{where} is not a valid timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ManifestError(f"{where} must be UTC")
    return parsed


def _digest(value: Any, where: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ManifestError(f"{where} must be a lowercase SHA-256 digest")
    return value


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise ManifestError(f"{where} is not a safe identifier")
    return value


def _validate_tool(tool: Any, where: str) -> None:
    if not isinstance(tool, dict) or set(tool) != {
        "name", "description", "parameters", "fixtures"
    }:
        raise ManifestError(f"{where} has an invalid tool shape")
    _identifier(tool["name"], f"{where}.name")
    if not isinstance(tool["description"], str) or not tool["description"]:
        raise ManifestError(f"{where}.description must be nonempty")
    if not isinstance(tool["parameters"], dict) or tool["parameters"].get("type") != "object":
        raise ManifestError(f"{where}.parameters must be an object JSON schema")
    if not isinstance(tool["fixtures"], list):
        raise ManifestError(f"{where}.fixtures must be an array")
    for index, fixture in enumerate(tool["fixtures"]):
        if not isinstance(fixture, dict) or set(fixture) != {"arguments", "result"}:
            raise ManifestError(f"{where}.fixtures[{index}] has an invalid shape")
        if not isinstance(fixture["arguments"], dict):
            raise ManifestError(f"{where}.fixtures[{index}].arguments must be an object")


def validate_definition(document: Any, *, require_published: bool = False) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ManifestError("definition must be an object")
    required = {
        "schema_version", "suite_id", "release", "description", "baseline_status",
        "historical_comparability", "freeze", "panels", "tasks", "resource_envelope",
        "reporting", "external_rotations",
    }
    if set(document) != required:
        raise ManifestError("definition top-level fields differ from the frozen contract")
    if document["schema_version"] != DEFINITION_SCHEMA:
        raise ManifestError("definition schema version differs")
    _identifier(document["suite_id"], "suite_id")
    if document["release"] != "1.0.0" or document["baseline_status"] != "not_started":
        raise ManifestError("release or initial baseline status differs")
    freeze = document["freeze"]
    if not isinstance(freeze, dict) or set(freeze) != {
        "status", "published_at", "review_at", "expiry_action", "witness"
    }:
        raise ManifestError("freeze contract differs")
    if freeze["review_at"] != REVIEW_AT or freeze["expiry_action"] != "review_required":
        raise ManifestError("freeze review boundary or action differs")
    _utc(freeze["review_at"], "freeze.review_at")
    if freeze["status"] == "draft":
        if freeze["published_at"] is not None or freeze["witness"] is not None:
            raise ManifestError("draft freeze cannot carry publication evidence")
        if require_published:
            raise ManifestError("runner refuses an unpublished draft definition")
    elif freeze["status"] == "published":
        published = _utc(freeze["published_at"], "freeze.published_at")
        review = _utc(freeze["review_at"], "freeze.review_at")
        if not published < review:
            raise ManifestError("publication must precede the review boundary")
        witness = freeze["witness"]
        if not isinstance(witness, dict) or set(witness) != {"kind", "ref", "sha256"}:
            raise ManifestError("publication witness shape differs")
        if witness["kind"] not in {"git_commit", "preregistration_receipt"}:
            raise ManifestError("publication witness kind is unsupported")
        if not isinstance(witness["ref"], str) or not witness["ref"]:
            raise ManifestError("publication witness ref must be nonempty")
        _digest(witness["sha256"], "freeze.witness.sha256")
    else:
        raise ManifestError("freeze.status must be draft or published")

    tasks = document["tasks"]
    if not isinstance(tasks, list) or len(tasks) != 21:
        raise ManifestError("definition must contain 18 capability tasks and 3 system missions")
    task_ids: list[str] = []
    model_calls = 0
    output_tokens = 0
    episode_runtime = 0
    for index, task in enumerate(tasks):
        where = f"tasks[{index}]"
        if not isinstance(task, dict):
            raise ManifestError(f"{where} must be an object")
        expected = {
            "id", "panel", "domain", "construct", "mode", "system", "prompt",
            "grader", "tools", "resource", "provenance",
        }
        if set(task) != expected:
            raise ManifestError(f"{where} fields differ")
        task_ids.append(_identifier(task["id"].lower(), f"{where}.id"))
        if not isinstance(task["id"], str) or task["id"] != task["id"].upper():
            raise ManifestError(f"{where}.id must use the frozen uppercase spelling")
        if task["mode"] not in {"chat", "code", "tools", "strategic", "system_mission"}:
            raise ManifestError(f"{where}.mode is unsupported")
        for tool_index, tool in enumerate(task["tools"]):
            _validate_tool(tool, f"{where}.tools[{tool_index}]")
        resource = task["resource"]
        if not isinstance(resource, dict) or set(resource) != {
            "max_tokens_per_call", "episode_timeout_s", "max_model_calls"
        }:
            raise ManifestError(f"{where}.resource differs")
        for key in resource:
            if isinstance(resource[key], bool) or not isinstance(resource[key], int) or resource[key] < 1:
                raise ManifestError(f"{where}.resource.{key} must be a positive integer")
        model_calls += resource["max_model_calls"]
        output_tokens += resource["max_model_calls"] * resource["max_tokens_per_call"]
        episode_runtime += resource["episode_timeout_s"]
    if len(set(task_ids)) != len(task_ids):
        raise ManifestError("task IDs must be unique")
    capability = [task for task in tasks if task["panel"] == "model_capability"]
    system = [task for task in tasks if task["panel"] == "system_micro_workflow"]
    if len(capability) != 18 or len(system) != 3:
        raise ManifestError("panel task counts differ")
    if set(task["construct"] for task in capability if task["domain"] == "strategic_behavior") != {
        "public_goods", "vickrey_auction", "cournot", "proper_scoring_reporting"
    }:
        raise ManifestError("strategic mechanisms differ")
    reporting = document["reporting"]
    required_reporting = {
        "no_omnibus_score", "descriptive_family_counts",
        "strategic_mechanism_counts", "family_count_interpretation",
        "strategic_metrics", "strategic_grouping",
        "strategic_regret_aggregation", "system_claim_scope",
        "independent_unit", "uncertainty", "promotion_from_small_n",
    }
    if not isinstance(reporting, dict) or set(reporting) != required_reporting:
        raise ManifestError("reporting contract fields differ")
    expected_families = {
        domain: sum(task["domain"] == domain for task in tasks)
        for domain in (
            "science_evidence", "functional_code_repair",
            "deterministic_tool_use", "system_harness",
        )
    }
    expected_mechanisms = {
        mechanism: sum(
            task["domain"] == "strategic_behavior" and task["construct"] == mechanism
            for task in tasks
        )
        for mechanism in (
            "public_goods", "vickrey_auction", "cournot", "proper_scoring_reporting",
        )
    }
    if reporting["descriptive_family_counts"] != expected_families:
        raise ManifestError("descriptive family denominators differ from the tasks")
    if reporting["strategic_mechanism_counts"] != expected_mechanisms:
        raise ManifestError("strategic mechanism denominators differ from the tasks")
    if (
        reporting["no_omnibus_score"] is not True
        or reporting["family_count_interpretation"]
        != "binary_objective_completion_descriptive_canary_only"
        or reporting["strategic_grouping"] != "mechanism"
        or reporting["strategic_regret_aggregation"] != "within_mechanism_only"
        or reporting["promotion_from_small_n"] != "never_automatic"
    ):
        raise ManifestError("reporting interpretation or promotion contract differs")
    envelope = document["resource_envelope"]
    if (
        envelope.get("max_model_calls_per_arm") != model_calls
        or envelope.get("max_model_calls_paired") != 2 * model_calls
        or envelope.get("max_output_tokens_per_arm") != output_tokens
        or envelope.get("max_episode_runtime_s_per_arm") != episode_runtime
        or envelope.get("max_supervised_window_s") != 7200
        or envelope.get("paid_api_cost_usd") != 0
    ):
        raise ManifestError("resource envelope does not equal the task-level ceilings")
    canonical_json(document)
    return document


def publish_definition(
    draft: dict[str, Any],
    *,
    published_at: str,
    witness: dict[str, str],
) -> dict[str, Any]:
    """Bind a draft to an external publication witness.

    This function does not invent the timestamp or witness.  The caller must
    obtain them from the public commit or preregistration receipt.
    """
    validate_definition(draft)
    if draft["freeze"]["status"] != "draft":
        raise ManifestError("only a draft definition can be published")
    result = deepcopy(draft)
    result["freeze"] = {
        "status": "published",
        "published_at": published_at,
        "review_at": REVIEW_AT,
        "expiry_action": "review_required",
        "witness": deepcopy(witness),
    }
    validate_definition(result, require_published=True)
    return result


_ARM_FIELDS = {"id", "label", "seed", "routes", "role_map"}
_ROLE_KEYS = {"capability", "system_actor", "system_critic"}
_ROUTE_FIELDS = {"backend", "model", "profile", "expected_policy", "runtime_identity"}
_POLICY_FIELDS = {"temperature", "top_p", "reasoning_effort", "sampling_extra"}
_SAMPLING_EXTRA_FIELDS = {
    "top_k", "min_p", "presence_penalty", "repetition_penalty",
    "chat_template_kwargs",
}


def _bounded_route_text(value: Any, where: str, *, maximum: int = 200) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ManifestError(f"{where} must be nonempty bounded printable text")


def _validate_sampling_extra(value: Any, where: str) -> None:
    if not isinstance(value, dict) or not set(value).issubset(_SAMPLING_EXTRA_FIELDS):
        raise ManifestError(f"{where} contains unsupported policy fields")
    if "top_k" in value:
        top_k = value["top_k"]
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 0 <= top_k <= 100000:
            raise ManifestError(f"{where}.top_k must be an integer in [0,100000]")
    for key, lower, upper, lower_open in (
        ("min_p", 0.0, 1.0, False),
        ("presence_penalty", -2.0, 2.0, False),
        ("repetition_penalty", 0.0, 10.0, True),
    ):
        if key not in value:
            continue
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ManifestError(f"{where}.{key} must be finite")
        number = float(item)
        if number > upper or number < lower or (lower_open and number == lower):
            interval = f"({lower},{upper}]" if lower_open else f"[{lower},{upper}]"
            raise ManifestError(f"{where}.{key} must be in {interval}")
    if "chat_template_kwargs" in value:
        kwargs = value["chat_template_kwargs"]
        if not isinstance(kwargs, dict) or set(kwargs) != {"enable_thinking"} or not isinstance(kwargs["enable_thinking"], bool):
            raise ManifestError(
                f"{where}.chat_template_kwargs must bind only boolean enable_thinking"
            )


def validate_arm(arm: Any) -> dict[str, Any]:
    if not isinstance(arm, dict) or set(arm) != _ARM_FIELDS:
        raise ManifestError("arm fields differ from the execution contract")
    _identifier(arm["id"], "arm.id")
    _bounded_route_text(arm["label"], "arm.label", maximum=160)
    if (
        isinstance(arm["seed"], bool) or not isinstance(arm["seed"], int)
        or not 0 <= arm["seed"] <= 2**31 - 1
    ):
        raise ManifestError("arm.seed must be an integer in [0,2^31-1]")
    role_map = arm["role_map"]
    routes = arm["routes"]
    if not isinstance(role_map, dict) or set(role_map) != _ROLE_KEYS:
        raise ManifestError("arm.role_map must bind capability, system_actor, and system_critic")
    if not isinstance(routes, dict) or not routes:
        raise ManifestError("arm.routes must contain at least one route")
    for role, route_id in role_map.items():
        _identifier(route_id, f"arm.role_map.{role}")
        if route_id not in routes:
            raise ManifestError(f"arm.role_map.{role} names an absent route")
    if set(routes) != set(role_map.values()):
        raise ManifestError("arm.routes must contain exactly the routes used by role_map")
    for route_id, route in routes.items():
        _identifier(route_id, f"arm.routes.{route_id}")
        if not isinstance(route, dict) or set(route) != _ROUTE_FIELDS:
            raise ManifestError(f"arm.routes.{route_id} fields differ")
        for key in ("backend", "model", "profile"):
            _bounded_route_text(route[key], f"arm.routes.{route_id}.{key}")
        policy = route["expected_policy"]
        if not isinstance(policy, dict) or set(policy) != _POLICY_FIELDS:
            raise ManifestError(
                f"arm.routes.{route_id}.expected_policy must bind every supported resolved lever"
            )
        temperature = policy["temperature"]
        top_p = policy["top_p"]
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(float(temperature))
            or not 0 <= float(temperature) <= 2
        ):
            raise ManifestError(
                f"arm.routes.{route_id}.expected_policy.temperature must be in [0,2]"
            )
        if (
            isinstance(top_p, bool)
            or not isinstance(top_p, (int, float))
            or not math.isfinite(float(top_p))
            or not 0 < float(top_p) <= 1
        ):
            raise ManifestError(
                f"arm.routes.{route_id}.expected_policy.top_p must be in (0,1]"
            )
        effort = policy["reasoning_effort"]
        if effort is not None and effort not in {"low", "medium", "xhigh"}:
            raise ManifestError(f"arm.routes.{route_id}.expected_policy.reasoning_effort is invalid")
        _validate_sampling_extra(
            policy["sampling_extra"],
            f"arm.routes.{route_id}.expected_policy.sampling_extra",
        )
        identity = route["runtime_identity"]
        required = {"served_model", "artifact_sha256", "runtime_sha256", "max_context_tokens"}
        if not isinstance(identity, dict) or set(identity) != required:
            raise ManifestError(f"arm.routes.{route_id}.runtime_identity fields differ")
        if identity["served_model"] != route["model"]:
            raise ManifestError(f"arm.routes.{route_id} served and requested models differ")
        _digest(identity["artifact_sha256"], f"arm.routes.{route_id}.runtime_identity.artifact_sha256")
        _digest(identity["runtime_sha256"], f"arm.routes.{route_id}.runtime_identity.runtime_sha256")
        if (
            isinstance(identity["max_context_tokens"], bool)
            or not isinstance(identity["max_context_tokens"], int)
            or not 4096 <= identity["max_context_tokens"] <= 1_000_000
        ):
            raise ManifestError(f"arm.routes.{route_id}.runtime_identity.max_context_tokens is invalid")
    return arm


def validate_harness_identity(identity: Any) -> dict[str, Any]:
    if not isinstance(identity, dict) or set(identity) != {
        "scaffold_id", "transport_contract", "source_sha256"
    }:
        raise ManifestError("harness identity fields differ")
    _identifier(identity["scaffold_id"], "harness_identity.scaffold_id")
    if identity["transport_contract"] != "injected-supervised-endpoint/v1":
        raise ManifestError("harness transport contract differs")
    sources = identity["source_sha256"]
    if not isinstance(sources, dict) or not sources:
        raise ManifestError("harness source bundle is empty")
    for path, digest in sources.items():
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
            raise ManifestError("harness source path is unsafe")
        _digest(digest, f"harness_identity.source_sha256[{path!r}]")
    return identity


def bind_run_manifest(
    definition: LoadedDocument | dict[str, Any],
    *,
    arm: dict[str, Any],
    comparison_id: str,
    harness_identity: dict[str, Any],
) -> dict[str, Any]:
    document = definition.document if isinstance(definition, LoadedDocument) else definition
    validate_definition(document, require_published=True)
    validate_arm(arm)
    validate_harness_identity(harness_identity)
    _identifier(comparison_id, "comparison_id")
    definition_sha = (
        definition.raw_sha256 if isinstance(definition, LoadedDocument) else sha256_json(document)
    )
    return {
        "schema_version": RUN_MANIFEST_SCHEMA,
        "suite_id": document["suite_id"],
        "release": document["release"],
        "definition_sha256": definition_sha,
        "comparison_id": comparison_id,
        "arm": deepcopy(arm),
        "harness_identity": deepcopy(harness_identity),
        "task_ids": [task["id"] for task in document["tasks"]],
        "resource_envelope": deepcopy(document["resource_envelope"]),
        "ordering": "frozen_definition_order",
        "admission_authorized": False,
    }


def validate_run_manifest(document: Any, definition: LoadedDocument) -> dict[str, Any]:
    required = {
        "schema_version", "suite_id", "release", "definition_sha256", "comparison_id",
        "arm", "harness_identity", "task_ids", "resource_envelope", "ordering",
        "admission_authorized",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise ManifestError("run manifest fields differ")
    if document["schema_version"] != RUN_MANIFEST_SCHEMA:
        raise ManifestError("run manifest schema differs")
    validate_definition(definition.document, require_published=True)
    if document["definition_sha256"] != definition.raw_sha256:
        raise ManifestError("run manifest definition hash differs")
    if document["suite_id"] != definition.document["suite_id"] or document["release"] != definition.document["release"]:
        raise ManifestError("run manifest suite identity differs")
    if document["task_ids"] != [task["id"] for task in definition.document["tasks"]]:
        raise ManifestError("run manifest task order differs")
    if document["resource_envelope"] != definition.document["resource_envelope"]:
        raise ManifestError("run manifest resource envelope differs")
    if document["ordering"] != "frozen_definition_order" or document["admission_authorized"] is not False:
        raise ManifestError("run ordering or authority differs")
    _identifier(document["comparison_id"], "comparison_id")
    validate_arm(document["arm"])
    validate_harness_identity(document["harness_identity"])
    canonical_json(document)
    return document


def write_document(path: Path | str, document: dict[str, Any], *, exclusive: bool = True) -> str:
    raw = canonical_json(document) + b"\n"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "xb" if exclusive else "wb"
    with target.open(mode) as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def load_definition(path: Path | str, *, require_published: bool = False) -> LoadedDocument:
    target, raw = _read_regular(path, limit=1_000_000)
    try:
        document = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ManifestError) as exc:
        raise ManifestError(f"cannot decode definition: {exc}") from exc
    _bound_json_shape(document)
    validate_definition(document, require_published=require_published)
    return LoadedDocument(document, hashlib.sha256(raw).hexdigest(), target)


def load_run_manifest(path: Path | str, definition: LoadedDocument) -> LoadedDocument:
    target, raw = _read_regular(path, limit=262_144)
    try:
        document = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ManifestError) as exc:
        raise ManifestError(f"cannot decode run manifest: {exc}") from exc
    _bound_json_shape(document)
    validate_run_manifest(document, definition)
    return LoadedDocument(document, hashlib.sha256(raw).hexdigest(), target)


def make_draft() -> dict[str, Any]:
    result = draft_definition()
    validate_definition(result)
    return result


__all__ = [
    "LoadedDocument", "ManifestError", "bind_run_manifest", "canonical_json",
    "load_definition", "load_run_manifest", "make_draft", "publish_definition",
    "sha256_json", "validate_arm", "validate_definition", "validate_run_manifest",
    "validate_harness_identity", "write_document",
]
