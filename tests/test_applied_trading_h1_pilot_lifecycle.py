"""Prestart and due/unknown receipt tests with no market GET or model call."""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bench.applied_trading import h1_pilot_lifecycle as l


def _roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    studies = tmp_path / "prospective-studies"
    publications = tmp_path / "publications"
    captures = tmp_path / "captures"
    for child in (studies, publications, captures):
        child.mkdir()
    monkeypatch.setattr(l, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(l, "STUDIES_ROOT", studies)
    monkeypatch.setattr(l, "PUBLICATION_ROOT", publications)
    monkeypatch.setattr(l, "CAPTURE_ROOT", captures)
    return studies, publications


def _future_start() -> datetime:
    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=2)).replace(minute=5, second=0,
                                                microsecond=0)
    if start - now < timedelta(minutes=20):
        start += timedelta(hours=1)
    return start


def _published(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    studies, publications = _roots(monkeypatch, tmp_path)
    start = _future_start()
    study_id = "h1-btcusdt-rest-20260915-test01"
    plan_receipt = l.publish_plan(study_id=study_id, start=start, hours=2)
    plan = json.loads((studies / study_id / "plan.raw.json").read_bytes())
    return studies, publications, study_id, start, plan, plan_receipt


def test_prestart_plan_is_raw_bound_and_reference_only(monkeypatch, tmp_path):
    _studies, publications, study_id, start, plan, receipt = _published(
        monkeypatch, tmp_path)
    assert receipt["status"] == "published_local_prestart"
    assert receipt["freeze_proof"] == "local_exclusive_write_only"
    assert receipt["external_plan_freeze_proof"] == "unverified"
    assert receipt["paper_supported"] is False
    assert receipt["orders_placed"] == 0
    assert l._utc(receipt["published_at"]) < start
    assert (plan["policy"]["candidate"] ==
            l.rest_reference_driver.ENGINEERING_CANDIDATE)
    assert (publications / l._plan_index_name(study_id)).is_file()
    with pytest.raises((FileExistsError, l.LifecycleError)):
        l.publish_plan(study_id=study_id, start=start, hours=2)


def test_tampered_plan_raw_fails_publication_binding(monkeypatch, tmp_path):
    studies, _publications, study_id, _start, _plan, _receipt = _published(
        monkeypatch, tmp_path)
    raw = studies / study_id / "plan.raw.json"
    value = json.loads(raw.read_bytes())
    value["cost"]["fee_leg_bps"] = 100
    raw.write_text(json.dumps(value))
    with pytest.raises(l.LifecycleError, match="exact plan/topic"):
        l._read_plan(study_id)


def test_due_busy_lease_retries_without_result(monkeypatch, tmp_path):
    _studies, publications, study_id, _start, plan, _receipt = _published(
        monkeypatch, tmp_path)
    required = l._utc(plan["split"]["forward_end"]) + timedelta(
        seconds=plan["policy"]["hold_s"] + plan["policy"]["exit_timeout_s"])
    monkeypatch.setattr(l, "_now", lambda: required + timedelta(minutes=2))

    @contextmanager
    def busy():
        yield "research_lease_busy"

    monkeypatch.setattr(l.capture_tick, "_idle_leases", busy)
    row = l.evaluate_due(study_id)
    assert row["status"] == "skipped_busy"
    assert not (publications / l._result_index_name(study_id)).exists()


def test_missing_source_closes_null_after_bounded_wait(monkeypatch, tmp_path):
    _studies, publications, study_id, _start, plan, _receipt = _published(
        monkeypatch, tmp_path)
    required = l._utc(plan["split"]["forward_end"]) + timedelta(
        seconds=plan["policy"]["hold_s"] + plan["policy"]["exit_timeout_s"])
    monkeypatch.setattr(l, "_now", lambda: required + timedelta(minutes=31))
    monkeypatch.setattr(l, "_capture_candidates", lambda **_kwargs: [])

    @contextmanager
    def idle():
        yield None

    monkeypatch.setattr(l.capture_tick, "_idle_leases", idle)
    row = l.evaluate_due(study_id)
    assert row["status"] == "closed_missing_source"
    assert row["scheduled_cells"] == 2
    assert row["unknown_scheduled_cells"] == 2
    assert row["candidate_net_bps_per_all_scheduled"] is None
    assert row["baseline_net_bps_per_all_scheduled"] is None
    assert row["paper_supported"] is False
    assert (publications / l._result_index_name(study_id)).is_file()
    assert l.evaluate_due(study_id)["status"] == "already_closed"


def test_clean_warmup_is_skipped_but_failed_incremental_is_not(monkeypatch,
                                                                tmp_path):
    _studies, _publications = _roots(monkeypatch, tmp_path)
    start = _future_start()
    required = start + timedelta(hours=2)

    def batch(when: datetime, *, warmup: bool, failure: str | None,
              through_due: bool = False) -> Path:
        child = l.CAPTURE_ROOT / ("spot-BTCUSDT-" +
                                  when.strftime("%Y%m%dT%H%M%SZ"))
        child.mkdir()
        (child / "capture-batch.json").write_bytes(l._canon({
            "symbol": "BTCUSDT", "started_at": l._stamp(when),
            "sealed_at": l._stamp(required + timedelta(minutes=1)
                                 if through_due else when + timedelta(minutes=1)),
            "status": "incomplete" if warmup or failure else
                      "complete_incremental_batch",
            "initial_history_gap": warmup, "failure": failure,
            "requests_failed": 0, "backlog_unresolved": False,
            "next_aggregate_id": 100,
        }))
        return child

    warmup = batch(start - timedelta(minutes=30), warmup=True, failure=None)
    failed = batch(start - timedelta(minutes=20), warmup=False,
                   failure="bounded_page_cap")
    complete = batch(start - timedelta(minutes=10), warmup=False,
                     failure=None, through_due=True)
    selected = l._capture_candidates(start=start, required=required)
    assert warmup not in selected
    assert selected == [failed, complete]


def test_numeric_publication_requires_exact_grade_replay(monkeypatch, tmp_path):
    _studies, publications = _roots(monkeypatch, tmp_path)
    study_id = "h1-btcusdt-rest-20260915-test02"
    child = l.STUDIES_ROOT / study_id
    result_child = child / "reference-result"
    result_child.mkdir(parents=True)
    (child / "features").mkdir()
    plan = {"study_id": study_id, "split": {
        "forward_start": "2026-09-15T16:05:00Z",
        "forward_end": "2026-09-15T18:05:00Z"}}
    plan_raw = l._canon(plan)
    (child / "plan.raw.json").write_bytes(plan_raw)
    (child / "topic-transfer.raw.json").write_bytes(b"{}\n")
    source = l.CAPTURE_ROOT / "spot-BTCUSDT-20260915T160000Z"
    source.mkdir()
    batch_raw = l._canon({"started_at": "2026-09-15T16:00:00Z"})
    (source / "capture-batch.json").write_bytes(batch_raw)
    cells = [{"schema": l.rest_reference_driver.CELL_SCHEMA,
              "cell_id": f"{study_id}.{index:04d}"} for index in range(2)]
    private_raw = b"".join(l.rest_reference_driver._canon(row)
                           for row in cells)
    (result_child / "reference-cells.jsonl").write_bytes(private_raw)
    monkeypatch.setattr(l, "_source_sha", lambda _module: "a" * 64)
    grade = {
        "schema": l.rest_reference_driver.RESULT_SCHEMA,
        "study_id": study_id, "status": "complete_reference_review",
        "temporal_window_closed": True, "plan_sha256": l._sha(plan_raw),
        "driver_source_sha256": "a" * 64,
        "scheduled_cells": 2, "source_valid_cells": 2,
        "missing_feature_cells": 0, "invalid_or_stale_feature_cells": 0,
        "batch_capture_sha256s": [l._sha(batch_raw)],
        "candidate": {"net_bps_per_all_scheduled": 1.0,
                      "unknown_outcome_cells": 0},
        "matched_momentum_baseline": {
            "net_bps_per_all_scheduled": 0.0,
            "unknown_outcome_cells": 0},
        "nonexecutable_reference_only": True, "paper_supported": False,
        "sequence_valid": False, "external_plan_freeze_proof": "unverified",
        "science_ladder_changed": False, "orders_placed": 0,
    }
    returned = copy.deepcopy(grade)
    returned["private_cells_sha256"] = l._sha(private_raw)
    (result_child / "result.json").write_bytes(l._canon(returned))
    monkeypatch.setattr(l.rest_reference_driver, "evaluate",
                        lambda *_args, **_kwargs: (copy.deepcopy(grade), cells))
    admitted = l._publish_result(child, plan, b"plan-index\n", [source])
    assert admitted["grade_replay"] == (
        "deterministic_rest_reference_result_and_private_cells")
    assert admitted["candidate_net_bps_per_all_scheduled"] == 1.0
    (publications / l._result_index_name(study_id)).unlink()
    returned["candidate"]["net_bps_per_all_scheduled"] = 999.0
    (result_child / "result.json").write_bytes(l._canon(returned))
    with pytest.raises(l.LifecycleError, match="numeric grade"):
        l._publish_result(child, plan, b"plan-index\n", [source])


def test_completed_feature_child_retries_exact_driver_stage(monkeypatch,
                                                            tmp_path):
    studies, _publications, study_id, _start, plan, _receipt = _published(
        monkeypatch, tmp_path)
    required = l._utc(plan["split"]["forward_end"]) + timedelta(
        seconds=plan["policy"]["hold_s"] + plan["policy"]["exit_timeout_s"])
    monkeypatch.setattr(l, "_now", lambda: required + timedelta(minutes=2))
    source = l.CAPTURE_ROOT / "spot-BTCUSDT-20260915T160000Z"
    source.mkdir()
    (source / "capture-batch.json").write_bytes(l._canon({
        "sealed_at": l._stamp(required + timedelta(minutes=1))}))
    monkeypatch.setattr(l, "_capture_candidates", lambda **_kwargs: [source])
    monkeypatch.setattr(l.prospective_hourly_features, "derive",
                        lambda *_args, **_kwargs: ({"batch_receipts": []}, []))

    @contextmanager
    def idle():
        yield None

    monkeypatch.setattr(l.capture_tick, "_idle_leases", idle)
    calls = []

    def interrupted(_args):
        calls.append("entered_driver")
        raise l.public_spot_capture.CaptureError("driver_interrupted")

    monkeypatch.setattr(l.rest_reference_driver, "main", interrupted)
    assert l.evaluate_due(study_id)["status"] == "waiting_for_source"
    feature_child = studies / study_id / "features"
    assert (feature_child / "features.jsonl").is_file()
    assert l.evaluate_due(study_id)["status"] == "waiting_for_source"
    assert calls == ["entered_driver", "entered_driver"]
