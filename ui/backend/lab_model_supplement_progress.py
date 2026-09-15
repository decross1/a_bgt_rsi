"""Narrow API view of independently admitted fresh and context lab pairs."""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
            "lab-eight-hour/evaluation-supplement-pairs")
SCHEMA = "lab-model-supplement-progress/v1"
REPORT_SCHEMA = "lab-model-supplement-paired-report/v1"
SHA = re.compile(r"[0-9a-f]{64}\Z")
KINDS = {
    "fresh": {
        "pair_id": "qfn-ab-lab-fresh-20260915-a", "denominator": 12,
        "grade_replay": "raw_sse_and_all_12_fresh_primary_grades_per_cohort",
        "claim_limit": "NEW_SYNTHETIC_DEVELOPMENT_CANARIES_NOT_TRADING_EVIDENCE",
        "suite_id": "lab-fresh-game-and-one-file-repair-development-20260915-v1",
        "cell_set": "new_six_finite_games_six_one_file_repairs",
        "variant_resident": "resident-role-bundle",
    },
    "context": {
        "pair_id": "qfn-ab-lab-context-20260915-a", "denominator": 36,
        "grade_replay": "raw_sse_and_all_36_context_objective_grades_per_cohort",
        "claim_limit": "PUBLIC_DEVELOPMENT_CONTEXT_DIAGNOSTIC_NOT_HELDOUT",
        "suite_id": "lab-matched-total-context-public-development-20260915-v1",
        "cell_set": "public_four_evidence_tasks_three_positions",
        "variant_resident": "resident-gemma",
    },
}
FLASH_VARIANT = "mia-925d7be6-mtp3-reduced47k-v2opt-v1"
FIELDS = ("declared", "attempted", "returned", "timeout", "error",
          "cancelled", "passed", "wall_s_including_failures")


def _count(value: object, ceiling: int) -> int:
    if type(value) is not int or not 0 <= value <= ceiling:
        raise ValueError("supplement count outside registered denominator")
    return value


