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
import stat
from collections.abc import Mapping
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
        "template_policy": {
            "enable_thinking": False,
        },
    },
    "qwen3.8-27b-nvfp4-mtp": {
        "path_env": "QWEN_TOKENIZER_PATH",
        "default_path": "/mnt/models/qwen3.8-27b-nvfp4-mtp",
        "serving_context_limit": 16384,
        "template_policy": {
            "enable_thinking": True,
            "reasoning_effort": "xhigh",
        },
    },
}

# These are the complete bounded set of local files that can affect tokenizer
# selection, vocabulary, special-token handling, or chat-template rendering for
# the two resident checkpoints. Weight shards and model quantization metadata
# are deliberately outside this CPU-only tokenization receipt.
TOKENIZER_ASSET_NAMES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "tokenizer.model",
    "special_tokens_map.json",
    "added_tokens.json",
    "processor_config.json",
    "preprocessor_config.json",
    "chat_template.jinja",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _tokenizer_asset_hashes(root: Path) -> dict[str, str]:
    """Hash every bounded tokenizer-affecting artifact present in ``root``."""
    hashes: dict[str, str] = {}
    for name in TOKENIZER_ASSET_NAMES:
        path = root / name
        if not path.exists():
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"redirected tokenizer artifact: {path}")
        hashes[name] = _sha256(path)
    required = {"config.json", "tokenizer.json", "tokenizer_config.json"}
    missing = sorted(required - hashes.keys())
    if missing:
        raise FileNotFoundError(
            f"cached tokenizer artifacts missing under {root}: {', '.join(missing)}"
        )
    if "chat_template.jinja" not in hashes:
        raise FileNotFoundError(f"cached chat template missing under {root}")
    return hashes


def _rendered_ids(
    tokenizer: Any,
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> list[int]:
    encoded = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=False,
        **kwargs,
    )
    if not isinstance(encoded, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in encoded
    ):
        raise TypeError("chat template did not return a flat token-id list")
    return encoded


def measure(
    *,
    manifest_path: Path | str = MANIFEST_PATH,
    tokenizer_paths: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    from tokenizers import __version__ as tokenizers_version
    from transformers import AutoTokenizer
    from transformers import __version__ as transformers_version

    manifest_path = Path(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
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
        configured_path = (
            tokenizer_paths[model_id]
            if tokenizer_paths is not None and model_id in tokenizer_paths
            else os.environ.get(spec["path_env"], spec["default_path"])
        )
        root = Path(configured_path)
        asset_hashes = _tokenizer_asset_hashes(root)
        tokenizer = AutoTokenizer.from_pretrained(
            str(root), local_files_only=True, trust_remote_code=False
        )
        counts: dict[str, int] = {}
        rendered_hashes: dict[str, str] = {}
        for task_id, task_messages in messages.items():
            default_encoded = _rendered_ids(tokenizer, task_messages)
            explicit_encoded = _rendered_ids(
                tokenizer, task_messages, **spec["template_policy"]
            )
            if default_encoded != explicit_encoded:
                raise ValueError(
                    f"resident default chat-template policy drift for {model_id}"
                )
            counts[task_id] = len(default_encoded)
            rendered_hashes[task_id] = hashlib.sha256(
                json.dumps(default_encoded, separators=(",", ":")).encode("ascii")
            ).hexdigest()
        output_tokens = max_output[model_id]
        totals = {task_id: count + output_tokens for task_id, count in counts.items()}
        context_limit = spec["serving_context_limit"]
        measured_models[model_id] = {
            "tokenizer_class": type(tokenizer).__name__,
            "tokenizer_asset_sha256": asset_hashes,
            "chat_template_sha256": hashlib.sha256(
                (tokenizer.chat_template or "").encode("utf-8")
            ).hexdigest(),
            "template_policy": spec["template_policy"],
            "default_template_matches_explicit_policy": True,
            "input_tokens_by_task": counts,
            "rendered_input_sha256_by_task": rendered_hashes,
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
        "tokenizers_version": tokenizers_version,
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
