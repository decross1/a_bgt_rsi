from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import orchestrator.research_pipeline_progress as progress_module
from orchestrator.research_campaign import bind_topic, load_campaign
from orchestrator.research_pipeline_progress import project_research_pipeline

NOW = datetime(2026, 9, 14, 23, 59, tzinfo=timezone.utc)
CUTOFF = "2026-09-14T16:17:51.902964Z"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_RELATIVE_FILES = (
    "schema/research_campaign.schema.json",
    "experiments/research_campaign_v2_agentic_game_theory_20260914.json",
    "experiments/agentic_game_theory_v2_calibration_2026-09-14.json",
    "experiments/PREREG_agentic_game_theory_v2_calibration_2026-09-14.md",
)
_SOURCE_CAMPAIGN = load_campaign(repo_root=SOURCE_ROOT)
DEFAULT_CAMPAIGN_LINK = bind_topic(
    _SOURCE_CAMPAIGN, _SOURCE_CAMPAIGN["research_question"]["text"],
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(root: Path, relative: str, rows: list[dict]) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    for relative in CAMPAIGN_RELATIVE_FILES:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_ROOT / relative, destination)
    _write_json(
        tmp_path / "run_state/weekly_upgrade/activation-2026-09-14/activation.json",
        {
            "schema_version": "weekly-upgrade-activation/v1",
            "activated_at": CUTOFF,
            "canonical_head": "a" * 40,
            "startup_verified": True,
            "service": {"ActiveState": "active", "SubState": "running"},
        },
    )
    _write_json(
        tmp_path / "run_state/active_research_campaign.json",
        {
            "schema_version": "research-campaign-activation/v1",
            "campaign_id": _SOURCE_CAMPAIGN["campaign_id"],
            "campaign_manifest_sha256": _SOURCE_CAMPAIGN["_manifest_sha256"],
            "activated_at": "2026-09-14T22:20:00Z",
            "activated_by": "projection-test",
        },
    )
    for relative in (
        "run_state/coordinator_cycles.jsonl",
        "memory/loop_memory.jsonl",
        "memory/promotion_near_misses.jsonl",
        "memory/surfaced_findings.jsonl",
        "memory/loop_feedback.jsonl",
        "run_state/health_signals.jsonl",
    ):
        _write_jsonl(tmp_path, relative, [])
    return tmp_path


def _campaign_link(root: Path) -> dict[str, str]:
    campaign = load_campaign(repo_root=root)
    return bind_topic(campaign, campaign["research_question"]["text"])


def _digest(request: dict) -> str:
    raw = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _cycle(
    *,
    run_id: str,
    step_id: str,
    iteration_id: str | None,
    at: str,
    outcome_status: str = "passed",
    args: dict | None = None,
    campaign: dict | None = DEFAULT_CAMPAIGN_LINK,
) -> dict:
    request = {"action": "run_loop_iteration", "args": args or {"seed": run_id}}
    digest = _digest(request)
    row = {
        "timestamp": at,
        "run_id": run_id,
        "status": "executed",
        "topic_source": "coordinator_propose",
        "dispatched_iteration_id": iteration_id,
        # This must never reach the public projection.
        "private_topic": "SECRET_TOPIC_PAYLOAD",
        "plan": [{"step_id": step_id, "action": request["action"], "args": request["args"], "request_digest": digest}],
        "outcomes": [{"step_id": step_id, "action": request["action"], "request": request, "request_digest": digest, "status": outcome_status}],
    }
    if campaign is not None:
        row["campaign"] = campaign
    return row


def _l3_iteration(
    iteration_id: str, *, at: str, topicality: str = "on",
    campaign: dict | None = DEFAULT_CAMPAIGN_LINK,
) -> dict:
    row = {
        "iteration_id": iteration_id,
        "started_at": at,
        "hypothesis": "SECRET_HYPOTHESIS_PAYLOAD",
        "retrieval": {"relevance": {"low_confidence": False, "topicality": topicality}},
        "novelty": {"class": "novel"},
        "critique": {"verdict": "survives"},
        "redteam": {"verdict": "proceed"},
        "experiment_outcome": {"trials": 30, "summary": "valid recorded result"},
        "cross_tier_comparison": {"replicated": True},
    }
    if campaign is not None:
        row["campaign"] = campaign
    return row


