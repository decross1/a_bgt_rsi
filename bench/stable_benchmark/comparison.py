"""Paired descriptive comparison for two admitted stable-benchmark arms."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

from .admission import ADMISSION_SCHEMA, admission_source_hashes
from .manifest import LoadedDocument, validate_definition
from .replay import REPLAY_SCHEMA, replay_source_hashes


class ComparisonError(ValueError):
    pass


NON_ADMISSIBLE_CELL_STATUSES = {"invalid", "skipped_budget", "unissued"}


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _verify_chain(
    definition: LoadedDocument,
    replay: dict[str, Any],
    replay_sha256: str,
    admission: dict[str, Any],
) -> None:
    if not _digest(replay_sha256):
        raise ComparisonError("replay digest is invalid")
    if replay.get("schema_version") != REPLAY_SCHEMA:
        raise ComparisonError("replay schema differs")
    if admission.get("schema_version") != ADMISSION_SCHEMA:
        raise ComparisonError("admission schema differs")
    if (
        replay.get("verified") is not True
        or replay.get("terminal_status") != "verified"
        or replay.get("mismatches") != []
    ):
        raise ComparisonError("replay is not verified")
    if (
        admission.get("admitted") is not True
        or admission.get("admission_status") != "admitted"
        or admission.get("reasons") != []
        or admission.get("promotion_authorized") is not False
    ):
        raise ComparisonError("arm is not admitted")
    if admission.get("definition_sha256") != definition.raw_sha256:
        raise ComparisonError("admission binds a different definition")
    if admission.get("replay_receipt_sha256") != replay_sha256:
        raise ComparisonError("admission binds a different replay")
    if replay.get("definition_sha256") != definition.raw_sha256:
        raise ComparisonError("replay binds a different definition")
    if replay.get("replay_source_sha256") != replay_source_hashes():
        raise ComparisonError("replay source bundle differs")
    if admission.get("admission_source_sha256") != admission_source_hashes():
        raise ComparisonError("admission source bundle differs")
    if admission.get("run_manifest_sha256") != replay.get("run_manifest_sha256"):
        raise ComparisonError("admission and replay bind different run manifests")
    if admission.get("run_receipt_sha256") != replay.get("run_receipt_sha256"):
        raise ComparisonError("admission and replay bind different run receipts")
    if admission.get("arm_id") != replay.get("arm_id"):
        raise ComparisonError("admission and replay bind different arms")
    if admission.get("comparison_id") != replay.get("comparison_id"):
        raise ComparisonError("admission and replay bind different comparison cohorts")


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _cluster_bootstrap(
    rows: list[dict[str, Any]], *, samples: int, seed: int
) -> dict[str, Any]:
    clusters: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        clusters[row["cluster"]].append(float(row["delta_right_minus_left"]))
    cluster_values = [_mean(values) or 0.0 for values in clusters.values()]
    # The estimand and resampling unit are both equal-weighted clusters.  This
    # avoids reporting a task-weighted point estimate with a cluster-weighted
    # interval when mechanisms contain different numbers of parameterizations.
    observed = _mean(cluster_values)
    if not cluster_values:
        return {
            "mean_delta": None, "ci95": [None, None], "clusters": 0,
            "samples": 0, "estimand": "equal_weighted_uncertainty_clusters",
            "interpretation": "not_estimated_no_clusters",
        }
    if len(cluster_values) < 4:
        return {
            "mean_delta": round(float(observed), 6),
            "ci95": [None, None],
            "clusters": len(cluster_values),
            "samples": 0,
            "estimand": "equal_weighted_uncertainty_clusters",
            "interpretation": "not_estimated_small_cluster_count",
        }
    rng = random.Random(seed)
    n = len(cluster_values)
    boot = [sum(cluster_values[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples)]
    boot.sort()
    lo = boot[int(0.025 * (samples - 1))]
    hi = boot[int(0.975 * (samples - 1))]
    return {
        "mean_delta": round(float(observed), 6),
        "ci95": [round(lo, 6), round(hi, 6)],
        "clusters": n,
        "samples": samples,
        "estimand": "equal_weighted_uncertainty_clusters",
        "interpretation": "descriptive_fixed_small_panel",
    }


def _fraction_to_float(value: Any) -> float | None:
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
        return None
    numerator, denominator = value["numerator"], value["denominator"]
    if (
        isinstance(numerator, bool) or not isinstance(numerator, int)
        or isinstance(denominator, bool) or not isinstance(denominator, int)
        or denominator == 0
    ):
        return None
    return numerator / denominator


def compare_admitted(
    definition: LoadedDocument,
    *,
    left_replay: dict[str, Any],
    left_replay_sha256: str,
    left_admission: dict[str, Any],
    right_replay: dict[str, Any],
    right_replay_sha256: str,
    right_admission: dict[str, Any],
    bootstrap_samples: int = 10000,
    bootstrap_seed: int = 160916,
) -> dict[str, Any]:
    """Compare matched units; never produce an across-construct omnibus score."""
    validate_definition(definition.document, require_published=True)
    if bootstrap_samples < 1000 or bootstrap_samples > 100000:
        raise ComparisonError("bootstrap_samples must be between 1000 and 100000")
    _verify_chain(definition, left_replay, left_replay_sha256, left_admission)
    _verify_chain(definition, right_replay, right_replay_sha256, right_admission)
    if left_admission.get("comparison_id") != right_admission.get("comparison_id"):
        raise ComparisonError("arms belong to different comparison cohorts")
    if left_admission.get("arm_id") == right_admission.get("arm_id"):
        raise ComparisonError("comparison requires two distinct arm IDs")
    tasks = {task["id"]: task for task in definition.document["tasks"]}
    task_ids = list(tasks)

    def checked_rows(replay: dict[str, Any], side: str) -> dict[str, dict[str, Any]]:
        rows = replay.get("outcomes")
        if (
            not isinstance(rows, list)
            or len(rows) != len(task_ids)
            or [row.get("task_id") for row in rows if isinstance(row, dict)] != task_ids
        ):
            raise ComparisonError(f"{side} replay task order or cardinality differs from the definition")
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            task_id = row["task_id"]
            task = tasks[task_id]
            calls = row.get("model_calls")
            if task_id in result:
                raise ComparisonError(f"{side} replay contains duplicate task {task_id}")
            if (
                row.get("verified") is not True
                or row.get("cell_status") in NON_ADMISSIBLE_CELL_STATUSES
                or not isinstance(row.get("score_credit"), bool)
                or isinstance(calls, bool)
                or not isinstance(calls, int)
                or calls < 0
                or calls > task["resource"]["max_model_calls"]
                or row.get("model_calls_exact") is not True
            ):
                raise ComparisonError(f"{side} replay has an inadmissible outcome for {task_id}")
            result[task_id] = row
        return result

    left = checked_rows(left_replay, "left")
    right = checked_rows(right_replay, "right")
    by_construct: dict[str, list[dict[str, Any]]] = defaultdict(list)
    strategic: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for task_id, task in tasks.items():
        left_credit = int(left[task_id].get("score_credit") is True)
        right_credit = int(right[task_id].get("score_credit") is True)
        row = {
            "task_id": task_id,
            "panel": task["panel"],
            "domain": task["domain"],
            "construct": task["construct"],
            "cluster": task["provenance"]["uncertainty_cluster"],
            "left_credit": left_credit,
            "right_credit": right_credit,
            "delta_right_minus_left": right_credit - left_credit,
        }
        pairs.append(row)
        by_construct[task["construct"]].append(row)
        if task["domain"] == "strategic_behavior":
            left_regret = _fraction_to_float(left[task_id].get("metrics", {}).get("own_utility_regret"))
            right_regret = _fraction_to_float(right[task_id].get("metrics", {}).get("own_utility_regret"))
            strategic.append({
                "task_id": task_id,
                "mechanism": task["construct"],
                "left_own_regret": left_regret,
                "right_own_regret": right_regret,
                "delta_right_minus_left": (
                    None if left_regret is None or right_regret is None else right_regret - left_regret
                ),
            })
    construct_rows: list[dict[str, Any]] = []
    for offset, (construct, rows) in enumerate(sorted(by_construct.items())):
        left_only = sum(row["left_credit"] == 1 and row["right_credit"] == 0 for row in rows)
        right_only = sum(row["left_credit"] == 0 and row["right_credit"] == 1 for row in rows)
        construct_rows.append({
            "construct": construct,
            "independent_units": len(rows),
            "discordant": {"left_only": left_only, "right_only": right_only},
            "paired_uncertainty": _cluster_bootstrap(
                rows,
                samples=bootstrap_samples,
                seed=bootstrap_seed + offset,
            ),
        })
    return {
        "schema_version": "stable-benchmark-comparison/v1",
        "comparison_id": left_admission["comparison_id"],
        "definition_sha256": definition.raw_sha256,
        "left_arm_id": left_admission["arm_id"],
        "right_arm_id": right_admission["arm_id"],
        "paired_units": pairs,
        "constructs": construct_rows,
        "strategic_regret": strategic,
        "omnibus_score": None,
        "promotion_authorized": False,
        "limitations": [
            "Fixed small-panel intervals are descriptive.",
            "Repeated parameterizations are clustered by mechanism.",
            "No across-construct average or automatic promotion decision is defined.",
        ],
    }


__all__ = ["ComparisonError", "compare_admitted"]
