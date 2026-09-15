"""UI-only v5 profile identity tests; run after Flash restoration."""
from __future__ import annotations

from pathlib import Path

from backend import model_runtime as mr


def test_reduced_mtp3_namespace_wins_over_generic_mtp3():
    from bench.flash_next_ab.followon_profiles import (
        MIA_MTP3,
        MIA_MTP3_REDUCED47K_OPT,
    )

    reduced_run = MIA_MTP3_REDUCED47K_OPT.run_id_prefix + "20260915-1100"
    generic_run = MIA_MTP3.run_id_prefix + "20260915-1100"
    assert mr._mia_spec_for_run(reduced_run) is MIA_MTP3_REDUCED47K_OPT
    assert mr._mia_spec_for_run(generic_run) is MIA_MTP3


def test_v5_source_plan_still_reconstructs_with_canonical_import_root(monkeypatch):
    """The q ROOT veto is worker-only; UI gets a fixed registered source."""
    from bench.flash_next_ab import followon_dispatch as grouped
    from bench.flash_next_ab import qualification as q
    from bench.flash_next_ab.followon_profiles import MIA_MTP3_REDUCED47K_OPT
    from bench.flash_next_ab.mia_candidate_integration import read_mia_contract

    spec = MIA_MTP3_REDUCED47K_OPT
    contract, raw_sha, _ = read_mia_contract(spec.contract_path, q)
    run_path = spec.output_root / (spec.run_id_prefix + "source-only-test")
    monkeypatch.setattr(q, "ROOT", Path("/home/decross1/projects/a_bgt_rsi"))
    plan = q.plan_qualification(contract, raw_sha, run_path, spec=spec)
    assert plan["registered_code_root"] == str(grouped.FOLLOWON_CODE_ROOT)
    assert plan["followon_source_bundle"] == (
        grouped.frozen_followon_source_bundle()
    )
    state = {
        "candidate": {"id": spec.spec_id,
                      "spec_sha256": spec.identity_sha256()},
        "model_artifact_sha256": spec.model_artifact_sha256(),
        "contract_sha256": raw_sha,
    }
    mr._validate_registered_mia_plan(
        run_path, state, plan, contract, raw_sha, spec,
    )
