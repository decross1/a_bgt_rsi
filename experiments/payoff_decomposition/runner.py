"""Run twelve preregistered payoff questions and retain raw transport evidence."""
from __future__ import annotations

import os
import re
import time
from fractions import Fraction
from pathlib import Path

from bench.flash_next_ab import transport
from experiments.payoff_decomposition import study

NUMBER = r"[+-]?(?:\d+(?:/\d+)?|\d+(?:\.\d+)?)"
ANSWER = re.compile(rf"focal=({NUMBER});sum=({NUMBER})")


def _write_once(path: Path, raw: bytes) -> None:
    with path.open("xb") as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())


def grade(content: str | None, task: dict) -> dict[str, bool]:
    if not isinstance(content, str) or len(content) > 80:
        return {"strict_shape_valid": False, "focal_correct": False,
                "total_correct": False, "both_correct": False}
    match = ANSWER.fullmatch(content.strip())
    if match is None:
        return {"strict_shape_valid": False, "focal_correct": False,
                "total_correct": False, "both_correct": False}
    try:
        focal, total = Fraction(match[1]), Fraction(match[2])
    except (ValueError, ZeroDivisionError, OverflowError):
        return {"strict_shape_valid": False, "focal_correct": False,
                "total_correct": False, "both_correct": False}
    f_ok = focal == Fraction(task["expected_focal"])
    t_ok = total == Fraction(task["expected_total"])
    return {"strict_shape_valid": True, "focal_correct": f_ok,
            "total_correct": t_ok, "both_correct": f_ok and t_ok}


def _safe(safety_check, cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("resident diagnostic canceled")
    safety_check()


def run_study(manifest: dict, *, output: Path, admission_gate, safety_check,
              cancel_event=None, invoke_fn=transport.complete,
              monotonic=time.monotonic) -> dict:
    """Run one finite panel; returned wrong answers stay in the denominator."""
    study.validate_manifest(manifest)
    observed = admission_gate()
    if observed != manifest["registered_admission"]:
        raise ValueError("current resident admission differs from frozen panel")
    endpoint = transport.LocalEndpoint(**manifest["endpoint"])
    endpoint.validate()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    (output / "private").mkdir(mode=0o700)
    _write_once(output / "manifest.json", study.raw_json(manifest) + b"\n")
    started = monotonic()
    deadline = started + study.MAX_WINDOW_S
    rows: list[dict] = []
    failure = None
    status = "complete"
    try:
        for task in manifest["tasks"]:
            _safe(safety_check, cancel_event)
            if monotonic() >= deadline:
                raise TimeoutError("panel cutoff before next registered request")
            ordinal = task["ordinal"]
            seed = manifest["seed_base"] + ordinal // 2
            messages = task["messages"]
            body = transport.request_body(endpoint, messages, manifest["policy"],
                                          manifest["max_tokens"], seed)
            request_sha = study.sha(transport.canonical(body))
            timeout = min(manifest["per_call_timeout_s"], deadline - monotonic())
            before = monotonic()
            response = None
            detail = None
            try:
                response = invoke_fn(endpoint, messages, policy=manifest["policy"],
                                     max_tokens=manifest["max_tokens"], timeout_s=timeout,
                                     seed=seed, cancel_event=cancel_event)
                private = response["private_evidence"]
                call_status = "returned" if response["request_sha256"] == request_sha else "provenance_drift"
                content = response["content"] if call_status == "returned" else None
                if call_status == "provenance_drift":
                    detail = "resolved request hash differs from frozen task"
            except Exception as exc:  # noqa: BLE001 - keep failed calls in denominator
                private = getattr(exc, "private_evidence", None)
                content = None
                call_status = "timeout" if isinstance(exc, TimeoutError) else "error"
                detail = f"{type(exc).__name__}: {exc}"
            raw = private.get("raw_response_stream", b"") if isinstance(private, dict) else b""
            if not isinstance(raw, bytes):
                raise TypeError("transport private SSE is not bytes")
            metadata = dict(private or {})
            metadata.pop("raw_response_stream", None)
            metadata["resolved_request"] = body
            metadata["task_sha256"] = task["task_sha256"]
            metadata["failure_detail"] = detail
            metadata_raw = study.raw_json(metadata) + b"\n"
            _write_once(output / "private" / f"{ordinal:04d}.sse", raw)
            _write_once(output / "private" / f"{ordinal:04d}.json", metadata_raw)
            row = {"ordinal": ordinal, "pair_id": task["pair_id"],
                   "task_sha256": task["task_sha256"], "seat": task["seat"],
                   "view": task["view"], "status": call_status,
                   "seed": seed, "request_sha256": request_sha,
                   "response_stream_sha256": study.sha(raw),
                   "private_stream_bytes": len(raw),
                   "private_metadata_sha256": study.sha(metadata_raw),
                   "private_metadata_bytes": len(metadata_raw),
                   "wall_s": max(0.0, monotonic() - before),
                   "latency_s": response.get("latency_s") if response else None,
                   "ttft_s": response.get("ttft_s") if response else None,
                   "usage": response.get("usage") if response else None,
                   "grade": grade(content, task),
                   "failure_code": (None if call_status == "returned" else
                                    "timeout" if call_status == "timeout" else
                                    "provenance_drift" if call_status == "provenance_drift" else
                                    "transport_or_runtime_error")}
            rows.append(row)
            _write_once(output / f"attempt-{ordinal:02d}.json", study.raw_json(row) + b"\n")
            if call_status == "provenance_drift":
                raise ValueError("payoff request provenance drift")
            _safe(safety_check, cancel_event)
    except Exception as exc:  # noqa: BLE001 - journal cutoff/safety without erasing attempts
        status = "incomplete"
        failure = ("provenance_drift" if "provenance" in str(exc) else
                   "window_cutoff" if isinstance(exc, TimeoutError) else
                   "canceled_or_safety_breach" if isinstance(exc, RuntimeError) else
                   "other_runtime_failure")
    summary = {key: sum(row["grade"][key] for row in rows)
               for key in ("strict_shape_valid", "focal_correct", "total_correct", "both_correct")}
    categories = ("strict_shape_valid", "focal_correct", "total_correct", "both_correct")
    by_view = {view: {"attempted": sum(row["view"] == view for row in rows),
                      "returned": sum(row["view"] == view and row["status"] == "returned"
                                      for row in rows),
                      **{key: sum(row["view"] == view and row["grade"][key] for row in rows)
                         for key in categories}}
               for view in study.VIEWS}
    by_seat = {str(seat): {"attempted": sum(row["seat"] == seat for row in rows),
                           **{key: sum(row["seat"] == seat and row["grade"][key]
                                      for row in rows) for key in categories}}
               for seat in study.SEATS}
    value = {"schema": study.RUN_SCHEMA, "study_id": study.STUDY_ID,
             "panel_id": manifest["panel_id"], "manifest_sha256": manifest["manifest_sha256"],
             "status": status if len(rows) == study.MAX_CALLS else "incomplete",
             "failure_code": failure,
             "scheduled_calls": study.MAX_CALLS, "attempted_calls": len(rows),
             "elapsed_s": max(0.0, monotonic() - started), "summary": summary,
             "by_view": by_view, "by_seat": by_seat,
             "attempts": rows, "comparison_eligible": False,
             "scientific_novelty_claimed": False, "trading_claim_authorized": False}
    if len(rows) < study.MAX_CALLS and value["failure_code"] is None:
        value["failure_code"] = "window_cutoff"
    _write_once(output / "run.json", study.raw_json(value) + b"\n")
    return value
