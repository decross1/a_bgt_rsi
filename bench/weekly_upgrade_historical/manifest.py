"""Strict manifest and prompt projection for the historical repair panel.

The loader reads only committed public blobs and the registered JSON file.  It
does not import the model wrapper, create workspaces, or write state.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .grader_assets import GRADER_ASSETS

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    REPO_ROOT / "experiments" / "weekly_historical_coding_panel_v2_2026-09-14.json"
)
SCHEMA_VERSION = "weekly-upgrade-historical-repair/v2"
PUBLICATION_CLASS = "public_historical"
EXPECTED_TASK_IDS = ("HCP-001", "HCP-002", "HCP-005", "HCP-006", "HCP-007", "HCP-008")
MAX_MANIFEST_BYTES = 512_000
MAX_GIT_BLOB_BYTES = 1_000_000

_TOP_KEYS = {
    "schema_version", "suite_id", "description", "publication_class",
    "contamination_resistant", "claim_limits", "ordering", "source_proof",
    "arm", "tasks", "resource_limits", "sandbox_runtime", "frozen_hashes",
}
_ARM_KEYS = {"id", "label", "backend", "model", "profile", "seed", "expected_policy"}
_TASK_KEYS = {
    "id", "title", "defect_contract", "base", "grader", "max_tokens",
    "request_timeout_s", "grader_timeout_s", "proof_task_sha256",
}
_BASE_KEYS = {
    "commit", "tree", "repair_path", "repair_sha256",
    "workspace_source_allowlist", "workspace_fixture_allowlist",
}
_GRADER_KEYS = {
    "kind", "fix_commit", "source_path", "source_sha256", "sandbox_path",
    "test_node", "expected_cases", "proof_grader_sha256",
}
_RESOURCE_KEYS = {
    "max_total_runtime_s", "max_grading_runtime_s", "planned_calls",
    "calls_serial", "max_raw_completion_bytes", "max_patch_bytes",
    "max_workspace_archive_bytes", "max_workspace_files", "max_grader_output_bytes",
}
_SANDBOX_KEYS = {
    "contract", "bubblewrap_path", "bubblewrap_sha256", "bubblewrap_version",
    "python_path", "python_sha256", "python_version", "pytest_version",
    "audit_guard_sha256", "result_plugin_sha256", "supervisor_sha256",
}


class ManifestError(ValueError):
    """A manifest or one of its immutable public inputs is invalid."""


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"value is not canonical JSON: {exc}") from exc


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
    if not isinstance(value, dict):
        raise ManifestError(f"{where} must be an object")
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise ManifestError(f"{where} fields differ: missing={missing}, extra={extra}")
    return value


def _text(value: Any, where: str, *, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ManifestError(f"{where} must be non-empty text of at most {maximum} characters")
    return value


def _sha(value: Any, where: str) -> str:
    text = _text(value, where, maximum=64)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ManifestError(f"{where} must be a lowercase SHA-256")
    return text


def _git_oid(value: Any, where: str) -> str:
    text = _text(value, where, maximum=40)
    if len(text) != 40 or any(character not in "0123456789abcdef" for character in text):
        raise ManifestError(f"{where} must be a full lowercase Git object ID")
    return text


def _integer(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ManifestError(f"{where} must be an integer >= {minimum}")
    return value


def _number(value: Any, where: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{where} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ManifestError(f"{where} must be finite{' and positive' if positive else ''}")
    return number


def _repo_path(value: Any, where: str) -> str:
    text = _text(value, where, maximum=240)
    path = PurePosixPath(text)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise ManifestError(f"{where} must be a normalized repository-relative path")
    return text


def _run_git(arguments: list[str], where: str, *, limit: int = MAX_GIT_BLOB_BYTES) -> bytes:
    try:
        process = subprocess.run(
            ["git", *arguments], cwd=REPO_ROOT, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=8, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ManifestError(f"cannot inspect {where}") from exc
    if process.returncode != 0:
        raise ManifestError(f"registered Git object is unavailable for {where}")
    if len(process.stdout) > limit:
        raise ManifestError(f"registered Git blob exceeds the bound for {where}")
    return process.stdout


def git_blob(commit: str, path: str) -> bytes:
    """Read one bounded public blob without exposing a shell parser."""
    _git_oid(commit, "commit")
    _repo_path(path, "blob path")
    size_raw = _run_git(["cat-file", "-s", f"{commit}:{path}"], f"{commit}:{path} size", limit=100)
    try:
        size = int(size_raw)
    except ValueError as exc:
        raise ManifestError("registered Git blob has no valid size") from exc
    if size < 0 or size > MAX_GIT_BLOB_BYTES:
        raise ManifestError("registered Git blob exceeds its fixed bound")
    return _run_git(["cat-file", "blob", f"{commit}:{path}"], f"{commit}:{path}")


def _proof_document(source: dict[str, Any]) -> dict[str, Any]:
    path = _repo_path(source["path"], "source_proof.path")
    resolved = (REPO_ROOT / path).resolve()
    if REPO_ROOT not in resolved.parents or resolved.is_symlink() or not resolved.is_file():
        raise ManifestError("source proof is unavailable or redirected")
    with resolved.open("rb") as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES or hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ManifestError("source proof content differs from its pin")
    try:
        proof = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("source proof is invalid JSON") from exc
    if not isinstance(proof, dict) or proof.get("panel_id") != source["panel_id"]:
        raise ManifestError("source proof panel identity differs")
    if (
        proof.get("status") != "PROOF_COMPLETE_REGISTRATION_PENDING"
        or proof.get("provenance", {}).get("class") != PUBLICATION_CLASS
        or proof.get("provenance", {}).get("contamination_resistant") is not False
        or proof.get("summary", {}).get("task_count") != 6
    ):
        raise ManifestError("source proof does not retain the admitted public-history boundary")
    return proof


def grader_source(task: dict[str, Any]) -> bytes:
    grader = task["grader"]
    if grader["kind"] == "fix_commit_test":
        return git_blob(grader["fix_commit"], grader["source_path"])
    if grader["kind"] == "embedded_focused":
        return GRADER_ASSETS[task["id"]].encode("utf-8")
    raise ManifestError("unsupported grader kind")


def grader_bundle(task: dict[str, Any]) -> dict[str, Any]:
    grader = task["grader"]
    return {
        "grader_source_sha256": hashlib.sha256(grader_source(task)).hexdigest(),
        "sandbox_path": grader["sandbox_path"],
        "test_node": grader["test_node"],
        "expected_cases": grader["expected_cases"],
        "fixture_sha256": {
            path: hashlib.sha256(git_blob(task["base"]["commit"], path)).hexdigest()
            for path in task["base"]["workspace_fixture_allowlist"]
        },
    }


def messages_for(task: dict[str, Any], base_source: str) -> list[dict[str, str]]:
    """Return the complete model-visible packet; no proof/fix/grader fields enter it."""
    return [
        {
            "role": "system",
            "content": (
                "Repair the supplied Python file. Return exactly one strict JSON object "
                "with keys path and patch. Do not use markdown or add any other keys."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task: {task['title']}\n"
                f"Required behavior: {task['defect_contract']}\n"
                f"Only this file may change: {task['base']['repair_path']}\n\n"
                "Produce a minimal unified diff against the exact file below. The diff must "
                "contain one `diff --git` section for that path, with `--- a/...` and "
                "`+++ b/...` headers. Return "
                f"{{\"path\":\"{task['base']['repair_path']}\",\"patch\":\"<unified diff>\"}}.\n\n"
                f"Current file:\n{base_source}"
            ),
        },
    ]


def validate_manifest(doc: Any) -> None:
    manifest = _keys(doc, _TOP_KEYS, "manifest")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ManifestError(f"schema_version must be {SCHEMA_VERSION!r}")
    _text(manifest["suite_id"], "suite_id", maximum=120)
    _text(manifest["description"], "description", maximum=500)
    if manifest["publication_class"] != PUBLICATION_CLASS:
        raise ManifestError(f"publication_class must be {PUBLICATION_CLASS!r}")
    if manifest["contamination_resistant"] is not False:
        raise ManifestError("public historical tasks cannot claim contamination resistance")
    limits = manifest["claim_limits"]
    if not isinstance(limits, list) or not limits or any(
        not isinstance(row, str) or not row.strip() or len(row) > 300 for row in limits
    ):
        raise ManifestError("claim_limits must be bounded non-empty strings")
    if manifest["ordering"] != "fixed_task_order_single_arm":
        raise ManifestError("ordering must remain fixed_task_order_single_arm")

    source = _keys(manifest["source_proof"], {"path", "sha256", "panel_id"}, "source_proof")
    _sha(source["sha256"], "source_proof.sha256")
    _text(source["panel_id"], "source_proof.panel_id", maximum=120)
    proof = _proof_document(source)
    proof_tasks = {
        row.get("task_id"): row for row in proof.get("tasks", []) if isinstance(row, dict)
    }

    arm = _keys(manifest["arm"], _ARM_KEYS, "arm")
    for key in ("id", "label", "backend", "model", "profile"):
        _text(arm[key], f"arm.{key}", maximum=160)
    if arm["id"] != "gemma_coding_precise" or arm["backend"] != "vllm-gemma" or arm["model"] != "gemma-4-26b-a4b" or arm["profile"] != "coding_precise":
        raise ManifestError("arm must remain the preregistered resident Gemma baseline")
    if isinstance(arm["seed"], bool) or not isinstance(arm["seed"], int):
        raise ManifestError("arm.seed must be an integer")
    policy = _keys(arm["expected_policy"], {"temperature", "top_p", "reasoning_effort"}, "arm.expected_policy")
    if policy != {"temperature": 0.2, "top_p": 0.9, "reasoning_effort": None}:
        raise ManifestError("arm expected policy differs from coding_precise on Gemma")

    tasks = manifest["tasks"]
    if not isinstance(tasks, list) or tuple(
        row.get("id") for row in tasks if isinstance(row, dict)
    ) != EXPECTED_TASK_IDS or len(tasks) != len(EXPECTED_TASK_IDS):
        raise ManifestError("tasks must be the six admitted task IDs in order")
    for index, raw_task in enumerate(tasks):
        task = _keys(raw_task, _TASK_KEYS, f"tasks[{index}]")
        for key in ("id", "title", "defect_contract"):
            _text(task[key], f"tasks[{index}].{key}", maximum=500)
        _sha(task["proof_task_sha256"], f"tasks[{index}].proof_task_sha256")
        base = _keys(task["base"], _BASE_KEYS, f"tasks[{index}].base")
        commit = _git_oid(base["commit"], f"tasks[{index}].base.commit")
        tree = _git_oid(base["tree"], f"tasks[{index}].base.tree")
        observed_tree = _run_git(["rev-parse", f"{commit}^{{tree}}"], f"{commit} tree", limit=100).decode().strip()
        if observed_tree != tree:
            raise ManifestError(f"tasks[{index}].base.tree differs")
        repair_path = _repo_path(base["repair_path"], f"tasks[{index}].base.repair_path")
        _sha(base["repair_sha256"], f"tasks[{index}].base.repair_sha256")
        repair_blob = git_blob(commit, repair_path)
        if hashlib.sha256(repair_blob).hexdigest() != base["repair_sha256"]:
            raise ManifestError(f"tasks[{index}] base repair hash differs")
        for field in ("workspace_source_allowlist", "workspace_fixture_allowlist"):
            rows = base[field]
            if not isinstance(rows, list) or any(
                not isinstance(row, str) or _repo_path(row, f"tasks[{index}].base.{field}") != row
                for row in rows
            ) or len(rows) != len(set(rows)):
                raise ManifestError(f"tasks[{index}].base.{field} must be unique safe paths")
        if repair_path not in base["workspace_source_allowlist"] and not any(
            repair_path.startswith(prefix.rstrip("/") + "/")
            for prefix in base["workspace_source_allowlist"]
        ):
            raise ManifestError(f"tasks[{index}] repair path is outside its source allowlist")

        grader = _keys(task["grader"], _GRADER_KEYS, f"tasks[{index}].grader")
        if grader["kind"] not in {"fix_commit_test", "embedded_focused"}:
            raise ManifestError(f"tasks[{index}].grader.kind is unsupported")
        _git_oid(grader["fix_commit"], f"tasks[{index}].grader.fix_commit")
        if grader["kind"] == "fix_commit_test":
            _repo_path(grader["source_path"], f"tasks[{index}].grader.source_path")
        elif grader["source_path"] != "bench/weekly_upgrade_historical/grader_assets.py" or task["id"] not in GRADER_ASSETS:
            raise ManifestError(f"tasks[{index}] embedded grader reference differs")
        _sha(grader["source_sha256"], f"tasks[{index}].grader.source_sha256")
        _sha(grader["proof_grader_sha256"], f"tasks[{index}].grader.proof_grader_sha256")
        _repo_path(grader["sandbox_path"], f"tasks[{index}].grader.sandbox_path")
        _text(grader["test_node"], f"tasks[{index}].grader.test_node", maximum=300)
        _integer(grader["expected_cases"], f"tasks[{index}].grader.expected_cases", minimum=1)
        source_bytes = grader_source(task)
        if hashlib.sha256(source_bytes).hexdigest() != grader["source_sha256"]:
            raise ManifestError(f"tasks[{index}] grader source hash differs")
        _integer(task["max_tokens"], f"tasks[{index}].max_tokens", minimum=1)
        _number(task["request_timeout_s"], f"tasks[{index}].request_timeout_s", positive=True)
        _number(task["grader_timeout_s"], f"tasks[{index}].grader_timeout_s", positive=True)

        proof_task = proof_tasks.get(task["id"])
        if not isinstance(proof_task, dict) or sha256_json(proof_task) != task["proof_task_sha256"]:
            raise ManifestError(f"tasks[{index}] is not bound to the proof task")
        proof_repair = (proof_task.get("repair_file_hashes") or {}).get(repair_path)
        proof_grader = proof_task.get("grader") or {}
        if (
            proof_task.get("base_commit") != commit
            or proof_task.get("base_tree") != tree
            or proof_task.get("title") != task["title"]
            or proof_task.get("defect_contract") != task["defect_contract"]
            or proof_task.get("allowed_repair_paths") != [repair_path]
            or not isinstance(proof_repair, dict)
            or proof_repair.get("base_sha256") != base["repair_sha256"]
            or proof_task.get("fix_commit") != grader["fix_commit"]
            or proof_grader.get("sha256") != grader["proof_grader_sha256"]
            or proof_task.get("workspace_source_allowlist") != base["workspace_source_allowlist"]
            or proof_task.get("workspace_fixture_allowlist") != base["workspace_fixture_allowlist"]
            or proof_task.get("status") != "PROVED_FOR_CURATION"
        ):
            raise ManifestError(f"tasks[{index}] proof binding differs")

    resources = _keys(manifest["resource_limits"], _RESOURCE_KEYS, "resource_limits")
    expected_resources = {
        "max_total_runtime_s": 1020,
        "max_grading_runtime_s": 90,
        "planned_calls": 6,
        "calls_serial": True,
        "max_raw_completion_bytes": 131072,
        "max_patch_bytes": 98304,
        "max_workspace_archive_bytes": 16000000,
        "max_workspace_files": 2000,
        "max_grader_output_bytes": 1048576,
    }
    if resources != expected_resources:
        raise ManifestError("resource_limits differ from the preregistration")
    if any(
        task["max_tokens"] != 4096
        or task["request_timeout_s"] != 145
        or task["grader_timeout_s"] != 15
        for task in tasks
    ):
        raise ManifestError("per-task generation or deadline budget differs")

    sandbox = _keys(manifest["sandbox_runtime"], _SANDBOX_KEYS, "sandbox_runtime")
    if sandbox["contract"] != "bubblewrap-pytest-repair/v1":
        raise ManifestError("sandbox_runtime.contract is unsupported")
    for key in ("bubblewrap_path", "bubblewrap_version", "python_path", "python_version", "pytest_version"):
        _text(sandbox[key], f"sandbox_runtime.{key}", maximum=240)
    for key in (
        "bubblewrap_sha256", "python_sha256", "audit_guard_sha256",
        "result_plugin_sha256", "supervisor_sha256",
    ):
        _sha(sandbox[key], f"sandbox_runtime.{key}")
    if not Path(sandbox["bubblewrap_path"]).is_absolute() or not Path(sandbox["python_path"]).is_absolute():
        raise ManifestError("sandbox executable paths must be absolute")

    expected_hashes = {
        "arm": sha256_json(arm),
        "tasks": {task["id"]: sha256_json(task) for task in tasks},
        "inputs": {
            task["id"]: sha256_json(messages_for(task, git_blob(task["base"]["commit"], task["base"]["repair_path"]).decode("utf-8")))
            for task in tasks
        },
        "graders": {task["id"]: sha256_json(grader_bundle(task)) for task in tasks},
    }
    if manifest["frozen_hashes"] != expected_hashes:
        raise ManifestError("frozen_hashes do not match the exact inputs and graders")


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise ManifestError("manifest is unavailable or redirected")
    manifest_path = candidate.resolve()
    if not manifest_path.is_file():
        raise ManifestError("manifest is unavailable or redirected")
    with manifest_path.open("rb") as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest exceeds the size bound")
    try:
        doc = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest is invalid JSON") from exc
    validate_manifest(doc)
    result = dict(doc)
    result["_path"] = str(manifest_path)
    result["_raw_sha256"] = hashlib.sha256(raw).hexdigest()
    result["_configuration_sha256"] = sha256_json(doc)
    return result


def plan_dict(manifest: dict[str, Any]) -> dict[str, Any]:
    tasks = manifest["tasks"]
    arm = manifest["arm"]
    order = [
        {
            "attempt_id": f"{task['id']}:{arm['id']}",
            "task_id": task["id"],
            "arm_id": arm["id"],
            "input_sha256": manifest["frozen_hashes"]["inputs"][task["id"]],
            "grader_sha256": manifest["frozen_hashes"]["graders"][task["id"]],
        }
        for task in tasks
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "suite_id": manifest["suite_id"],
        "manifest_path": manifest["_path"],
        "manifest_sha256": manifest["_raw_sha256"],
        "configuration_sha256": manifest["_configuration_sha256"],
        "fixture_ids": [task["id"] for task in tasks],
        "arm_ids": [arm["id"]],
        "seeds": [arm["seed"]],
        "declared_attempts": len(order),
        "expected_attempt_ids": [row["attempt_id"] for row in order],
        "expected_input_sha256": manifest["frozen_hashes"]["inputs"],
        "expected_grader_sha256": manifest["frozen_hashes"]["graders"],
        "runtime_ceiling_s": manifest["resource_limits"]["max_total_runtime_s"],
        "order": order,
        "publication_class": manifest["publication_class"],
        "contamination_resistant": manifest["contamination_resistant"],
        "notice": (
            "Single-arm public-historical baseline; it is descriptive, not a "
            "contamination-resistant or causal upgrade comparison."
        ),
    }


__all__ = [
    "DEFAULT_MANIFEST",
    "EXPECTED_TASK_IDS",
    "PUBLICATION_CLASS",
    "REPO_ROOT",
    "SCHEMA_VERSION",
    "ManifestError",
    "canonical_json",
    "git_blob",
    "grader_bundle",
    "grader_source",
    "load_manifest",
    "messages_for",
    "plan_dict",
    "sha256_json",
    "validate_manifest",
]
