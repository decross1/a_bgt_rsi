"""Closed, immutable inputs for the role-effort pilot."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from bench.weekly_upgrade_eval.manifest import (
    _unique_object,
    canonical_json,
    sha256_json,
)

SCHEMA = "weekly-upgrade-role-effort-manifest/v1"
ARMS = ("xhigh", "medium", "adaptive")


def load_manifest(path):
    path = Path(path)
    with path.open("rb") as stream:
        raw = stream.read(200_001)
    if len(raw) > 200_000:
        raise ValueError("oversized role-effort manifest")
    doc = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(doc, dict):
        raise TypeError("role-effort manifest must be an object")
    if set(doc) != {
        "schema_version",
        "suite_id",
        "description",
        "model",
        "backend",
        "seed",
        "max_tokens",
        "attempt_timeout_s",
        "arms",
        "tasks",
    }:
        raise ValueError("role-effort manifest fields differ")
    if doc["schema_version"] != SCHEMA or doc["backend"] != "vllm-qwen" or doc["model"] != "qwen3.8-27b-nvfp4-mtp":
        raise ValueError("role-effort model/schema differs")
    if (
        not isinstance(doc["arms"], list)
        or any(not isinstance(arm, dict) for arm in doc["arms"])
        or [arm.get("id") for arm in doc["arms"]] != list(ARMS)
        or any(set(arm) != {"id", "label"} for arm in doc["arms"])
        or any(
            not isinstance(arm["label"], str) or not arm["label"].strip()
            for arm in doc["arms"]
        )
    ):
        raise ValueError("role-effort arms differ")
    if type(doc["seed"]) is not int or doc["seed"] < 0:
        raise ValueError("explicit nonnegative seed required")
    if type(doc["max_tokens"]) is not int or not 512 <= doc["max_tokens"] <= 4096:
        raise ValueError("output budget out of bounds")
    if type(doc["attempt_timeout_s"]) is not int or not 10 <= doc["attempt_timeout_s"] <= 90:
        raise ValueError("attempt deadline out of bounds")
    if (
        not isinstance(doc["tasks"], list)
        or any(not isinstance(task, dict) for task in doc["tasks"])
        or len(doc["tasks"]) != 6
        or len({task.get("id") for task in doc["tasks"]}) != 6
    ):
        raise ValueError("six unique task fixtures required")
    for role in ("critic", "evidence", "execution"):
        if sum(t.get("role") == role for t in doc["tasks"]) != 2:
            raise ValueError("exactly two fixtures per role required")
    for t in doc["tasks"]:
        if set(t) != {"id", "role", "prompt", "output_schema", "expected"}:
            raise ValueError("unexpected task fields")
        if any(
            not isinstance(t[k], str) or not t[k].strip()
            for k in ("id", "role", "prompt")
        ):
            raise ValueError("invalid task text")
        schema = t["output_schema"]
        Draft202012Validator.check_schema(schema)
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError("closed object output schema required")
        if schema.get("properties", {}).get("needs_review") != {"type": "boolean"}:
            raise ValueError("observable uncertainty flag required")
        if set(schema.get("required", [])) != set(schema["properties"]):
            raise ValueError("every output field must be required")
        if set(t["expected"]) != set(schema["properties"]) - {"needs_review"}:
            raise ValueError("answer oracle differs from public output contract")
        Draft202012Validator(schema).validate({**t["expected"], "needs_review": False})
    canonical_json(doc)
    doc["_raw_sha256"] = hashlib.sha256(raw).hexdigest()
    doc["_configuration_sha256"] = sha256_json(
        {k: v for k, v in doc.items() if not k.startswith("_")}
    )
    doc["_path"] = str(path.resolve())
    return doc


def plan_dict(manifest):
    order = []
    for i, task in enumerate(manifest["tasks"]):
        arms = ARMS[i % 3:] + ARMS[:i % 3]
        order.extend(
            {
                "attempt_id": f"{task['id']}:{arm}",
                "task_id": task["id"],
                "arm": arm,
            }
            for arm in arms
        )
    return {
        "fixture_ids": [t["id"] for t in manifest["tasks"]],
        "arm_ids": list(ARMS),
        "seeds": [manifest["seed"]],
        "order": order,
        "input_sha256": {
            t["id"]: sha256_json(
                {k: v for k, v in t.items() if k != "expected"}
            )
            for t in manifest["tasks"]
        },
        "grader_sha256": {
            t["id"]: sha256_json(
                {
                    "expected": t["expected"],
                    "schema": t["output_schema"],
                    "version": 1,
                }
            )
            for t in manifest["tasks"]
        },
    }
