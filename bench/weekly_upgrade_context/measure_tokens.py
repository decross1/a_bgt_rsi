#!/usr/bin/env python3
"""Measure frozen context requests with locally cached tokenizer artifacts.

This utility loads tokenizers only. It forces offline mode before importing
Transformers and never loads weights, contacts a server, or allocates a GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPO_ROOT / "experiments" / "weekly_context_capability_v1_2026-09-14.json"
)
OUTPUT_PATH = Path(__file__).with_name("token_counts.json")

TOKENIZERS = {
    "gemma-4-26b-a4b": {
        "path_env": "GEMMA_TOKENIZER_PATH",
        "default_path": "/mnt/models/gemma-4-26b-a4b-nvfp4",
        "serving_context_limit": 32768,
    },
    "qwen3.8-27b-nvfp4-mtp": {
        "path_env": "QWEN_TOKENIZER_PATH",
        "default_path": "/mnt/models/qwen3.8-27b-nvfp4-mtp",
        "serving_context_limit": 16384,
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def measure() -> dict[str, Any]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    from transformers import AutoTokenizer
    from transformers import __version__ as transformers_version

    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest = json.loads(manifest_bytes)
    messages = {
        task["id"]: [
            {"role": "system", "content": task["system"]},
            {"role": "user", "content": task["prompt"]},
        ]
        for task in manifest["tasks"]
    }
    max_output = {arm["model"]: arm["max_tokens"] for arm in manifest["arms"]}
    measured_models = {}
    for model_id, spec in TOKENIZERS.items():
        root = Path(os.environ.get(spec["path_env"], spec["default_path"]))
        tokenizer_json = root / "tokenizer.json"
        tokenizer_config = root / "tokenizer_config.json"
        if not tokenizer_json.is_file() or not tokenizer_config.is_file():
            raise FileNotFoundError(f"cached tokenizer artifacts missing for {model_id}")
        tokenizer = AutoTokenizer.from_pretrained(
            str(root), local_files_only=True, trust_remote_code=False
        )
        counts = {}
        for task_id, task_messages in messages.items():
            encoded = tokenizer.apply_chat_template(
                task_messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=False,
            )
            counts[task_id] = len(encoded)
        output_tokens = max_output[model_id]
        totals = {task_id: count + output_tokens for task_id, count in counts.items()}
        context_limit = spec["serving_context_limit"]
        measured_models[model_id] = {
            "tokenizer_class": type(tokenizer).__name__,
            "tokenizer_json_sha256": _sha256(tokenizer_json),
            "tokenizer_config_sha256": _sha256(tokenizer_config),
            "chat_template_sha256": hashlib.sha256(
                (tokenizer.chat_template or "").encode("utf-8")
            ).hexdigest(),
            "input_tokens_by_task": counts,
            "reserved_output_tokens": output_tokens,
            "maximum_total_tokens": max(totals.values()),
            "serving_context_limit": context_limit,
            "minimum_context_margin_tokens": min(
                context_limit - total for total in totals.values()
            ),
        }
    return {
        "schema_version": "weekly-context-token-counts/v1",
        "measurement_method": (
            "AutoTokenizer.apply_chat_template(tokenize=True, "
            "add_generation_prompt=True, return_dict=False)"
        ),
        "offline": True,
        "transformers_version": transformers_version,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "models": measured_models,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = _canonical_bytes(measure())
    if args.check:
        if not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_bytes() != expected:
            raise SystemExit("frozen tokenizer measurement drift")
    else:
        OUTPUT_PATH.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
