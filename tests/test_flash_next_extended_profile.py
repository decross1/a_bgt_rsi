"""Pure off-tree checks for the distinct long-cohort paging profile."""
from __future__ import annotations

import hashlib
import json

import pytest

from bench.flash_next_ab import qualification as q
from bench.flash_next_ab.candidate_registry import MIA


def module():
    from bench.flash_next_ab import evaluation_window
    return evaluation_window


def fixture(monkeypatch, tmp_path, *, mia=False):
    ew = module()
    output = tmp_path / "qfn-ab-profile-unit.flash"
    monkeypatch.setattr(ew, "_evaluation_output", lambda _id, _path, must_be_absent: output)
    variant = MIA if mia else None
    policy = variant.paging_policy() if mia else q.PAGING_POLICY
    argv = q.launch_argv(variant)
    model = MIA.served_name if mia else q.SERVED_MODEL
    artifact = MIA.model_artifact_sha256() if mia else q.model_artifact_sha256()
    plan = {
        "schema": "qwen-flash-next-qualification-plan/v4" if mia
                  else "qwen-flash-next-qualification-plan/v3",
        "candidate": {"id": MIA.spec_id, "spec_sha256": MIA.identity_sha256()}
                     if mia else None,
        "contract_sha256": "c" * 64,
        "image_id": MIA.image_id if mia else q.IMAGE_ID,
        "model_path": str(MIA.model_path if mia else q.MODEL_PATH),
        "model_artifact_sha256": artifact,
        "served_model": model,
        "probe_set": "flash-next-minimal-v1",
        "setup_quiescence_seconds": 60,
        "ready_quiescence_seconds": 60,
        "paging_policy": policy,
        "docker_create_argv": argv,
        "docker_create_argv_sha256": q.sha256(argv),
    }
    plan_sha = hashlib.sha256(json.dumps(
        plan, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    summary = {
        "admission_eligible": True,
        "variant_id": MIA.spec_id if mia else None,
        "qualification_receipt_sha256": "a" * 64,
        "qualification_plan_sha256": plan_sha,
        "runtime_sha256": "b" * 64,
        "contract_sha256": plan["contract_sha256"],
        "model_artifact_sha256": artifact,
        "served_model": model,
    }
    window = ew.FrozenEvaluationWindow(
        document={
            "pair_id": "qfn-ab-profile-unit", "cohort": "flash",
            "safety": {"window_deadline_seconds": 14_400,
                       "restoration_reserve_seconds": 600},
            "benchmark": {"plan_path": str(tmp_path / "benchmark.json"),
                          "runtime_budget_seconds": 10_430},
        },
        source_path=tmp_path / "window.json", source_sha256="d" * 64,
        benchmark_plan={}, benchmark_plan_file_sha256="e" * 64,
        qualification_summary=summary, qualification_plan=plan,
    )
    return ew, window, output


@pytest.mark.parametrize("mia", (False, True))
def test_extended_profile_is_distinct_from_c0_and_variant_bound(
    monkeypatch, tmp_path, mia
):
    ew, window, output = fixture(monkeypatch, tmp_path, mia=mia)
    planned = ew.build_extended_evaluation_plan(window, output)
    assert planned["schema_version"] == "flash-next-extended-evaluation-plan/v3"
    assert planned["paging_policy"] == (MIA.paging_policy() if mia else q.PAGING_POLICY)
    assert planned["candidate_variant_id"] == (
        MIA.spec_id if mia else "nvidia-nvfp4-fc694b54"
    )
    assert planned["candidate_spec_sha256"] == (MIA.identity_sha256() if mia else None)
    serving = planned["extended_serving_profile"]
    assert serving["host_pswpout_5s_burst_bytes"] == 512 * 1024**2
    assert serving["host_pswpout_60s_burst_bytes"] == 2 * 1024**3
    assert serving["host_pswpout_total_action"] == "diagnostic_only"
    assert serving["max_raw_memory_bytes"] == 64 * 1024**2
    assert serving["max_memory_rows"] == 20_000
    assert planned["extended_serving_profile_sha256"] == hashlib.sha256(
        json.dumps(serving, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_other_mia_identity_or_incomplete_prior_c0_is_rejected(monkeypatch, tmp_path):
    ew, window, output = fixture(monkeypatch, tmp_path, mia=True)
    window.qualification_plan["candidate"]["spec_sha256"] = "f" * 64
    with pytest.raises(ew.EvaluationWindowError, match="prior C0"):
        ew.build_extended_evaluation_plan(window, output)