def test_empty_post_cutoff_window_is_not_yet_observed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write_jsonl(
        root,
        "run_state/coordinator_cycles.jsonl",
        [{"timestamp": "2026-09-14T22:30:00Z", "run_id": "cycle-noop", "status": "executed", "plan": [{"action": "noop"}], "outcomes": []}],
    )

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["status"] == "not_yet_observed"
    assert result["counts"]["topic_attempts"] == 0
    assert result["bottleneck"]["stage"] == "dispatch"
    assert result["coverage"][0]["rate"] is None
    assert result["cohort"]["cutoff_at"] == CUTOFF
    assert result["cohort"]["cutoff_receipt_sha256"]
    assert result["campaign"]["campaign_id"] == "v2-agentic-game-theory-20260914"
    assert result["campaign"]["status"] == "prepared"
    assert result["campaign"]["runtime"] == {
        "status": "active",
        "activated_at": "2026-09-14T22:20:00Z",
        "activation_sha256": result["campaign"]["runtime"]["activation_sha256"],
        "closed_at": None,
        "closure_sha256": None,
    }
    assert len(result["campaign"]["runtime"]["activation_sha256"]) == 64
    assert result["campaign"]["evidence"] == {
        "cpu_calibration_registered": True,
        "cpu_calibration_verified": None,
        "model_trial_status": "not_registered",
    }
    assert "not_run" not in json.dumps(result["campaign"]["evidence"])
    assert result["window"]["mode"] == "campaign_to_date"
    assert result["window"]["start_at"] == "2026-09-14T22:20:00Z"
    assert all(
        source["window_sha256"]
        for source in result["provenance"]["sources"]
        if source["available"]
    )
    closure_source = next(
        source for source in result["provenance"]["sources"]
        if source["id"] == "campaign_closure"
    )
    assert closure_source["available"] is False
    assert closure_source["malformed_rows"] == 0


def test_campaign_membership_requires_exact_link_not_time_or_text(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    unlinked = _cycle(
        run_id="cycle-legacy", step_id="cycle-legacy:step:0",
        iteration_id="iter-legacy", at="2026-09-14T22:31:00Z", campaign=None,
    )
    unlinked["topic"] = _SOURCE_CAMPAIGN["research_question"]["text"]
    different = _cycle(
        run_id="cycle-other", step_id="cycle-other:step:0",
        iteration_id="iter-other", at="2026-09-14T22:32:00Z",
        campaign={**DEFAULT_CAMPAIGN_LINK, "campaign_id": "another-campaign"},
    )
    malformed = _cycle(
        run_id="cycle-malformed", step_id="cycle-malformed:step:0",
        iteration_id="iter-malformed", at="2026-09-14T22:33:00Z",
        campaign={"campaign_id": "v2-agentic-game-theory-20260914"},
    )
    matched = _cycle(
        run_id="cycle-match", step_id="cycle-match:step:0",
        iteration_id="iter-match", at="2026-09-14T22:34:00Z",
    )
    _write_jsonl(
        root, "run_state/coordinator_cycles.jsonl",
        [unlinked, different, malformed, matched],
    )
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration(
            "iter-legacy", at="2026-09-14T22:31:01Z", campaign=None,
        ),
        _l3_iteration("iter-match", at="2026-09-14T22:34:01Z"),
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["counts"]["topic_attempts"] == 1
    assert result["counts"]["iterations_recorded"] == 1
    assert [row["cycle_run_id"] for row in result["records"]] == ["cycle-match"]
    lineage = result["provenance"]["campaign_lineage"]
    assert lineage["coordinator_cycles"] == {
        "explicit_match": 1,
        "unlinked_legacy": 1,
        "malformed_campaign_link": 1,
        "different_campaign": 1,
        "campaign_link_mismatch": 0,
        "malformed_record": 0,
    }
    assert lineage["loop_memory"]["explicit_match"] == 1
    assert lineage["loop_memory"]["unlinked_legacy"] == 1
    assert any(
        item["code"] == "coordinator_cycles_campaign_rows_excluded"
        for item in result["qualifications"]
    )
    encoded = json.dumps(result)
    # The question is intentionally public once in campaign metadata. The
    # same unlinked row text is neither exposed nor used as lineage evidence.
    assert encoded.count(_SOURCE_CAMPAIGN["research_question"]["text"]) == 1


def test_exact_identifier_chain_can_earn_l5_without_exposing_payloads(tmp_path: Path) -> None:
    root = _root(tmp_path)
    iteration_id = "iter-2026-09-14-009"
    cycle = _cycle(
        run_id="cycle-1", step_id="cycle-1:step:0",
        iteration_id=iteration_id, at="2026-09-14T22:30:00Z",
    )
    cycle["topic_source"] = "campaign_preregistered"
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        cycle,
    ])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration(iteration_id, at="2026-09-14T22:30:01Z")
    ])
    _write_jsonl(root, "memory/surfaced_findings.jsonl", [{
        "campaign": DEFAULT_CAMPAIGN_LINK,
        "source_iteration_id": iteration_id,
        "finding_id": f"sf-{iteration_id}",
        "promoted_at": "2026-09-14T22:45:00Z",
        "finding": "SECRET_FINDING_PAYLOAD",
        "adversarial": {"survived": True},
    }])
    _write_jsonl(root, "memory/loop_feedback.jsonl", [{
        "iteration_id": iteration_id,
        "gated_at": "2026-09-14T23:00:00Z",
        "verdict": "valid",
        "notes": "SECRET_HUMAN_NOTES",
    }])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["counts"]["topic_attempts"] == 1
    assert result["counts"]["iterations_recorded"] == 1
    assert result["counts"]["in_scope"] == 1
    assert result["counts"]["l4_validated"] == 1
    assert result["counts"]["l5_human_validated"] == 1
    assert result["records"] == [{
        "attempt_id": "cycle-1:step:0",
        "cycle_run_id": "cycle-1",
        "recorded_at": "2026-09-14T22:30:00Z",
        "topic_source": "campaign_preregistered",
        "campaign_id": "v2-agentic-game-theory-20260914",
        "topic_id": "topic-incentives-identified-history-001",
        "dispatch_status": "completed",
        "iteration_id": iteration_id,
        "iteration_status": "recorded",
        "scope_status": "in_scope",
        "evidence_level": "L5",
        "evidence_provisional": [],
        "skeptic_status": "validated",
        "promotion_status": "validated",
        "human_validation_status": "validated",
        "promotion_review_attempts": 1,
    }]
    encoded = json.dumps(result)
    assert "SECRET_" not in encoded


