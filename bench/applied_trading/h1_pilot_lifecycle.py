"""One fixed H1 REST reference pilot: prestart plan and due evaluation.

This local-file lifecycle never places an order or makes a market/model GET.
Capture is performed by the separate bounded capture timer. The result is a
displayed-quote diagnostic, never executable paper evidence.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (
    capture_tick,
    prospective_hourly_features,
    public_spot_capture,
    rest_reference_driver,
)
from .collection_projection import _read_relative
from .public_spot_capture import strict_json

DATA_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
    "applied-trading-public-data"
)
STUDIES_ROOT = DATA_ROOT / "prospective-studies"
PUBLICATION_ROOT = DATA_ROOT / "publications"
CAPTURE_ROOT = DATA_ROOT / "captures"
TOPIC_PATH = Path(__file__).parent / "h1_topic_transfer.json"
INDEX_SCHEMA = "applied-trading-publication/v1"
PLAN_KIND = "h1_rest_pilot_plan"
RESULT_KIND = "h1_rest_pilot_result"
STUDY_PATTERN = re.compile(r"h1-btcusdt-rest-[0-9]{8}-[a-z0-9]{3,16}\Z")
BATCH_PATTERN = re.compile(r"spot-BTCUSDT-[0-9]{8}T[0-9]{6}Z\Z")
MAX_CAPTURE_CHILDREN = 10_000
MAX_BATCHES = 96
LOOKBACK = timedelta(minutes=90)
LATE_SOURCE_WAIT = timedelta(minutes=30)


class LifecycleError(RuntimeError):
    pass


def _must(ok: bool, reason: str) -> None:
    if not ok:
        raise LifecycleError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canon(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode() + b"\n"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: str) -> datetime:
    _must(isinstance(value, str), "pilot time is not text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("pilot time is malformed") from exc
    _must(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0),
          "pilot time must carry UTC offset")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fixed_dir(path: Path) -> None:
    _must(path.is_dir() and not path.is_symlink()
          and path.resolve() == path.absolute(),
          "pilot input/output directory is absent or redirected")


def _source_sha(module: object) -> str:
    path = Path(module.__file__)
    _must(path.is_file() and not path.is_symlink(),
          "registered pilot source is unavailable")
    return _sha(path.read_bytes())


def _write_new(path: Path, raw: bytes) -> None:
    _fixed_dir(path.parent)
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY |
                        os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                     0o600, dir_fd=parent_fd)
        try:
            view = memoryview(raw)
            while view:
                size = os.write(fd, view)
                _must(size > 0, "pilot receipt write failed")
                view = view[size:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _study_id(value: str) -> str:
    _must(isinstance(value, str) and STUDY_PATTERN.fullmatch(value) is not None,
          "one H1 REST study ID is malformed")
    return value


def _study_child(value: str) -> Path:
    child = STUDIES_ROOT / _study_id(value)
    _fixed_dir(child)
    return child


@contextmanager
def _due_lock(child: Path):
    """A second timer process cannot close a still-running first attempt."""
    _fixed_dir(child)
    directory_fd = os.open(child, os.O_RDONLY | os.O_DIRECTORY |
                           os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open("due.lock", os.O_RDWR | os.O_CREAT | os.O_NONBLOCK |
                     os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                     0o600, dir_fd=directory_fd)
        try:
            info = os.fstat(fd)
            path_info = os.stat("due.lock", dir_fd=directory_fd,
                                follow_symlinks=False)
            _must(stat.S_ISREG(info.st_mode) and info.st_size <= 4096
                  and (info.st_dev, info.st_ino) ==
                      (path_info.st_dev, path_info.st_ino),
                  "due evaluator lock is nonregular or replaced")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
            else:
                yield True
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)


def _plan_index_name(value: str) -> str:
    return "h1-rest-" + value + ".plan.json"


def _result_index_name(value: str) -> str:
    return "h1-rest-" + value + ".result.json"


def _plan_receipt_raw(value: str) -> bytes:
    return _read_relative(PUBLICATION_ROOT, _plan_index_name(value), 32_000)


def _read_plan(value: str) -> tuple[Path, bytes, dict, bytes, dict]:
    child = _study_child(value)
    plan_raw = _read_relative(child, "plan.raw.json", 64_000)
    topic_raw = _read_relative(child, "topic-transfer.raw.json", 64_000)
    publication_raw = _plan_receipt_raw(value)
    plan = strict_json(plan_raw)
    receipt = strict_json(publication_raw)
    _must(isinstance(receipt, dict)
          and receipt.get("schema") == INDEX_SCHEMA
          and receipt.get("kind") == PLAN_KIND
          and receipt.get("status") == "published_local_prestart"
          and receipt.get("study_id") == value
          and receipt.get("plan_relpath") ==
              f"prospective-studies/{value}/plan.raw.json"
          and receipt.get("plan_raw_sha256") == _sha(plan_raw)
          and receipt.get("topic_transfer_relpath") ==
              f"prospective-studies/{value}/topic-transfer.raw.json"
          and receipt.get("topic_transfer_raw_sha256") == _sha(topic_raw)
          and receipt.get("freeze_proof") == "local_exclusive_write_only"
          and receipt.get("external_plan_freeze_proof") == "unverified"
          and receipt.get("nonexecutable_reference_only") is True
          and receipt.get("paper_supported") is False,
          "prestart publication does not bind the exact plan/topic")
    _must(isinstance(plan, dict) and plan.get("study_id") == value
          and plan.get("topic_transfer_sha256") == _sha(topic_raw)
          and receipt["forward_start"] == plan["split"]["forward_start"]
          and receipt["forward_end"] == plan["split"]["forward_end"]
          and _utc(receipt["published_at"]) <
              _utc(receipt["forward_start"]),
          "plan publication chronology or policy differs")
    _must(receipt.get("capture_tick_source_sha256") ==
              _source_sha(capture_tick)
          and receipt.get("collector_source_sha256") ==
              _source_sha(public_spot_capture)
          and receipt.get("feature_builder_source_sha256") ==
              _source_sha(prospective_hourly_features)
          and receipt.get("driver_source_sha256") ==
              _source_sha(rest_reference_driver)
          and receipt.get("lifecycle_source_sha256") ==
              _sha(Path(__file__).read_bytes()),
          "pilot source bundle changed since prestart publication")
    rest_reference_driver.validate_plan(
        plan, collector_source=Path(public_spot_capture.__file__),
        feature_builder_source=Path(prospective_hourly_features.__file__))
    return child, plan_raw, plan, publication_raw, receipt


def publish_plan(*, study_id: str, start: datetime, hours: int) -> dict:
    """Write plan/topic first; index publication last, before forward start."""
    _study_id(study_id)
    _fixed_dir(DATA_ROOT)
    _fixed_dir(STUDIES_ROOT)
    _fixed_dir(PUBLICATION_ROOT)
    _must(type(hours) is int and 2 <= hours <= 5,
          "pilot block needs two to five scheduled H1 decisions")
    created_at = _now()
    _must(start - created_at >= timedelta(minutes=20),
          "plan must be created at least 20 minutes before first decision")
    end = start + timedelta(hours=hours)
    topic_raw = _read_relative(TOPIC_PATH.parent, TOPIC_PATH.name, 64_000)
    plan = {
        "schema": rest_reference_driver.PLAN_SCHEMA,
        "study_id": study_id, "symbol": "BTCUSDT",
        "rule_origin": rest_reference_driver.RULE_ORIGIN,
        "topic_transfer_sha256": _sha(topic_raw),
        "source": {
            "source_id": "binance-spot-public",
            "collector_source_sha256": _source_sha(public_spot_capture),
            "feature_builder_source_sha256":
                _source_sha(prospective_hourly_features),
        },
        "split": {"frozen_at": _stamp(created_at),
                  "forward_start": _stamp(start), "forward_end": _stamp(end)},
        "policy": {
            "hold_s": 3600, "latency_s": 30,
            "entry_timeout_s": 600, "exit_timeout_s": 600,
            "max_quote_receive_delay_s": 30,
            "max_observation_age_s": 300, "paper_size_quote": 100,
            "candidate": dict(rest_reference_driver.ENGINEERING_CANDIDATE),
            "baseline": dict(rest_reference_driver.ENGINEERING_BASELINE),
        },
        "cost": {"fee_leg_bps": 10, "slippage_leg_bps": 5,
                 "double_multiplier": 2,
                 "fee_source_url": rest_reference_driver.FEE_URL},
    }
    rest_reference_driver.validate_plan(
        plan, collector_source=Path(public_spot_capture.__file__),
        feature_builder_source=Path(prospective_hourly_features.__file__))
    child = STUDIES_ROOT / study_id
    _must(not child.exists() and not child.is_symlink()
          and not (PUBLICATION_ROOT / _plan_index_name(study_id)).exists(),
          "H1 plan child/publication already exists")
    child.mkdir(mode=0o700)
    _write_new(child / "plan.raw.json", _canon(plan))
    _write_new(child / "topic-transfer.raw.json", topic_raw)
    published_at = _now()
    _must(published_at < start,
          "pilot publication missed its first decision; child stays unindexed")
    index = {
        "schema": INDEX_SCHEMA, "kind": PLAN_KIND,
        "status": "published_local_prestart", "study_id": study_id,
        "published_at": _stamp(published_at),
        "forward_start": _stamp(start), "forward_end": _stamp(end),
        "plan_relpath": f"prospective-studies/{study_id}/plan.raw.json",
        "plan_raw_sha256": _sha(_canon(plan)),
        "topic_transfer_relpath":
            f"prospective-studies/{study_id}/topic-transfer.raw.json",
        "topic_transfer_raw_sha256": _sha(topic_raw),
        "capture_tick_source_sha256": _source_sha(capture_tick),
        "collector_source_sha256": _source_sha(public_spot_capture),
        "feature_builder_source_sha256":
            _source_sha(prospective_hourly_features),
        "driver_source_sha256": _source_sha(rest_reference_driver),
        "lifecycle_source_sha256": _sha(Path(__file__).read_bytes()),
        "freeze_proof": "local_exclusive_write_only",
        "external_plan_freeze_proof": "unverified",
        "nonexecutable_reference_only": True,
        "paper_supported": False, "science_ladder_changed": False,
        "orders_placed": 0,
    }
    _write_new(PUBLICATION_ROOT / _plan_index_name(study_id), _canon(index))
    return index


def _capture_candidates(*, start: datetime, required: datetime) -> list[Path]:
    """Bounded metadata scan; every selected batch is later fully reprojected."""
    _fixed_dir(CAPTURE_ROOT)
    choices = []
    observed_children = 0
    with os.scandir(CAPTURE_ROOT) as rows:
        for row in rows:
            observed_children += 1
            _must(observed_children <= MAX_CAPTURE_CHILDREN,
                  "capture root exceeds registered metadata scan")
            if BATCH_PATTERN.fullmatch(row.name) is None:
                continue
            # The name contains a UTC capture start; open raw receipts only
            # for the fixed pilot range, not months of older batches.
            name_start = datetime.strptime(row.name[-16:-1],
                                           "%Y%m%dT%H%M%S").replace(
                                               tzinfo=timezone.utc)
            if not (start - LOOKBACK <= name_start <=
                    required + timedelta(minutes=10)):
                continue
            _must(row.is_dir(follow_symlinks=False),
                  "registered capture name is not a regular child directory")
            child = CAPTURE_ROOT / row.name
            raw = _read_relative(child, "capture-batch.json", 32_000)
            batch = strict_json(raw)
            _must(isinstance(batch, dict)
                  and batch.get("symbol") == "BTCUSDT",
                  "capture candidate is malformed")
            began, sealed = _utc(batch["started_at"]), _utc(batch["sealed_at"])
            _must(abs((began - name_start).total_seconds()) <= 180,
                  "capture name and original request time differ")
            _must(began <= sealed,
                  "capture candidate has inverted start/seal chronology")
            if batch.get("status") == "incomplete" and (
                    batch.get("initial_history_gap") is True
                    and batch.get("failure") is None
                    and batch.get("requests_failed") == 0
                    and batch.get("backlog_unresolved") is False
                    and type(batch.get("next_aggregate_id")) is int):
                # A clean venue-tail warmup seeds the next batch cursor but
                # is not a continuous closed-hour observation. Failed or
                # capped incomplete batches remain in the selected window
                # and will fail source admission rather than be skipped.
                continue
            if began >= start - LOOKBACK and began <= required + timedelta(minutes=10):
                choices.append((began, sealed, child))
    choices.sort(key=lambda item: (item[0], str(item[2])))
    _must(len(choices) <= MAX_BATCHES,
          "frozen H1 window exceeds the exact 96-batch feature cap")
    selected = []
    for _began, sealed, child in choices:
        selected.append(child)
        if sealed >= required:
            break
    return selected


def _attempt_receipt(child: Path, status: str, reason: str,
                     source_batches: list[Path]) -> None:
    attempts = child / "due-attempts"
    if not attempts.exists():
        attempts.mkdir(mode=0o700)
    _fixed_dir(attempts)
    name = _now().strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8] + ".json"
    _write_new(attempts / name, _canon({
        "schema": "applied-h1-rest-due-attempt/v1",
        "observed_at": _stamp(_now()), "status": status, "reason": reason,
        "selected_batch_relpaths": ["captures/" + row.name for row in source_batches],
        "GET_requests": 0, "model_calls": 0, "orders": 0,
    }))


def _publish_missing(child: Path, plan: dict, plan_publication_raw: bytes,
                     reason: str, selected: list[Path]) -> dict:
    """Close unknown evidence with null scores, never a synthetic driver row."""
    study_id = plan["study_id"]
    declared = int((_utc(plan["split"]["forward_end"]) -
                    _utc(plan["split"]["forward_start"])).total_seconds() / 3600)
    receipt = {
        "schema": INDEX_SCHEMA, "kind": RESULT_KIND,
        "status": "closed_missing_source", "study_id": study_id,
        "published_at": _stamp(_now()),
        "plan_publication_relpath":
            "publications/" + _plan_index_name(study_id),
        "plan_publication_raw_sha256": _sha(plan_publication_raw),
        "result_relpath": None, "result_raw_sha256": None,
        "private_cells_relpath": None, "private_cells_raw_sha256": None,
        "selected_batch_relpaths": ["captures/" + row.name for row in selected],
        "selected_batches_count": len(selected),
        "scheduled_cells": declared,
        "source_valid_cells": None, "unknown_scheduled_cells": declared,
        "candidate_net_bps_per_all_scheduled": None,
        "baseline_net_bps_per_all_scheduled": None,
        "missing_reason": reason,
        "nonexecutable_reference_only": True, "paper_supported": False,
        "sequence_valid": False, "external_plan_freeze_proof": "unverified",
        "science_ladder_changed": False, "orders_placed": 0,
    }
    _write_new(PUBLICATION_ROOT / _result_index_name(study_id), _canon(receipt))
    return receipt


def _publish_result(child: Path, plan: dict, plan_publication_raw: bytes,
                    selected: list[Path]) -> dict:
    result_child = child / "reference-result"
    result_raw = _read_relative(result_child, "result.json", 1_000_000)
    private_raw = _read_relative(result_child, "reference-cells.jsonl", 8_000_000)
    result = strict_json(result_raw)
    study_id = plan["study_id"]
    plan_raw = _read_relative(child, "plan.raw.json", 64_000)
    _must(isinstance(result, dict)
          and result.get("schema") == rest_reference_driver.RESULT_SCHEMA
          and result.get("study_id") == study_id
          and result.get("status") in {
              "complete_reference_review", "closed_with_missing_evidence"}
          and result.get("temporal_window_closed") is True
          and result.get("plan_sha256") == _sha(plan_raw)
          and result.get("private_cells_sha256") == _sha(private_raw)
          and result.get("driver_source_sha256") ==
              _source_sha(rest_reference_driver)
          and result.get("scheduled_cells") == int((
              _utc(plan["split"]["forward_end"]) -
              _utc(plan["split"]["forward_start"])).total_seconds() / 3600)
          and result.get("nonexecutable_reference_only") is True
          and result.get("paper_supported") is False
          and result.get("sequence_valid") is False
          and result.get("external_plan_freeze_proof") == "unverified"
          and result.get("science_ladder_changed") is False
          and result.get("orders_placed") == 0,
          "REST result/private ledger fails source-bound reference admission")
    _must(type(result.get("batch_capture_sha256s")) is list
          and len(result["batch_capture_sha256s"]) == len(selected),
          "REST result hides or adds selected source batches")
    cell_lines = private_raw.splitlines()
    _must(len(cell_lines) == result["scheduled_cells"],
          "REST private ledger omitted a declared scheduled cell")
    for ordinal, line in enumerate(cell_lines):
        cell = strict_json(line)
        _must(isinstance(cell, dict)
              and cell.get("schema") == rest_reference_driver.CELL_SCHEMA
              and cell.get("cell_id") == f"{study_id}.{ordinal:04d}",
              "REST private ledger cell identity/order differs")
    for path, digest in zip(selected, result["batch_capture_sha256s"]):
        _must(_sha(_read_relative(path, "capture-batch.json", 32_000)) == digest,
              "REST result source batch digest differs")
    topic_raw = _read_relative(child, "topic-transfer.raw.json", 64_000)
    replay_result, replay_cells = rest_reference_driver.evaluate(
        plan, batch_paths=selected, feature_dir=child / "features",
        collector_source=Path(public_spot_capture.__file__),
        feature_builder_source=Path(prospective_hourly_features.__file__),
        plan_raw=plan_raw, topic_raw=topic_raw)
    replay_private_raw = b"".join(rest_reference_driver._canon(cell)
                                  for cell in replay_cells)
    replay_result["private_cells_sha256"] = _sha(replay_private_raw)
    _must(result == replay_result and private_raw == replay_private_raw,
          "REST numeric grade/private ledger differs from deterministic replay")
    receipt = {
        "schema": INDEX_SCHEMA, "kind": RESULT_KIND,
        "status": "admitted_reference_result", "study_id": study_id,
        "published_at": _stamp(_now()),
        "plan_publication_relpath":
            "publications/" + _plan_index_name(study_id),
        "plan_publication_raw_sha256": _sha(plan_publication_raw),
        "result_relpath":
            f"prospective-studies/{study_id}/reference-result/result.json",
        "result_raw_sha256": _sha(result_raw),
        "private_cells_relpath":
            f"prospective-studies/{study_id}/reference-result/reference-cells.jsonl",
        "private_cells_raw_sha256": _sha(private_raw),
        "driver_source_sha256": _source_sha(rest_reference_driver),
        "grade_replay": "deterministic_rest_reference_result_and_private_cells",
        "selected_batch_relpaths": ["captures/" + row.name for row in selected],
        "selected_batches_count": len(selected),
        "scheduled_cells": result["scheduled_cells"],
        "source_valid_cells": result["source_valid_cells"],
        "missing_feature_cells": result["missing_feature_cells"],
        "invalid_or_stale_feature_cells":
            result["invalid_or_stale_feature_cells"],
        "candidate_unknown_outcome_cells":
            result["candidate"]["unknown_outcome_cells"],
        "baseline_unknown_outcome_cells":
            result["matched_momentum_baseline"]["unknown_outcome_cells"],
        "candidate_net_bps_per_all_scheduled": (
            result["candidate"]["net_bps_per_all_scheduled"]
            if result["status"] == "complete_reference_review" else None),
        "baseline_net_bps_per_all_scheduled": (
            result["matched_momentum_baseline"]["net_bps_per_all_scheduled"]
            if result["status"] == "complete_reference_review" else None),
        "nonexecutable_reference_only": True, "paper_supported": False,
        "sequence_valid": False, "external_plan_freeze_proof": "unverified",
        "science_ladder_changed": False, "orders_placed": 0,
    }
    if result["status"] == "closed_with_missing_evidence":
        _must(receipt["candidate_net_bps_per_all_scheduled"] is None and
              receipt["baseline_net_bps_per_all_scheduled"] is None,
              "unknown evidence was silently scored")
    _write_new(PUBLICATION_ROOT / _result_index_name(study_id), _canon(receipt))
    return receipt


def evaluate_due(study_id: str) -> dict:
    """One due attempt; busy leases retry, exhausted source closes unknown."""
    child = _study_child(study_id)
    with _due_lock(child) as acquired:
        if not acquired:
            return {"status": "skipped_busy_due_worker"}
        return _evaluate_due_locked(study_id)


def _evaluate_due_locked(study_id: str) -> dict:
    """Lock-held evaluator body. Publication is its irreversible final step."""
    child, _plan_raw, plan, plan_publication_raw, _receipt = _read_plan(study_id)
    result_index = PUBLICATION_ROOT / _result_index_name(study_id)
    _must(not result_index.is_symlink(),
          "H1 result publication is redirected")
    if result_index.exists():
        closed_raw = _read_relative(PUBLICATION_ROOT,
                                    _result_index_name(study_id), 64_000)
        closed = strict_json(closed_raw)
        _must(isinstance(closed, dict)
              and closed.get("schema") == INDEX_SCHEMA
              and closed.get("kind") == RESULT_KIND
              and closed.get("study_id") == study_id
              and closed.get("status") in {
                  "admitted_reference_result", "closed_missing_source"},
              "existing H1 result publication has invalid identity")
        return {"status": "already_closed", "study_id": study_id}
    required = (_utc(plan["split"]["forward_end"]) +
                timedelta(seconds=plan["policy"]["hold_s"] +
                                  plan["policy"]["exit_timeout_s"]))
    current = _now()
    if current < required:
        return {"status": "not_due", "next_due_at": _stamp(required)}
    with capture_tick._idle_leases() as busy:
        if busy is not None:
            _attempt_receipt(child, "skipped_busy", busy, [])
            return {"status": "skipped_busy", "reason": busy}
        selected: list[Path] = []
        try:
            selected = _capture_candidates(
                start=_utc(plan["split"]["forward_start"]), required=required)
            _must(selected, "no prospective capture batch in frozen window")
            last = strict_json(_read_relative(
                selected[-1], "capture-batch.json", 32_000))
            _must(_utc(last["sealed_at"]) >= required,
                  "prospective captures have not sealed through hold/exit")
            # Derive validates exact-source GET chain, cursor, venue trade
            # chronology and no cursor or >15-minute time gaps before scoring.
            source, features = prospective_hourly_features.derive(
                selected,
                collector_sha256=plan["source"]["collector_source_sha256"],
                symbol="BTCUSDT")
            feature_child = child / "features"
            features_raw = b"".join(_canon(row) for row in features)
            source["features_sha256"] = _sha(features_raw)
            _must(not feature_child.is_symlink(),
                  "H1 feature child is redirected")
            if feature_child.exists():
                # A completed feature stage without a result index can resume
                # only when the exact replayed files are still present.
                _must(_read_relative(feature_child, "features.jsonl",
                                     2_000_000) == features_raw
                      and _read_relative(feature_child, "feature-source.json",
                                         128_000) == _canon(source),
                      "orphan feature child differs from exact source replay")
            else:
                feature_child.mkdir(mode=0o700)
                _write_new(feature_child / "features.jsonl", features_raw)
                _write_new(feature_child / "feature-source.json", _canon(source))
            args = ["--plan", str(child / "plan.raw.json"),
                    "--topic-transfer", str(child / "topic-transfer.raw.json"),
                    "--feature-dir", str(feature_child)]
            for batch in selected:
                args += ["--batch", str(batch)]
            args += ["--output-dir", str(child / "reference-result")]
            result_child = child / "reference-result"
            _must(not result_child.is_symlink(),
                  "H1 result child is redirected")
            if result_child.exists():
                _must((result_child / "result.json").is_file()
                      and (result_child / "reference-cells.jsonl").is_file(),
                      "orphan REST result is incomplete; no selective rerun")
            else:
                rest_reference_driver.main(args)
            published = _publish_result(child, plan, plan_publication_raw,
                                        selected)
            _attempt_receipt(child, "published", "source_valid_reference_review",
                             selected)
            return published
        except (OSError, ValueError, KeyError, LifecycleError,
                public_spot_capture.CaptureError) as exc:
            # An invalid/missing source must remain unknown, not a fabricated
            # complete REST row. Wait at most thirty minutes for late capture.
            reason = type(exc).__name__ + ":" + str(exc)[:160]
            if current < required + LATE_SOURCE_WAIT:
                _attempt_receipt(child, "waiting_for_source", reason, selected)
                return {"status": "waiting_for_source", "reason": reason}
            _attempt_receipt(child, "closed_missing_source", reason, selected)
            return _publish_missing(child, plan, plan_publication_raw,
                                    reason, selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--publish-plan", action="store_true")
    modes.add_argument("--evaluate-due", action="store_true")
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--forward-start-utc")
    parser.add_argument("--hours", type=int)
    args = parser.parse_args(argv)
    if args.publish_plan:
        _must(args.forward_start_utc is not None and args.hours is not None,
              "plan publication needs exact future start and hours")
        row = publish_plan(study_id=args.study_id,
                           start=_utc(args.forward_start_utc), hours=args.hours)
    else:
        _must(args.forward_start_utc is None and args.hours is None,
              "due evaluator reads only the published plan")
        row = evaluate_due(args.study_id)
    print(json.dumps({"status": row["status"],
                      "study_id": args.study_id}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