def _seconds(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100_000:
        raise ValueError("supplement time outside registered bound")
    return float(value)


def _score(value: object, declared: int) -> dict:
    if not isinstance(value, dict):
        raise TypeError("supplement score missing")
    shown = {key: _seconds(value.get(key)) if key == "wall_s_including_failures"
             else _count(value.get(key), declared) for key in FIELDS}
    if (shown["declared"] != declared or shown["attempted"] != declared
            or shown["passed"] > shown["returned"]
            or sum(shown[key] for key in ("returned", "timeout", "error", "cancelled"))
            != shown["attempted"]):
        raise ValueError("supplement score denominator differs")
    return shown


def _measured_tokens(value: object, *, ceiling: int = 131_072) -> int | None:
    return None if value is None else _count(value, ceiling)


def _endpoint_tokens(value: object, *, measured: bool) -> dict[str, int | None]:
    if not isinstance(value, dict) or not 1 <= len(value) <= 3 or not set(value) <= {
            "resident_qwen", "resident_gemma", "flash_next_mia"}:
        raise ValueError("supplement endpoint context inventory differs")
    return {route: _measured_tokens(tokens) if measured else _count(tokens, 131_072)
            for route, tokens in value.items()}


def _group(value: object, names: tuple[str, ...], declared: int,
           total: dict) -> dict:
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError("supplement group inventory differs")
    shown = {name: _score(value[name], declared) for name in names}
    for key in FIELDS[:-1]:
        if sum(row[key] for row in shown.values()) != total[key]:
            raise ValueError("supplement group count does not match total")
    return shown


def _cohort(value: object, *, kind: str, cohort: str, denominator: int) -> dict:
    if (not isinstance(value, dict) or value.get("status") != "complete"
            or value.get("variant_id") != (
                FLASH_VARIANT if cohort == "flash" else KINDS[kind]["variant_resident"])
            or value.get("raw_response_replay_passed") is not True):
        raise ValueError("supplement cohort admission differs")
    scores = value.get("scores")
    if not isinstance(scores, dict):
        raise TypeError("supplement scores missing")
    total = _score(scores.get("total"), denominator)
    shown = {"variant_id": value["variant_id"], "elapsed_s": _seconds(value.get("elapsed_s")),
             "scores": {"total": total}}
    if kind == "fresh":
        shown["scores"]["by_kind"] = _group(scores.get("by_kind"),
                                           ("science", "coding"), 6, total)
        configured = _endpoint_tokens(value.get("configured_context_tokens_by_endpoint"),
                                      measured=False)
        measured = _endpoint_tokens(value.get("measured_prompt_tokens_max_by_endpoint"),
                                    measured=True)
        if set(configured) != set(measured) or any(
                tokens is not None and tokens > configured[route]
                for route, tokens in measured.items()):
            raise ValueError("fresh observed context exceeds declared route")
        diagnostic = value.get("normalization_diagnostic")
        if (not isinstance(diagnostic, dict)
                or diagnostic.get("never_replaces_primary_score") is not True
                or not 0 <= _count(diagnostic.get("coding_returned_attempted"), 6)
                or _count(diagnostic.get("sandbox_passes_after_predeclared_transform"), 6)
                > diagnostic["coding_returned_attempted"]):
            raise ValueError("fresh normalization diagnostic differs")
        shown.update(configured_context_tokens_by_endpoint=configured,
                     measured_prompt_tokens_max_by_endpoint=measured,
                     normalization_diagnostic={
                         "coding_returned_attempted": diagnostic["coding_returned_attempted"],
                         "sandbox_passes_after_predeclared_transform":
                             diagnostic["sandbox_passes_after_predeclared_transform"],
                         "never_replaces_primary_score": True})
    else:
        capacities = ("8192", "16384", "32768")
        placements = ("early", "middle", "late")
        by_capacity = _group(scores.get("by_capacity"), capacities, 12, total)
        by_placement = _group(scores.get("by_placement"), placements, 12, total)
        grid = scores.get("by_capacity_placement")
        if not isinstance(grid, dict) or set(grid) != set(capacities):
            raise ValueError("context capacity-placement grid differs")
        shown_grid = {cap: _group(grid[cap], placements, 4, by_capacity[cap])
                      for cap in capacities}
        for placement in placements:
            if any(sum(shown_grid[cap][placement][key] for cap in capacities)
                   != by_placement[placement][key] for key in FIELDS[:-1]):
                raise ValueError("context placement grid differs")
        observed_by_capacity = scores.get("measured_prompt_tokens_max_by_capacity")
        if not isinstance(observed_by_capacity, dict) or set(observed_by_capacity) != set(capacities):
            raise ValueError("context observed capacity inventory differs")
        maxima = {cap: _measured_tokens(observed_by_capacity[cap])
                  for cap in capacities}
        configured = _count(value.get("configured_context_tokens"), 131_072)
        observed = _measured_tokens(value.get("measured_prompt_tokens_max"))
        if (configured != 32_768 or value.get("output_reserve_tokens") != 2048
                or observed is not None and observed > configured
                or any(tokens is not None and tokens > int(cap)
                       for cap, tokens in maxima.items())):
            raise ValueError("context configured and measured ceilings differ")
        shown["scores"].update(by_capacity=by_capacity, by_placement=by_placement,
                               by_capacity_placement=shown_grid,
                               measured_prompt_tokens_max_by_capacity=maxima)
        shown.update(configured_context_tokens=configured,
                     measured_prompt_tokens_max=observed,
                     output_reserve_tokens=2048)
    return shown


def _project_report(report: dict, *, kind: str) -> dict:
    registered = KINDS[kind]
    if (report.get("schema_version") != REPORT_SCHEMA or report.get("kind") != kind
            or report.get("pair_id") != registered["pair_id"]
            or report.get("status") != "complete_admitted_pair"
            or report.get("denominator_per_cohort") != registered["denominator"]
            or report.get("claim_limit") != registered["claim_limit"]
            or report.get("suite_id") != registered["suite_id"]
            or report.get("cell_set") != registered["cell_set"]
            or not SHA.fullmatch(str(report.get("plan_raw_sha256", "")))
            or report.get("original_scores_rebased") is not False
            or report.get("heldout_claim") is not False
            or report.get("private_content_exported") is not False
            or report.get("promotion_authorized") is not False
            or not isinstance(report.get("cohorts"), dict)
            or set(report["cohorts"]) != {"resident", "flash"}):
        raise ValueError("supplement report identity or claim differs")
    return {"plan_raw_sha256": report["plan_raw_sha256"],
            "suite_id": report["suite_id"], "cell_set": report["cell_set"],
            "cohorts": {
                cohort: _cohort(report["cohorts"][cohort], kind=kind, cohort=cohort,
                                denominator=registered["denominator"])
                for cohort in ("resident", "flash")}}


def project_progress(*, publication_reader: Callable[[Path], dict] | None = None,
                     publication_root: Path = ROOT) -> dict:
    """Only a final source-admitted index may supply numeric supplement counts."""
    from . import model_runtime as mr

    observed = datetime.now(timezone.utc).isoformat()
    pairs = {}
    for kind, registered in KINDS.items():
        pair_id = registered["pair_id"]
        entry = {"kind": kind, "pair_id": pair_id,
                 "status": "pending_publication", "denominator_per_cohort":
                     registered["denominator"], "plan_raw_sha256": None,
                 "publication_index_raw_sha256": None, "cohorts": None,
                 "grade_replay": "not_available", "promotion_authorized": False}
        index = publication_root / pair_id / "index.json"
        if index.exists() or index.is_symlink():
            entry["status"] = "source_unavailable"
            try:
                raw = mr._read_path(index, maximum=128_000,
                                    label="lab supplement publication index")
                index_sha = hashlib.sha256(raw).hexdigest()
                reader = publication_reader
                if reader is None:
                    from bench.flash_next_ab.lab_eval_supplement_report import (
                        read_publication,
                    )
                    reader = read_publication
                report = reader(index)
                projected = _project_report(report, kind=kind)
                entry.update(status="complete_admitted_pair",
                             publication_index_raw_sha256=index_sha,
                             grade_replay=registered["grade_replay"], **projected)
            except (ImportError, OSError, RuntimeError, TypeError, ValueError, KeyError):
                pass
        pairs[kind] = entry
    return {"schema_version": SCHEMA, "observed_at": observed, "pairs": pairs,
            "original_scores_rebased": False, "private_content_exported": False,
            "promotion_authorized": False}


def register(app, *, projector: Callable[[], dict] = project_progress) -> None:
    router = APIRouter()

    @router.get("/api/lab_model_supplement_progress")
    def lab_model_supplement_progress():
        return projector()

    app.include_router(router)
