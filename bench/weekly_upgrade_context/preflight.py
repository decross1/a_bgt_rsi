"""Offline, context-specific admission receipt for the frozen capability panel.

The live trial controller calls :func:`validate_context_preflight` before it
reserves Spark time.  That function reads only checked-in fixtures and cached
tokenizer assets: it neither loads model weights nor contacts a model server.
Recovery uses :func:`validate_preflight_receipt`, which is deliberately pure
and does not reload the comparatively large tokenizer files.
"""
from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bench.weekly_upgrade_context import generate_packs, measure_tokens
from bench.weekly_upgrade_eval.manifest import ManifestError, load_manifest, sha256_json

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_REPO_PATH = "experiments/weekly_context_capability_v1_2026-09-14.json"
MANIFEST_PATH = REPO_ROOT / MANIFEST_REPO_PATH
PACKS_REPO_PATH = "bench/weekly_upgrade_context/packs.json"
PACKS_PATH = REPO_ROOT / PACKS_REPO_PATH
TOKEN_COUNTS_REPO_PATH = "bench/weekly_upgrade_context/token_counts.json"
TOKEN_COUNTS_PATH = REPO_ROOT / TOKEN_COUNTS_REPO_PATH
GENERATOR_REPO_PATH = "bench/weekly_upgrade_context/generate_packs.py"
MEASURE_REPO_PATH = "bench/weekly_upgrade_context/measure_tokens.py"
PREFLIGHT_REPO_PATH = "bench/weekly_upgrade_context/preflight.py"

SCHEMA_VERSION = "weekly-context-preflight/v1"
MINIMUM_MARGIN_TOKENS = 512
MAX_JSON_BYTES = 1_000_000

REPOSITORY_ARTIFACT_PATHS = (
    GENERATOR_REPO_PATH,
    PACKS_REPO_PATH,
    MEASURE_REPO_PATH,
    TOKEN_COUNTS_REPO_PATH,
    PREFLIGHT_REPO_PATH,
)

TASK_IDS = (
    "long_context_8k_grim_threshold",
    "long_context_8k_attrition",
    "long_context_14k_social_choice",
    "long_context_14k_primary_endpoint",
)

MODEL_CONTRACTS = {
    "gemma-4-26b-a4b": {
        "serving_context_limit": 32768,
        "template_policy": {"enable_thinking": False},
    },
    "qwen3.8-27b-nvfp4-mtp": {
        "serving_context_limit": 16384,
        "template_policy": {
            "enable_thinking": True,
            "reasoning_effort": "xhigh",
        },
    },
}

_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "offline",
    "suite_id",
    "manifest_path",
    "manifest_sha256",
    "source_snapshot",
    "repository_artifact_sha256",
    "runtime_libraries",
    "minimum_required_margin_tokens",
    "token_measurement_sha256",
    "token_measurement",
}

_MEASUREMENT_KEYS = {
    "schema_version",
    "measurement_method",
    "offline",
    "transformers_version",
    "tokenizers_version",
    "manifest_sha256",
    "models",
}

_MODEL_KEYS = {
    "tokenizer_class",
    "tokenizer_asset_sha256",
    "chat_template_sha256",
    "template_policy",
    "default_template_matches_explicit_policy",
    "input_tokens_by_task",
    "rendered_input_sha256_by_task",
    "reserved_output_tokens",
    "maximum_total_tokens",
    "serving_context_limit",
    "minimum_context_margin_tokens",
}


