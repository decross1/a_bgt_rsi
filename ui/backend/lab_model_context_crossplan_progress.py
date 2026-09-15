"""Content-free view of one independently admitted Qwen/Flash context study."""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
    "lab-eight-hour/context-crossplan-qwen-mia"
)
PUBLICATION_ID = "qfn-context-qwen-mia-20260915-a"
SCHEMA = "lab-context-crossplan-progress/v1"
REPORT_SCHEMA = "lab-context-crossplan-matched24-report/v1"
GRADE_REPLAY = "private_sse_and_all_24_qwen_all_36_mia_objective_grades"
FLASH_VARIANT = "mia-925d7be6-mtp3-reduced47k-v2opt-v1"
PACK_SHA = "4a6203e9c28ff8f7b74ec21b4d530aceb1430172a049a57912a386f3626b49f9"
SHA = re.compile(r"[0-9a-f]{64}\Z")


def _whole(value: object, *, ceiling: int) -> int:
    if type(value) is not int or not 0 <= value <= ceiling:
        raise ValueError("context count outside registered denominator")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise ValueError("context source digest differs")
    return value


def _lane(value: object, *, capacity: int) -> dict:
    if not isinstance(value, dict):
        raise TypeError("matched context lane missing")
    counts = {
        name: _whole(value.get(name), ceiling=12)
        for name in ("declared", "attempted", "passed", "returned", "timeout",
                     "error", "cancelled")
    }
    prompt = value.get("measured_prompt_tokens_max")
    if prompt is not None:
        prompt = _whole(prompt, ceiling=capacity - 2048)
    elapsed = value.get("wall_s_including_failures")
    if (type(elapsed) not in (int, float) or not math.isfinite(elapsed)
            or not 0 <= elapsed <= 3000
            or counts["declared"] != 12 or counts["attempted"] != 12
            or counts["passed"] > counts["returned"]
            or sum(counts[name] for name in ("returned", "timeout", "error", "cancelled")) != 12
            or value.get("observed_2048_output_reserve_within_total_band")
            is not (True if prompt is not None else None)):
        raise ValueError("matched context lane counts or reserve differ")
    return {
        "declared": 12, "attempted": 12,
        "passed": counts["passed"], "returned": counts["returned"],
        "timeout": counts["timeout"], "error": counts["error"],
        "cancelled": counts["cancelled"],
        "measured_prompt_tokens_max": prompt,
    }


def _categories(value: object, *, qwen_passed: int, flash_passed: int) -> dict:
    if not isinstance(value, dict) or set(value) != {
            "qwen_only", "mia_only", "both_pass", "neither_pass"}:
        raise ValueError("matched pass categories differ")
    shown = {name: _whole(value[name], ceiling=12) for name in value}
    if (sum(shown.values()) != 12
            or shown["qwen_only"] + shown["both_pass"] != qwen_passed
            or shown["mia_only"] + shown["both_pass"] != flash_passed):
        raise ValueError("matched pass counts disagree with both arms")
    return shown


