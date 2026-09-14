"""Trust, denominator, and longitudinal tests for Benchmark Progress."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.weekly_upgrade_progress import compose_progress, register

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _sha(value) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, value, *, pretty: bool = False) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
        if pretty else _canonical(value) + b"\n"
    )
    path.write_bytes(raw)
    return raw


def _roots(tmp_path: Path):
    canonical = tmp_path / "canonical"
    upgrade = tmp_path / "upgrade-runs"
    reviews = tmp_path / "review-runs"
    (canonical / "run_state" / "weekly_upgrade" / "trials").mkdir(parents=True)
    (canonical / "run_state" / "weekly_upgrade" / "evaluations").mkdir()
    upgrade.mkdir()
    reviews.mkdir()
    return canonical, upgrade, reviews


def _arm_observation(
    arm: str, *, transport_expected: int, transport_returned: int,
    objective_successes: int | None, objective_total: int | None,
    repair_successes: int | None = None, repair_total: int | None = None,
):
    return {
        "arm": arm,
        "fixed_attempts_expected": transport_expected,
        "fixed_attempts_returned": transport_returned,
        "fixed_attempts_protocol_valid": None,
        "objective_cases_passed": objective_successes,
        "objective_cases_total": objective_total,
        "repair_cases_passed": repair_successes,
        "repair_cases_total": repair_total,
        "annotation_disagreements": None,
    }


def _make_trial(
    canonical: Path,
    upgrade: Path,
    *,
    week: str,
    suffix: str,
    date: str,
    baseline_successes: int = 1,
    candidate_successes: int = 2,
    objective_total: int = 2,
    baseline_transport: int = 2,
    candidate_transport: int = 2,
    candidate_returned: int | None = None,
    complete: bool = True,
    grader: str = SHA_A,
    candidate_label: str = "Candidate policy",
    execution_sha: str = SHA_A,
    secret: str | None = None,
) -> dict:
    trial_id = f"{week}-{suffix}"
    output = upgrade / week / suffix
    evaluation_dir = output / "evaluation"
    evaluation_dir.mkdir(parents=True)
    candidate_returned = (
        candidate_transport if candidate_returned is None else candidate_returned
    )
    manifest = {
        "schema_version": "weekly-upgrade-eval-manifest/v1",
        "arms": [
            {
                "id": "A", "label": "Current baseline policy",
                "backend": "vllm-qwen", "model": "model-1",
                "profile": "current", "max_tokens": 100,
                "request_timeout_s": 10, "seed": 7,
            },
            {
                "id": "B", "label": candidate_label,
                "backend": "vllm-qwen", "model": "model-1",
                "profile": "candidate", "max_tokens": 100,
                "request_timeout_s": 10, "seed": 7,
            },
        ],
    }
    manifest_raw = _write_json(evaluation_dir / "manifest.snapshot.json", manifest)
    manifest_sha = _sha(manifest_raw)
    fixtures = ["case-1", "case-2"]
    manifest_path = f"experiments/weekly_test_suite_{date}.json"
    plan = {
        "schema_version": "weekly-upgrade-trial-plan/v1",
        "trial_id": trial_id,
        "week_id": week,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha,
        "manifest_configuration_sha256": SHA_B,
        "kind": "objective",
        "arm_ids": ["A", "B"],
        "fixture_ids": fixtures,
        "expected_input_sha256": {item: SHA_C for item in fixtures},
        "expected_grader_sha256": {item: grader for item in fixtures},
        "expected_attempt_ids": [],
        "execution_dependencies": {},
        "declared_attempts": baseline_transport + candidate_transport,
        "payload_budget_s": 100,
        "reservation_s": 130,
        "seeds": [7],
        "include_primary_r0": False,
        "production_change_authorized": False,
        "review_sha256": None,
    }
    outcomes = []
    for arm, returned, successes in (
        ("A", baseline_transport, baseline_successes),
        ("B", candidate_returned, candidate_successes),
    ):
        for index in range(returned):
            passed = index < successes
            outcomes.append({
                "arm_id": arm,
                "task_id": f"case-{index + 1}",
                "duration_s": 2.0,
                "status": "passed" if passed else "failed",
                "failure_code": None,
                "completion": secret if index == 0 else None,
            })
        if returned < (baseline_transport if arm == "A" else candidate_transport):
            outcomes.append({
                "arm_id": arm, "task_id": "case-timeout", "duration_s": 10.0,
                "status": "timeout", "failure_code": "timeout",
                "completion": secret,
            })
    run = {
        "schema_version": "weekly-upgrade-eval-run/v1",
        "status": "complete" if complete else "incomplete_transport",
        "execution_source_sha256": {"runner.py": execution_sha},
        "summary": {
            "arms": {
                "A": {"charged_wall_s_including_failures": 4.0},
                "B": {"charged_wall_s_including_failures": 4.0 if complete else 12.0},
            },
            "pairs": [],
            "paired_failure_inclusive": {
                "ci95": [-0.5, 1.0], "n_task_templates": 2,
            },
        },
        "outcomes": outcomes,
    }
    run_raw = _write_json(evaluation_dir / "run.json", run)
    run_sha = _sha(run_raw)
    terminal_status = "completed" if complete else "failed"
    binding = _sha({"plan": plan, "output": str(output)})
    budget_receipt = {
        "run_id": trial_id, "manifest_sha256": binding, "week_id": week,
        "reserved_s": 130.0, "elapsed_s": 20.0, "charged_s": 20.0,
        "state": "finished", "status": terminal_status,
        "reserved_at": None, "finished_at": None,
    }
    result = {
        "schema_version": "weekly-upgrade-trial-result/v1",
        "trial_id": trial_id,
        "status": terminal_status,
        "plan_sha256": _sha(plan),
        "elapsed_s": 20.0,
        "process": {"returncode": 0 if complete else 1},
        "error": None,
        "evaluation": {
            "path": str(evaluation_dir / "run.json"),
            "sha256": run_sha,
            "artifact_sha256": {
                "run.json": run_sha, "manifest.snapshot.json": manifest_sha,
            },
            "status": "complete" if complete else "incomplete_transport",
            "execution_complete": complete,
            "semantic_benefit_measured": False,
        },
        "evaluation_dir": str(evaluation_dir),
        "semantic_benefit_measured": False,
        "production_change_authorized": False,
        "budget_receipt": budget_receipt,
    }
    result_raw = _write_json(output / "trial_result.json", result, pretty=True)
    journal = {
        "phase": "finished", "plan": plan, "output": str(output),
        "binding_sha256": binding, "result": result,
    }
    journal_raw = _write_json(
        canonical / "run_state" / "weekly_upgrade" / "trials" / f"{trial_id}.json",
        journal, pretty=True,
    )
    arms = [
        _arm_observation(
            "A", transport_expected=baseline_transport,
            transport_returned=baseline_transport,
            objective_successes=baseline_successes, objective_total=objective_total,
        ),
        _arm_observation(
            "B", transport_expected=candidate_transport,
            transport_returned=candidate_returned,
            objective_successes=candidate_successes, objective_total=objective_total,
        ),
    ]
    summary = {
        "schema_version": "weekly-upgrade-evaluation-summary/v1",
        "trial_id": trial_id,
        "recorded_at": f"{date}T02:00:00+00:00",
        "provenance": "operator_recorded",
        "trial_journal_sha256": _sha(journal_raw),
        "trial_result_sha256": _sha(result_raw),
        "transport_evaluation_sha256": run_sha,
        "summary_artifact_sha256": SHA_C,
        "annotation_artifacts": [],
        "observations": {
            "fixed_attempts_expected": baseline_transport + candidate_transport,
            "fixed_attempts_returned": baseline_transport + candidate_returned,
            "fixed_attempts_protocol_valid": None,
            "objective_cases_passed": baseline_successes + candidate_successes,
            "objective_cases_total": objective_total * 2,
            "repair_cases_passed": None,
            "repair_cases_total": None,
            "annotation_disagreements": None,
            "failure_categories": ([{"code": "timeout", "count": 1}] if not complete else []),
        },
        "arm_observations": arms,
    }
    _write_json(
        canonical / "run_state" / "weekly_upgrade" / "evaluations" / f"{trial_id}.json",
        summary,
    )
    return {
        "trial_id": trial_id, "binding": binding, "week": week,
        "status": terminal_status, "reserved": 130.0, "elapsed": 20.0,
        "charged": 20.0, "output": output,
    }


def _write_budget(canonical: Path, trials: list[dict], *, prior_week: str | None = None):
    rows = []
    previous = None

    def add(row):
        nonlocal previous
        row = {
            "schema_version": "weekly-upgrade-budget-v1",
            "sequence": len(rows) + 1,
            **row,
            "previous_event_sha256": previous,
        }
        row["event_sha256"] = _sha(row)
        previous = row["event_sha256"]
        rows.append(row)

    week_dates = {
        "2026-W38": "2026-09-14",
        "2026-W39": "2026-09-21",
        "2026-W40": "2026-09-28",
    }
    if prior_week:
        add({
            "event": "debit", "event_at": f"{week_dates[prior_week]}T00:10:00Z",
            "week_id": prior_week, "run_id": f"{prior_week}-prior",
            "manifest_sha256": SHA_A, "elapsed_s": 180.0,
            "charged_s": 180.0, "status": "imported",
        })
    for trial in trials:
        day = week_dates[trial["week"]]
        add({
            "event": "reserve", "event_at": f"{day}T01:00:00Z",
            "week_id": trial["week"], "run_id": trial["trial_id"],
            "manifest_sha256": trial["binding"], "reserved_s": trial["reserved"],
        })
        add({
            "event": "finish", "event_at": f"{day}T01:01:00Z",
            "week_id": trial["week"], "run_id": trial["trial_id"],
            "manifest_sha256": trial["binding"], "reserved_s": trial["reserved"],
            "elapsed_s": trial["elapsed"], "charged_s": trial["charged"],
            "status": trial["status"],
        })
    path = canonical / "run_state" / "weekly_upgrade_budget.jsonl"
    path.write_bytes(b"".join(_canonical(row) + b"\n" for row in rows))


def _write_review(reviews: Path, week: str, *, with_counts: bool = True):
    proposal = {"proposal_id": "p1", "week_id": week}
    proposal_sha = _sha(proposal)
    run_id = f"{week}-review"
    report = {
        "schema_version": "weekly-upgrade-report-v1",
        "week_id": week,
        "run_id": run_id,
        "status": "REVISION_REQUIRED",
        "proposal": proposal,
        "proposal_sha256": proposal_sha,
        "snapshot_sha256": SHA_A,
        "frontier_calls_used": 2 if with_counts else None,
        "experiment_card": None,
    }
    cycle_review = {
        "status": report["status"], "run_id": run_id,
        "proposal_sha256": proposal_sha, "snapshot_sha256": SHA_A,
        "frontier_calls_used": report["frontier_calls_used"],
        "experiment_card_sha256": None,
    }
    cycle = {
        "schema_version": "weekly-upgrade-cycle/v1", "week_id": week,
        "status": "REVIEW_COMPLETE", "review": cycle_review,
        "source": {"summary": {"fetched": 8 if with_counts else None}},
    }
    _write_json(reviews / week / "review" / "weekly_report.json", report)
    _write_json(reviews / week / "cycle_report.json", cycle)


def _write_activation(canonical: Path):
    state = canonical / "run_state" / "weekly_upgrade"
    _write_json(state / "completion.json", {
        "schema_version": "weekly-upgrade-implementation-completion/v1",
    })
    _write_json(state / "activation-2026-09-14" / "activation.json", {
        "schema_version": "weekly-upgrade-activation/v1",
        "status": "ACTIVE_REVIEW_ONLY",
        "review_only": True,
        "activated_at": "2026-09-14T16:17:51+00:00",
        "cron_line": "30 5 * * 0 NARA_WEEKLY_UPGRADE=1 command",
        "automatic_promotion_enabled": False,
        "trial_manifest": None,
    })


def _client(canonical: Path, upgrade: Path, reviews: Path, now: datetime):
    app = FastAPI()
    register(
        app, canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews, now=now,
    )
    return TestClient(app)


def test_real_contract_separates_denominators_budget_and_untrusted_evidence(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    trial = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="abc123", date="2026-09-14",
        baseline_successes=1, candidate_successes=2,
        baseline_transport=2, candidate_transport=4,
        secret="PRIVATE RAW MODEL TEXT",
    )
    _write_budget(canonical, [trial], prior_week="2026-W38")
    _write_review(reviews, "2026-W38")
    _write_activation(canonical)

    response = _client(
        canonical, upgrade, reviews,
        datetime(2026, 9, 14, 12, tzinfo=timezone.utc),
    ).get("/api/weekly_upgrade/progress")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "weekly-upgrade-progress/v1"
    assert body["summary"]["terminal_trials"] == 1
    assert body["summary"]["recorded_evaluations"] == 1
    assert body["summary"]["complete_executions"] == 1
    assert body["summary"]["upgrade_established"] is False
    budget = body["summary"]["current_week_budget"]
    assert budget["charged_minutes"] == 200 / 60
    assert budget["trial_charge_minutes"] == 20 / 60
    assert budget["prior_import_minutes"] == 3
    assert budget["overrun_minutes"] == 0
    family = body["weeks"][0]["families"][0]
    [baseline, candidate] = family["arms"]
    assert baseline["transport_expected"] == 2
    assert candidate["transport_expected"] == 4
    assert candidate["objective_successes"] == 2
    assert candidate["objective_total"] == 2
    assert candidate["metrics"]["success_rate"] == 1.0
    assert family["evidence"] == {
        "class": "UNVERIFIED_OPERATOR_SUMMARY",
        "candidate_benefit_verified": False,
    }
    assert family["comparison"]["eligible"] is False
    assert family["comparison"]["history_points"] == 1
    assert body["automation"]["mode"] == "review_only"
    assert body["weeks"][0]["review"]["experiment_proposals"] == 1
    assert "PRIVATE RAW MODEL TEXT" not in json.dumps(body)
    assert str(tmp_path) not in json.dumps(body)


def test_two_identical_cohorts_form_trend_but_changed_grader_breaks_series(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    first = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="same001", date="2026-09-14",
        baseline_successes=1, candidate_successes=2,
    )
    second = _make_trial(
        canonical, upgrade, week="2026-W39", suffix="same002", date="2026-09-21",
        baseline_successes=1, candidate_successes=1,
        candidate_label="New candidate configuration",
    )
    changed = _make_trial(
        canonical, upgrade, week="2026-W40", suffix="changed3", date="2026-09-28",
        baseline_successes=2, candidate_successes=2, grader=SHA_B,
    )
    _write_budget(canonical, [first, second, changed])
    body = compose_progress(
        canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews,
        now=datetime(2026, 9, 28, 12, tzinfo=timezone.utc),
    )
    by_week = {week["week"]: week for week in body["weeks"]}
    first_family = by_week["2026-W38"]["families"][0]
    second_family = by_week["2026-W39"]["families"][0]
    changed_family = by_week["2026-W40"]["families"][0]
    assert first_family["comparison"]["eligible"] is True
    assert second_family["comparison"]["eligible"] is True
    assert first_family["comparison"]["history_points"] == 2
    points = first_family["comparison"]["points"]
    assert [point["week"] for point in points] == ["2026-W38", "2026-W39"]
    assert [point["delta_success_rate"] for point in points] == [0.5, 0.0]
    assert changed_family["comparison"]["eligible"] is False
    assert changed_family["comparison"]["history_points"] == 1
    assert "cohort contract changed" in changed_family["comparison"]["explanation"]
    assert body["summary"]["comparable_transitions"] == 1


@pytest.mark.parametrize("semantic_change", ["larger_objective", "repair"])
def test_changed_success_denominator_breaks_longitudinal_series(
    tmp_path, semantic_change,
):
    canonical, upgrade, reviews = _roots(tmp_path)
    first = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="denom001", date="2026-09-14",
    )
    second = _make_trial(
        canonical, upgrade, week="2026-W39", suffix="denom002", date="2026-09-21",
    )
    summary_path = (
        canonical / "run_state" / "weekly_upgrade" / "evaluations"
        / f"{second['trial_id']}.json"
    )
    summary = json.loads(summary_path.read_text())
    observations = [summary["observations"], *summary["arm_observations"]]
    if semantic_change == "larger_objective":
        for observation in observations:
            observation["objective_cases_total"] = (
                400 if "failure_categories" in observation else 200
            )
    else:
        for observation in observations:
            observation["repair_cases_passed"] = observation["objective_cases_passed"]
            observation["repair_cases_total"] = observation["objective_cases_total"]
            observation["objective_cases_passed"] = None
            observation["objective_cases_total"] = None
    _write_json(summary_path, summary)
    _write_budget(canonical, [first, second])

    body = compose_progress(
        canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews,
        now=datetime(2026, 9, 21, 12, tzinfo=timezone.utc),
    )
    families = {
        week["week"]: week["families"][0] for week in body["weeks"]
    }
    assert body["summary"]["comparable_transitions"] == 0
    assert families["2026-W38"]["comparison"]["eligible"] is False
    assert families["2026-W39"]["comparison"]["eligible"] is False
    assert families["2026-W38"]["comparison"]["fingerprint"] != (
        families["2026-W39"]["comparison"]["fingerprint"]
    )


def test_missing_or_plan_mismatched_operator_counts_cannot_form_trend(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    first = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="valid001", date="2026-09-14",
    )
    invalid = _make_trial(
        canonical, upgrade, week="2026-W39", suffix="invalid2", date="2026-09-21",
    )
    missing = _make_trial(
        canonical, upgrade, week="2026-W40", suffix="missing3", date="2026-09-28",
    )
    invalid_path = (
        canonical / "run_state" / "weekly_upgrade" / "evaluations"
        / f"{invalid['trial_id']}.json"
    )
    invalid_summary = json.loads(invalid_path.read_text())
    invalid_summary["observations"]["fixed_attempts_expected"] = 5
    invalid_summary["arm_observations"][1]["fixed_attempts_expected"] = 3
    _write_json(invalid_path, invalid_summary)
    (
        canonical / "run_state" / "weekly_upgrade" / "evaluations"
        / f"{missing['trial_id']}.json"
    ).unlink()
    _write_budget(canonical, [first, invalid, missing])

    response = _client(
        canonical, upgrade, reviews,
        datetime(2026, 9, 28, 12, tzinfo=timezone.utc),
    ).get("/api/weekly_upgrade/progress")
    assert response.status_code == 200
    body = response.json()
    families = {
        week["week"]: week["families"][0] for week in body["weeks"]
    }
    assert body["summary"]["comparable_transitions"] == 0
    assert families["2026-W39"]["evaluation_status"] == "invalid"
    assert families["2026-W39"]["comparison"]["fingerprint"] is None
    assert families["2026-W40"]["evaluation_status"] == "missing"
    assert families["2026-W40"]["comparison"]["fingerprint"] is None
    assert not any(
        family["comparison"]["eligible"] for family in families.values()
    )


def test_incomplete_run_keeps_timeouts_in_transport_and_objective_denominators(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    trial = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="timeout1", date="2026-09-14",
        candidate_successes=1, candidate_transport=2, candidate_returned=1,
        complete=False,
    )
    _write_budget(canonical, [trial])
    body = compose_progress(
        canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews,
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    week = body["weeks"][0]
    family = week["families"][0]
    candidate = family["arms"][1]
    assert week["status"] == "partial"
    assert week["complete_executions"] == 0
    assert family["execution_status"] == "incomplete"
    assert family["completeness"] == {
        "expected": 4, "returned": 3, "protocol_valid": None, "timeouts": 1,
    }
    assert candidate["transport_expected"] == 2
    assert candidate["transport_returned"] == 1
    assert candidate["objective_successes"] == 1
    assert candidate["objective_total"] == 2
    assert candidate["metrics"]["success_rate"] == 0.5


def test_redirected_trial_and_tampered_artifact_are_withheld_without_leak(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    safe = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="safe001", date="2026-09-14",
        secret="NEVER EXPOSE THIS",
    )
    _write_budget(canonical, [safe])
    # The run stays countable from the canonical receipts, but a changed
    # snapshot must remove config/comparability data and produce a warning.
    snapshot = safe["output"] / "evaluation" / "manifest.snapshot.json"
    snapshot.write_text('{"stolen":"NEVER EXPOSE THIS"}\n', encoding="utf-8")
    body = compose_progress(
        canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews,
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    assert body["summary"]["terminal_trials"] == 1
    assert any(item["code"] == "trial_artifact_invalid" for item in body["warnings"])
    assert body["weeks"][0]["families"][0]["comparison"]["fingerprint"] is None
    assert "NEVER EXPOSE THIS" not in json.dumps(body)

    # Re-pointing the canonical journal outside the bounded run root with a
    # matching binding still cannot make the endpoint read that directory.
    trial_path = (
        canonical / "run_state" / "weekly_upgrade" / "trials"
        / f"{safe['trial_id']}.json"
    )
    journal = json.loads(trial_path.read_text())
    outside = tmp_path / "outside"
    outside.mkdir()
    journal["output"] = str(outside)
    journal["binding_sha256"] = _sha({"plan": journal["plan"], "output": str(outside)})
    _write_json(trial_path, journal, pretty=True)
    body = compose_progress(
        canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews,
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    assert body["summary"]["terminal_trials"] == 0
    assert any(item["code"] == "trial_invalid" for item in body["warnings"])


def test_budget_mismatch_and_orphan_are_explicit_and_not_counted(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    trial = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="mismatch", date="2026-09-14",
    )
    _write_budget(canonical, [trial])
    budget_path = canonical / "run_state" / "weekly_upgrade_budget.jsonl"
    rows = [json.loads(line) for line in budget_path.read_text().splitlines()]
    # Rewrite a valid hash chain whose terminal charge conflicts with the
    # trial's copied receipt.
    rows[1]["elapsed_s"] = 21.0
    rows[1]["charged_s"] = 21.0
    rows[1].pop("event_sha256")
    rows[1]["event_sha256"] = _sha(rows[1])
    budget_path.write_bytes(b"".join(_canonical(row) + b"\n" for row in rows))
    body = compose_progress(
        canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews,
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    assert body["summary"]["terminal_trials"] == 0
    codes = {item["code"] for item in body["warnings"]}
    assert {"trial_budget_mismatch", "budget_orphan"} <= codes


def test_missing_and_partial_sources_degrade_without_fabricated_zeroes(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    _write_review(reviews, "2026-W38", with_counts=False)
    budget_path = canonical / "run_state" / "weekly_upgrade_budget.jsonl"
    budget_path.write_bytes(b'{"partial":true}')
    body = _client(
        canonical, upgrade, reviews,
        datetime(2026, 9, 14, tzinfo=timezone.utc),
    ).get("/api/weekly_upgrade/progress").json()
    assert body["availability"]["budget"] is False
    assert body["summary"]["current_week_budget"] is None
    assert body["summary"]["upgrade_established"] is None
    assert body["weeks"][0]["review"]["source_count"] is None
    assert body["weeks"][0]["review"]["frontier_calls"] is None
    assert any(item["code"] == "budget_invalid" for item in body["warnings"])


def test_cross_unbound_review_is_withheld(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    _write_review(reviews, "2026-W38")
    report_path = reviews / "2026-W38" / "review" / "weekly_report.json"
    report = json.loads(report_path.read_text())
    report["run_id"] = "different-run"
    _write_json(report_path, report)
    body = compose_progress(
        canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews,
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    assert body["weeks"] == []
    assert any(item["code"] == "review_invalid" for item in body["warnings"])


@pytest.mark.parametrize("bad_arms", [
    ["A", {"bad": 1}], ["A", "A"], [], "A,B",
])
def test_malformed_nested_plan_never_500s(tmp_path, bad_arms):
    canonical, upgrade, reviews = _roots(tmp_path)
    trial = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="badplan", date="2026-09-14",
    )
    trial_path = (
        canonical / "run_state" / "weekly_upgrade" / "trials"
        / f"{trial['trial_id']}.json"
    )
    journal = json.loads(trial_path.read_text())
    journal["plan"]["arm_ids"] = bad_arms
    journal["result"]["plan_sha256"] = _sha(journal["plan"])
    journal["binding_sha256"] = _sha({
        "plan": journal["plan"], "output": journal["output"],
    })
    journal["result"]["budget_receipt"]["manifest_sha256"] = journal["binding_sha256"]
    _write_json(Path(journal["output"]) / "trial_result.json", journal["result"], pretty=True)
    _write_json(trial_path, journal, pretty=True)
    client = _client(
        canonical, upgrade, reviews,
        datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    response = client.get("/api/weekly_upgrade/progress")
    assert response.status_code == 200
    assert response.json()["summary"]["terminal_trials"] == 0
    assert any(item["code"] == "trial_invalid" for item in response.json()["warnings"])


def test_impossible_operator_counts_are_invalid_not_over_100_percent(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    trial = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="badcount", date="2026-09-14",
    )
    _write_budget(canonical, [trial])
    summary_path = (
        canonical / "run_state" / "weekly_upgrade" / "evaluations"
        / f"{trial['trial_id']}.json"
    )
    summary = json.loads(summary_path.read_text())
    summary["arm_observations"][1]["objective_cases_passed"] = 3
    _write_json(summary_path, summary)
    response = _client(
        canonical, upgrade, reviews,
        datetime(2026, 9, 14, tzinfo=timezone.utc),
    ).get("/api/weekly_upgrade/progress")
    assert response.status_code == 200
    body = response.json()
    family = body["weeks"][0]["families"][0]
    assert family["evaluation_status"] == "invalid"
    assert all(arm["metrics"]["success_rate"] is None for arm in family["arms"])
    assert any(item["code"] == "evaluation_invalid" for item in body["warnings"])


def test_missing_repeat_summary_withholds_aggregate_score_and_ctt(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    first = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="repeat01", date="2026-09-14",
    )
    second = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="repeat02", date="2026-09-14",
    )
    _write_budget(canonical, [first, second])
    missing = (
        canonical / "run_state" / "weekly_upgrade" / "evaluations"
        / f"{second['trial_id']}.json"
    )
    missing.unlink()
    body = compose_progress(
        canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews,
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )
    family = body["weeks"][0]["families"][0]
    assert family["evaluation_status"] == "partial"
    for arm in family["arms"]:
        assert arm["transport_expected"] is None
        assert arm["objective_successes"] is None
        assert arm["metrics"]["success_rate"] is None
        assert arm["metrics"]["ctt_per_hour"] is None


def test_changed_harness_and_inconsistent_repeat_config_disable_comparison(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    first = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="harness1", date="2026-09-14",
        execution_sha=SHA_A,
    )
    changed_harness = _make_trial(
        canonical, upgrade, week="2026-W39", suffix="harness2", date="2026-09-21",
        execution_sha=SHA_B,
    )
    repeat_one = _make_trial(
        canonical, upgrade, week="2026-W40", suffix="repeat-a", date="2026-09-28",
        candidate_label="Candidate one",
    )
    repeat_two = _make_trial(
        canonical, upgrade, week="2026-W40", suffix="repeat-b", date="2026-09-28",
        candidate_label="Candidate two",
    )
    _write_budget(canonical, [first, changed_harness, repeat_one, repeat_two])
    body = compose_progress(
        canonical_root=canonical, upgrade_runs_root=upgrade,
        review_runs_root=reviews,
        now=datetime(2026, 9, 28, tzinfo=timezone.utc),
    )
    assert body["summary"]["comparable_transitions"] == 0
    families = {
        week["week"]: week["families"][0] for week in body["weeks"]
    }
    assert families["2026-W38"]["comparison"]["eligible"] is False
    assert families["2026-W39"]["comparison"]["eligible"] is False
    assert families["2026-W40"]["comparison"]["fingerprint"] is None
    assert any(
        "configurations differ across repeats" in reason
        for reason in families["2026-W40"]["comparison"]["break_reasons"]
    )


def test_hash_rebound_malformed_run_summary_degrades_instead_of_500(tmp_path):
    canonical, upgrade, reviews = _roots(tmp_path)
    trial = _make_trial(
        canonical, upgrade, week="2026-W38", suffix="badrun", date="2026-09-14",
    )
    _write_budget(canonical, [trial])
    run_path = trial["output"] / "evaluation" / "run.json"
    run = json.loads(run_path.read_text())
    run["summary"] = [1]
    run_raw = _write_json(run_path, run)
    run_sha = _sha(run_raw)

    trial_path = (
        canonical / "run_state" / "weekly_upgrade" / "trials"
        / f"{trial['trial_id']}.json"
    )
    journal = json.loads(trial_path.read_text())
    journal["result"]["evaluation"]["sha256"] = run_sha
    journal["result"]["evaluation"]["artifact_sha256"]["run.json"] = run_sha
    result_raw = _write_json(
        trial["output"] / "trial_result.json", journal["result"], pretty=True,
    )
    journal_raw = _write_json(trial_path, journal, pretty=True)

    summary_path = (
        canonical / "run_state" / "weekly_upgrade" / "evaluations"
        / f"{trial['trial_id']}.json"
    )
    summary = json.loads(summary_path.read_text())
    summary["transport_evaluation_sha256"] = run_sha
    summary["trial_result_sha256"] = _sha(result_raw)
    summary["trial_journal_sha256"] = _sha(journal_raw)
    _write_json(summary_path, summary)

    response = _client(
        canonical, upgrade, reviews,
        datetime(2026, 9, 14, tzinfo=timezone.utc),
    ).get("/api/weekly_upgrade/progress")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["terminal_trials"] == 1
    family = body["weeks"][0]["families"][0]
    assert family["comparison"]["fingerprint"] is None
    assert all(arm["metrics"]["recorded_wall_seconds"] is None for arm in family["arms"])
    assert any(item["code"] == "trial_artifact_invalid" for item in body["warnings"])