def test_repeated_attempts_adverse_order_and_unlinked_records_stay_explicit(tmp_path: Path) -> None:
    root = _root(tmp_path)
    linked = "iter-linked"
    missing = "iter-missing"
    unlinked = "iter-unlinked"
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(run_id="cycle-2", step_id="cycle-2:step:0", iteration_id=linked, at="2026-09-14T22:32:00Z"),
        _cycle(run_id="cycle-1", step_id="cycle-1:step:0", iteration_id=linked, at="2026-09-14T22:31:00Z"),
        _cycle(run_id="cycle-3", step_id="cycle-3:step:0", iteration_id=missing, at="2026-09-14T22:33:00Z"),
        _cycle(run_id="cycle-4", step_id="cycle-4:step:0", iteration_id=None, at="2026-09-14T22:34:00Z"),
    ])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration(unlinked, at="2026-09-14T22:30:20Z"),
        _l3_iteration(linked, at="2026-09-14T22:30:10Z"),
    ])
    # Latest timestamp wins despite adverse file ordering.
    _write_jsonl(root, "memory/promotion_near_misses.jsonl", [
        {"source_iteration_id": linked, "timestamp": "2026-09-14T23:15:00Z", "stage": "adversarial"},
        {"source_iteration_id": linked, "timestamp": "2026-09-14T23:00:00Z", "stage": "threshold"},
        {"source_iteration_id": linked, "timestamp": "bad-time", "stage": "adversarial"},
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    counts = result["counts"]
    assert counts["topic_attempts"] == 4
    assert counts["dispatch_completions"] == 3
    assert counts["distinct_dispatched_iterations"] == 2
    assert counts["iterations_recorded"] == 1
    assert counts["missing_iteration_records"] == 1
    assert counts["unlinked_iteration_records"] == 1
    assert counts["missing_dispatch_iteration_links"] == 1
    assert counts["promotion_rejections"] == 1
    linked_records = [row for row in result["records"] if row["iteration_id"] == linked]
    assert len(linked_records) == 2
    assert all(row["skeptic_status"] == "rejected" for row in linked_records)


def test_invalid_or_duplicate_identities_never_create_false_completion(tmp_path: Path) -> None:
    root = _root(tmp_path)
    repeated = _cycle(
        run_id="cycle-repeat", step_id="repeated-step", iteration_id="iter-false",
        at="2026-09-14T22:30:00Z",
    )
    bad_digest = _cycle(
        run_id="cycle-digest", step_id="digest-step", iteration_id="iter-false-2",
        at="2026-09-14T22:31:00Z",
    )
    bad_digest["plan"][0]["request_digest"] = "sha256:" + "0" * 64
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [repeated, repeated, bad_digest])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration("iter-false", at="2026-09-14T22:30:10Z"),
        _l3_iteration("iter-false", at="2026-09-14T22:30:20Z"),
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["counts"]["topic_attempts"] == 3
    assert result["counts"]["dispatch_completions"] == 0
    assert result["counts"]["ambiguous_dispatches"] == 3
    assert result["counts"]["iterations_recorded"] == 0
    codes = {item["code"] for item in result["qualifications"]}
    assert {"duplicate_dispatch_identity", "duplicate_iteration_identity"} <= codes


def test_cycle_id_collisions_with_other_cohorts_are_ambiguous(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    exact_legacy = _cycle(
        run_id="cycle-shared-legacy", step_id="exact-legacy:step:0",
        iteration_id="iter-exact-legacy", at="2026-09-14T22:30:00Z",
    )
    legacy = _cycle(
        run_id="cycle-shared-legacy", step_id="legacy:step:0",
        iteration_id="iter-legacy", at="2026-09-14T22:29:00Z", campaign=None,
    )
    exact_other = _cycle(
        run_id="cycle-shared-other", step_id="exact-other:step:0",
        iteration_id="iter-exact-other", at="2026-09-14T22:32:00Z",
    )
    other = _cycle(
        run_id="cycle-shared-other", step_id="other:step:0",
        iteration_id="iter-other", at="2026-09-14T22:31:00Z",
        campaign={**DEFAULT_CAMPAIGN_LINK, "campaign_id": "other-campaign"},
    )
    _write_jsonl(
        root, "run_state/coordinator_cycles.jsonl",
        [legacy, exact_legacy, other, exact_other],
    )
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration("iter-exact-legacy", at="2026-09-14T22:30:10Z"),
        _l3_iteration("iter-exact-other", at="2026-09-14T22:32:10Z"),
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["counts"]["topic_attempts"] == 2
    assert result["counts"]["dispatch_completions"] == 0
    assert result["counts"]["ambiguous_dispatches"] == 2
    assert result["counts"]["iterations_recorded"] == 0
    assert any(
        item["code"] == "duplicate_dispatch_identity"
        for item in result["qualifications"]
    )


def test_iteration_id_collisions_with_other_cohorts_cannot_join_feedback(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    iteration_ids = ("iter-shared-legacy", "iter-shared-other")
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(
            run_id=f"cycle-{iteration_id}",
            step_id=f"cycle-{iteration_id}:step:0",
            iteration_id=iteration_id,
            at=f"2026-09-14T22:{30 + index:02d}:00Z",
        )
        for index, iteration_id in enumerate(iteration_ids)
    ])
    exact_rows = [
        _l3_iteration(iteration_id, at=f"2026-09-14T22:{30 + index:02d}:10Z")
        for index, iteration_id in enumerate(iteration_ids)
    ]
    legacy_collision = _l3_iteration(
        iteration_ids[0], at="2026-09-14T22:20:00Z", campaign=None,
    )
    other_collision = _l3_iteration(
        iteration_ids[1], at="2026-09-14T22:21:00Z",
        campaign={**DEFAULT_CAMPAIGN_LINK, "campaign_id": "other-campaign"},
    )
    _write_jsonl(
        root, "memory/loop_memory.jsonl",
        [legacy_collision, *exact_rows, other_collision],
    )
    _write_jsonl(root, "memory/loop_feedback.jsonl", [
        {
            "iteration_id": iteration_id,
            "gated_at": "2026-09-14T23:00:00Z",
            "verdict": "valid",
        }
        for iteration_id in iteration_ids
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["counts"]["dispatch_completions"] == 2
    assert result["counts"]["iterations_recorded"] == 0
    assert result["counts"]["missing_iteration_records"] == 2
    assert result["counts"]["l5_human_validated"] == 0
    assert any(
        item["code"] == "duplicate_iteration_identity"
        for item in result["qualifications"]
    )


def test_finding_id_collision_outside_campaign_cannot_promote(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    iteration_id = "iter-finding-collision"
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(
            run_id="cycle-finding-collision",
            step_id="cycle-finding-collision:step:0",
            iteration_id=iteration_id,
            at="2026-09-14T22:30:00Z",
        ),
    ])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration(iteration_id, at="2026-09-14T22:30:10Z"),
    ])
    finding = {
        "campaign": DEFAULT_CAMPAIGN_LINK,
        "source_iteration_id": iteration_id,
        "finding_id": f"sf-{iteration_id}",
        "promoted_at": "2026-09-14T22:45:00Z",
        "adversarial": {"survived": True},
    }
    _write_jsonl(root, "memory/surfaced_findings.jsonl", [
        {**finding, "campaign": None, "promoted_at": "2026-09-14T22:40:00Z"},
        finding,
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["counts"]["iterations_recorded"] == 1
    assert result["counts"]["l4_validated"] == 0
    assert result["records"][0]["promotion_status"] == "not_yet_observed"
    assert any(
        item["code"] == "duplicate_finding_identity"
        for item in result["qualifications"]
    )


def test_missing_cycle_identity_cannot_create_a_completion(tmp_path: Path) -> None:
    root = _root(tmp_path)
    invalid = _cycle(
        run_id="cycle-invalid", step_id="cycle-invalid:step:0",
        iteration_id="iter-invalid", at="2026-09-14T22:30:00Z",
    )
    invalid["run_id"] = None
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [invalid])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration("iter-invalid", at="2026-09-14T22:30:10Z"),
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["counts"]["topic_attempts"] == 1
    assert result["counts"]["dispatch_completions"] == 0
    assert result["counts"]["ambiguous_dispatches"] == 1
    assert result["counts"]["iterations_recorded"] == 0


def test_incomplete_cycle_tail_withholds_counts_instead_of_emitting_zero(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _root(tmp_path)
    early = _cycle(
        run_id="cycle-early", step_id="cycle-early:step:0",
        iteration_id="iter-early", at="2026-09-14T22:30:00Z",
    )
    late = _cycle(
        run_id="cycle-late", step_id="cycle-late:step:0",
        iteration_id="iter-late", at="2026-09-14T22:31:00Z", campaign=None,
    )
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [early, late])
    monkeypatch.setattr(progress_module, "MAX_SOURCE_ROWS", 1)

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["status"] == "unavailable"
    assert result["counts"]["topic_attempts"] is None
    source = next(
        item for item in result["provenance"]["sources"]
        if item["id"] == "coordinator_cycles"
    )
    assert source["truncated_before"] is True
    assert all(stage["status"] == "unavailable" for stage in result["stages"])
    assert all(item["status"] == "unavailable" for item in result["coverage"])
    assert result["provenance"]["campaign_lineage"]["coordinator_cycles"][
        "explicit_match"
    ] is None


def test_byte_truncated_cycle_tail_withholds_counts(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    rows = [
        _cycle(
            run_id=f"cycle-{index}", step_id=f"cycle-{index}:step:0",
            iteration_id=f"iter-{index}", at="2026-09-14T22:30:00Z",
            campaign=DEFAULT_CAMPAIGN_LINK if index == 0 else None,
        )
        for index in range(4)
    ]
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", rows)
    monkeypatch.setattr(progress_module, "MAX_SOURCE_BYTES", 700)

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["status"] == "unavailable"
    assert result["counts"]["topic_attempts"] is None
    source = next(
        item for item in result["provenance"]["sources"]
        if item["id"] == "coordinator_cycles"
    )
    assert source["truncated_before"] is True


def test_malformed_cycle_source_withholds_counts_instead_of_emitting_zero(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    path = root / "run_state/coordinator_cycles.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["status"] == "unavailable"
    assert result["counts"]["topic_attempts"] is None
    assert any(
        item["code"] == "coordinator_cycles_malformed_rows"
        for item in result["qualifications"]
    )
    assert all(stage["status"] == "unavailable" for stage in result["stages"])
    assert all(item["status"] == "unavailable" for item in result["coverage"])


def test_bounded_object_reader_survives_path_replacement(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _root(tmp_path)
    path = root / progress_module.DEFAULT_CUTOFF
    original_raw = path.read_bytes()
    original_read = progress_module._read_at_most
    replaced = False

    def replace_then_read(file_descriptor: int, limit: int) -> bytes:
        nonlocal replaced
        if not replaced:
            replaced = True
            path.replace(path.with_suffix(".original"))
            path.write_text("{not-json}\n", encoding="utf-8")
        return original_read(file_descriptor, limit)

    monkeypatch.setattr(progress_module, "_read_at_most", replace_then_read)

    value, provenance = progress_module._read_object(
        root, progress_module.DEFAULT_CUTOFF,
    )

    assert value is not None
    assert value["canonical_head"] == "a" * 40
    assert provenance["window_sha256"] == hashlib.sha256(original_raw).hexdigest()
    assert provenance["available"] is True


def test_oversized_object_is_rejected_without_an_unbounded_read(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _root(tmp_path)
    path = root / progress_module.DEFAULT_CUTOFF
    path.write_bytes(b"{" + b"x" * progress_module.MAX_OBJECT_BYTES + b"}")
    called = False

    def unexpected_read(_file_descriptor: int, _limit: int) -> bytes:
        nonlocal called
        called = True
        return b""

    monkeypatch.setattr(progress_module, "_read_at_most", unexpected_read)

    value, provenance = progress_module._read_object(
        root, progress_module.DEFAULT_CUTOFF,
    )

    assert value is None
    assert called is False
    assert provenance["available"] is False
    assert provenance["truncated_before"] is True
    assert provenance["total_bytes"] == progress_module.MAX_OBJECT_BYTES + 2


def test_missing_health_source_withholds_provisional_flags(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "run_state/health_signals.jsonl").unlink()
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(
            run_id="cycle-health", step_id="cycle-health:step:0",
            iteration_id="iter-health", at="2026-09-14T22:30:00Z",
        ),
    ])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration("iter-health", at="2026-09-14T22:30:10Z"),
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["records"][0]["evidence_provisional"] is None
    assert any(
        item["code"] == "health_signals_unavailable"
        for item in result["qualifications"]
    )


def test_campaign_progress_survives_iso_week_rollover(tmp_path: Path) -> None:
    root = _root(tmp_path)
    iteration_id = "iter-rollover"
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(
            run_id="cycle-rollover", step_id="cycle-rollover:step:0",
            iteration_id=iteration_id, at="2026-09-20T23:50:00Z",
        ),
    ])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration(iteration_id, at="2026-09-20T23:51:00Z"),
    ])
    _write_jsonl(root, "memory/surfaced_findings.jsonl", [{
        "campaign": DEFAULT_CAMPAIGN_LINK,
        "source_iteration_id": iteration_id,
        "finding_id": f"sf-{iteration_id}",
        "promoted_at": "2026-09-21T00:10:00Z",
        "adversarial": {"survived": True},
    }])
    _write_jsonl(root, "memory/loop_feedback.jsonl", [{
        "iteration_id": iteration_id,
        "gated_at": "2026-09-21T00:20:00Z",
        "verdict": "valid",
    }])

    result = project_research_pipeline(
        canonical_root=root,
        now=datetime(2026, 9, 21, 1, tzinfo=timezone.utc),
    )

    assert result["window"]["week"] == "2026-W39"
    assert result["window"]["start_at"] == "2026-09-14T22:20:00Z"
    assert result["counts"]["topic_attempts"] == 1
    assert result["counts"]["l4_validated"] == 1
    assert result["counts"]["l5_human_validated"] == 1


