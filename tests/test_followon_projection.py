"""Public follow-on projection source and admission tests.

The real dashboard must pass the shared v5 source/private-evidence validator,
not this test's injected summary. These tests cover profile prefix binding and
the fail-closed rendering boundary only.
"""
from __future__ import annotations

from dataclasses import replace

from bench.flash_next_ab import followon_projection as projection
from bench.flash_next_ab.followon_profiles import (
    MIA_MTP1,
    MIA_MTP3_REDUCED47K_OPT,
)


def _files(root, spec):
    output = root / f"{spec.run_id_prefix}unit"
    output.mkdir()
    for name in ("result.json", "plan.json", "launch-contract.snapshot.json",
                 "launch-contract.raw.json"):
        (output / name).write_text("{}\n")
    return output


def test_registered_v5_projection_only_after_shared_admission(tmp_path, monkeypatch):
    spec = replace(MIA_MTP1, output_root=tmp_path)
    monkeypatch.setattr(projection, "FOLLOWON_SPECS", (spec,))
    output = _files(tmp_path, spec)
    summary = {
        "schema_version": "flash-next-qualification-validation/v3",
        "variant_id": spec.spec_id, "run_id": output.name,
        "model_artifact_sha256": spec.model_artifact_sha256(),
        "served_model": spec.served_name, "endpoint_name": spec.endpoint_name,
        "status": "passed", "admission_eligible": True,
        "qualification_receipt_sha256": "a" * 64,
        "min_mem_available_gib": 29.0, "probe_count": 3,
        "restoration_status": "verified",
    }
    selected = projection.public_followon_trial(output,
        validator=lambda *a, **kw: summary)
    assert selected["status"] == "passed"
    assert selected["admission_eligible"] is True
    assert selected["comparison_eligible"] is False
    assert selected["mtp_speculative_tokens"] == 1


def test_unsupported_v5_and_wrong_variant_stay_unknown(tmp_path, monkeypatch):
    spec = replace(MIA_MTP1, output_root=tmp_path)
    monkeypatch.setattr(projection, "FOLLOWON_SPECS", (spec,))
    output = _files(tmp_path, spec)
    unavailable = projection.public_followon_trial(output,
        validator=lambda *a, **kw: (_ for _ in ()).throw(ValueError("v5 unsupported")))
    assert unavailable["status"] == "unknown"
    assert unavailable["admission_eligible"] is False
    wrong = projection.public_followon_trial(output,
        validator=lambda *a, **kw: {
            "schema_version": "flash-next-qualification-validation/v3",
            "variant_id": "mia-925d7be6-c0-s1", "run_id": output.name,
            "status": "passed", "admission_eligible": True,
        })
    assert wrong["status"] == "unknown" and wrong["comparison_eligible"] is False


def test_unregistered_prefix_never_scanned():
    assert projection.spec_for_run_name("qfn-mia-mtp9-bad") is None
    assert projection.spec_for_run_name("qfn-mia-c0-existing") is None


def test_reduced_prefix_selects_child_instead_of_full_vocab_mtp3():
    assert projection.spec_for_run_name(
        "qfn-mia-mtp3-red47k-child"
    ) is MIA_MTP3_REDUCED47K_OPT
