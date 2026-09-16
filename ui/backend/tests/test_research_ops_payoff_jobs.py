"""The two registered queue rows are bounded observations, not timer proof."""
from __future__ import annotations

import copy
import hashlib
import json
import types
from datetime import datetime, timezone
from pathlib import Path

from backend import research_ops_status as status


def _queue(tmp_path: Path):
    repo = tmp_path / "repo"
    source = repo / "experiments/payoff_decomposition/queue.py"
    source.parent.mkdir(parents=True)
    source.write_text("# exact test-only registered queue source\n", encoding="utf-8")
    root = tmp_path / "payoff-decomposition"
    root.mkdir()
    calls = []

    def observe(job_id: str, *, now: datetime):
        calls.append((job_id, now))
        registered = status.PAYOFF_JOBS[job_id]
        return {
            "schema": "known-opponent-payoff-job-status/v1",
            "job_id": job_id, "panel_id": registered["panel_id"],
            "not_before": registered["not_before"],
            "expires_at": registered["expires_at"], "role": registered["role"],
            "state": "not_due", "attempt_index": 0, "window_path": None,
            "comparison_eligible": False,
        }

    module = types.SimpleNamespace(__file__=str(source),
                                   JOBS=copy.deepcopy(status.PAYOFF_JOBS),
                                   MAX_AVAILABILITY_REFUSALS=24,
                                   controller=types.SimpleNamespace(OUTPUT_ROOT=root),
                                   status=observe)
    return repo, root, source, module, calls


def _observe(repo: Path, *, payoff_root: Path, now: datetime, queue_module):
    """Inject a test-only source snapshot; the deployed reader pins a frozen SHA."""
    return status._payoff_jobs(repo, payoff_root=payoff_root, now=now,
                               queue_module=queue_module, expected_source_sha256=None)


def _terminal_fixture(root: Path, module, *, job_id: str = "payoff-representation-b",
                      impossible_counts: bool = False):
    output = root / job_id
    output.mkdir()
    (output / "window.json").write_text("{}", encoding="utf-8")
    window_sha = "a" * 64
    registered = status.PAYOFF_JOBS[job_id]

    def write(name: str, value: dict) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        (output / name).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    reservation = {
        "schema": "known-opponent-payoff-job-dispatch/v1", "job_id": job_id,
        "attempt_index": 0, "window_sha256": window_sha,
        "not_before": registered["not_before"], "expires_at": registered["expires_at"],
        "reserved_at": "2026-09-16T03:35:02+00:00", "comparison_eligible": False,
    }
    reservation_sha = write("dispatch-reservation.json", reservation)
    summary = {"strict_shape_valid": 12, "focal_correct": 1,
               "total_correct": 1, "both_correct": 1 if impossible_counts else 0}
    by_view = {
        "seat_table": {"attempted": 6, "returned": 6, "strict_shape_valid": 6,
                       "focal_correct": 0, "total_correct": 1,
                       "both_correct": 1 if impossible_counts else 0},
        "word_list": {"attempted": 6, "returned": 6, "strict_shape_valid": 6,
                      "focal_correct": 1, "total_correct": 0, "both_correct": 0},
    }
    study_validation = {
        "schema": "known-opponent-payoff-decomposition-validation/v1",
        "status": "admitted_diagnostic",
        "study_id": "known-opponent-payoff-representation-v1",
        "panel_id": registered["panel_id"], "scheduled_calls": 12,
        "returned_sse_verified": 12, "admission_eligible": True,
        "attempted_calls": 12, "summary": summary, "by_view": by_view,
        "private_content_exported": False, "comparison_eligible": False,
        "scientific_novelty_claimed": False,
    }
    admission = {
        "schema": "known-opponent-payoff-resident-admission/v1",
        "window_sha256": window_sha, "study_validation": study_validation,
        "comparison_eligible": False, "promotion_authorized": False,
        "trading_claim_authorized": False,
    }
    admission_sha = write("admission.json", admission)
    dispatch = {
        "schema": "known-opponent-payoff-job-dispatch-result/v1", "job_id": job_id,
        "attempt_index": 0, "window_sha256": window_sha,
        "reservation_sha256": reservation_sha, "admission_receipt_sha256": admission_sha,
        "supervisor_returncode": 0, "admission_error_code": None,
        "status": "admitted_diagnostic", "finished_at": "2026-09-16T03:35:08+00:00",
        "comparison_eligible": False,
    }
    dispatch_sha = write("dispatch-result.json", dispatch)
    replay = {
        "schema": "known-opponent-payoff-job-validation/v1", "job_id": job_id,
        "panel_id": registered["panel_id"], "attempt_index": 0,
        "window_sha256": window_sha, "reservation_sha256": reservation_sha,
        "dispatch_result_sha256": dispatch_sha,
        "admission_receipt_sha256": admission_sha, "attempted_calls": 12,
        "summary": summary, "by_view": by_view, "status": "admitted_diagnostic",
        "comparison_eligible": False, "scientific_novelty_claimed": False,
    }
    job_receipt_sha = write("job-admission.json", replay)
    original = module.status

    def observe(job: str, *, now: datetime):
        row = original(job, now=now)
        if job == job_id:
            row.update(state="admitted_attempt_verified", attempt_index=0,
                       window_path=str(output / "window.json"))
        return row

    module.status = observe
    module.validate_dispatch = lambda selected: copy.deepcopy(replay) if selected == job_id else None
    return {"output": output, "replay": replay, "job_receipt_sha": job_receipt_sha,
            "admission_sha": admission_sha, "dispatch_sha": dispatch_sha}


