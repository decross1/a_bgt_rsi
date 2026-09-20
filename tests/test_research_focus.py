from __future__ import annotations

import hashlib
import json

import pytest

from orchestrator import research_campaign
from orchestrator import research_focus as focus


@pytest.fixture
def source(tmp_path, monkeypatch):
    (tmp_path / "memory").mkdir()
    row = {
        "iteration_id": "iter-2026-09-15-007",
        "campaign": {
            "campaign_id": "seed-campaign",
            "campaign_manifest_sha256": "a" * 64,
        },
        "hypothesis": {"text": '{"candidates": ["truncated'},
        "retrieval": {"relevance": {"low_confidence": False}},
        "novelty": {"class": "novel"},
        "critique": {"verdict": "survives"},
    }
    (tmp_path / "memory/loop_memory.jsonl").write_text(json.dumps(row) + "\n")
    monkeypatch.setattr(
        research_campaign,
        "load_campaign",
        lambda name, **kw: {"campaign_id": name, "_manifest_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        research_campaign,
        "record_matches",
        lambda row, campaign: (
            row.get("campaign", {}).get("campaign_manifest_sha256") == "a" * 64
        ),
    )
    return tmp_path, row


def choose(root, **kw):
    return focus.select_focus(
        root,
        iteration_id="iter-2026-09-15-007",
        focus_id="focus-payoff-support",
        title="Payoff assistance and agent behavior",
        reason="Continue a historical seed; it is not a clean validated claim.",
        selected_by="codex",
        next_action="Refine the claim and freeze the study.",
        next_gate={
            "from": "research_seed",
            "to": "study_ready",
            "artifact": "protocol",
            "status": "pending",
            "owner": "Oracle + Codex",
        },
        blockers=["Raw structured hypothesis needs clean refinement."],
        **kw,
    )


def test_selection_is_not_scientific_credit_or_campaign_activation(source):
    root, row = source
    original = (root / "memory/loop_memory.jsonl").read_bytes()
    result = choose(root)
    assert result["status"] == "selected"
    assert result["source_record_ordinal"] == 1
    assert (
        result["source_row_sha256"]
        == hashlib.sha256(original.splitlines()[0]).hexdigest()
    )
    assert result["source_quality"] == "raw_structured_hypothesis"
    assert result["source_evidence_level"] is None
    assert result["evidence_refs"] == [
        {
            "path": "memory/loop_memory.jsonl",
            "iteration_id": row["iteration_id"],
            "record_ordinal": 1,
            "row_sha256": result["source_row_sha256"],
        }
    ]
    assert result["stage"] == "needs_clean_refinement"
    assert result["execution_authorized"] is False
    assert result["scientific_credit"] == "none_selection_only"
    assert not (root / "run_state/active_research_campaign.json").exists()
    assert (root / "memory/loop_memory.jsonl").read_bytes() == original


def test_append_does_not_invalidate_but_source_edit_does(source):
    root, row = source
    choose(root)
    ledger = root / "memory/loop_memory.jsonl"
    with ledger.open("a") as stream:
        stream.write(json.dumps({"iteration_id": "other"}) + "\n")
    assert focus.project_focus(root)["status"] == "selected"
    row["hypothesis"]["text"] = "rewritten"
    ledger.write_text(json.dumps(row) + "\n")
    assert focus.project_focus(root)["status"] == "source_invalid"


def test_semantically_identical_raw_row_rewrite_invalidates_exact_source(source):
    root, row = source
    choose(root)
    (root / "memory/loop_memory.jsonl").write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    )
    assert focus.project_focus(root)["status"] == "source_invalid"


def test_source_record_ordinal_is_bound_even_when_raw_row_is_unchanged(source):
    root, _ = source
    choose(root)
    ledger = root / "memory/loop_memory.jsonl"
    original = ledger.read_bytes()
    ledger.write_bytes(b'{"iteration_id":"earlier"}\n' + original)
    assert focus.project_focus(root)["status"] == "source_invalid"


def test_plain_hypothesis_keeps_historical_derived_level_without_credit(source):
    root, row = source
    text = "Payoff assistance can change oracle-consistent actions."
    row["hypothesis"] = {
        "text": text,
        "candidates_considered": 1,
        "all_candidates": [text],
    }
    (root / "memory/loop_memory.jsonl").write_text(json.dumps(row) + "\n")
    result = choose(root)
    assert result["source_quality"] == "plain_hypothesis"
    assert result["source_evidence_level"] == "L1"
    assert result["scientific_credit"] == "none_selection_only"


def test_missing_hypothesis_has_no_source_evidence_level(source):
    root, row = source
    row.pop("hypothesis")
    (root / "memory/loop_memory.jsonl").write_text(json.dumps(row) + "\n")
    result = choose(root)
    assert result["source_quality"] == "missing_hypothesis"
    assert result["source_evidence_level"] is None


def test_malformed_hypothesis_has_no_source_evidence_level(source):
    root, row = source
    row["hypothesis"] = ["not", "the", "contract"]
    (root / "memory/loop_memory.jsonl").write_text(json.dumps(row) + "\n")
    result = choose(root)
    assert result["source_quality"] == "missing_hypothesis"
    assert result["source_evidence_level"] is None


