"""Read-only supervisor dispatch checks against the admitted first pair."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import extended_lifecycle as flash
from bench.flash_next_ab import followon_plans as plans
from bench.flash_next_ab import followon_prepare as prepare
from bench.flash_next_ab import followon_profiles
from bench.flash_next_ab import resident_evaluation_window as resident


def test_flash_supervisor_selects_grouped_qualified_parent_before_mutation(
    tmp_path, monkeypatch,
):
    parent = prepare._parents(prepare.PARENT_ID)["flash"]
    spec = followon_profiles.MIA
    contract, contract_sha, _raw = flash.read_mia_contract(spec.contract_path, flash.q)
    source = tmp_path / "qfn-followon-selection.flash.json"
    output = tmp_path / "qfn-followon-selection.flash"
    window = SimpleNamespace(qualification_plan=parent.qualification_plan)
    plan = {
        "candidate_variant_id": spec.spec_id,
        "candidate_spec_sha256": spec.identity_sha256(),
        "contract_sha256": contract_sha,
        "paging_policy": contract["safety"]["paging_policy"],
        "extended_serving_profile": flash.EXTENDED_SERVING_PROFILE,
        "effective_invocation_deadline_seconds": 14_400,
        "restoration_reserve_seconds": 600,
        "controller_source_bundle": {"registered": True},
        "controller_source_bundle_sha256": flash.sha256({"registered": True}),
    }
    monkeypatch.setattr(flash, "select_window", None, raising=False)
    from bench.flash_next_ab import followon_selection

    monkeypatch.setattr(followon_selection, "select_window",
                        lambda *_args, **_kwargs:
                        SimpleNamespace(kind="followon"))
    monkeypatch.setattr(plans, "load_execution", lambda *_args, **_kwargs: window)
    monkeypatch.setattr(plans, "flash_plan", lambda *_args, **_kwargs: plan)
    selected, actual_plan, prior, actual_contract, raw, actual_spec = (
        flash._registered(source, output, must_be_absent=True)
    )
    assert selected is window and actual_plan is plan
    assert prior == parent.qualification_plan
    assert actual_contract == contract and raw == _raw
    assert actual_spec is spec
    assert not output.exists()
    plan["candidate_spec_sha256"] = "0" * 64
    with pytest.raises(flash.EvaluationWindowError, match="qualified parent"):
        flash._registered(source, output, must_be_absent=True)


def test_resident_plan_cli_selects_grouped_namespace_without_starting_worker(
    tmp_path, monkeypatch, capsys,
):
    source = tmp_path / "qfn-followon-selection.resident.json"
    output = tmp_path / "qfn-followon-selection.resident"
    window = SimpleNamespace(pair_id="qfn-followon-selection")
    plan = {"schema_version": "flash-followon-resident-plan/v1",
            "pair_id": window.pair_id}
    from bench.flash_next_ab import followon_selection

    monkeypatch.setattr(followon_selection, "select_window",
                        lambda *_args, **_kwargs:
                        SimpleNamespace(kind="followon"))
    monkeypatch.setattr(plans, "load_execution", lambda *_args, **_kwargs: window)
    monkeypatch.setattr(plans, "resident_plan", lambda *_args, **_kwargs: plan)
    assert resident.main(["--plan", "--eval-plan", str(source),
                          "--output-dir", str(output)]) == 0
    assert json.loads(capsys.readouterr().out) == plan
    assert resident._sentinel_name(window.pair_id).startswith(
        "vllm-qwen-ab-resident-"
    )
    assert not output.exists()