class ContextPreflightError(RuntimeError):
    """The frozen context trial cannot be admitted safely."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _exact_keys(value: Any, keys: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ContextPreflightError(f"{where} has an invalid field set")
    return value


def _positive_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContextPreflightError(f"{where} must be a positive integer")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContextPreflightError(f"{where} must be a non-empty string")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContextPreflightError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _read_regular(path: Path, *, maximum_bytes: int = MAX_JSON_BYTES) -> bytes:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ContextPreflightError(f"missing frozen artifact: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ContextPreflightError(f"redirected frozen artifact: {path}")
    if metadata.st_size > maximum_bytes:
        raise ContextPreflightError(f"oversized frozen artifact: {path}")
    return path.read_bytes()


def _read_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = _read_regular(path)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ContextPreflightError(f"non-finite JSON: {constant}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextPreflightError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ContextPreflightError(f"artifact must contain one JSON object: {path}")
    return raw, value


def _validate_digest_map(value: Any, where: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ContextPreflightError(f"{where} must be a non-empty object")
    for key, digest in value.items():
        if not isinstance(key, str) or not key or not _is_digest(digest):
            raise ContextPreflightError(f"{where} contains an invalid digest")
    return value


def _validate_token_measurement(
    measurement: Any,
    manifest_sha256: str,
) -> dict[str, Any]:
    value = _exact_keys(measurement, _MEASUREMENT_KEYS, "token_measurement")
    if value["schema_version"] != "weekly-context-token-counts/v1":
        raise ContextPreflightError("unexpected token-measurement schema")
    if value["offline"] is not True:
        raise ContextPreflightError("token measurement was not offline")
    if value["manifest_sha256"] != manifest_sha256:
        raise ContextPreflightError("token measurement is bound to another manifest")
    if "apply_chat_template" not in _text(
        value["measurement_method"], "token_measurement.measurement_method"
    ):
        raise ContextPreflightError("unexpected token measurement method")
    _text(value["transformers_version"], "token_measurement.transformers_version")
    _text(value["tokenizers_version"], "token_measurement.tokenizers_version")
    models = value["models"]
    if not isinstance(models, dict) or set(models) != set(MODEL_CONTRACTS):
        raise ContextPreflightError("token measurement has the wrong model set")

    for model_id, contract in MODEL_CONTRACTS.items():
        model = _exact_keys(models[model_id], _MODEL_KEYS, f"models.{model_id}")
        _text(model["tokenizer_class"], f"models.{model_id}.tokenizer_class")
        assets = _validate_digest_map(
            model["tokenizer_asset_sha256"],
            f"models.{model_id}.tokenizer_asset_sha256",
        )
        required_assets = {
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "chat_template.jinja",
        }
        if not required_assets.issubset(assets):
            raise ContextPreflightError(f"models.{model_id} lacks tokenizer assets")
        if not set(assets).issubset(measure_tokens.TOKENIZER_ASSET_NAMES):
            raise ContextPreflightError(f"models.{model_id} has unbounded asset names")
        if not _is_digest(model["chat_template_sha256"]):
            raise ContextPreflightError(f"models.{model_id} has an invalid template hash")
        if model["chat_template_sha256"] != assets["chat_template.jinja"]:
            raise ContextPreflightError(f"models.{model_id} template hashes disagree")
        if model["template_policy"] != contract["template_policy"]:
            raise ContextPreflightError(f"models.{model_id} template policy drift")
        if model["default_template_matches_explicit_policy"] is not True:
            raise ContextPreflightError(
                f"models.{model_id} default template policy is not reproduced"
            )

        counts = model["input_tokens_by_task"]
        rendered = model["rendered_input_sha256_by_task"]
        if not isinstance(counts, dict) or set(counts) != set(TASK_IDS):
            raise ContextPreflightError(f"models.{model_id} task counts drift")
        if not isinstance(rendered, dict) or set(rendered) != set(TASK_IDS):
            raise ContextPreflightError(f"models.{model_id} rendered inputs drift")
        for task_id, digest in rendered.items():
            if not _is_digest(digest):
                raise ContextPreflightError(
                    f"models.{model_id}.{task_id} has an invalid rendered hash"
                )
        for task_id, count in counts.items():
            count = _positive_int(count, f"models.{model_id}.{task_id}.input_tokens")
            lower, upper = ((7800, 8500) if "_8k_" in task_id else (13800, 14600))
            if not lower <= count <= upper:
                raise ContextPreflightError(
                    f"models.{model_id}.{task_id} left its declared token band"
                )

        reserve = _positive_int(
            model["reserved_output_tokens"],
            f"models.{model_id}.reserved_output_tokens",
        )
        if reserve != 1024:
            raise ContextPreflightError(f"models.{model_id} output reserve drift")
        limit = _positive_int(
            model["serving_context_limit"],
            f"models.{model_id}.serving_context_limit",
        )
        if limit != contract["serving_context_limit"]:
            raise ContextPreflightError(f"models.{model_id} serving limit drift")
        totals = [count + reserve for count in counts.values()]
        if model["maximum_total_tokens"] != max(totals):
            raise ContextPreflightError(f"models.{model_id} maximum total is invalid")
        margin = min(limit - total for total in totals)
        if model["minimum_context_margin_tokens"] != margin:
            raise ContextPreflightError(f"models.{model_id} context margin is invalid")
        if margin < MINIMUM_MARGIN_TOKENS:
            raise ContextPreflightError(f"models.{model_id} has insufficient headroom")
    return value


def validate_preflight_receipt(
    receipt: Mapping[str, Any],
    manifest_sha256: str,
    execution_dependencies: Mapping[str, str],
) -> dict[str, Any]:
    """Validate a persisted receipt without reading files or tokenizers.

    ``execution_dependencies`` is the trial controller's already-computed map
    of repository-relative paths to literal file SHA-256 values.
    """
    if not _is_digest(manifest_sha256):
        raise ContextPreflightError("invalid expected manifest digest")
    value = _exact_keys(dict(receipt), _RECEIPT_KEYS, "preflight receipt")
    if value["schema_version"] != SCHEMA_VERSION or value["status"] != "passed":
        raise ContextPreflightError("context preflight did not pass")
    if value["offline"] is not True:
        raise ContextPreflightError("context preflight was not offline")
    if value["suite_id"] != generate_packs.SUITE_ID:
        raise ContextPreflightError("context preflight suite drift")
    if value["manifest_path"] != MANIFEST_REPO_PATH:
        raise ContextPreflightError("context preflight manifest path drift")
    if value["manifest_sha256"] != manifest_sha256:
        raise ContextPreflightError("context preflight manifest hash mismatch")
    if value["minimum_required_margin_tokens"] != MINIMUM_MARGIN_TOKENS:
        raise ContextPreflightError("context preflight margin contract drift")

    artifacts = _validate_digest_map(
        value["repository_artifact_sha256"], "repository_artifact_sha256"
    )
    if set(artifacts) != set(REPOSITORY_ARTIFACT_PATHS):
        raise ContextPreflightError("context preflight repository artifact set drift")
    if not isinstance(execution_dependencies, Mapping):
        raise ContextPreflightError("execution dependency fingerprint is invalid")
    for path, digest in artifacts.items():
        if execution_dependencies.get(path) != digest:
            raise ContextPreflightError(f"execution dependency mismatch: {path}")

    source = _exact_keys(value["source_snapshot"], {"path", "sha256"}, "source_snapshot")
    if (
        source["path"] != GENERATOR_REPO_PATH
        or source["sha256"] != artifacts[GENERATOR_REPO_PATH]
    ):
        raise ContextPreflightError("source snapshot is not bound to the generator")

    measurement = _validate_token_measurement(
        value["token_measurement"], manifest_sha256
    )
    if (
        not _is_digest(value["token_measurement_sha256"])
        or value["token_measurement_sha256"] != sha256_json(measurement)
    ):
        raise ContextPreflightError("token measurement hash mismatch")
    if (
        _sha256_bytes(measure_tokens._canonical_bytes(measurement))
        != artifacts[TOKEN_COUNTS_REPO_PATH]
    ):
        raise ContextPreflightError(
            "token measurement is not the checked-in execution dependency"
        )
    runtime = _exact_keys(
        value["runtime_libraries"], {"transformers", "tokenizers"}, "runtime_libraries"
    )
    if runtime != {
        "transformers": measurement["transformers_version"],
        "tokenizers": measurement["tokenizers_version"],
    }:
        raise ContextPreflightError("tokenizer runtime version mismatch")
    return value


def validate_context_preflight(
    manifest_path: Path | str = MANIFEST_PATH,
    *,
    packs_path: Path | str = PACKS_PATH,
    token_counts_path: Path | str = TOKEN_COUNTS_PATH,
    tokenizer_paths: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    """Reproduce frozen context inputs and return a durable admission receipt."""
    manifest_path = Path(manifest_path)
    packs_path = Path(packs_path)
    token_counts_path = Path(token_counts_path)
    manifest_raw, manifest_doc = _read_json(manifest_path)
    packs_raw, packs_doc = _read_json(packs_path)
    counts_raw, frozen_measurement = _read_json(token_counts_path)

    expected_outputs = generate_packs.rendered_outputs()
    if manifest_raw != expected_outputs[generate_packs.MANIFEST_PATH]:
        raise ContextPreflightError("context manifest differs from its generator")
    if packs_raw != expected_outputs[generate_packs.PACKS_PATH]:
        raise ContextPreflightError("context packs differ from their generator")
    try:
        manifest = load_manifest(manifest_path)
    except (ManifestError, OSError, ValueError) as exc:
        raise ContextPreflightError("context manifest is invalid") from exc
    if (
        manifest.suite_id != generate_packs.SUITE_ID
        or tuple(task.id for task in manifest.tasks) != TASK_IDS
        or {arm.model for arm in manifest.arms} != set(MODEL_CONTRACTS)
    ):
        raise ContextPreflightError("context manifest contract drift")

    generator_raw = _read_regular(REPO_ROOT / GENERATOR_REPO_PATH)
    generator_sha = _sha256_bytes(generator_raw)
    source = manifest_doc.get("source_snapshot")
    if source != {"path": GENERATOR_REPO_PATH, "sha256": generator_sha}:
        raise ContextPreflightError("manifest source snapshot is stale")
    if packs_doc.get("generator") != source:
        raise ContextPreflightError("pack and manifest source snapshots disagree")
    manifest_sha = _sha256_bytes(manifest_raw)
    if frozen_measurement.get("manifest_sha256") != manifest_sha:
        raise ContextPreflightError("frozen token measurement is stale")
    if tokenizer_paths is not None and set(tokenizer_paths) != set(MODEL_CONTRACTS):
        raise ContextPreflightError("tokenizer_paths must bind both resident models")

    try:
        fresh_measurement = measure_tokens.measure(
            manifest_path=manifest_path,
            tokenizer_paths=tokenizer_paths,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ContextPreflightError(f"offline tokenization preflight failed: {exc}") from exc
    if frozen_measurement != fresh_measurement:
        raise ContextPreflightError("cached tokenizer measurement drift")
    if counts_raw != measure_tokens._canonical_bytes(fresh_measurement):
        raise ContextPreflightError("frozen token measurement encoding drift")

    artifact_hashes = {
        path: _sha256_bytes(_read_regular(REPO_ROOT / path))
        for path in REPOSITORY_ARTIFACT_PATHS
    }
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "offline": True,
        "suite_id": generate_packs.SUITE_ID,
        "manifest_path": MANIFEST_REPO_PATH,
        "manifest_sha256": manifest_sha,
        "source_snapshot": source,
        "repository_artifact_sha256": artifact_hashes,
        "runtime_libraries": {
            "transformers": fresh_measurement["transformers_version"],
            "tokenizers": fresh_measurement["tokenizers_version"],
        },
        "minimum_required_margin_tokens": MINIMUM_MARGIN_TOKENS,
        "token_measurement_sha256": sha256_json(fresh_measurement),
        "token_measurement": fresh_measurement,
    }
    return validate_preflight_receipt(receipt, manifest_sha, artifact_hashes)
