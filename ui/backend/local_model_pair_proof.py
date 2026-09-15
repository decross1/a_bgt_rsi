"""Off-tree draft for local_model_research._comparison after first pair.

The existing dashboard reader must not render a pair from the two saved runs
alone. This helper checks immutable recorded admission first, then reports
whether the current controller sources can replay that admission.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from pathlib import Path

PAIR = re.compile(r"qfn-ab-[a-z0-9][a-z0-9._-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
ROOT_PREFIX = "evaluation/"
PROOF_SCHEMA = "flash-next-recorded-pair-admission/v1"
AGGREGATE_SCHEMA = "flash-next-content-free-aggregate/v1"
GATE_SCHEMA = "flash-next-supervised-pair-validation/v1"
FAMILIES = {"objective", "topic", "context", "portfolio", "diversity",
            "role_effort", "historical"}


class ProofError(ValueError):
    """A recorded source changed or the proof does not support its claim."""


def _require(valid: bool, message: str) -> None:
    if not valid:
        raise ProofError(message)


def _digest(value) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _ref(value, *, prefix=ROOT_PREFIX) -> dict:
    _require(isinstance(value, dict) and set(value) == {"path", "sha256"},
             "pair source reference has invalid shape")
    path, digest = value["path"], value["sha256"]
    normalized = Path(path) if isinstance(path, str) else None
    _require(isinstance(path, str) and path.startswith(prefix)
             and normalized is not None and not normalized.is_absolute()
             and normalized.as_posix() == path
             and all(part not in {".", ".."} for part in normalized.parts)
             and _digest(digest),
             "pair source reference is outside the registered root")
    return value


def _read_ref(reader, value, *, prefix=ROOT_PREFIX) -> dict:
    ref = _ref(value, prefix=prefix)
    record, digest = reader.read(ref["path"], digest=ref["sha256"])
    _require(digest == ref["sha256"], "pair source raw hash differs")
    return record


def _rate(value) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1


def _number(value) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _recorded_counts(run: dict) -> dict:
    """Recount saved outcomes without requiring today's model/adapter code."""
    outcomes = run.get("outcomes")
    _require(isinstance(outcomes, list) and 0 < len(outcomes) <= 2048,
             "recorded outcomes exceed the task-run bound")
    counts = {}
    seen = set()
    for outcome in outcomes:
        _require(isinstance(outcome, dict)
                 and outcome.get("family") in FAMILIES
                 and isinstance(outcome.get("cell_id"), str)
                 and outcome["cell_id"] not in seen
                 and outcome.get("status") in {"returned", "timeout", "error"}
                 and type(outcome.get("passed")) is bool
                 and (not outcome["passed"] or outcome["status"] == "returned")
                 and _number(outcome.get("wall_s")),
                 "recorded outcome cannot support a complete denominator")
        seen.add(outcome["cell_id"])
        row = counts.setdefault(outcome["family"], {"declared": 0, "passed": 0, "wall_s": 0.0})
        row["declared"] += 1
        row["passed"] += int(outcome["passed"])
        row["wall_s"] += outcome["wall_s"]
    return counts