def test_two_literal_queue_observations_are_not_timer_activation(tmp_path):
    repo, root, _, module, calls = _queue(tmp_path)
    status._PAYOFF_CACHE = None
    now = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)
    view = _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert view["schema_version"] == "registered-payoff-jobs-observation/v1"
    assert view["source_status"] == "available"
    assert view["timer_activation"] == "not_verified"
    assert view["comparison_eligible"] is False
    assert [job["job_id"] for job in view["jobs"]] == list(status.PAYOFF_JOBS)
    assert [job["state"] for job in view["jobs"]] == ["not_due", "not_due"]
    assert [job["last_availability_refusal"] for job in view["jobs"]] == [None, None]
    assert [job["terminal_diagnostic"] for job in view["jobs"]] == [None, None]
    assert view["jobs"][0]["eligibility_window"] == {
        "not_before": status.PAYOFF_JOBS["payoff-representation-a"]["not_before"],
        "expires_at": status.PAYOFF_JOBS["payoff-representation-a"]["expires_at"],
    }
    assert "window_path" not in json.dumps(view)
    assert len(calls) == 2
    again = _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert again == view
    assert len(calls) == 2


def test_verified_terminal_diagnostic_projects_only_bounded_instrument_metrics(tmp_path):
    repo, root, _, module, _calls = _queue(tmp_path)
    fixture = _terminal_fixture(root, module)
    status._PAYOFF_CACHE = None
    now = datetime(2026, 9, 16, 4, 0, tzinfo=timezone.utc)
    view = _observe(repo, payoff_root=root, now=now, queue_module=module)
    job = next(row for row in view["jobs"] if row["job_id"] == "payoff-representation-b")
    terminal = job["terminal_diagnostic"]
    assert terminal["schema_version"] == "registered-payoff-terminal-diagnostic/v1"
    assert terminal["finished_at"] == "2026-09-16T03:35:08+00:00"
    assert terminal["attempted_calls"] == 12
    assert terminal["summary"] == {"strict_shape_valid": 12, "focal_correct": 1,
                                   "total_correct": 1, "both_correct": 0}
    assert terminal["by_view"]["seat_table"]["focal_correct"] == 0
    assert terminal["by_view"]["word_list"]["focal_correct"] == 1
    assert terminal["admission_receipt_sha256"] == fixture["admission_sha"]
    assert terminal["job_admission_receipt_sha256"] == fixture["job_receipt_sha"]
    assert terminal["dispatch_result_sha256"] == fixture["dispatch_sha"]
    assert terminal["claim_scope"] == "instrument_only_unlinked"
    assert terminal["campaign_link"] is None
    assert terminal["thesis_credit"] is False
    assert terminal["promotion_authorized"] is False
    assert terminal["comparison_eligible"] is False
    assert terminal["scientific_novelty_claimed"] is False
    assert "study_validation" not in terminal


