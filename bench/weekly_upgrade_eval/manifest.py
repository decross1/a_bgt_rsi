"""Load and validate immutable inputs for the weekly paired canary.

This module is intentionally stdlib-only and side-effect free.  In particular,
loading or rendering a plan never imports ``agent_wrapper`` and cannot contact
a model server.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST_PATH = Path(__file__).with_name("fixtures.json")
SCHEMA_VERSION = "weekly-upgrade-eval-manifest/v1"

GRADER_VERSIONS = {
    "zero_sum_equilibrium": "1",
    "external_regret": "1",
    "repeated_pd_trace": "1",
    "critic_classification": "1",
    "evidence_attribution": "1",
    "tool_semantics": "1",
}

_FAMILIES = {"game_theory", "critic", "evidence", "tool"}
_MODES = {"chat", "tools"}
_ARM_KEYS = {
    "id", "label", "backend", "profile", "model", "max_tokens",
    "request_timeout_s", "seed",
}
_TASK_KEYS = {
    "id", "family", "mode", "system", "prompt", "grader", "tools",
}
_MANIFEST_KEYS = {
    "schema_version", "suite_id", "description", "bootstrap_seed",
    "bootstrap_samples", "ordering", "arms", "tasks", "source_snapshot",
}


class ManifestError(ValueError):
    """Raised when a manifest is ambiguous, incomplete, or internally invalid."""


def canonical_json(value: Any) -> bytes:
    """Return a stable UTF-8 JSON representation used by all content hashes."""
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ManifestError(f"duplicate JSON key: {key!r}")
        obj[key] = value
    return obj


def _expect_keys(obj: dict[str, Any], allowed: set[str], where: str) -> None:
    extra = sorted(set(obj) - allowed)
    if extra:
        raise ManifestError(f"{where} has unknown field(s): {', '.join(extra)}")


def _nonempty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where} must be a non-empty string")
    return value


def _positive_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{where} must be a positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ManifestError(f"{where} must be finite and > 0")
    return number


def _finite_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{where} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ManifestError(f"{where} must be a finite number")
    return number


@dataclass(frozen=True)
class Arm:
    id: str
    label: str
    backend: str
    profile: str
    model: str | None
    max_tokens: int
    request_timeout_s: float
    seed: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "backend": self.backend,
            "profile": self.profile,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "request_timeout_s": self.request_timeout_s,
            "seed": self.seed,
        }


@dataclass(frozen=True)
class Task:
    id: str
    family: str
    mode: str
    system: str
    prompt: str
    grader: dict[str, Any]
    tools: tuple[dict[str, Any], ...]
    input_sha256: str
    grader_sha256: str

    def as_dict(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "id": self.id,
            "family": self.family,
            "mode": self.mode,
            "system": self.system,
            "prompt": self.prompt,
            "grader": self.grader,
        }
        if self.tools:
            doc["tools"] = list(self.tools)
        return doc


@dataclass(frozen=True)
class EvaluationManifest:
    path: Path
    raw_sha256: str
    schema_version: str
    suite_id: str
    description: str
    bootstrap_seed: int
    bootstrap_samples: int
    ordering: str
    arms: tuple[Arm, Arm]
    tasks: tuple[Task, ...]
    source_snapshot: dict[str, Any] | None
    configuration_sha256: str

    @property
    def arm_ids(self) -> tuple[str, str]:
        return self.arms[0].id, self.arms[1].id

    def plan_dict(self) -> dict[str, Any]:
        first, second = self.arm_ids
        pair_order = [
            {
                "task_id": task.id,
                "family": task.family,
                "order": [first, second] if index % 2 == 0 else [second, first],
                "input_sha256": task.input_sha256,
                "grader_sha256": task.grader_sha256,
            }
            for index, task in enumerate(self.tasks)
        ]
        return {
            "schema_version": self.schema_version,
            "suite_id": self.suite_id,
            "manifest_path": str(self.path),
            "manifest_sha256": self.raw_sha256,
            "configuration_sha256": self.configuration_sha256,
            "ordering": self.ordering,
            "arms": [arm.as_dict() for arm in self.arms],
            "task_count": len(self.tasks),
            "planned_invocations": len(self.tasks) * 2,
            "pair_order": pair_order,
            "source_snapshot": self.source_snapshot,
            "notice": (
                "Descriptive canary only. This plan contains no promotion "
                "threshold and grants no production authority."
            ),
        }


def _validate_arm(raw: Any, index: int) -> Arm:
    where = f"arms[{index}]"
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be an object")
    _expect_keys(raw, _ARM_KEYS, where)
    missing = sorted((_ARM_KEYS - {"model", "seed"}) - set(raw))
    if missing:
        raise ManifestError(f"{where} is missing: {', '.join(missing)}")
    model = raw.get("model")
    if model is not None:
        model = _nonempty_string(model, f"{where}.model")
    max_tokens = raw["max_tokens"]
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise ManifestError(f"{where}.max_tokens must be an integer >= 1")
    seed = raw.get("seed")
    if seed is not None and (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or seed < -(2 ** 63)
        or seed > 2 ** 63 - 1
    ):
        raise ManifestError(f"{where}.seed must be null or a signed 64-bit integer")
    return Arm(
        id=_nonempty_string(raw["id"], f"{where}.id"),
        label=_nonempty_string(raw["label"], f"{where}.label"),
        backend=_nonempty_string(raw["backend"], f"{where}.backend"),
        profile=_nonempty_string(raw["profile"], f"{where}.profile"),
        model=model,
        max_tokens=max_tokens,
        request_timeout_s=_positive_number(
            raw["request_timeout_s"], f"{where}.request_timeout_s"
        ),
        seed=seed,
    )


def _validate_tool(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be an object")
    allowed = {"name", "description", "parameters", "expected_arguments", "result"}
    _expect_keys(raw, allowed, where)
    missing = sorted(allowed - set(raw))
    if missing:
        raise ManifestError(f"{where} is missing: {', '.join(missing)}")
    _nonempty_string(raw["name"], f"{where}.name")
    _nonempty_string(raw["description"], f"{where}.description")
    if not isinstance(raw["parameters"], dict):
        raise ManifestError(f"{where}.parameters must be an object")
    if not isinstance(raw["expected_arguments"], dict):
        raise ManifestError(f"{where}.expected_arguments must be an object")
    parameters = raw["parameters"]
    if parameters.get("type") != "object" or not isinstance(
        parameters.get("properties"), dict
    ):
        raise ManifestError(f"{where}.parameters must define object properties")
    if any(not isinstance(spec, dict) for spec in parameters["properties"].values()):
        raise ManifestError(f"{where}.parameters property schemas must be objects")
    if parameters.get("additionalProperties") is not False:
        raise ManifestError(
            f"{where}.parameters must set additionalProperties=false"
        )
    required = parameters.get("required")
    if (
        not isinstance(required, list)
        or any(not isinstance(name, str) for name in required)
        or len(required) != len(set(required))
        or not set(required).issubset(parameters["properties"])
    ):
        raise ManifestError(f"{where}.parameters.required is invalid")
    if set(raw["expected_arguments"]) != set(required):
        raise ManifestError(
            f"{where}.expected_arguments must cover exactly the required arguments"
        )
    for name, value in raw["expected_arguments"].items():
        declared_type = parameters["properties"][name].get("type")
        type_ok = {
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
        }.get(declared_type, False)
        if not type_ok:
            raise ManifestError(
                f"{where}.expected_arguments.{name} does not match its simple type"
            )
    canonical_json(raw)
    return raw


def _validate_grader(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be an object")
    kind = _nonempty_string(raw.get("kind"), f"{where}.kind")
    if kind not in GRADER_VERSIONS:
        raise ManifestError(f"{where}.kind is unsupported: {kind!r}")
    if not isinstance(raw.get("expected"), dict):
        raise ManifestError(f"{where}.expected must be an object")
    allowed = {"kind", "expected", "absolute_tolerance"}
    _expect_keys(raw, allowed, where)
    tolerance = raw.get("absolute_tolerance", 1e-6)
    numeric_kinds = {
        "zero_sum_equilibrium", "external_regret", "repeated_pd_trace",
        "tool_semantics",
    }
    if kind in numeric_kinds:
        _positive_number(tolerance, f"{where}.absolute_tolerance")
    elif "absolute_tolerance" in raw:
        raise ManifestError(f"{where}.absolute_tolerance is unused for {kind}")

    expected = raw["expected"]
    expected_keys = {
        "zero_sum_equilibrium": {"row_mixture", "column_mixture", "value"},
        "external_regret": {
            "chosen_total", "best_fixed_total", "total_external_regret",
            "average_external_regret",
        },
        "repeated_pd_trace": {
            "player1_actions", "player2_actions", "player1_total",
            "player2_total",
        },
        "critic_classification": {"verdict", "reason_code"},
        "evidence_attribution": {"answer_code", "citations"},
        "tool_semantics": {"tool_name", "arguments", "answer"},
    }[kind]
    if set(expected) != expected_keys:
        raise ManifestError(
            f"{where}.expected fields must be exactly {sorted(expected_keys)}"
        )
    if kind == "zero_sum_equilibrium":
        for key in ("row_mixture", "column_mixture"):
            mixture = expected[key]
            if (
                not isinstance(mixture, list)
                or len(mixture) != 2
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in mixture
                )
            ):
                raise ManifestError(f"{where}.expected.{key} must have two finite numbers")
        _finite_number(expected["value"], f"{where}.expected.value")
    elif kind == "external_regret":
        for key, value in expected.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ManifestError(f"{where}.expected.{key} must be finite")
    elif kind == "repeated_pd_trace":
        for key in ("player1_actions", "player2_actions"):
            actions = expected[key]
            if not isinstance(actions, list) or not actions or any(
                action not in {"C", "D"} for action in actions
            ):
                raise ManifestError(f"{where}.expected.{key} must be a C/D trace")
        for key in ("player1_total", "player2_total"):
            value = expected[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ManifestError(f"{where}.expected.{key} must be finite")
    elif kind == "critic_classification":
        if expected["verdict"] not in {"fatal_flaw", "proceed"}:
            raise ManifestError(f"{where}.expected.verdict is invalid")
        _nonempty_string(expected["reason_code"], f"{where}.expected.reason_code")
    elif kind == "evidence_attribution":
        _nonempty_string(expected["answer_code"], f"{where}.expected.answer_code")
        citations = expected["citations"]
        if (
            not isinstance(citations, list)
            or not citations
            or any(not isinstance(item, str) or not item for item in citations)
            or len(citations) != len(set(citations))
        ):
            raise ManifestError(
                f"{where}.expected.citations must be unique document IDs"
            )
    elif kind == "tool_semantics":
        _nonempty_string(expected["tool_name"], f"{where}.expected.tool_name")
        if not isinstance(expected["arguments"], dict):
            raise ManifestError(f"{where}.expected.arguments must be an object")
        if not isinstance(expected["answer"], dict):
            raise ManifestError(f"{where}.expected.answer must be an object")
    canonical_json(raw)
    return raw


def _validate_task(raw: Any, index: int) -> Task:
    where = f"tasks[{index}]"
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be an object")
    _expect_keys(raw, _TASK_KEYS, where)
    required = {"id", "family", "mode", "system", "prompt", "grader"}
    missing = sorted(required - set(raw))
    if missing:
        raise ManifestError(f"{where} is missing: {', '.join(missing)}")
    family = _nonempty_string(raw["family"], f"{where}.family")
    if family not in _FAMILIES:
        raise ManifestError(f"{where}.family is unsupported: {family!r}")
    mode = _nonempty_string(raw["mode"], f"{where}.mode")
    if mode not in _MODES:
        raise ManifestError(f"{where}.mode is unsupported: {mode!r}")
    tools_raw = raw.get("tools", [])
    if not isinstance(tools_raw, list):
        raise ManifestError(f"{where}.tools must be an array")
    tools = tuple(
        _validate_tool(tool, f"{where}.tools[{tool_index}]")
        for tool_index, tool in enumerate(tools_raw)
    )
    if mode == "tools" and not tools:
        raise ManifestError(f"{where} is a tools task but defines no tools")
    if mode == "chat" and tools:
        raise ManifestError(f"{where} is a chat task but defines tools")
    tool_names = [tool["name"] for tool in tools]
    if len(tool_names) != len(set(tool_names)):
        raise ManifestError(f"{where} has duplicate tool names")
    grader = _validate_grader(raw["grader"], f"{where}.grader")
    if (mode == "tools") != (grader["kind"] == "tool_semantics"):
        raise ManifestError(f"{where} must pair tools mode with tool_semantics grader")
    if mode == "tools":
        expected = grader["expected"]
        by_name = {tool["name"]: tool for tool in tools}
        if expected["tool_name"] not in by_name:
            raise ManifestError(
                f"{where}.grader expects unavailable tool {expected['tool_name']!r}"
            )
        if expected["arguments"] != by_name[expected["tool_name"]]["expected_arguments"]:
            raise ManifestError(
                f"{where}.grader arguments differ from the tool fixture arguments"
            )

    task_id = _nonempty_string(raw["id"], f"{where}.id")
    system = _nonempty_string(raw["system"], f"{where}.system")
    prompt = _nonempty_string(raw["prompt"], f"{where}.prompt")
    input_doc = {
        "id": task_id,
        "family": family,
        "mode": mode,
        "system": system,
        "prompt": prompt,
        "tools": list(tools),
    }
    grader_doc = {
        "grader": grader,
        "implementation_version": GRADER_VERSIONS[grader["kind"]],
    }
    return Task(
        id=task_id,
        family=family,
        mode=mode,
        system=system,
        prompt=prompt,
        grader=grader,
        tools=tools,
        input_sha256=sha256_json(input_doc),
        grader_sha256=sha256_json(grader_doc),
    )


def load_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> EvaluationManifest:
    """Load a manifest and freeze its raw, configuration, input, and grader hashes."""
    manifest_path = Path(path).resolve()
    try:
        raw_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {manifest_path}: {exc}") from exc
    try:
        doc = json.loads(raw_bytes, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestError(f"invalid JSON in {manifest_path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise ManifestError("manifest root must be an object")
    _expect_keys(doc, _MANIFEST_KEYS, "manifest")
    required = _MANIFEST_KEYS - {"source_snapshot"}
    missing = sorted(required - set(doc))
    if missing:
        raise ManifestError(f"manifest is missing: {', '.join(missing)}")
    if doc["schema_version"] != SCHEMA_VERSION:
        raise ManifestError(
            f"unsupported schema_version {doc['schema_version']!r}; expected {SCHEMA_VERSION!r}"
        )
    if doc["ordering"] != "alternating_ab_ba":
        raise ManifestError("ordering must be 'alternating_ab_ba'")
    arms_raw = doc["arms"]
    if not isinstance(arms_raw, list) or len(arms_raw) != 2:
        raise ManifestError("arms must contain exactly two configurations")
    arms = (_validate_arm(arms_raw[0], 0), _validate_arm(arms_raw[1], 1))
    if arms[0].id == arms[1].id:
        raise ManifestError("arm ids must be unique")
    tasks_raw = doc["tasks"]
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise ManifestError("tasks must be a non-empty array")
    tasks = tuple(_validate_task(task, index) for index, task in enumerate(tasks_raw))
    task_ids = [task.id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ManifestError("task ids must be unique")
    bootstrap_seed = doc["bootstrap_seed"]
    bootstrap_samples = doc["bootstrap_samples"]
    if isinstance(bootstrap_seed, bool) or not isinstance(bootstrap_seed, int):
        raise ManifestError("bootstrap_seed must be an integer")
    if (
        isinstance(bootstrap_samples, bool)
        or not isinstance(bootstrap_samples, int)
        or bootstrap_samples < 100
        or bootstrap_samples > 100_000
    ):
        raise ManifestError("bootstrap_samples must be an integer in [100, 100000]")
    source_snapshot = doc.get("source_snapshot")
    if source_snapshot is not None:
        if not isinstance(source_snapshot, dict):
            raise ManifestError("source_snapshot must be an object or null")
        _expect_keys(source_snapshot, {"path", "sha256"}, "source_snapshot")
        _nonempty_string(source_snapshot.get("path"), "source_snapshot.path")
        digest = _nonempty_string(source_snapshot.get("sha256"), "source_snapshot.sha256")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ManifestError("source_snapshot.sha256 must be lowercase SHA-256 hex")

    config_doc = {
        "schema_version": SCHEMA_VERSION,
        "suite_id": doc["suite_id"],
        "ordering": doc["ordering"],
        "arms": [arm.as_dict() for arm in arms],
        "task_inputs": {task.id: task.input_sha256 for task in tasks},
        "task_graders": {task.id: task.grader_sha256 for task in tasks},
        "bootstrap_seed": bootstrap_seed,
        "bootstrap_samples": bootstrap_samples,
    }
    return EvaluationManifest(
        path=manifest_path,
        raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        schema_version=SCHEMA_VERSION,
        suite_id=_nonempty_string(doc["suite_id"], "suite_id"),
        description=_nonempty_string(doc["description"], "description"),
        bootstrap_seed=bootstrap_seed,
        bootstrap_samples=bootstrap_samples,
        ordering=doc["ordering"],
        arms=arms,
        tasks=tasks,
        source_snapshot=source_snapshot,
        configuration_sha256=sha256_json(config_doc),
    )