def test_inactive_campaign_never_counts_explicit_rows_as_runtime_progress(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    (root / progress_module.CAMPAIGN_ACTIVATION).unlink()
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(
            run_id="cycle-before-activation",
            step_id="cycle-before-activation:step:0",
            iteration_id="iter-before-activation",
            at="2026-09-14T22:30:00Z",
        ),
    ])
    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["campaign"]["status"] == "prepared"
    assert result["campaign"]["runtime"]["status"] == "inactive"
    assert result["counts"]["topic_attempts"] == 0
    assert result["bottleneck"]["stage"] == "activation"
    assert any(
        item["code"] == "campaign_not_activated"
        for item in result["qualifications"]
    )


def test_closed_campaign_caps_campaign_to_date_window(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    campaign = load_campaign(repo_root=root)
    closure_path = (
        root / progress_module.CAMPAIGN_CLOSURE_DIR
        / f"{campaign['campaign_id']}.json"
    )
    _write_json(closure_path, {
        "schema_version": "research-campaign-closure/v1",
        "campaign_id": campaign["campaign_id"],
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "closed_at": "2026-09-14T22:40:00Z",
        "closed_by": "projection-test",
    })
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(
            run_id="cycle-before-close", step_id="cycle-before-close:step:0",
            iteration_id="iter-before-close", at="2026-09-14T22:30:00Z",
        ),
        _cycle(
            run_id="cycle-after-close", step_id="cycle-after-close:step:0",
            iteration_id="iter-after-close", at="2026-09-14T22:50:00Z",
        ),
    ])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration(
            "iter-before-close", at="2026-09-14T22:45:00Z",
        ),
    ])
    _write_jsonl(root, "memory/surfaced_findings.jsonl", [{
        "campaign": DEFAULT_CAMPAIGN_LINK,
        "source_iteration_id": "iter-before-close",
        "finding_id": "sf-iter-before-close",
        "promoted_at": "2026-09-14T23:00:00Z",
        "adversarial": {"survived": True},
    }])
    _write_jsonl(root, "memory/loop_feedback.jsonl", [{
        "iteration_id": "iter-before-close",
        "gated_at": "2026-09-14T23:10:00Z",
        "verdict": "valid",
    }])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    runtime = result["campaign"]["runtime"]
    assert runtime["status"] == "closed"
    assert runtime["closed_at"] == "2026-09-14T22:40:00Z"
    assert len(runtime["closure_sha256"]) == 64
    assert result["window"]["end_at"] == "2026-09-14T23:59:00Z"
    assert result["window"]["dispatch_end_at"] == "2026-09-14T22:40:00Z"
    assert result["window"]["dispatch_closed"] is True
    assert result["window"]["complete"] is False
    assert result["counts"]["topic_attempts"] == 1
    assert result["counts"]["iterations_recorded"] == 1
    assert result["counts"]["l5_human_validated"] == 1
    assert result["records"][0]["cycle_run_id"] == "cycle-before-close"


