"""The one archived cap startup abort can restore operating mode, never scores."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend import lab_diversity_cap_progress as cap
from backend import model_runtime_lab as lab
from bench.flash_next_ab import qualification as q


@pytest.fixture
def archived_cap():
    """Optional host archive integration; clean checkouts remain testable."""
    required = (cap.PLAN, cap.WINDOW, cap.OUTPUT / "state.json",
                cap.OUTPUT / "result.json", cap.OUTPUT / "supervision.json",
                cap.OUTPUT / "memory.jsonl", lab.CAP_AUDIT_PATH,
                lab.CAP_AUDIT_SOURCE_PATH,
                cap.CODE_ROOT / "bench/flash_next_ab/lab_window.py")
    if any(not path.is_file() for path in required):
        pytest.skip("archived cap public evidence absent in this checkout")


def _closed(monkeypatch, archived_cap):
    # Exercise archived immutable public refs without Docker calls.
    monkeypatch.setattr(lab, "_live_restored", lambda _state, _cohort: "running")
    monkeypatch.setattr(q, "_inspect_container", lambda _ops, _identity: None)
    return lab.project_lab_runtime(observed=datetime.now(timezone.utc))


def test_exact_closed_cap_restores_mode_with_no_quality_admission(monkeypatch, archived_cap):
    row = _closed(monkeypatch, archived_cap)
    assert row["mode"] == "resident"
    assert row["mode_source"] == "lab_evaluation_state"
    assert row["run_id"] == lab.CAP_RUN_ID
    assert row["phase"] == "aborted"
    assert row["source_error"] is None
    assert row["resident_services_expected"] == "online"
    assert row["nara_service_expected"] == "running"
    assert len(row["mode_source_sha256"]) == 64


def test_cap_audit_or_current_source_drift_stays_unknown(monkeypatch, archived_cap):
    monkeypatch.setattr(lab, "CAP_AUDIT_SHA", "0" * 64)
    assert _closed(monkeypatch, archived_cap)["mode"] == "unknown"
    monkeypatch.setattr(lab, "CAP_AUDIT_SHA", "4a94d553dc47b7a55f297634b2e077ad3f7b8a5b9a485baf12a503bf1a8be1f0")
    actual = lab.mr._read_path

    def drift(path, **kwargs):
        if path == cap.CODE_ROOT / "bench/flash_next_ab/lab_window.py":
            return b"changed frozen controller"
        return actual(path, **kwargs)

    monkeypatch.setattr(lab.mr, "_read_path", drift)
    assert _closed(monkeypatch, archived_cap)["mode"] == "unknown"


def test_cap_restoration_requires_live_nara_and_absent_candidate(monkeypatch, archived_cap):
    monkeypatch.setattr(lab, "_live_restored", lambda _state, _cohort: "paused")
    monkeypatch.setattr(q, "_inspect_container", lambda _ops, _identity: None)
    assert lab.project_lab_runtime(observed=datetime.now(timezone.utc))["mode"] == "unknown"
    monkeypatch.setattr(lab, "_live_restored", lambda _state, _cohort: "running")
    monkeypatch.setattr(q, "_inspect_container", lambda _ops, _identity: {"id": "a" * 64})
    assert lab.project_lab_runtime(observed=datetime.now(timezone.utc))["mode"] == "unknown"


def test_newer_invalid_lab_state_does_not_fall_back_to_cap(tmp_path):
    root = tmp_path / "model-windows"
    older = root / lab.CAP_RUN_ID
    older.mkdir(parents=True)
    (older / "state.json").write_bytes(b"{}")
    newer = root / "qfn-ab-lab-other-later.flash"
    newer.mkdir(parents=True)
    (newer / "state.json").write_bytes(b"{invalid")
    row = lab.project_lab_runtime(root, observed=datetime.now(timezone.utc))
    assert row["mode"] == "unknown"
    assert row["mode_source_sha256"] is None
