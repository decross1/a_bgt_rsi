"""Read-only recent public market-data collection; no strategy or order execution."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

DEFAULT_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/captures"
)
SCHEMA = "applied-market-research-progress/v1"
BATCH_NAME = re.compile(r"spot-(?:BTCUSDT|ETHUSDT)-[0-9]{8}T[0-9]{6}Z(?:-[a-z0-9]{1,12})?\Z")
# More than one month of five-minute primary-symbol batches, still bounded.
MAX_DIRECTORY_ENTRIES = 16_384
MAX_RECENT_BATCHES = 8
PUBLIC_FIELDS = frozenset({
    "schema", "stage", "source_id", "symbol", "status", "started_at", "sealed_at",
    "batch_sha256", "collector_source_sha256", "collector_source_verified", "collector_source_status",
    "attempt_count", "requests_attempted", "requests_succeeded", "requests_failed",
    "requests_unjournaled", "attempt_denominator_verified", "source_valid_frames",
    "raw_bytes", "has_depth_snapshot", "trade_pages", "cursor_gap", "page_gap",
    "backlog_unresolved", "depth_venue_event_time", "historical_executable_l2_proven",
    "study_preregistered", "paper_result", "orders_placed",
})


def project_market_research(root: Path = DEFAULT_ROOT) -> dict:
    result = {
        "schema_version": SCHEMA,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "not_started", "research_focus": "Hourly liquidity and signed-flow application",
        "evidence_scope": "Recent source collection, not a strategy performance claim",
        "paper_result": "not_tested", "orders_placed": 0,
        "scan_complete": True, "max_recent_batches": MAX_RECENT_BATCHES,
        "batches": [], "warnings": [],
        "stages": [
            {"id": "capture", "label": "Public data", "status": "not_recorded"},
            {"id": "features", "label": "As-of features", "status": "not_recorded"},
            {"id": "matched_test", "label": "Matched test", "status": "not_recorded"},
            {"id": "forward_paper", "label": "Forward paper outcomes", "status": "not_recorded"},
        ],
    }
    if root.is_symlink() or root.exists() and (not root.is_dir() or root.resolve() != root.absolute()):
        result.update(status="unavailable", scan_complete=False)
        result["warnings"].append("Registered data directory is unavailable or redirected.")
        return result
    if not root.exists():
        return result
    from bench.applied_trading.collection_projection import project_known_collection
    names = []
    try:
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_DIRECTORY_ENTRIES:
                    result["scan_complete"] = False
                    break
                if BATCH_NAME.fullmatch(entry.name) and entry.is_dir(follow_symlinks=False):
                    names.append(entry.name)
        for name in sorted(names, reverse=True)[:MAX_RECENT_BATCHES]:
            try:
                row = project_known_collection(root / name)
                current = row.get("collector_source_status") == "current_verified" and row.get("collector_source_verified") is True
                historical = row.get("collector_source_status") == "historical_source_unavailable" and row.get("collector_source_verified") is False
                if not (current or historical):
                    raise ValueError("source verifier did not classify collector")
                result["batches"].append({"id": name, **{
                    key: value for key, value in row.items() if key in PUBLIC_FIELDS
                }})
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                result["batches"].append({"id": name, "status": "invalid_receipt"})
                result["warnings"].append(f"Collection {name} did not pass source verification.")
    except OSError:
        result.update(status="unavailable", scan_complete=False)
        result["warnings"].append("Registered data directory could not be read.")
        return result
    rows = result["batches"]
    valid = [row for row in rows if row.get("collector_source_verified") is True]
    if rows:
        result["status"] = ("data_recorded" if any(row.get("source_valid_frames", 0) > 0 for row in valid)
                            else "attempts_recorded" if valid else "unavailable")
    if valid:
        result["stages"][0]["status"] = "recorded"
    if not result["scan_complete"]:
        result["warnings"].append("Directory scan reached its bound; recent coverage is incomplete.")
    return result


def register(app, *, root: Path = DEFAULT_ROOT) -> None:
    router = APIRouter()

    @router.get("/api/applied_data_collection")
    def applied_data_collection():
        return project_market_research(root)

    app.include_router(router)