def _recorded_pair_statistics(runs: dict, family: str, samples: int, seed: int) -> dict:
    """Replay v1 source-task statistics from the saved paired outcomes."""
    indices = {cohort: {row["cell_id"]: row for row in runs[cohort]["outcomes"]}
               for cohort in ("resident", "flash")}
    _require(set(indices["resident"]) == set(indices["flash"]),
             "saved arms have different task cells")
    ordered = runs["resident"].get("declared_cells")
    _require(isinstance(ordered, list) and len(ordered) == len(set(ordered))
             and set(ordered) == set(indices["resident"]),
             "saved arm has no unique declared task order")
    groups = {}
    paired = {"both_passed_task_runs": 0, "resident_only_passed_task_runs": 0,
              "flash_only_passed_task_runs": 0, "neither_passed_task_runs": 0}
    differences = []
    for cell in ordered:
        a, b = indices["resident"][cell], indices["flash"][cell]
        _require(a.get("family") == b.get("family") and a.get("source") == b.get("source"),
                 "saved paired source identities differ")
        if a["family"] != family:
            continue
        source = a.get("source")
        _require(isinstance(source, dict) and isinstance(source.get("suite_id"), str)
                 and _digest(source.get("manifest_sha256"))
                 and _digest(source.get("task_sha256")), "saved task source is invalid")
        key = tuple(source[name] for name in ("suite_id", "manifest_sha256", "task_sha256"))
        difference = int(b["passed"]) - int(a["passed"])
        groups.setdefault(key, []).append(difference)
        differences.append(difference)
        paired_key = ("both_passed_task_runs" if a["passed"] and b["passed"] else
                      "resident_only_passed_task_runs" if a["passed"] else
                      "flash_only_passed_task_runs" if b["passed"] else "neither_passed_task_runs")
        paired[paired_key] += 1
    _require(bool(groups), "recorded family has no source tasks")
    means = [sum(values) / len(values) for values in groups.values()]
    interval = None
    if len(means) >= 2:
        raw = json.dumps([seed, family], sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode()
        rng = random.Random(int.from_bytes(hashlib.sha256(raw).digest()[:16], "big"))
        draws = sorted(sum(rng.choice(means) for _ in means) / len(means)
                       for _ in range(samples))
        def quantile(q):
            position = (len(draws) - 1) * q
            lo, hi = math.floor(position), math.ceil(position)
            return draws[lo] + (draws[hi] - draws[lo]) * (position - lo)
        interval = [quantile(.025), quantile(.975)]
    return {"paired_success_delta": sum(differences) / len(differences),
            "equal_source_task_success_delta": sum(means) / len(means),
            "source_task_interval_95": interval, "resampling_units": len(groups),
            "paired_outcomes": paired}


def _sanitize_aggregate(aggregate: dict, pair_id: str,
                        proof: dict, runs: dict) -> list[dict]:
    _require(
        aggregate.get("schema_version") == AGGREGATE_SCHEMA
        and aggregate.get("pair_id") == pair_id
        and aggregate.get("admission_class")
            == "RECORDED_COMPLETED_PAIR_ADMISSION"
        and aggregate.get("status") == "descriptive_complete"
        and aggregate.get("comparison_eligible_at_recording") is True
        and aggregate.get("promotion_authorized") is False
        and aggregate.get("causal_attribution") is None
        and aggregate.get("benchmark_plan_file_sha256")
            == proof["admission_at_recording"]["flash"][
                "benchmark_plan_file_sha256"
            ]
        and aggregate.get("controller_source_bundle_sha256")
            == proof["controller_source_bundle_sha256"]
        and aggregate.get("run_sha256") == {
            cohort: proof["sources"][cohort]["run"]["sha256"]
            for cohort in ("resident", "flash")
        }
        and aggregate.get("manifest_sha256")
            == runs["resident"].get("manifest_sha256")
            == runs["flash"].get("manifest_sha256")
        and aggregate.get("candidate_variant_id")
            == proof["extended_plan"]["candidate_variant_id"]
        and aggregate.get("candidate_spec_sha256")
            == proof["extended_plan"]["candidate_spec_sha256"],
        "recorded aggregate and admitted sources disagree",
    )
    families = aggregate.get("families")
    source_counts = {cohort: _recorded_counts(runs[cohort])
                     for cohort in ("resident", "flash")}
    _require(isinstance(families, dict) and families
             and set(families) == set(source_counts["resident"])
             == set(source_counts["flash"]) <= FAMILIES,
             "aggregate has unregistered benchmark families")
    samples, seed = aggregate.get("bootstrap_samples"), aggregate.get("bootstrap_seed")
    _require(type(samples) is int and 100 <= samples <= 10_000
             and type(seed) is int, "recorded bootstrap configuration is invalid")
    projected = []
    for family, row in sorted(families.items()):
        statistics = _recorded_pair_statistics(runs, family, samples, seed)
        _require(all(row.get(key) == value for key, value in statistics.items()),
                 "aggregate paired statistics differ from saved outcomes")
        cohorts = row.get("cohorts")
        _require(isinstance(cohorts, dict)
                 and set(cohorts) == {"resident", "flash"},
                 "aggregate arms are unavailable")
        arms = {}
        for cohort in ("resident", "flash"):
            arm = cohorts[cohort]
            counts = ("declared", "attempted", "passed")
            _require(isinstance(arm, dict)
                     and all(type(arm.get(key)) is int and arm[key] >= 0
                             for key in counts)
                     and 0 < arm["declared"]
                     and arm["attempted"] == arm["declared"]
                     and arm["passed"] <= arm["attempted"] <= arm["declared"]
                     and _rate(arm.get("success_rate"))
                     and _number(arm.get("wall_s_including_failures"))
                     and (arm.get("successful_task_runs_per_hour") is None
                          or _number(arm["successful_task_runs_per_hour"])),
                     "aggregate task denominators or wall are invalid")
            _require(abs(arm["success_rate"]
                         - arm["passed"] / arm["declared"]) < 1e-12,
                     "aggregate rate has a different denominator")
            original = source_counts[cohort][family]
            _require(arm["declared"] == original["declared"]
                     and arm["passed"] == original["passed"]
                     and math.isclose(arm["wall_s_including_failures"], original["wall_s"],
                                      rel_tol=1e-9, abs_tol=1e-9),
                     "aggregate counts or elapsed time differ from saved outcomes")
            expected_throughput = (3600 * original["passed"] / original["wall_s"]
                                   if original["wall_s"] > 0 else None)
            _require(arm["successful_task_runs_per_hour"] is None
                     if expected_throughput is None else
                     arm["successful_task_runs_per_hour"] is not None
                     and math.isclose(arm["successful_task_runs_per_hour"], expected_throughput,
                                      rel_tol=1e-9, abs_tol=1e-9),
                     "aggregate throughput differs from saved outcomes")
            arms[cohort] = {key: arm[key] for key in (
                "declared", "attempted", "passed", "success_rate",
                "wall_s_including_failures", "successful_task_runs_per_hour",
            )}
        intervals = row.get("source_task_interval_95")
        _require(intervals is None or (
            isinstance(intervals, list) and len(intervals) == 2
            and all(type(value) in {int, float} and math.isfinite(value)
                    and -1 <= value <= 1 for value in intervals)
            and intervals[0] <= intervals[1]
        ), "source-task interval is invalid")
        for field in ("paired_success_delta", "equal_source_task_success_delta"):
            value = row.get(field)
            _require(type(value) in {int, float} and math.isfinite(value)
                     and -1 <= value <= 1, "paired delta is invalid")
        _require(type(row.get("task_runs")) is int
                 and row["task_runs"] == arms["flash"]["declared"]
                 == arms["resident"]["declared"]
                 and type(row.get("resampling_units")) is int
                 and row["resampling_units"] > 0,
                 "aggregate family has incompatible tasks")
        projected.append({
            "family": family, "cohorts": arms, "comparison_eligible": True,
            "paired_success_delta": row["paired_success_delta"],
            "equal_source_task_success_delta": row[
                "equal_source_task_success_delta"
            ],
            "source_task_interval_95": intervals,
        })
    return projected


def _source_replay(root: Path, pair_id: str, proof: dict) -> str:
    """Current source drift affects replay, not recorded admission history."""
    try:
        from bench.flash_next_ab import evaluation_window as ew
    except ImportError:
        return "unavailable"
    try:
        bundle = ew.frozen_controller_source_bundle()
        raw = json.dumps(bundle, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()
        current_sha = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, AttributeError, TypeError):
        return "unavailable"
    if current_sha != proof["controller_source_bundle_sha256"]:
        return "unavailable"
    # With identical source bundle, a failed pure replay is a changed/missing
    # receipt, not merely a new software revision. The caller withholds scores.
    try:
        from bench.flash_next_ab.extended_admission import validate_completed_pair

        plans = root / "evaluation/window-plans"
        runs = root / "evaluation/runs"
        replay = validate_completed_pair(
            plans / f"{pair_id}.flash.window.json", runs / f"{pair_id}.flash",
            plans / f"{pair_id}.resident.window.json", runs / f"{pair_id}.resident",
        )
    except ImportError:
        return "unavailable"
    except Exception as exc:
        raise ProofError("unchanged controller cannot replay completed admission") from exc
    _require(replay == proof["admission_at_recording"],
             "current source replay changed recorded admission")
    return "verified"


def project_proof_aware_pair(reader, entry: dict) -> dict:
    """Project recorded aggregate or raise; never infer from raw runs alone."""
    _require(isinstance(entry, dict) and PAIR.fullmatch(str(entry.get("id", "")))
             is not None, "pair index identity is invalid")
    pair_id = entry["id"]
    _require(entry.get("comparison_eligible_at_recording") is True
             and entry.get("promotion_authorized") is False,
             "index is missing the recorded-admission boundary")
    admission_ref = _ref(entry.get("admission"))
    aggregate_ref = _ref(entry.get("aggregate"))
    _require(admission_ref["path"] == f"evaluation/pair-proofs/{pair_id}.json"
             and aggregate_ref["path"]
             == f"evaluation/aggregate-summaries/{pair_id}.json",
             "indexed proof paths are outside this pair namespace")
    proof = _read_ref(reader, admission_ref)
    aggregate = _read_ref(reader, aggregate_ref)
    gate = proof.get("admission_at_recording")
    _require(
        proof.get("schema_version") == PROOF_SCHEMA
        and proof.get("pair_id") == pair_id
        and proof.get("aggregate") == aggregate_ref
        and proof.get("promotion_authorized") is False
        and _digest(proof.get("controller_source_bundle_sha256"))
        and isinstance(gate, dict) and gate.get("schema") == GATE_SCHEMA
        and gate.get("pair_id") == pair_id
        and gate.get("promotion_authorized") is False,
        "pair proof does not record an admitted gate",
    )
    sources = proof.get("sources")
    _require(isinstance(sources, dict) and set(sources) == {"resident", "flash"},
             "pair proof has no matching cohorts")
    runs = {}
    windows = {}
    for cohort in ("resident", "flash"):
        _require(isinstance(gate.get(cohort), dict)
                 and gate[cohort].get("cohort") == cohort
                 and gate[cohort].get("restoration_verified") is True
                 and gate[cohort].get("weekly_budget_debit") is False
                 and gate[cohort].get("paid_api_calls") == 0
                 and gate[cohort].get("production_change_authorized") is False,
                 "completed-cohort claim is absent")
        source = sources[cohort]
        _require(isinstance(source, dict), "proof source shape is invalid")
        expected_prefix = f"evaluation/runs/{pair_id}.{cohort}"
        _require(
            _ref(source.get("window"))["path"]
                == f"evaluation/window-plans/{pair_id}.{cohort}.window.json"
            and _ref(source.get("result"))["path"]
                == f"{expected_prefix}/result.json"
            and _ref(source.get("run"))["path"]
                == f"{expected_prefix}/harness/run.json"
            and entry.get(cohort) == source["run"]
            and gate[cohort].get("result_sha256") == source["result"]["sha256"]
            and gate[cohort].get("harness_run_sha256")
                == source["run"]["sha256"],
            "indexed raw run or result differs from completed admission",
        )
        if cohort == "flash":
            _require(gate[cohort].get("window_plan_sha256")
                     == source["window"]["sha256"],
                     "Flash window differs from completed admission")
        window = _read_ref(reader, source["window"])
        result = _read_ref(reader, source["result"])
        run = _read_ref(reader, source["run"])
        _require(window.get("pair_id") == pair_id
                 and window.get("cohort") == cohort
                 and result.get("pair_id") == pair_id
                 and result.get("status") == "complete"
                 and result.get("window_plan_sha256")
                    == source["window"]["sha256"]
                 and run.get("status") == "complete"
                 and run.get("cohort") == cohort
                 and run.get("promotion_authorized") is False,
                 "recorded cohort source identity is invalid")
        quals = source.get("qualifications")
        expected_keys = (
            {"receipt", "plan", "contract", "contract_raw"}
            if cohort == "flash" else {"receipt", "artifacts"}
        )
        _require(isinstance(quals, dict) and set(quals) == expected_keys,
                 "admitted qualifier source set is incomplete")
        indexed_qualifications = entry.get("qualifications", {}).get(cohort)
        _require(isinstance(indexed_qualifications, dict)
                 and set(indexed_qualifications)
                    == expected_keys - {"contract_raw"}
                 and all(indexed_qualifications[key] == quals[key]["path"]
                         for key in indexed_qualifications),
                 "index qualification paths differ from proof")
        qualifier_prefix = "qualification-runs/" if cohort == "flash" else "runtime/"
        for reference in quals.values():
            _read_ref(reader, reference, prefix=qualifier_prefix)
        runs[cohort], windows[cohort] = run, window
    _require(gate["flash"]["benchmark_plan_file_sha256"]
             == gate["resident"]["benchmark_plan_file_sha256"],
             "completed cohorts differ in benchmark plan")
    extended_plan_ref = _ref(sources["flash"].get("extended_plan"))
    _require(extended_plan_ref["path"]
             == f"evaluation/runs/{pair_id}.flash/extended-plan.json",
             "producer plan is outside admitted pair")
    extended_plan = _read_ref(reader, extended_plan_ref)
    _require(extended_plan.get("controller_source_bundle_sha256")
             == proof["controller_source_bundle_sha256"]
             and extended_plan.get("pair_id") == pair_id,
             "recorded source revision differs")
    proof["extended_plan"] = extended_plan
    families = _sanitize_aggregate(aggregate, pair_id, proof, runs)
    replay = _source_replay(reader.root, pair_id, proof)
    return {
        "id": pair_id, "status": "complete",
        "comparison_eligible": True,
        "comparison_eligible_at_recording": True,
        "admission_class": "RECORDED_COMPLETED_PAIR_ADMISSION",
        "current_source_replay": replay,
        "manifest_sha256": aggregate["manifest_sha256"],
        "run_sha256": aggregate["run_sha256"],
        "families": families,
        "promotion_authorized": False,
    }
