"""Hermetic tests for V2 source-bound empirical admission."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from orchestrator import experiment_admission as admission
from workers.evidence_ladder import derive_level


def _raw(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _case(
    tmp_path: Path,
    *,
    units: int = 30,
    l2_capable: bool = True,
    evidence_kind: str = "registered_synthetic_study",
) -> dict:
    root = tmp_path / "repo"
    (root / "experiments").mkdir(parents=True)
    (root / "run_state").mkdir()
    verifier_path = root / "experiments/test_admission_verifier.py"
    verifier_path.write_text("# frozen test verifier\n")
    prereg_path = root / "experiments/PREREG_test.md"
    prereg_path.write_text("# frozen test preregistration\n")
    study_manifest = {
        "campaign_id": "v2-test-campaign",
        "study_id": "registered-study-v1",
        "execution_modules": {
            "independent_admission_path": "experiments/test_admission_verifier.py",
            "independent_admission_sha256": _sha(verifier_path.read_bytes()),
        },
    }
    study_path = root / "experiments/study.json"
    study_path.write_bytes(_raw(study_manifest))

    artifact_base = tmp_path / "allowlisted-artifacts"
    output = artifact_base / "run-a"
    output.mkdir(parents=True)
    run = {"status": "complete", "independent_episodes": units, "effect": 0.25}
    (output / "run.json").write_bytes(_raw(run))

    calls: list[Path] = []

    def validator(path: Path) -> dict:
        calls.append(path)
        raw = (path / "run.json").read_bytes()
        value = json.loads(raw)
        if value.get("status") != "complete":
            return {
                "campaign_id": "v2-test-campaign",
                "study_id": "registered-study-v1",
                "admission_eligible": False,
            }
        return {
            "campaign_id": "v2-test-campaign",
            "study_id": "registered-study-v1",
            "admission_eligible": True,
            "recorded_episodes": value["independent_episodes"],
            "run_sha256": _sha(raw),
            "effect": value["effect"],
        }

    def outcome_builder(gate: dict) -> dict:
        return {
            "experiment_id": "registered-study-v1",
            "metric": "registered_effect",
            "value": {
                "effect": gate["effect"],
                "run_sha256": gate["run_sha256"],
            },
            "trials": gate["recorded_episodes"],
            "summary": "Registered synthetic outcome.",
        }

    spec = admission.VerifierSpec(
        verifier_id="test-study/v1",
        campaign_id="v2-test-campaign",
        study_id="registered-study-v1",
        metric="registered_effect",
        verifier_source_path="experiments/test_admission_verifier.py",
        raw_result_path="run.json",
        unit_name="independent_episodes",
        evidence_kind=evidence_kind,
        l2_capable=l2_capable,
        artifact_roots={"test-root": artifact_base},
        validator_loader=lambda: validator,
        outcome_builder=outcome_builder,
    )
    campaign = {
        "campaign_id": "v2-test-campaign",
        "_manifest_sha256": "a" * 64,
        "_repo_root": root,
        "research_question": {
            "question_id": "rq-test",
            "text_sha256": "b" * 64,
        },
        "topic_policy": {
            "topics": [
                {
                    "topic_id": "topic-test",
                    "text": "Registered test topic",
                    "text_sha256": "c" * 64,
                }
            ]
        },
        "study_manifests": [
            {
                "study_id": "registered-study-v1",
                "path": "experiments/study.json",
                "sha256": _sha(study_path.read_bytes()),
                "preregistration_path": "experiments/PREREG_test.md",
                "preregistration_sha256": _sha(prereg_path.read_bytes()),
            }
        ],
    }
    link = {
        "schema_version": "research-campaign-link/v1",
        "campaign_id": campaign["campaign_id"],
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "research_question_id": "rq-test",
        "research_question_sha256": "b" * 64,
        "topic_id": "topic-test",
        "topic_sha256": "c" * 64,
    }
    raw_run = (output / "run.json").read_bytes()
    gate = {
        "recorded_episodes": units,
        "run_sha256": _sha(raw_run),
        "effect": run["effect"],
    }
    outcome = outcome_builder(gate)
    request = admission.AdmissionRequest(
        verifier_id=spec.verifier_id,
        artifact_root_id="test-root",
        artifact_subpath="run-a",
    )
    return {
        "root": root,
        "campaign": campaign,
        "link": link,
        "outcome": outcome,
        "request": request,
        "specs": {spec.verifier_id: spec},
        "output": output,
        "prereg_path": prereg_path,
        "calls": calls,
    }


def _row(case: dict, reference: dict) -> dict:
    text = "Agents condition equilibrium play on a disclosed payoff signal."
    return {
        "iteration_id": "iter-2099-01-01-001",
        "campaign": copy.deepcopy(case["link"]),
        "hypothesis": {
            "text": text,
            "candidates_considered": 1,
            "all_candidates": [text],
        },
        "retrieval": {"relevance": {"low_confidence": False}},
        "novelty": {"class": "novel"},
        "critique": {"verdict": "survives"},
        "experiment_outcome": copy.deepcopy(case["outcome"]),
        "experiment_admission_ref": copy.deepcopy(reference),
    }


def _admit(case: dict) -> admission.AdmissionBundle:
    return admission.admit_for_dispatch(
        repo_root=case["root"],
        campaign=case["campaign"],
        campaign_link=case["link"],
        outcome=case["outcome"],
        request=case["request"],
        specs=case["specs"],
    )


def _load(case: dict, row: dict) -> admission.AdmissionContext | None:
    return admission.load_context(
        row,
        repo_root=case["root"],
        specs=case["specs"],
        campaign_loader=lambda _campaign_id, _root: copy.deepcopy(case["campaign"]),
    )


def test_verified_registered_30_episode_fixture_can_earn_v2_l2(tmp_path):
    case = _case(tmp_path)
    bundle = _admit(case)
    row = _row(case, bundle.reference)
    context = _load(case, row)
    assert context is not None
    result = derive_level(row, None, None, [], admission_context=context)
    assert result["level"] == "L2"
    assert bundle.reference["independent_units"] == 30
    receipt = case["root"] / bundle.reference["receipt_path"]
    assert _sha(receipt.read_bytes()) == bundle.reference["receipt_sha256"]
    assert len(case["calls"]) == 2  # dispatch admission + reader replay


def test_registered_29_episode_fixture_remains_l1(tmp_path):
    case = _case(tmp_path, units=29)
    bundle = _admit(case)
    row = _row(case, bundle.reference)
    context = _load(case, row)
    result = derive_level(row, None, None, [], admission_context=context)
    assert result["level"] == "L1"
    assert any(
        "verified independent_episodes=29" in item
        for item in result["missing_for_next"]
    )


def test_verified_diagnostic_never_earns_l2_even_with_30_units(tmp_path):
    case = _case(tmp_path, l2_capable=False, evidence_kind="diagnostic")
    bundle = _admit(case)
    row = _row(case, bundle.reference)
    context = _load(case, row)
    result = derive_level(row, None, None, [], admission_context=context)
    assert result["level"] == "L1"
    assert any(
        "diagnostic" in item and "cannot earn L2" in item
        for item in result["missing_for_next"]
    )


def test_diagnostic_verifier_cannot_declare_itself_l2_capable(tmp_path):
    case = _case(tmp_path, l2_capable=True, evidence_kind="diagnostic")
    with pytest.raises(admission.AdmissionError, match="diagnostic verifier"):
        _admit(case)
    assert case["calls"] == []


def test_study_must_preregister_the_exact_independent_verifier(tmp_path):
    case = _case(tmp_path)
    study_path = case["root"] / "experiments/study.json"
    study = json.loads(study_path.read_bytes())
    study["execution_modules"] = {}
    study_path.write_bytes(_raw(study))
    case["campaign"]["study_manifests"][0]["sha256"] = _sha(study_path.read_bytes())
    with pytest.raises(admission.AdmissionError, match="registered independent"):
        _admit(case)
    assert case["calls"] == []


def test_raw_result_cannot_change_while_verifier_runs(tmp_path):
    case = _case(tmp_path)
    spec = next(iter(case["specs"].values()))
    validator = spec.validator_loader()

    def mutating_validator(path: Path) -> dict:
        gate = validator(path)
        (path / "run.json").write_bytes(
            _raw({"status": "complete", "independent_episodes": 31, "effect": 0.25})
        )
        return gate

    case["specs"] = {
        spec.verifier_id: replace(spec, validator_loader=lambda: mutating_validator)
    }
    with pytest.raises(admission.AdmissionError, match="changed during verification"):
        _admit(case)


def test_registered_topic_receipt_is_taken_from_trusted_registry(tmp_path):
    case = _case(tmp_path)
    topic = case["campaign"]["topic_policy"]["topics"].pop()
    topic["topic_registration_sha256"] = "d" * 64
    case["campaign"]["_registered_topics"] = [topic]
    case["link"]["topic_registration_sha256"] = "d" * 64
    bundle = _admit(case)
    assert bundle.reference["topic_id"] == topic["topic_id"]

    forged = copy.deepcopy(case["link"])
    forged["topic_registration_sha256"] = "e" * 64
    with pytest.raises(admission.AdmissionError, match="campaign/topic link differs"):
        admission.admit_for_dispatch(
            repo_root=case["root"],
            campaign=case["campaign"],
            campaign_link=forged,
            outcome=case["outcome"],
            request=case["request"],
            specs=case["specs"],
        )


def test_receipt_is_idempotent_and_content_addressed(tmp_path):
    case = _case(tmp_path)
    first = _admit(case)
    second = _admit(case)
    assert first.reference == second.reference
    receipts = list((case["root"] / admission.RECEIPT_DIRECTORY).glob("*.json"))
    assert len(receipts) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "raw_result",
        "preregistration",
        "campaign_topic",
        "outcome",
        "reference",
        "receipt",
    ],
)
def test_reader_rejects_every_source_binding_tamper(tmp_path, mutation):
    case = _case(tmp_path)
    bundle = _admit(case)
    row = _row(case, bundle.reference)
    if mutation == "raw_result":
        (case["output"] / "run.json").write_bytes(
            _raw({"status": "complete", "independent_episodes": 31, "effect": 0.25})
        )
    elif mutation == "preregistration":
        case["prereg_path"].write_text("changed preregistration\n")
    elif mutation == "campaign_topic":
        row["campaign"]["topic_sha256"] = "d" * 64
    elif mutation == "outcome":
        row["experiment_outcome"]["summary"] = "Different result."
    elif mutation == "reference":
        row["experiment_admission_ref"]["independent_units"] = 31
    else:
        receipt = case["root"] / bundle.reference["receipt_path"]
        receipt.write_bytes(
            receipt.read_bytes().replace(b"registered_effect", b"changed_metric")
        )
    with pytest.raises(admission.AdmissionError):
        _load(case, row)


@pytest.mark.parametrize(
    "admission_request",
    [
        admission.AdmissionRequest("test-study/v1", "unknown-root", "run-a"),
        admission.AdmissionRequest("test-study/v1", "test-root", "../run-a"),
        admission.AdmissionRequest("unknown/v1", "test-root", "run-a"),
    ],
)
def test_unallowlisted_or_traversing_request_refuses_before_verifier(
    tmp_path, admission_request
):
    case = _case(tmp_path)
    with pytest.raises(admission.AdmissionError):
        admission.admit_for_dispatch(
            repo_root=case["root"],
            campaign=case["campaign"],
            campaign_link=case["link"],
            outcome=case["outcome"],
            request=admission_request,
            specs=case["specs"],
        )
    assert case["calls"] == []


def test_self_asserted_verified_flag_has_no_reader_authority(tmp_path):
    case = _case(tmp_path)
    row = _row(case, {})
    row.pop("experiment_admission_ref")
    row["experiment_outcome"]["verified"] = True
    assert _load(case, row) is None
    assert derive_level(row, None, None, [])["level"] == "L1"


def test_verified_level_helper_replays_valid_reference(tmp_path, monkeypatch):
    case = _case(tmp_path)
    bundle = _admit(case)
    row = _row(case, bundle.reference)
    context = _load(case, row)
    monkeypatch.setattr(admission, "load_context", lambda *_args, **_kwargs: context)
    result = admission.derive_verified_level(
        row, None, None, [], repo_root=case["root"]
    )
    assert result["level"] == "L2"
    assert "experiment_admission_invalid" not in result["provisional"]


def test_verified_level_helper_leaves_missing_reference_fail_closed(tmp_path):
    case = _case(tmp_path)
    row = _row(case, {})
    row.pop("experiment_admission_ref")
    result = admission.derive_verified_level(
        row, None, None, [], repo_root=case["root"]
    )
    assert result["level"] == "L1"
    assert "experiment_admission_invalid" not in result["provisional"]


def test_verified_level_helper_surfaces_invalid_reference_without_mutating_row(
    tmp_path,
):
    case = _case(tmp_path)
    bundle = _admit(case)
    row = _row(case, bundle.reference)
    row["experiment_admission_ref"]["receipt_sha256"] = "f" * 64
    before = copy.deepcopy(row)
    result = admission.derive_verified_level(
        row, None, None, [], repo_root=case["root"]
    )
    assert result["level"] == "L1"
    assert "experiment_admission_invalid" in result["provisional"]
    assert any("admission replay failed" in reason for reason in result["reasons"])
    assert row == before


def test_verified_level_helper_does_not_hide_programming_failures(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        admission,
        "load_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bug")),
    )
    with pytest.raises(RuntimeError, match="bug"):
        admission.derive_verified_level({}, None, None, [], repo_root=tmp_path)


def test_known_opponent_projection_is_supported_but_twelve_is_below_l2():
    spec = admission.DEFAULT_VERIFIERS["known-opponent-utility-pilot/v1"]
    gate = {
        "scheduled_action_calls": 96,
        "valid_action_calls": 96,
        "scheduled_episodes": 12,
        "complete_episodes": 12,
        "zero_regret_complete_episodes": 3,
        "comprehension_passed": 0,
        "attempted_calls": 108,
        "run_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "recorded_episodes": 12,
    }
    outcome = spec.outcome_builder(gate)
    assert outcome["trials"] == 12
    assert spec.l2_capable is True
    assert spec.unit_name == "independent_episodes"
