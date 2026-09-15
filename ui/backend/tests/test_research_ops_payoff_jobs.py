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
    assert "window_path" not in json.dumps(view)
    assert len(calls) == 2
    again = _observe(repo, payoff_root=root, now=now, queue_module=module)
    assert again == view
    assert len(calls) == 2


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
