"""Content-free paper-trial projection. No source text, quote values or order UI."""

from __future__ import annotations

import hashlib
import json

from .trial_contract import RESULT_SCHEMA, TrialError, canonical_sha256, sha256

PROJECTION_SCHEMA = "applied-trial-paper-projection/v1"


def project(manifest: dict, result: dict, ledger: list[dict]) -> dict:
    if result.get("schema") != RESULT_SCHEMA or result.get("trial_id") != manifest.get("trial_id"):
        raise TrialError("result is not the same registered trial")
    if result.get("manifest_canonical_sha256") != canonical_sha256(manifest):
        raise TrialError("result does not bind the full canonical manifest")
    if result.get("scheduled_cells") != len(ledger) or len({row.get("cell_id") for row in ledger}) != len(ledger):
        raise TrialError("paper ledger is incomplete or has duplicate cells")
    if any(row.get("trial_id") != result["trial_id"] or row.get("manifest_sha256") != result["manifest_sha256"] for row in ledger):
        raise TrialError("paper ledger cross-trial donation")
    ledger_data = b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        for row in ledger
    )
    if result.get("paper_ledger_sha256") != sha256(ledger_data):
        raise TrialError("paper ledger bytes are not bound by result")
    if result.get("paper_only") is not True or result.get("promotion_to_science_or_live_orders") is not False:
        raise TrialError("projection may display paper evidence only")
    if result.get("disposition") not in {"not_tested", "invalid", "negative", "paper_supported", "needs_replication"}:
        raise TrialError("application disposition is outside the closed set")
    if result["disposition"] == "paper_supported":
        # Strings inside a self-consistent result are not an external proof.
        # Production must add a separate, hash-bound capture/placebo source
        # validator before the UI can display this positive disposition.
        raise TrialError("paper_supported external admission is not integrated")
    # The UI consumer should use its own safely-read result/manifest/ledger source
    # snapshot; this pure function validates the essential identity joins.
    return {
        "schema": PROJECTION_SCHEMA,
        "trial_id": result["trial_id"],
        "trial_type": "spot_liquidity_state",
        "paper_only": True,
        "prior_classification": manifest["prior"]["classification"],
        "source_campaign_link": None,
        "manifest_sha256": result["manifest_sha256"],
        "manifest_canonical_sha256": result["manifest_canonical_sha256"],
        "result_sha256": hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        "paper_ledger_sha256": result["paper_ledger_sha256"],
        "source_id": result["registered_source_id"],
        "venue": result["registered_venue"],
        "forward_start": result["forward_start"],
        "forward_end": result["forward_end"],
        "run_status": result["run_status"],
        "disposition": result["disposition"],
        "scheduled_cells": result["scheduled_cells"],
        "valid_days": result["valid_days"],
        "fillable_candidate_days": result["fillable_candidate_days"],
        "candidate_paper_fills": result["candidate"]["paper_fills"],
        "baseline_paper_fills": result["equal_hold_exposure_baseline"]["paper_fills"],
        "candidate_net_bps_per_schedule": result["candidate"]["paper_net_bps_per_schedule"],
        "baseline_net_bps_per_schedule": result["equal_hold_exposure_baseline"]["paper_net_bps_per_schedule"],
        "candidate_doubled_cost_net_bps_per_schedule": result["candidate"]["paper_net_doubled_cost_bps_per_schedule"],
        "operational_gate": result["operational_gate"],
        "economic_gate": result["economic_gate"],
        "capture_admission": result["capture_admission"],
        "placebo_admission": result["placebo_admission"],
        "live_order_action_available": False,
    }
