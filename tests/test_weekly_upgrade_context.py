"""Offline contracts for the public-synthetic long-context capability panel."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from bench.weekly_upgrade_context import generate_packs, measure_tokens, preflight
from bench.weekly_upgrade_eval.manifest import load_manifest, sha256_json
from bench.weekly_upgrade_eval.runner import InvocationResult, grade_task

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "experiments" / "weekly_context_capability_v1_2026-09-14.json"
PACKS = ROOT / "bench" / "weekly_upgrade_context" / "packs.json"
COUNTS = ROOT / "bench" / "weekly_upgrade_context" / "token_counts.json"
PREFLIGHT = ROOT / "bench" / "weekly_upgrade_context" / "preflight.py"
PREREG = ROOT / "experiments" / "PREREG_weekly_context_capability_v1_2026-09-14.md"
TASK_IDS = (
    "long_context_8k_grim_threshold",
    "long_context_8k_attrition",
    "long_context_14k_social_choice",
    "long_context_14k_primary_endpoint",
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _frozen_preflight_receipt() -> tuple[dict, dict[str, str]]:
    measurement = _json(COUNTS)
    artifacts = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in preflight.REPOSITORY_ARTIFACT_PATHS
    }
    receipt = {
        "schema_version": preflight.SCHEMA_VERSION,
        "status": "passed",
        "offline": True,
        "suite_id": generate_packs.SUITE_ID,
        "manifest_path": preflight.MANIFEST_REPO_PATH,
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "source_snapshot": _json(MANIFEST)["source_snapshot"],
        "repository_artifact_sha256": artifacts,
        "runtime_libraries": {
            "transformers": measurement["transformers_version"],
            "tokenizers": measurement["tokenizers_version"],
        },
        "minimum_required_margin_tokens": preflight.MINIMUM_MARGIN_TOKENS,
        "token_measurement_sha256": sha256_json(measurement),
        "token_measurement": measurement,
    }
    return receipt, dict(artifacts)


@pytest.fixture(scope="module")
def cached_preflight_receipt() -> dict:
    pytest.importorskip("transformers")
    roots = [Path(spec["default_path"]) for spec in measure_tokens.TOKENIZERS.values()]
    if not all((root / "tokenizer.json").is_file() for root in roots):
        pytest.skip("qualified local tokenizer artifacts are not installed")
    return preflight.validate_context_preflight(MANIFEST)


def test_generator_outputs_are_frozen_and_manifest_loads():
    for path, expected in generate_packs.rendered_outputs().items():
        assert path.read_bytes() == expected

    manifest = load_manifest(MANIFEST)
    assert manifest.suite_id == generate_packs.SUITE_ID
    assert tuple(task.id for task in manifest.tasks) == TASK_IDS
    assert manifest.plan_dict()["planned_invocations"] == 8
    assert manifest.plan_dict()["task_count"] == 4
    assert "not a causal inference-policy" in manifest.description
    assert "Qwen retains its template-default xhigh thinking mode" in manifest.description
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
    assert "non-thinking" in gemma.label
    assert "template-default xhigh" in qwen.label


def test_packs_have_exact_unique_sources_and_planted_positions():
    packs = _json(PACKS)
    manifest = load_manifest(MANIFEST)
    assert packs["publication_class"] == "public_synthetic_development"
    assert len(packs["claim_limits"]) == 4
    by_task = {task.id: task for task in manifest.tasks}

    for pack in packs["packs"]:
        prompt = pack["prompt"]
        assert by_task[pack["task_id"]].prompt == prompt
        assert hashlib.sha256(prompt.encode()).hexdigest() == pack["prompt_sha256"]
        source_ids = re.findall(r"^\[([A-Z0-9-]+)\]", prompt, re.MULTILINE)
        assert len(source_ids) == pack["record_count"]
        assert len(source_ids) == len(set(source_ids))
        assert set(pack["expected"]["citations"]).issubset(source_ids)
        roles = pack["expected"]["citation_roles"]
        assert len(roles) == len(pack["expected"]["citations"])
        question = prompt.splitlines()[-1]
        assert "exactly one focal GT source ID for each required role" in question
        for index, role in enumerate(roles, 1):
            assert f"({index}) {role}" in question
        assert by_task[pack["task_id"]].grader["expected"] == {
            "answer_code": pack["expected"]["answer_code"],
            "citations": pack["expected"]["citations"],
        }
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
        assert model["default_template_matches_explicit_policy"] is True
        assert set(model["rendered_input_sha256_by_task"]) == set(TASK_IDS)
        assert {
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "chat_template.jinja",
        }.issubset(model["tokenizer_asset_sha256"])
        assert (
            model["chat_template_sha256"]
            == model["tokenizer_asset_sha256"]["chat_template.jinja"]
        )

    qwen = counts["models"]["qwen3.8-27b-nvfp4-mtp"]
    gemma = counts["models"]["gemma-4-26b-a4b"]
    assert qwen["serving_context_limit"] == 16384
    assert qwen["minimum_context_margin_tokens"] >= 512
    assert qwen["template_policy"] == {
        "enable_thinking": True,
        "reasoning_effort": "xhigh",
    }
    assert gemma["serving_context_limit"] == 32768
    assert gemma["template_policy"] == {"enable_thinking": False}
    assert counts["transformers_version"]
    assert counts["tokenizers_version"]


def test_cached_tokenizers_reproduce_frozen_receipt_when_available(
    cached_preflight_receipt,
):
    assert cached_preflight_receipt["token_measurement"] == _json(COUNTS)


def test_pure_preflight_receipt_validation_binds_dependencies_and_survives_json_order():
    receipt, dependencies = _frozen_preflight_receipt()
    round_tripped = json.loads(json.dumps(receipt, sort_keys=True))
    assert preflight.validate_preflight_receipt(
        round_tripped,
        receipt["manifest_sha256"],
        dependencies,
    ) == round_tripped


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda receipt: receipt["token_measurement"]["models"]
            ["qwen3.8-27b-nvfp4-mtp"].__setitem__(
                "minimum_context_margin_tokens", 999
            ),
            "context margin",
        ),
        (
            lambda receipt: receipt["token_measurement"]["models"]
            ["qwen3.8-27b-nvfp4-mtp"].__setitem__(
                "template_policy", {"enable_thinking": False}
            ),
            "template policy",
        ),
        (
            lambda receipt: receipt["source_snapshot"].__setitem__(
                "sha256", "0" * 64
            ),
            "source snapshot",
        ),
    ),
)
def test_pure_preflight_receipt_rejects_cross_field_tampering(mutation, message):
    receipt, dependencies = _frozen_preflight_receipt()
    mutation(receipt)
    with pytest.raises(preflight.ContextPreflightError, match=message):
        preflight.validate_preflight_receipt(
            receipt,
            hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
            dependencies,
        )


def test_pure_preflight_receipt_rejects_execution_dependency_drift():
    receipt, dependencies = _frozen_preflight_receipt()
    dependencies[preflight.TOKEN_COUNTS_REPO_PATH] = "0" * 64
    with pytest.raises(preflight.ContextPreflightError, match="execution dependency"):
        preflight.validate_preflight_receipt(
            receipt,
            receipt["manifest_sha256"],
            dependencies,
        )


def test_pure_preflight_rejects_rehashed_measurement_not_in_frozen_dependency():
    receipt, dependencies = _frozen_preflight_receipt()
    measurement = receipt["token_measurement"]
    measurement["models"]["qwen3.8-27b-nvfp4-mtp"][
        "rendered_input_sha256_by_task"
    ][TASK_IDS[0]] = "0" * 64
    receipt["token_measurement_sha256"] = sha256_json(measurement)
    with pytest.raises(preflight.ContextPreflightError, match="checked-in"):
        preflight.validate_preflight_receipt(
            receipt,
            receipt["manifest_sha256"],
            dependencies,
        )


def test_full_offline_context_preflight_when_cached_tokenizers_are_available(
    cached_preflight_receipt,
):
    assert cached_preflight_receipt["status"] == "passed"


def test_preregistration_binds_every_generated_artifact():
    prereg = PREREG.read_text(encoding="utf-8")
    paths = (
        Path("bench/weekly_upgrade_context/generate_packs.py"),
        Path("bench/weekly_upgrade_context/packs.json"),
        Path("bench/weekly_upgrade_context/measure_tokens.py"),
        Path("bench/weekly_upgrade_context/token_counts.json"),
        Path("bench/weekly_upgrade_context/preflight.py"),
        Path("experiments/weekly_context_capability_v1_2026-09-14.json"),
    )
    for relative in paths:
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert f"| `{relative}` | `{digest}` |" in prereg