def test_invalid_campaign_closure_fails_projection_closed(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    campaign = load_campaign(repo_root=root)
    _write_json(
        root / progress_module.CAMPAIGN_CLOSURE_DIR
        / f"{campaign['campaign_id']}.json",
        {
            "schema_version": "research-campaign-closure/v1",
            "campaign_id": campaign["campaign_id"],
            "campaign_manifest_sha256": "0" * 64,
            "closed_at": "2026-09-14T22:40:00Z",
            "closed_by": "projection-test",
        },
    )

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["status"] == "unavailable"
    assert result["campaign"]["runtime"]["status"] == "invalid"
    assert result["counts"] is None
    assert any(
        item["code"] == "campaign_closure_invalid"
        for item in result["qualifications"]
    )


def test_missing_promotion_sources_do_not_look_like_awaiting_review(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    (root / "memory/promotion_near_misses.jsonl").unlink()
    (root / "memory/surfaced_findings.jsonl").unlink()
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(
            run_id="cycle-skeptic", step_id="cycle-skeptic:step:0",
            iteration_id="iter-skeptic", at="2026-09-14T22:30:00Z",
        ),
    ])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration("iter-skeptic", at="2026-09-14T22:30:10Z"),
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["status"] == "partial"
    assert result["bottleneck"]["stage"] == "source_coverage"
    assert result["counts"]["skeptic_reviews_recorded"] is None
    assert result["counts"]["promotion_validations"] is None
    assert all(
        value is None for value in result["counts"]["evidence_levels"].values()
    )
    assert result["records"][0]["evidence_level"] is None
    assert result["records"][0]["evidence_provisional"] is None
    assert result["stages"][5]["status"] == "unavailable"
    assert result["stages"][6]["status"] == "unavailable"