def test_missing_or_mismatched_terminal_receipt_withholds_metrics(tmp_path):
    repo, root, _, module, _calls = _queue(tmp_path)
    fixture = _terminal_fixture(root, module)
    status._PAYOFF_CACHE = None
    now = datetime(2026, 9, 16, 4, 0, tzinfo=timezone.utc)
    fixture["output"].joinpath("dispatch-result.json").unlink()
    missing = _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert missing["jobs"][1]["terminal_diagnostic"] is None

    # Rebuild the fixture in a fresh root, then break the independently recorded copy.
    repo2, root2, _, module2, _calls2 = _queue(tmp_path / "mismatch")
    fixture2 = _terminal_fixture(root2, module2)
    job_receipt = copy.deepcopy(fixture2["replay"])
    job_receipt["summary"]["focal_correct"] = 2
    fixture2["output"].joinpath("job-admission.json").write_text(
        json.dumps(job_receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    status._PAYOFF_CACHE = None
    mismatched = _observe(repo2, payoff_root=root2, now=now, queue_module=module2)
    assert mismatched["jobs"][1]["terminal_diagnostic"] is None

    repo3, root3, _, module3, _calls3 = _queue(tmp_path / "bad-time")
    fixture3 = _terminal_fixture(root3, module3)
    dispatch = json.loads(fixture3["output"].joinpath("dispatch-result.json").read_text())
    dispatch["finished_at"] = "2026-09-16T09:00:00+00:00"
    dispatch_raw = json.dumps(dispatch, sort_keys=True, separators=(",", ":")).encode()
    fixture3["output"].joinpath("dispatch-result.json").write_bytes(dispatch_raw)
    fixture3["replay"]["dispatch_result_sha256"] = hashlib.sha256(dispatch_raw).hexdigest()
    fixture3["output"].joinpath("job-admission.json").write_text(
        json.dumps(fixture3["replay"], sort_keys=True, separators=(",", ":")),
        encoding="utf-8")
    status._PAYOFF_CACHE = None
    malformed = _observe(repo3, payoff_root=root3, now=now, queue_module=module3)
    assert malformed["jobs"][1]["terminal_diagnostic"] is None

    repo4, root4, _, module4, _calls4 = _queue(tmp_path / "impossible-counts")
    _terminal_fixture(root4, module4, impossible_counts=True)
    status._PAYOFF_CACHE = None
    impossible = _observe(repo4, payoff_root=root4, now=now, queue_module=module4)
    assert impossible["jobs"][1]["terminal_diagnostic"] is None


def test_queue_source_or_public_receipt_change_invalidates_cache(tmp_path):
    repo, root, source, module, calls = _queue(tmp_path)
    status._PAYOFF_CACHE = None
    now = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)
    _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert len(calls) == 2
    first = root / "payoff-representation-a"
    first.mkdir()
    (first / "window.json").write_text("{}", encoding="utf-8")
    _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert len(calls) == 4
    (first / "dispatch-reservation.json").write_text('{"reserved":true}', encoding="utf-8")
    _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert len(calls) == 6
    (first / "job-admission.json").write_text('{"admitted":true}', encoding="utf-8")
    _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert len(calls) == 8
    source.write_text("# revised test-only registered queue source\n", encoding="utf-8")
    _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert len(calls) == 10


def test_source_or_row_drift_stays_unknown_and_never_claims_timer(tmp_path):
    repo, root, source, module, calls = _queue(tmp_path)
    status._PAYOFF_CACHE = None
    now = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)
    unregistered_source = status._payoff_jobs(
        repo, payoff_root=root, now=now, queue_module=module)
    assert unregistered_source["source_status"] == "source_unknown"
    assert calls == []
    module.JOBS["payoff-representation-b"]["not_before"] = "2026-09-16T04:00:00+00:00"
    wrong = _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert wrong["source_status"] == "source_unknown"
    assert wrong["jobs"] is None
    assert wrong["timer_activation"] == "not_verified"
    assert calls == []
    module.JOBS = copy.deepcopy(status.PAYOFF_JOBS)
    original = module.status

    def bad(job_id: str, *, now: datetime):
        row = original(job_id, now=now)
        row["state"] = "admitted_attempt_verified"
        row["comparison_eligible"] = True
        return row

    module.status = bad
    wrong = _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert wrong["source_status"] == "source_unknown"
    assert wrong["jobs"] is None
    source.unlink()
    absent = _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert absent["source_status"] == "package_unavailable"
    assert absent["timer_activation"] == "not_verified"


def test_bound_availability_refusal_is_categorical_and_invalidates_cache(tmp_path):
    repo, root, _, module, calls = _queue(tmp_path)
    status._PAYOFF_CACHE = None
    now = datetime(2026, 9, 15, 19, 20, tzinfo=timezone.utc)
    first = root / "payoff-representation-a"
    first.mkdir()
    (first / "window.json").write_text("{}", encoding="utf-8")
    refusal = first / "availability-refusal-00.json"
    refusal.write_text('{"failure_code":"resource_lease_busy"}', encoding="utf-8")
    refusal_sha = hashlib.sha256(refusal.read_bytes()).hexdigest()
    original = module.status

    def observed(job_id: str, *, now: datetime):
        row = original(job_id, now=now)
        if job_id == "payoff-representation-a":
            row["window_path"] = str(first / "window.json")
            row["last_availability_refusal"] = {
                "failure_code": "resource_lease_busy",
                "refused_at": "2026-09-15T19:10:00+00:00",
                "receipt_sha256": refusal_sha,
            }
        return row

    module.status = observed
    view = _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert view["jobs"][0]["last_availability_refusal"]["failure_code"] == "resource_lease_busy"
    assert view["timer_activation"] == "not_verified"
    assert len(calls) == 2
    refusal.write_text('{"failure_code":"availability_unknown"}', encoding="utf-8")
    wrong = _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert wrong["source_status"] == "source_unknown"
    assert wrong["jobs"] is None
