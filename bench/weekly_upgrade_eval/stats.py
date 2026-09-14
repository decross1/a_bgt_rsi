"""Descriptive, failure-inclusive summaries for paired canary outcomes.

These statistics are intentionally not a promotion rule.  The task is the
resampling unit; seeded repeats of one prompt must not be represented as new
task templates.
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from typing import Any, Iterable


COMPLETED_STATUSES = frozenset({"passed", "failed"})


def _percentile(sorted_values: list[float], probability: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def paired_bootstrap_ci(
    deltas: Iterable[float], *, samples: int, seed: int
) -> dict[str, Any]:
    """Percentile CI for the mean paired delta, resampling whole tasks.

    The result is descriptive because this small fixed panel is not a random
    sample from a defined task population.
    """
    values = [float(value) for value in deltas]
    if not values:
        return {
            "n_task_templates": 0,
            "mean_delta": None,
            "ci95": [None, None],
            "samples": samples,
            "seed": seed,
            "interpretation": "descriptive_only",
        }
    rng = random.Random(seed)
    n_values = len(values)
    boot = [
        sum(values[rng.randrange(n_values)] for _ in range(n_values)) / n_values
        for _ in range(samples)
    ]
    boot.sort()
    return {
        "n_task_templates": n_values,
        "mean_delta": round(sum(values) / n_values, 6),
        "ci95": [
            round(float(_percentile(boot, 0.025)), 6),
            round(float(_percentile(boot, 0.975)), 6),
        ],
        "samples": samples,
        "seed": seed,
        "interpretation": "descriptive_only",
    }


def exact_two_sided_sign_p(a_only: int, b_only: int) -> float | None:
    """Exact two-sided sign-test p-value over discordant completed pairs."""
    discordant = a_only + b_only
    if discordant == 0:
        return None
    tail = min(a_only, b_only)
    numerator = sum(math.comb(discordant, k) for k in range(tail + 1))
    return min(1.0, 2.0 * numerator / (2 ** discordant))


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _outcome_indicator(outcome: dict[str, Any]) -> int:
    # Timeouts, transport errors, canceled work and budget-skipped work are
    # failures in the planned-panel denominator.  They never become missing
    # observations that make a partial run look stronger.
    return int(outcome.get("status") == "passed")


def summarize_outcomes(
    outcomes: list[dict[str, Any]],
    *,
    task_ids: list[str],
    task_families: dict[str, str],
    arm_ids: tuple[str, str],
    elapsed_s: float,
    bootstrap_samples: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    """Summarize exactly one outcome for every planned task/arm cell."""
    if elapsed_s < 0 or not math.isfinite(elapsed_s):
        raise ValueError("elapsed_s must be finite and >= 0")
    expected = {(task_id, arm_id) for task_id in task_ids for arm_id in arm_ids}
    by_cell: dict[tuple[str, str], dict[str, Any]] = {}
    for outcome in outcomes:
        cell = (outcome.get("task_id"), outcome.get("arm_id"))
        if cell not in expected:
            raise ValueError(f"unexpected outcome cell: {cell!r}")
        if cell in by_cell:
            raise ValueError(f"duplicate outcome cell: {cell!r}")
        by_cell[cell] = outcome
    missing = sorted(expected - set(by_cell))
    if missing:
        raise ValueError(f"missing outcome cell(s): {missing!r}")

    first, second = arm_ids
    pair_counts = Counter()
    completed_pair_counts = Counter()
    deltas: list[int] = []
    completed_deltas: list[int] = []
    family_deltas: dict[str, list[int]] = defaultdict(list)
    pair_rows: list[dict[str, Any]] = []
    for task_id in task_ids:
        a = by_cell[(task_id, first)]
        b = by_cell[(task_id, second)]
        a_pass = _outcome_indicator(a)
        b_pass = _outcome_indicator(b)
        delta = b_pass - a_pass
        deltas.append(delta)
        family_deltas[task_families[task_id]].append(delta)
        both_completed = (
            a.get("status") in COMPLETED_STATUSES
            and b.get("status") in COMPLETED_STATUSES
        )
        if both_completed:
            completed_deltas.append(delta)
        if a_pass and b_pass:
            category = "both_pass"
        elif a_pass:
            category = "a_only"
        elif b_pass:
            category = "b_only"
        else:
            category = "both_not_passed"
        pair_counts[category] += 1
        if both_completed:
            pair_counts["both_completed"] += 1
            completed_pair_counts[category] += 1
        else:
            pair_counts["incomplete_pair"] += 1
        pair_rows.append({
            "task_id": task_id,
            "family": task_families[task_id],
            "a_status": a.get("status"),
            "b_status": b.get("status"),
            "delta_b_minus_a": delta,
            "both_completed": both_completed,
        })

    arm_summary: dict[str, Any] = {}
    for arm_id in arm_ids:
        arm_outcomes = [by_cell[(task_id, arm_id)] for task_id in task_ids]
        pass_count = sum(_outcome_indicator(outcome) for outcome in arm_outcomes)
        completed_count = sum(
            outcome.get("status") in COMPLETED_STATUSES for outcome in arm_outcomes
        )
        charged_s = sum(
            max(0.0, float(outcome.get("duration_s") or 0.0))
            for outcome in arm_outcomes
        )
        arm_summary[arm_id] = {
            "planned": len(task_ids),
            "passed": pass_count,
            "completed_responses": completed_count,
            "status_counts": dict(sorted(Counter(
                str(outcome.get("status")) for outcome in arm_outcomes
            ).items())),
            "failure_inclusive_pass_rate": _rate(pass_count, len(task_ids)),
            "charged_wall_s_including_failures": round(charged_s, 6),
            "successful_tasks_per_charged_hour": (
                round(pass_count / (charged_s / 3600.0), 6) if charged_s else None
            ),
        }

    all_passes = sum(_outcome_indicator(outcome) for outcome in outcomes)
    global_ctt = (
        round(all_passes / (elapsed_s / 3600.0), 6) if elapsed_s else None
    )
    family_summary = {
        family: {
            "n_task_templates": len(values),
            "mean_failure_inclusive_delta_b_minus_a": round(
                sum(values) / len(values), 6
            ),
        }
        for family, values in sorted(family_deltas.items())
    }
    sign_p = exact_two_sided_sign_p(
        completed_pair_counts["a_only"], completed_pair_counts["b_only"]
    )
    return {
        "planned_task_pairs": len(task_ids),
        "planned_arm_task_outcomes": len(outcomes),
        "pair_counts": {
            key: pair_counts[key]
            for key in (
                "both_pass", "a_only", "b_only", "both_not_passed",
                "both_completed", "incomplete_pair",
            )
        },
        "arms": arm_summary,
        "paired_failure_inclusive": paired_bootstrap_ci(
            deltas, samples=bootstrap_samples, seed=bootstrap_seed
        ),
        "paired_completed_responses_only": paired_bootstrap_ci(
            completed_deltas, samples=bootstrap_samples, seed=bootstrap_seed + 1
        ),
        "exact_sign_test_completed_pairs": {
            "a_only": completed_pair_counts["a_only"],
            "b_only": completed_pair_counts["b_only"],
            "two_sided_p": round(sign_p, 6) if sign_p is not None else None,
            "interpretation": "descriptive_only",
        },
        "by_family": family_summary,
        "failure_inclusive_correct_task_throughput": {
            "successful_arm_tasks": all_passes,
            "elapsed_wall_s_including_failures": round(elapsed_s, 6),
            "successful_arm_tasks_per_wall_hour": global_ctt,
        },
        "pairs": pair_rows,
        "warning": (
            "This fixed, small canary supports diagnosis only. Bootstrap and "
            "sign-test values are descriptive and do not authorize promotion."
        ),
    }
