"""Independent raw-SSE replay of the payoff representation instrument."""
from __future__ import annotations

import math
from pathlib import Path

from bench.flash_next_ab import transport
from experiments.known_opponent_utility import admission as raw_gate
from experiments.payoff_decomposition import runner, study

SCHEMA = "known-opponent-payoff-decomposition-validation/v1"
MAX_MANIFEST_BYTES = 1_000_000
MAX_RUN_BYTES = 1_000_000
MAX_METADATA_BYTES = 128_000
MAX_STREAM_BYTES = 2_000_000


def _must(ok: bool, reason: str) -> None:
    if not ok:
        raise raw_gate.PilotAdmissionError(reason)


def _number(value: object, maximum: float) -> bool:
    return (not isinstance(value, bool) and isinstance(value, int | float)
            and math.isfinite(value) and 0 <= value <= maximum)


def validate_study(output: Path) -> dict:
    """Admit only the exact twelve-call schedule; wrong answers remain measured."""
    manifest_raw = raw_gate._read(output, "manifest.json", MAX_MANIFEST_BYTES)
    manifest = raw_gate._object(manifest_raw)
    _must(manifest_raw == study.raw_json(manifest) + b"\n", "manifest raw bytes drifted")
    study.validate_manifest(manifest)
    run_raw = raw_gate._read(output, "run.json", MAX_RUN_BYTES)
    run = raw_gate._object(run_raw)
    _must(run_raw == study.raw_json(run) + b"\n", "run raw bytes drifted")
    _must(run.get("schema") == study.RUN_SCHEMA
          and run.get("study_id") == study.STUDY_ID
          and run.get("panel_id") == manifest["panel_id"]
          and run.get("manifest_sha256") == manifest["manifest_sha256"]
          and run.get("scheduled_calls") == study.MAX_CALLS
          and type(run.get("attempted_calls")) is int
          and 0 <= run["attempted_calls"] <= study.MAX_CALLS
          and isinstance(run.get("attempts"), list)
          and len(run["attempts"]) == run["attempted_calls"]
          and _number(run.get("elapsed_s"), study.MAX_WINDOW_S + 60)
          and run.get("comparison_eligible") is False
          and run.get("scientific_novelty_claimed") is False
          and run.get("trading_claim_authorized") is False,
          "payoff public run identity or ceiling drifted")
    endpoint = transport.LocalEndpoint(**manifest["endpoint"])
    endpoint.validate()
    replay_counts = {key: 0 for key in (
        "strict_shape_valid", "focal_correct", "total_correct", "both_correct")}
    by_view = {view: {"attempted": 0, "returned": 0,
                      **{key: 0 for key in replay_counts}} for view in study.VIEWS}
    by_seat = {str(seat): {"attempted": 0,
                          **{key: 0 for key in replay_counts}} for seat in study.SEATS}
    returned = 0
    for ordinal, row in enumerate(run["attempts"]):
        task = manifest["tasks"][ordinal]
        seed = manifest["seed_base"] + ordinal // 2
        body = transport.request_body(endpoint, task["messages"], manifest["policy"],
                                      manifest["max_tokens"], seed)
        expected_request = study.sha(transport.canonical(body))
        _must(isinstance(row, dict) and row.get("ordinal") == ordinal
              and row.get("pair_id") == task["pair_id"]
              and row.get("task_sha256") == task["task_sha256"]
              and row.get("seat") == task["seat"]
              and row.get("view") == task["view"]
              and row.get("seed") == seed
              and row.get("request_sha256") == expected_request
              and row.get("status") in {"returned", "timeout", "error", "provenance_drift"}
              and _number(row.get("wall_s"), study.PER_CALL_TIMEOUT_S + 10),
              "attempt differs from its frozen task/request")
        attempt_raw = raw_gate._read(output, f"attempt-{ordinal:02d}.json", MAX_METADATA_BYTES)
        _must(attempt_raw == study.raw_json(row) + b"\n", "attempt journal differs from run")
        stream = raw_gate._read(output, f"private/{ordinal:04d}.sse", MAX_STREAM_BYTES)
        metadata_raw = raw_gate._read(output, f"private/{ordinal:04d}.json", MAX_METADATA_BYTES)
        metadata = raw_gate._object(metadata_raw)
        _must(row.get("response_stream_sha256") == study.sha(stream)
              and row.get("private_stream_bytes") == len(stream)
              and row.get("private_metadata_sha256") == study.sha(metadata_raw)
              and row.get("private_metadata_bytes") == len(metadata_raw)
              and metadata.get("resolved_request") == body
              and metadata.get("task_sha256") == task["task_sha256"]
              and metadata.get("response_stream_sha256", study.sha(stream)) == study.sha(stream),
              "private stream/metadata/request differs from public receipt")
        if row["status"] == "returned":
            replay = raw_gate._returned_sse(stream, endpoint.served_model)
            for field in ("content", "reasoning_content", "tool_calls", "response_id",
                          "response_model", "finish_reason", "usage", "stream_events"):
                _must(metadata.get(field) == replay[field],
                      f"returned {field} differs from raw SSE")
            _must(row.get("usage") == replay["usage"]
                  and row.get("failure_code") is None
                  and _number(row.get("latency_s"), study.PER_CALL_TIMEOUT_S + 10)
                  and (row.get("ttft_s") is None or
                       (_number(row["ttft_s"], study.PER_CALL_TIMEOUT_S + 10)
                        and row["ttft_s"] <= row["latency_s"])),
                  "public returned usage/timing differs from replay")
            observed_grade = runner.grade(replay["content"], task)
            returned += 1
        else:
            _must(row.get("failure_code") == {
                "timeout": "timeout", "error": "transport_or_runtime_error",
                "provenance_drift": "provenance_drift"}[row["status"]],
                "failed attempt's public status/code mapping drifted")
            observed_grade = runner.grade(None, task)
        _must(row.get("grade") == observed_grade,
              "public rational grade differs from private returned content")
        by_view[task["view"]]["attempted"] += 1
        by_view[task["view"]]["returned"] += row["status"] == "returned"
        by_seat[str(task["seat"])]["attempted"] += 1
        for key in replay_counts:
            replay_counts[key] += observed_grade[key]
            by_view[task["view"]][key] += observed_grade[key]
            by_seat[str(task["seat"])][key] += observed_grade[key]
    _must(run.get("summary") == replay_counts
          and run.get("by_view") == by_view
          and run.get("by_seat") == by_seat,
          "summary/view/seat denominators differ from private replay")
    full = len(run["attempts"]) == study.MAX_CALLS
    if full:
        _must(run.get("status") == "complete" and run.get("failure_code") is None,
              "complete twelve-call panel carried an abort marker")
    else:
        _must(run.get("status") == "incomplete"
              and run.get("failure_code") in {
                  "provenance_drift", "window_cutoff", "canceled_or_safety_breach",
                  "other_runtime_failure"},
              "partial panel was falsely marked complete")
    return {"schema": SCHEMA, "status": "admitted_diagnostic" if full else "partial_observed",
            "admission_eligible": full, "study_id": study.STUDY_ID,
            "panel_id": manifest["panel_id"],
            "manifest_sha256": manifest["manifest_sha256"],
            "run_sha256": study.sha(run_raw), "scheduled_calls": study.MAX_CALLS,
            "attempted_calls": len(run["attempts"]), "returned_sse_verified": returned,
            "summary": replay_counts, "by_view": by_view, "by_seat": by_seat,
            "comparison_eligible": False,
            "scientific_novelty_claimed": False, "private_content_exported": False}
