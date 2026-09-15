"""CPU-only off-tree operational observer and completed-proof regressions."""
from __future__ import annotations

import hashlib
import importlib
import json
from datetime import datetime, timezone

import pytest


def draft(name):
    return importlib.import_module(f"bench.flash_next_ab.{name}")


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class Done:
    def __init__(self, clock, ticks=3):
        self.clock = clock
        self.ticks = ticks
        self.calls = 0
        self.stopped = False

    def is_set(self):
        return self.stopped or self.calls >= self.ticks

    def wait(self, timeout):
        self.calls += 1
        self.clock.now += timeout
        return self.is_set()

    def set(self):
        self.stopped = True


class Monitor:
    def __init__(self):
        self.breaches = []

    def report_external_breach(self, reason):
        self.breaches.append(reason)


def source(tmp_path, *, failed_ticks=()):
    ew = draft("evaluation_window")
    observer = draft("extended_observer")
    admission = draft("observer_admission")
    clock, monitor = Clock(), Monitor()
    hits = 0

    def request(url, timeout):
        nonlocal hits
        assert url in observer.URLS and timeout == 2
        clock.now += 0.01
        hits += 1
        return 503 if (hits - 1) // len(observer.URLS) in failed_ticks else 200

    selected = observer.UIObserver(
        tmp_path, monitor=monitor, pair_id="pair_1",
        extended_plan_sha256="a" * 64, profile=ew.EXTENDED_SERVING_PROFILE,
        clock=clock, request=request,
    )
    selected.done = Done(clock)
    selected.start()
    selected.thread.join(timeout=1)
    assert not selected.thread.is_alive()
    summary = selected.stop()
    raw_summary = json.dumps(summary, sort_keys=True).encode()
    (tmp_path / "ui-observer-summary.json").write_bytes(raw_summary)
    result = {
        "ui_observer_log_sha256": summary["observer_log_sha256"],
        "ui_observer_summary_sha256": hashlib.sha256(raw_summary).hexdigest(),
        "extended_plan_sha256": "a" * 64,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "restoration": {"verified_at": datetime.now(timezone.utc).isoformat()},
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    state = {"initial": {"captured_at": datetime.now(timezone.utc).isoformat()}}
    # The plan record is created after the test's logical worker start.
    rows = [json.loads(line) for line in (tmp_path / "ui-observer.jsonl").read_text().splitlines()]
    result["started_at"] = rows[0]["observed_at"]
    state["initial"]["captured_at"] = rows[-1]["observed_at"]
    plan = {"pair_id": "pair_1", "extended_serving_profile": ew.EXTENDED_SERVING_PROFILE,
            "extended_serving_profile_sha256": "b" * 64}
    return admission, summary, result, state, plan, monitor


def test_healthy_observer_bound_by_raw_and_summary(tmp_path):
    admission, _summary, result, state, plan, monitor = source(tmp_path)
    proof = admission.validate_ui_observer(tmp_path, result, state, plan)
    assert proof["tick_count"] == 3 and proof["failed_tick_count"] == 0
    assert monitor.breaches == []


def test_one_transient_failure_is_measurement_not_operational_abort(tmp_path):
    admission, _summary, result, state, plan, monitor = source(tmp_path, failed_ticks=(0,))
    proof = admission.validate_ui_observer(tmp_path, result, state, plan)
    assert proof["failed_tick_count"] == 1 and monitor.breaches == []


def test_two_failed_ticks_abort_and_never_admit(tmp_path):
    admission, summary, result, state, plan, monitor = source(tmp_path, failed_ticks=(0, 1))
    assert summary["failed"] and monitor.breaches == ["two UI health failures within 30 seconds"]
    with pytest.raises(admission.ObserverAdmissionError):
        admission.validate_ui_observer(tmp_path, result, state, plan)


def test_resealed_observer_blind_interval_rejected(tmp_path):
    admission, summary, result, state, plan, _monitor = source(tmp_path)
    path = tmp_path / "ui-observer.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[6]["elapsed_monotonic_seconds"] = 100  # second completed tick
    raw = b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows)
    path.write_bytes(raw)
    summary["observer_log_sha256"] = hashlib.sha256(raw).hexdigest()
    summary["observer_log_bytes"] = len(raw)
    summary_raw = json.dumps(summary, sort_keys=True).encode()
    (tmp_path / "ui-observer-summary.json").write_bytes(summary_raw)
    result["ui_observer_log_sha256"] = summary["observer_log_sha256"]
    result["ui_observer_summary_sha256"] = hashlib.sha256(summary_raw).hexdigest()
    with pytest.raises(admission.ObserverAdmissionError):
        admission.validate_ui_observer(tmp_path, result, state, plan)