def test_missing_feedback_does_not_look_like_an_awaiting_human_verdict(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    (root / "memory/loop_feedback.jsonl").unlink()
    iteration_id = "iter-feedback"
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(
            run_id="cycle-feedback", step_id="cycle-feedback:step:0",
            iteration_id=iteration_id, at="2026-09-14T22:30:00Z",
        ),
    ])
    _write_jsonl(root, "memory/loop_memory.jsonl", [
        _l3_iteration(iteration_id, at="2026-09-14T22:30:10Z"),
    ])
    _write_jsonl(root, "memory/surfaced_findings.jsonl", [{
        "campaign": DEFAULT_CAMPAIGN_LINK,
        "source_iteration_id": iteration_id,
        "finding_id": f"sf-{iteration_id}",
        "promoted_at": "2026-09-14T22:45:00Z",
        "adversarial": {"survived": True},
    }])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["status"] == "partial"
    assert result["bottleneck"]["stage"] == "source_coverage"
    assert result["counts"]["l4_validated"] == 1
    assert result["counts"]["human_verdicts_recorded"] is None
    assert result["counts"]["l5_human_validated"] is None
    assert all(
        value is None for value in result["counts"]["evidence_levels"].values()
    )
    assert result["records"][0]["evidence_level"] is None
    assert result["records"][0]["evidence_provisional"] is None
    assert result["stages"][7]["status"] == "unavailable"


