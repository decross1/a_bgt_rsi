#!/usr/bin/env python3
"""Write experiment.lock — reproducibility snapshot for exp001_repeated_pd.

Captures the version-pin truth-table that an external reproducer needs
to re-run the experiment:

    vLLM image digest    -- from run_state/vllm_image.digest
    Gemma 4 weights hash -- sha256 of /mnt/models/gemma-4-26b-a4b-nvfp4/config.json
    BGE-M3 hash          -- sha256 of /mnt/models/bge-m3/config.json
    OpenSpiel version    -- importlib.metadata (open_spiel)
    GRA version          -- importlib.metadata (game_reasoning_arena)
    sampling params      -- T, max_tokens, seed used in baseline + variants
    git commit           -- HEAD at lock time
    timestamp            -- UTC of lock write

The Day-7 baseline run + the 4-run diagnostic ladder are listed
together; each lock entry maps to a results directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata as im
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

GEMMA_CONFIG = Path("/mnt/models/gemma-4-26b-a4b-nvfp4/config.json")
BGE_CONFIG = Path("/mnt/models/bge-m3/config.json")
VLLM_DIGEST_FILE = REPO_ROOT / "run_state" / "vllm_image.digest"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def safe_version(dist_name: str) -> str:
    try:
        return im.version(dist_name)
    except im.PackageNotFoundError:
        return "<not-installed>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    lock = {
        "experiment": "exp001_repeated_pd",
        "lock_written_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": git_head(),
        "version_pins": {
            "open_spiel": safe_version("open_spiel"),
            "game_reasoning_arena": safe_version("game_reasoning_arena"),
            "pandas": safe_version("pandas"),
            "matplotlib": safe_version("matplotlib"),
            "chromadb": safe_version("chromadb"),
            "sentence_transformers": safe_version("sentence-transformers"),
            "openai": safe_version("openai"),
            "python": sys.version.split()[0],
        },
        "hashes": {
            "vllm_image_digest": (
                VLLM_DIGEST_FILE.read_text().strip()
                if VLLM_DIGEST_FILE.exists() else "<digest-file-missing>"
            ),
            "gemma_config_sha256": (
                sha256_file(GEMMA_CONFIG) if GEMMA_CONFIG.exists()
                else "<config-missing>"
            ),
            "bge_m3_config_sha256": (
                sha256_file(BGE_CONFIG) if BGE_CONFIG.exists()
                else "<config-missing>"
            ),
        },
        "served_model_name": "gemma-4-26b-a4b",
        "served_weights_path": "/mnt/models/gemma-4-26b-a4b-nvfp4",
        "moe_backend": "marlin",
        "runs": [
            {
                "label": "baseline",
                "results_dir": "experiments/exp001_repeated_pd/results/",
                "jsonl_log": "logs/exp001.jsonl",
                "temperature": 0.0,
                "max_tokens": 4,
                "seed": None,
                "rules_variant": "baseline",
                "rounds_per_opponent": 100,
                "opponents": ["tft", "grim_trigger", "all_c", "all_d", "mirror_llm"],
                "via_orchestrator": True,
            },
            {
                "label": "day7_1_t0p2",
                "results_dir": "experiments/exp001_repeated_pd/results_7_1/",
                "jsonl_log": "logs/exp001_7_1.jsonl",
                "temperature": 0.2,
                "max_tokens": 4,
                "seed": None,
                "rules_variant": "baseline",
                "rounds_per_opponent": 100,
                "opponents": ["tft", "grim_trigger", "all_c", "all_d", "mirror_llm"],
                "via_orchestrator": True,
            },
            {
                "label": "day7_2_t0p7",
                "results_dir": "experiments/exp001_repeated_pd/results_7_2/",
                "jsonl_log": "logs/exp001_7_2.jsonl",
                "temperature": 0.7,
                "max_tokens": 4,
                "seed": None,
                "rules_variant": "baseline",
                "rounds_per_opponent": 100,
                "opponents": ["tft", "grim_trigger", "all_c", "all_d", "mirror_llm"],
                "via_orchestrator": True,
            },
            {
                "label": "day7_3_exploitation_hint",
                "results_dir": "experiments/exp001_repeated_pd/results_7_3/",
                "jsonl_log": "logs/exp001_7_3.jsonl",
                "temperature": 0.0,
                "max_tokens": 4,
                "seed": None,
                "rules_variant": "exploitation_hint",
                "rounds_per_opponent": 100,
                "opponents": ["tft", "grim_trigger", "all_c", "all_d", "mirror_llm"],
                "via_orchestrator": True,
            },
        ],
        "expected_range_note": "notes/day7_expected_range.md (range amended to [0.60, 1.00] after 4-run diagnostic)",
        "publication_gate": "day7_publication_review (state.human_gates_pending; never auto-clears)",
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        json.dump(lock, f, indent=2)

    print(f"wrote {out} (git_head={lock['git_head'][:8]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
