"""Bounded public projection for the benchmark-program API.

This module never reads raw responses and never performs replay.  Scores are
projected only when a supplied admission receipt cryptographically binds the
same run and replay receipts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from .admission import ADMISSION_SCHEMA
from .manifest import LoadedDocument, validate_definition
from .replay import REPLAY_SCHEMA
from .runner import CELL_STATUSES, RUN_SCHEMA


Receipt = tuple[dict[str, Any], str]
NON_ADMISSIBLE_CELL_STATUSES = {"invalid", "skipped_budget", "unissued"}


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _index(records: Iterable[Receipt], schema: str, join_key: str) -> dict[str, Receipt]:
    result: dict[str, Receipt] = {}
    for document, digest in records:
        if not isinstance(document, dict) or document.get("schema_version") != schema or not _valid_digest(digest):
            continue
        key = document.get(join_key)
        if _valid_digest(key):
            if key in result:
                raise ValueError(f"duplicate conflicting {schema} receipt for {join_key}={key}")
            result[key] = (document, digest)
    return result


def _fraction(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
        return None
    numerator, denominator = value["numerator"], value["denominator"]
    if (
        isinstance(numerator, bool) or not isinstance(numerator, int)
        or isinstance(denominator, bool) or not isinstance(denominator, int)
        or denominator <= 0 or abs(numerator) > 10**15 or denominator > 10**15
    ):
        return None
    return {"numerator": numerator, "denominator": denominator}


def _safe_metrics(task: dict[str, Any], value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    if task["domain"] == "strategic_behavior":
        required = {
            "mechanism", "own_utility", "joint_utility", "best_response_utility",
            "own_utility_regret", "valid_action",
        }
        allowed = required | {"joint_utility_interpretation"}
        fields = set(value)
        if (fields != required and fields != allowed) or value.get("mechanism") != task["construct"]:
            return {}
        result: dict[str, Any] = {"mechanism": value["mechanism"]}
        for key in ("own_utility", "joint_utility", "best_response_utility", "own_utility_regret"):
            fraction = _fraction(value.get(key))
            if fraction is None:
                return {}
            result[key] = fraction
        if not isinstance(value.get("valid_action"), bool):
            return {}
        result["valid_action"] = value["valid_action"]
        if "joint_utility_interpretation" in value:
            if value["joint_utility_interpretation"] != "descriptive_only":
                return {}
            result["joint_utility_interpretation"] = "descriptive_only"
        return result
    if task["construct"] in {"evidence_abstention", "evidence_attribution"} and set(value) == {
        "abstention_expected", "abstention_correct"
    } and all(isinstance(value[key], bool) for key in value):
        return dict(value)
    return {}


def _bounded_text(value: Any, *, limit: int = 160) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def _exact_task_rows(rows: Any, task_ids: list[str]) -> bool:
    return (
        isinstance(rows, list)
        and len(rows) == len(task_ids)
        and [row.get("task_id") for row in rows if isinstance(row, dict)] == task_ids
        and len({row.get("task_id") for row in rows if isinstance(row, dict)}) == len(task_ids)
    )


def _valid_outcomes(
    rows: Any,
    tasks: dict[str, dict[str, Any]],
    task_ids: list[str],
    *,
    replay: bool,
) -> bool:
    if not _exact_task_rows(rows, task_ids):
        return False
    for row in rows:
        task = tasks[row["task_id"]]
        calls = row.get("model_calls")
        status = row.get("cell_status")
        if (
            status not in CELL_STATUSES
            or status in NON_ADMISSIBLE_CELL_STATUSES
            or isinstance(calls, bool)
            or not isinstance(calls, int)
            or calls < 0
            or calls > task["resource"]["max_model_calls"]
            or row.get("model_calls_exact") is not True
            or not isinstance(row.get("score_credit"), bool)
            or (replay and row.get("verified") is not True)
        ):
            return False
        metrics = row.get("metrics")
        safe_metrics = _safe_metrics(task, metrics)
        if metrics not in ({}, safe_metrics):
            return False
    return True


def _same_outcomes(run_rows: list[dict[str, Any]], replay_rows: list[dict[str, Any]]) -> bool:
    fields = (
        "task_id", "cell_status", "score_credit", "failure_code", "model_calls",
        "model_calls_exact", "metrics", "raw_evidence_sha256",
    )
    return all(
        all(left.get(key) == right.get(key) for key in fields)
        for left, right in zip(run_rows, replay_rows)
    )


def _admitted_summary(
    replay: dict[str, Any], tasks: dict[str, dict[str, Any]], task_ids: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    outcomes = replay.get("outcomes")
    if not _exact_task_rows(outcomes, task_ids):
        return {"error": "replay_outcomes_invalid"}, []
    statuses: Counter[str] = Counter()
    families: dict[str, dict[str, int]] = {
        name: {"planned": 0, "credited": 0}
        for name in (
            "science_evidence", "functional_code_repair",
            "deterministic_tool_use", "system_harness",
        )
    }
    strategic: dict[str, dict[str, int]] = {
        name: {"planned": 0, "credited": 0}
        for name in (
            "public_goods", "vickrey_auction", "cournot", "proper_scoring_reporting",
        )
    }
    task_rows: list[dict[str, Any]] = []
    for row in outcomes:
        if not isinstance(row, dict) or not isinstance(row.get("task_id"), str):
            return {"error": "replay_outcomes_invalid"}, []
        status = row.get("cell_status")
        calls = row.get("model_calls")
        if (
            status not in CELL_STATUSES
            or isinstance(calls, bool)
            or not isinstance(calls, int)
            or calls < 0
            or calls > tasks[row["task_id"]]["resource"]["max_model_calls"]
            or row.get("model_calls_exact") is not True
            or not isinstance(row.get("score_credit"), bool)
        ):
            return {"error": "replay_outcomes_invalid"}, []
        statuses[str(status)] += 1
        task = tasks[row["task_id"]]
        target = (
            strategic[task["construct"]]
            if task["domain"] == "strategic_behavior"
            else families[task["domain"]]
        )
        target["planned"] += 1
        target["credited"] += int(row.get("score_credit") is True)
        task_rows.append({
            "task_id": row["task_id"],
            "cell_status": status,
            "score_credit": row.get("score_credit") is True,
            "model_calls": calls,
            "model_calls_exact": True,
            "metrics": _safe_metrics(tasks[row["task_id"]], row.get("metrics")),
        })
    return {
        "independent_units": len(task_rows),
        "status_counts": dict(sorted(statuses.items())),
        "descriptive_family_counts": families,
        "strategic_mechanism_counts": strategic,
        "omnibus_score": None,
    }, task_rows


def program_projection(
    definition: LoadedDocument,
    *,
    run_receipts: Iterable[Receipt] = (),
    replay_receipts: Iterable[Receipt] = (),
    admission_receipts: Iterable[Receipt] = (),
) -> dict[str, Any]:
    """Return a prompt-free, grader-free, raw-free program summary."""
    validate_definition(definition.document)
    document = definition.document
    replay_by_run = _index(replay_receipts, REPLAY_SCHEMA, "run_receipt_sha256")
    admission_by_run = _index(admission_receipts, ADMISSION_SCHEMA, "run_receipt_sha256")
    tasks = {task["id"]: task for task in document["tasks"]}
    task_ids = list(tasks)
    runs: list[dict[str, Any]] = []
    seen_run_digests: set[str] = set()
    for run, run_sha in list(run_receipts)[:32]:
        if not isinstance(run, dict) or run.get("schema_version") != RUN_SCHEMA or not _valid_digest(run_sha):
            continue
        if run_sha in seen_run_digests:
            raise ValueError(f"duplicate run receipt {run_sha}")
        seen_run_digests.add(run_sha)
        replay_pair = replay_by_run.get(run_sha)
        admission_pair = admission_by_run.get(run_sha)
        verified = False
        admission_status = "not_evaluated"
        summary: dict[str, Any] | None = None
        task_rows: list[dict[str, Any]] = []
        replay_sha = None
        run_rows = run.get("outcomes")
        run_rows_valid = _valid_outcomes(run_rows, tasks, task_ids, replay=False)
        if replay_pair is not None:
            replay, replay_sha = replay_pair
            replay_rows = replay.get("outcomes")
            verified = (
                replay.get("verified") is True
                and replay.get("terminal_status") == "verified"
                and replay.get("definition_sha256") == definition.raw_sha256
                and replay.get("run_manifest_sha256") == run.get("run_manifest_sha256")
                and replay.get("arm_id") == run.get("arm_id")
                and replay.get("comparison_id") == run.get("comparison_id")
                and replay.get("mismatches") == []
                and _valid_outcomes(replay_rows, tasks, task_ids, replay=True)
                and run_rows_valid
                and _same_outcomes(run_rows, replay_rows)
            )
        if admission_pair is not None:
            admission, _admission_sha = admission_pair
            hashes_match = (
                admission.get("run_receipt_sha256") == run_sha
                and replay_sha is not None
                and admission.get("replay_receipt_sha256") == replay_sha
                and admission.get("definition_sha256") == definition.raw_sha256
                and admission.get("run_manifest_sha256") == run.get("run_manifest_sha256")
                and admission.get("arm_id") == run.get("arm_id")
                and admission.get("comparison_id") == run.get("comparison_id")
                and run.get("definition_sha256") == definition.raw_sha256
                and run.get("terminal_status") == "complete"
                and document["freeze"]["status"] == "published"
                and admission.get("promotion_authorized") is False
                and admission.get("reasons") == []
                and run_rows_valid
            )
            if hashes_match:
                admission_status = (
                    "admitted"
                    if admission.get("admission_status") == "admitted" and admission.get("admitted") is True
                    else "withheld"
                )
                if admission_status == "admitted" and verified:
                    summary, task_rows = _admitted_summary(replay_pair[0], tasks, task_ids)
            else:
                admission_status = "invalid_receipt_chain"
        runs.append({
            "run_id": _bounded_text(run.get("run_id"), limit=200),
            "arm_id": _bounded_text(run.get("arm_id"), limit=96),
            "comparison_id": _bounded_text(run.get("comparison_id"), limit=96),
            "observed_terminal_status": (
                run.get("terminal_status")
                if run.get("terminal_status") in {"complete", "aborted", "unissued"}
                else "invalid"
            ),
            "replay_status": "verified" if verified else ("invalid" if replay_pair else "not_run"),
            "admission_status": admission_status,
            "summary": summary,
            "task_outcomes": task_rows,
        })
    task_index = [
        {
            "task_id": task["id"],
            "panel": task["panel"],
            "domain": task["domain"],
            "construct": task["construct"],
            "max_model_calls": task["resource"]["max_model_calls"],
        }
        for task in document["tasks"]
    ]
    return {
        "schema_version": "benchmark-program/v1",
        "suite_id": document["suite_id"],
        "release": document["release"],
        "definition_sha256": definition.raw_sha256,
        "freeze": {
            "status": document["freeze"]["status"],
            "published_at": document["freeze"]["published_at"],
            "review_at": document["freeze"]["review_at"],
            "expiry_action": document["freeze"]["expiry_action"],
        },
        "baseline_status": document["baseline_status"],
        "historical_comparability": document["historical_comparability"],
        "panels": [
            {
                "id": panel["id"],
                "role": panel["role"],
                "layer": panel["layer"],
                "independent_units": panel["independent_units"],
                "max_model_calls_per_arm": panel["max_model_calls_per_arm"],
                "task_ids": list(panel["task_ids"]),
            }
            for panel in document["panels"]
        ],
        "resource_envelope": {
            key: document["resource_envelope"][key]
            for key in (
                "max_model_calls_per_arm", "max_model_calls_paired",
                "max_output_tokens_per_arm", "max_episode_runtime_s_per_arm",
                "max_supervised_window_s", "paid_api_cost_usd", "execution",
            )
        },
        "reporting": {
            key: document["reporting"][key]
            for key in (
                "no_omnibus_score", "descriptive_family_counts",
                "strategic_mechanism_counts", "family_count_interpretation",
                "strategic_metrics", "strategic_grouping",
                "strategic_regret_aggregation", "system_claim_scope",
                "independent_unit", "uncertainty", "promotion_from_small_n",
            )
        },
        "task_index": task_index,
        "runs": runs,
        "warnings": (
            (["Draft definitions cannot execute."] if document["freeze"]["status"] == "draft" else [])
            + [
                "Scores appear only after raw replay and external lifecycle admission.",
                "No omnibus score is defined across constructs.",
            ]
        ),
    }


__all__ = ["program_projection"]