def _project_report(report: dict) -> dict:
    if (not isinstance(report, dict)
            or report.get("schema_version") != REPORT_SCHEMA
            or report.get("publication_id") != PUBLICATION_ID
            or report.get("status") != "complete_cross_plan_diagnostic"
            or report.get("comparison_kind") !=
            "cross_plan_matched24_development_diagnostic"
            or report.get("matched_cells") != 24
            or report.get("capacities_total_tokens") != [8192, 16384]
            or report.get("output_reserve_tokens") != 2048
            or report.get("grade_replay") != GRADE_REPLAY
            or report.get("packet_raw_sha256") != PACK_SHA
            or report.get("qwen_window_id") != "qfn-ab-lab-context-qwen-20260915-a"
            or report.get("mia_window_id") != "qfn-ab-lab-context-20260915-a"
            or report.get("same_plan_pair") is not False
            or report.get("qwen_plan_flash_arm_issued_for_this_comparison") is not False
            or report.get("private_response_exported") is not False
            or report.get("heldout_claim") is not False
            or report.get("promotion_authorized") is not False):
        raise ValueError("cross-plan publication identity or claim differs")
    for name in ("qwen_plan_raw_sha256", "mia_plan_raw_sha256",
                 "overlap_receipts_sha256"):
        _digest(report.get(name))
    identities = report.get("arm_identities")
    if not isinstance(identities, dict) or set(identities) != {
            "resident_qwen", "flash_next_mia"}:
        raise ValueError("cross-plan arm inventory differs")
    expected = {
        "resident_qwen": ("resident-qwen", "qwen3.8-27b-nvfp4-mtp", 16384),
        "flash_next_mia": (FLASH_VARIANT, "qwen3.8-flash-next-mia", 32768),
    }
    for route, (variant, served, configured) in expected.items():
        arm = identities[route]
        if (not isinstance(arm, dict)
                or arm.get("candidate_variant_id") != variant
                or arm.get("served_model") != served
                or arm.get("configured_max_context_tokens") != configured):
            raise ValueError("cross-plan route or configured context differs")
        _digest(arm.get("artifact_sha256"))
        _digest(arm.get("runtime_sha256"))
    rows = report.get("by_capacity")
    if not isinstance(rows, dict) or set(rows) != {"8192", "16384"}:
        raise ValueError("matched capacity inventory differs")
    shown = {}
    for band in ("8192", "16384"):
        row = rows[band]
        if not isinstance(row, dict) or set(row) != {
                "resident_qwen", "flash_next_mia", "matched_cell_pass_categories"}:
            raise ValueError("matched route inventory differs")
        qwen = _lane(row["resident_qwen"], capacity=int(band))
        flash = _lane(row["flash_next_mia"], capacity=int(band))
        shown[band] = {
            "resident_qwen": qwen,
            "flash_next_mia": flash,
            "matched_cell_pass_categories": _categories(
                row["matched_cell_pass_categories"],
                qwen_passed=qwen["passed"], flash_passed=flash["passed"],
            ),
        }
    return {
        "qwen_window_id": report["qwen_window_id"],
        "mia_window_id": report["mia_window_id"],
        "overlap_receipts_sha256": report["overlap_receipts_sha256"],
        "configured_total_tokens": {
            "resident_qwen": 16384, "flash_next_mia": 32768,
        },
        "by_capacity": shown,
    }


def project_progress(*, publication_reader: Callable[[Path], dict] | None = None,
                     publication_root: Path = ROOT) -> dict:
    """Use the strict reader only after the one registered final index exists."""
    from . import model_runtime as mr

    entry = {
        "schema_version": SCHEMA,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "publication_id": PUBLICATION_ID,
        "status": "pending_publication",
        "matched_cells": 24,
        "publication_index_raw_sha256": None,
        "grade_replay": "not_available",
        "same_plan_pair": False,
        "by_capacity": None,
        "configured_total_tokens": None,
        "promotion_authorized": False,
        "private_content_exported": False,
    }
    index = publication_root / PUBLICATION_ID / "index.json"
    if index.exists() or index.is_symlink():
        entry["status"] = "source_unavailable"
        try:
            raw = mr._read_path(
                index, maximum=128_000, label="Qwen cross-plan publication index",
            )
            reader = publication_reader
            if reader is None:
                from bench.flash_next_ab.lab_eval_context_crossplan import (
                    read_publication,
                )

                reader = read_publication
            shown = _project_report(reader(index))
            entry.update(
                status="complete_cross_plan_diagnostic",
                publication_index_raw_sha256=hashlib.sha256(raw).hexdigest(),
                grade_replay=GRADE_REPLAY,
                **shown,
            )
        except (ImportError, OSError, RuntimeError, TypeError, ValueError, KeyError):
            pass
    return entry


def register(app, *, projector: Callable[[], dict] = project_progress) -> None:
    router = APIRouter()

    @router.get("/api/lab_model_context_crossplan_progress")
    def lab_model_context_crossplan_progress():
        return projector()

    app.include_router(router)