def test_plain_text_with_incomplete_worker_contract_has_no_derived_level(source):
    root, row = source
    row["hypothesis"] = {
        "text": "A visible sentence is not enough to prove a selected candidate.",
        "candidates_considered": 1,
    }
    (root / "memory/loop_memory.jsonl").write_text(json.dumps(row) + "\n")
    result = choose(root)
    assert result["source_quality"] == "raw_structured_hypothesis"
    assert result["source_evidence_level"] is None


def test_duplicate_identity_is_not_a_valid_source(source):
    root, row = source
    choose(root)
    with (root / "memory/loop_memory.jsonl").open("a") as stream:
        stream.write(json.dumps(row) + "\n")
    assert focus.project_focus(root)["status"] == "source_invalid"


def test_reselection_requires_exact_previous_digest_and_preserves_receipt(source):
    root, _ = source
    first = choose(root)
    path = root / focus.DIRECTORY / (first["receipt_sha256"] + ".json")
    original = path.read_bytes()
    with pytest.raises(focus.FocusError, match="changed"):
        choose(root)
    second = choose(root, expected_previous_sha256=first["receipt_sha256"])
    assert second["status"] == "selected"
    assert path.read_bytes() == original
    assert len(list((root / focus.DIRECTORY).glob("*.json"))) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "receipt_tamper",
        "receipt_symlink",
        "pointer_duplicate",
        "pointer_symlink_loop",
        "tail",
    ],
)
def test_corrupt_or_redirected_data_is_invalid_not_absent(source, mutation):
    root, _ = source
    result = choose(root)
    receipt = root / focus.DIRECTORY / (result["receipt_sha256"] + ".json")
    if mutation == "receipt_tamper":
        receipt.write_text(receipt.read_text().replace("codex", "other"))
    elif mutation == "receipt_symlink":
        data = receipt.read_bytes()
        receipt.unlink()
        target = root / "other.json"
        target.write_bytes(data)
        receipt.symlink_to(target)
    elif mutation == "pointer_duplicate":
        (root / focus.POINTER).write_text('{"receipt_sha256":"a","receipt_sha256":"b"}')
    elif mutation == "pointer_symlink_loop":
        pointer = root / focus.POINTER
        pointer.unlink()
        pointer.symlink_to(pointer.name)
    else:
        with (root / "memory/loop_memory.jsonl").open("a") as stream:
            stream.write('{"incomplete":')
    assert focus.project_focus(root)["status"] == "source_invalid"


def test_absent_is_distinct_from_invalid(tmp_path):
    assert focus.project_focus(tmp_path) == {
        "status": "none",
        "execution_authorized": False,
    }


def test_invalid_policy_cannot_be_installed(source):
    root, _ = source
    with pytest.raises(focus.FocusError, match="policy"):
        choose(root, intake_policy="execute_study")
    assert focus.project_focus(root)["status"] == "none"


@pytest.mark.parametrize("stage", ["study_ready", "diagnostic_recorded"])
def test_unverified_advanced_stage_cannot_be_installed(source, stage):
    root, _ = source
    with pytest.raises(focus.FocusError, match="stage"):
        choose(root, stage=stage)
    assert focus.project_focus(root)["status"] == "none"


@pytest.mark.parametrize("status", ["selected", "source_invalid"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_focus_holds_discovery_before_registration_or_model_call(
    monkeypatch, tmp_path, status, dry_run
):
    from orchestrator import coordinator, daily_research

    view = {"status": status, "intake_policy": "focus_before_new_topics"}
    monkeypatch.setattr(focus, "project_focus", lambda _root: view)
    monkeypatch.setattr(
        daily_research, "replenish", lambda *_a: pytest.fail("new topic registered")
    )
    monkeypatch.setattr(
        coordinator, "plan", lambda *_a, **_kw: pytest.fail("model planner called")
    )
    monkeypatch.setattr(
        coordinator,
        "assess_state",
        lambda **_kw: {
            "topic_suggestions": [{"topic": "another discovery"}],
            "gaps": [],
        },
    )
    receipts = []
    monkeypatch.setattr(
        coordinator.coordinator_cycle_log, "write_coordinator_cycle", receipts.append
    )
    monkeypatch.setattr(
        coordinator.coordinator_cycle_log, "emit_health_signals", lambda *_a: None
    )
    campaign = {
        "topic_policy": {"mode": "registered_exploratory"},
        "campaign_id": "daily",
        "_manifest_sha256": "a" * 64,
        "_repo_root": tmp_path,
    }
    report = coordinator._coordinator_cycle(
        run_id="focus-test",
        budget=6,
        dry_run=dry_run,
        execute_handlers=None,
        backend=None,
        model=None,
        loop_memory_path=tmp_path / "loop.jsonl",
        surfaced_path=tmp_path / "surfaced.jsonl",
        feedback_path=tmp_path / "feedback.jsonl",
        active_run_path=tmp_path / "active.json",
        campaign=campaign,
    )
    assert report["status"] == (
        "focus_pending" if status == "selected" else "focus_invalid"
    )
    assert report["gate_reason"] == "research_focus"
    assert report["state"]["research_focus"] == view
    assert report["plan"] == report["executed"] == []
    assert receipts == [report]
