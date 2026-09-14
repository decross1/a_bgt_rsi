"""Offline contracts for the public-synthetic long-context capability panel."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from bench.weekly_upgrade_context import generate_packs, measure_tokens
from bench.weekly_upgrade_eval.manifest import load_manifest
from bench.weekly_upgrade_eval.runner import InvocationResult, grade_task

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "experiments" / "weekly_context_capability_v1_2026-09-14.json"
PACKS = ROOT / "bench" / "weekly_upgrade_context" / "packs.json"
COUNTS = ROOT / "bench" / "weekly_upgrade_context" / "token_counts.json"
PREREG = ROOT / "experiments" / "PREREG_weekly_context_capability_v1_2026-09-14.md"
TASK_IDS = (
    "long_context_8k_grim_threshold",
    "long_context_8k_attrition",
    "long_context_14k_social_choice",
    "long_context_14k_primary_endpoint",
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_generator_outputs_are_frozen_and_manifest_loads():
    for path, expected in generate_packs.rendered_outputs().items():
        assert path.read_bytes() == expected

    manifest = load_manifest(MANIFEST)
    assert manifest.suite_id == generate_packs.SUITE_ID
    assert tuple(task.id for task in manifest.tasks) == TASK_IDS
    assert manifest.plan_dict()["planned_invocations"] == 8
    assert manifest.plan_dict()["task_count"] == 4
    assert "causal inference-policy" in manifest.description
    assert "no production authority" in manifest.description


def test_arms_freeze_same_sampling_and_bounded_resident_context_contracts():
    manifest = load_manifest(MANIFEST)
    gemma, qwen = manifest.arms
    assert (
        gemma.id,
        gemma.backend,
        gemma.model,
        gemma.profile,
    ) == ("A", "vllm-gemma", "gemma-4-26b-a4b", "deterministic")
    assert (
        qwen.id,
        qwen.backend,
        qwen.model,
        qwen.profile,
    ) == ("B", "vllm-qwen", "qwen3.8-27b-nvfp4-mtp", "deterministic")
    for arm in manifest.arms:
        assert arm.max_tokens == 1024
        assert arm.request_timeout_s == 120
        assert arm.seed == 0


def test_packs_have_exact_unique_sources_and_planted_positions():
    packs = _json(PACKS)
    manifest = load_manifest(MANIFEST)
    assert packs["publication_class"] == "public_synthetic_development"
    assert len(packs["claim_limits"]) == 3
    by_task = {task.id: task for task in manifest.tasks}

    for pack in packs["packs"]:
        prompt = pack["prompt"]
        assert by_task[pack["task_id"]].prompt == prompt
        assert hashlib.sha256(prompt.encode()).hexdigest() == pack["prompt_sha256"]
        source_ids = re.findall(r"^\[([A-Z0-9-]+)\]", prompt, re.MULTILINE)
        assert len(source_ids) == pack["record_count"]
        assert len(source_ids) == len(set(source_ids))
        assert set(pack["expected"]["citations"]).issubset(source_ids)
        for citation, position in zip(
            pack["expected"]["citations"], pack["planted_positions"], strict=True
        ):
            assert prompt.splitlines()[position].startswith(f"[{citation}]")
            assert prompt.count(f"[{citation}]") == 1
        for line in prompt.splitlines():
            if line.startswith("[SYN-"):
                assert line.endswith(
                    "This metadata record contains no result about the focal "
                    "claim and must not be cited."
                )


def test_existing_objective_grader_accepts_only_exact_answer_and_citations():
    manifest = load_manifest(MANIFEST)
    for task in manifest.tasks:
        expected = task.grader["expected"]
        correct = InvocationResult(completion=json.dumps(expected))
        assert grade_task(task, correct).passed

        wrong_answer = copy.deepcopy(expected)
        wrong_answer["answer_code"] = "insufficient_evidence"
        assert not grade_task(
            task, InvocationResult(completion=json.dumps(wrong_answer))
        ).passed

        missing_source = copy.deepcopy(expected)
        missing_source["citations"] = missing_source["citations"][:-1]
        assert not grade_task(
            task, InvocationResult(completion=json.dumps(missing_source))
        ).passed

        invented_source = copy.deepcopy(expected)
        invented_source["citations"][-1] = "SYN-INVENTED-9999"
        assert not grade_task(
            task, InvocationResult(completion=json.dumps(invented_source))
        ).passed


def test_frozen_token_receipt_proves_bands_and_qwen_headroom():
    counts = _json(COUNTS)
    assert counts["offline"] is True
    assert counts["manifest_sha256"] == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    assert "apply_chat_template" in counts["measurement_method"]

    for model in counts["models"].values():
        by_task = model["input_tokens_by_task"]
        assert 7800 <= by_task[TASK_IDS[0]] <= 8500
        assert 7800 <= by_task[TASK_IDS[1]] <= 8500
        assert 13800 <= by_task[TASK_IDS[2]] <= 14600
        assert 13800 <= by_task[TASK_IDS[3]] <= 14600
        assert model["reserved_output_tokens"] == 1024
        assert model["maximum_total_tokens"] <= model["serving_context_limit"]

    qwen = counts["models"]["qwen3.8-27b-nvfp4-mtp"]
    gemma = counts["models"]["gemma-4-26b-a4b"]
    assert qwen["serving_context_limit"] == 16384
    assert qwen["minimum_context_margin_tokens"] >= 512
    assert gemma["serving_context_limit"] == 32768


def test_cached_tokenizers_reproduce_frozen_receipt_when_available():
    pytest.importorskip("transformers")
    roots = [
        Path(spec["default_path"])
        for spec in measure_tokens.TOKENIZERS.values()
    ]
    if not all((root / "tokenizer.json").is_file() for root in roots):
        pytest.skip("qualified local tokenizer artifacts are not installed")
    assert measure_tokens.measure() == _json(COUNTS)


def test_preregistration_binds_every_generated_artifact():
    prereg = PREREG.read_text(encoding="utf-8")
    paths = (
        Path("bench/weekly_upgrade_context/generate_packs.py"),
        Path("bench/weekly_upgrade_context/packs.json"),
        Path("bench/weekly_upgrade_context/measure_tokens.py"),
        Path("bench/weekly_upgrade_context/token_counts.json"),
        Path("experiments/weekly_context_capability_v1_2026-09-14.json"),
    )
    for relative in paths:
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert f"| `{relative}` | `{digest}` |" in prereg