def test_attempt_table_discloses_its_display_cap(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(
            run_id=f"cycle-{index:03d}", step_id=f"cycle-{index:03d}:step:0",
            iteration_id=f"iter-{index:03d}", at="2026-09-14T22:30:00Z",
        )
        for index in range(201)
    ])

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["counts"]["topic_attempts"] == 201
    assert result["records_window"] == {
        "displayed": 200, "total": 201, "truncated": True,
    }
    assert len(result["records"]) == 200
    assert result["records"][0]["cycle_run_id"] == "cycle-001"
    assert any(
        item["code"] == "records_display_truncated"
        for item in result["qualifications"]
    )


def test_planned_cycle_and_outcome_without_bound_request_are_not_completions(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    planned = _cycle(
        run_id="cycle-plan", step_id="cycle-plan:step:0",
        iteration_id="iter-plan", at="2026-09-14T22:30:00Z",
    )
    planned["status"] = "planned"
    missing_request = _cycle(
        run_id="cycle-no-request", step_id="cycle-no-request:step:0",
        iteration_id="iter-no-request", at="2026-09-14T22:31:00Z",
    )
    missing_request["outcomes"][0].pop("request")
    _write_jsonl(
        root, "run_state/coordinator_cycles.jsonl", [planned, missing_request]
    )

    result = project_research_pipeline(canonical_root=root, now=NOW)

    assert result["counts"]["topic_attempts"] == 1
    assert result["counts"]["dispatch_completions"] == 0
    assert result["counts"]["ambiguous_dispatches"] == 1


def test_missing_cutoff_or_loop_source_is_not_coerced_to_progress(tmp_path: Path) -> None:
    missing_cutoff = project_research_pipeline(canonical_root=tmp_path, now=NOW)
    assert missing_cutoff["status"] == "unavailable"
    assert missing_cutoff["counts"] is None

    root = _root(tmp_path)
    (root / "memory/loop_memory.jsonl").unlink()
    _write_jsonl(root, "run_state/coordinator_cycles.jsonl", [
        _cycle(run_id="cycle-1", step_id="cycle-1:step:0", iteration_id="iter-unknown", at="2026-09-14T22:30:00Z")
    ])
    result = project_research_pipeline(canonical_root=root, now=NOW)
    assert result["status"] == "partial"
    assert result["bottleneck"]["stage"] == "source_coverage"
    assert result["counts"]["iterations_recorded"] is None
    for key in (
        "iterations_recorded", "scope_assessed", "evidence_assessed",
        "skeptic_reviews_recorded", "promotion_rejections",
        "promotion_validations", "l4_validated", "human_verdicts_recorded",
        "l5_human_validated",
    ):
        assert result["counts"][key] is None
    assert all(stage["status"] == "unavailable" for stage in result["stages"][2:])
    assert any(item["code"] == "loop_memory_unavailable" for item in result["qualifications"])
