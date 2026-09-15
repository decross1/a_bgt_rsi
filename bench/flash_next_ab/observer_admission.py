"""UNAPPLIED DRAFT: reconstruct an operational health proof after restoration."""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path

from .extended_observer import MAX_OBSERVER_BYTES, MAX_OBSERVER_ROWS, URLS
from .harness import _read_regular_file, _strict_object


class ObserverAdmissionError(ValueError):
    """UI observation did not continuously protect the evaluated window."""


def _require(condition, reason: str):
    if not condition:
        raise ObserverAdmissionError(reason)


def _time(value, source: str):
    try:
        observed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ObserverAdmissionError(f"{source} time is malformed") from exc
    _require(observed.tzinfo is not None, f"{source} time has no timezone")
    return observed.astimezone(timezone.utc)


def validate_ui_observer(output: Path, result: dict, state: dict, plan: dict) -> dict:
    """Admit exact URL/policy/order/cadence and raw observer SHA, without HTTP."""
    raw, observed = _read_regular_file(
        output / "ui-observer.jsonl", label="extended UI observer raw evidence",
        max_bytes=MAX_OBSERVER_BYTES,
    )
    _require(observed == (output / "ui-observer.jsonl").absolute()
             and 5 <= len(raw.splitlines()) <= MAX_OBSERVER_ROWS
             and result.get("ui_observer_log_sha256") == hashlib.sha256(raw).hexdigest(),
             "UI observer raw bytes or bounded row count differ")
    summary_raw, summary_path = _read_regular_file(
        output / "ui-observer-summary.json", label="extended UI observer summary",
        max_bytes=2_000_000,
    )
    _require(summary_path == (output / "ui-observer-summary.json").absolute()
             and result.get("ui_observer_summary_sha256")
             == hashlib.sha256(summary_raw).hexdigest(),
             "UI observer summary digest differs")
    summary = _strict_object(summary_raw, "UI observer summary")
    rows = [_strict_object(line, "UI observer row") for line in raw.splitlines()]
    expected_plan_sha = plan["extended_serving_profile_sha256"]
    expected_extended_sha = result["extended_plan_sha256"]
    first, last = rows[0], rows[-1]
    _require(
        first.get("schema") == "flash-next-ui-observer/v1"
        and first.get("event") == "plan"
        and first.get("pair_id") == plan["pair_id"]
        and first.get("extended_plan_sha256") == expected_extended_sha
        and first.get("profile") == plan["extended_serving_profile"]
        and first.get("urls") == list(URLS)
        and first.get("model_requests") == 0
        and first.get("weekly_budget_debit") is False
        and last.get("schema") == "flash-next-ui-observer/v1"
        and last.get("event") == "finished"
        and last.get("pair_id") == first["pair_id"]
        and last.get("extended_plan_sha256") == expected_extended_sha
        and last.get("failed") is False
        and last.get("error_type") is None
        and summary.get("schema") == "flash-next-ui-observer-summary/v1"
        and summary.get("pair_id") == first["pair_id"]
        and summary.get("extended_plan_sha256") == expected_extended_sha
        and summary.get("observer_log_sha256") == result["ui_observer_log_sha256"]
        and summary.get("observer_log_bytes") == len(raw)
        and summary.get("joined") is True
        and summary.get("failed") is False
        and summary.get("error_type") is None,
        "UI observer ended without code-owned source/profile and joined success",
    )
    _require(len(rows) % 3 == 2, "UI observer rows are not complete plan/probe/tick triples")
    tick_rows = []
    failure_tick_elapsed = []
    timestamps = [_time(row.get("observed_at"), "UI observer row") for row in rows]
    _require(all(a <= b for a, b in pairwise(timestamps)),
             "UI observer timestamps decreased")
    for position in range(1, len(rows) - 1, 3):
        first_probe, second_probe, tick = rows[position:position+3]
        _require(
            len((first_probe, second_probe, tick)) == 3
            and [first_probe.get("event"), second_probe.get("event"), tick.get("event")]
                == ["probe", "probe", "tick"]
            and first_probe.get("url") == URLS[0]
            and second_probe.get("url") == URLS[1]
            and first_probe.get("schema") == second_probe.get("schema")
                == tick.get("schema") == "flash-next-ui-observer/v1"
            and tick.get("tick") == len(tick_rows) + 1
            and type(tick.get("failed")) is bool,
            "UI observer probe/tick identities or verdict differ",
        )
        probe_failed = False
        for probe in (first_probe, second_probe):
            latency = probe.get("elapsed_seconds")
            _require(
                type(latency) in {int, float}
                and math.isfinite(latency) and 0 <= latency <= 6
                and ("error_type" not in probe or
                     type(probe["error_type"]) is str and len(probe["error_type"]) <= 80)
                and ("http_status" not in probe or
                     type(probe["http_status"]) is int and
                     100 <= probe["http_status"] <= 599),
                "UI observer HTTP result/latency is malformed",
            )
            probe_failed |= probe.get("http_status") != 200 or latency > 2 or "error_type" in probe
        elapsed_mono = tick.get("elapsed_monotonic_seconds")
        _require(type(elapsed_mono) in {int, float} and math.isfinite(elapsed_mono)
                 and elapsed_mono >= 0 and tick["failed"] == probe_failed,
                 "UI observer failed tick differs from its two endpoint probes")
        if probe_failed:
            failure_tick_elapsed.append(elapsed_mono)
        tick_rows.append(tick)
    _require(type(last.get("ticks")) is int and last["ticks"] >= 2
             and last["ticks"] == len(tick_rows)
             and last.get("probes") == last["ticks"] * len(URLS)
             and last.get("failed_ticks") == len(failure_tick_elapsed)
             and summary.get("ticks") == last["ticks"]
             and summary.get("probes") == last["probes"]
             and summary.get("failed_ticks") == last["failed_ticks"]
             and summary.get("first_tick_at") == last.get("first_tick_at")
             and summary.get("last_tick_at") == last.get("last_tick_at"),
             "UI observer final and summary counts differ")
    tick_times = [_time(row.get("observed_at"), "UI observer tick") for row in tick_rows]
    tick_elapsed = [row["elapsed_monotonic_seconds"] for row in tick_rows]
    _require(
        tick_elapsed[0] == 0
        and all(0 <= next_ - previous <= 15
                for previous, next_ in pairwise(tick_elapsed))
        and all(0 <= (next_ - previous).total_seconds() <= 15
                for previous, next_ in pairwise(tick_times))
        and all(next_ - previous > 30
                for previous, next_ in pairwise(failure_tick_elapsed)),
        "UI observer had a blind interval longer than fifteen seconds",
    )
    started = _time(result.get("started_at"), "window start")
    completed = _time(result.get("restoration", {}).get("verified_at"), "restoration")
    finished = _time(result.get("finished_at"), "window end")
    _require(
        started <= timestamps[0] <= tick_times[0]
        and 0 <= (tick_times[0] - timestamps[0]).total_seconds() <= 15
        and timestamps[0] <= _time(state.get("initial", {}).get("captured_at"),
                                    "initial resident capture")
        and tick_times[-1] <= timestamps[-1] <= finished
        and -5 <= (completed - tick_times[-1]).total_seconds() <= 20,
        "UI observer did not continuously cover the actual resident stop/restore window",
    )
    return {
        "observer_log_sha256": result["ui_observer_log_sha256"],
        "observer_summary_sha256": result["ui_observer_summary_sha256"],
        "profile_sha256": expected_plan_sha,
        "tick_count": last["ticks"], "failed_tick_count": last["failed_ticks"],
        "operational_abort": False,
    }
