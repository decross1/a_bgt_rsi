"""Record descriptive progress summaries after replaying terminal trial receipts.

This is an explicit operator action, not a promotion or an independent judge.
Only the three followthrough schemas below have defined counting semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("fixed_attempts_expected", "fixed_attempts_returned", "fixed_attempts_protocol_valid",
          "objective_cases_passed", "objective_cases_total", "repair_cases_passed",
          "repair_cases_total", "annotation_disagreements")


def observations(plan, run, raw):
    arms, failures = [], Counter()
    kind = plan["kind"]
    if kind not in {"diversity", "role_effort", "historical_repair"}:
        raise ValueError("unsupported counting semantics")
    for arm in plan["arm_ids"]:
        result = dict.fromkeys(FIELDS)
        result["arm"] = arm
        rows = [r for r in run["outcomes"] if r.get("condition", r.get("arm", r.get("arm_id"))) == arm]
        if not rows:
            raise ValueError("missing planned arm outcomes")
        if kind == "diversity":
            if any("structured_output_diagnostics" not in r for r in rows):
                raise ValueError("legacy diversity has different counting semantics")
            calls = [r for r in raw if r["condition"] == arm]
            result["fixed_attempts_expected"] = sum(len(r["attempt_ids"]) for r in rows)
            result["fixed_attempts_returned"] = sum(r["status"] == "returned" for r in calls)
            result["fixed_attempts_protocol_valid"] = sum(d is None for r in rows for d in r["structured_output_diagnostics"])
            result["objective_cases_total"] = len(rows)
            result["objective_cases_passed"] = sum(r["creditable_task_success"] for r in rows)
            for row in rows:
                failures.update(d["failure_code"] for d in row["structured_output_diagnostics"] if d)
                failures["substantive_proposal_failure"] += len(row["substantive_proposal_failures"])
                failures["substantive_selection_failure"] += bool(row["substantive_selection_failure"])
        elif kind == "role_effort":
            result["fixed_attempts_expected"] = len(rows)
            result["fixed_attempts_returned"] = sum(r["status"] == "returned" for r in rows)
            result["fixed_attempts_protocol_valid"] = sum(r["protocol_valid"] for r in rows)
            result["objective_cases_total"] = len(rows)
            result["objective_cases_passed"] = sum(r["passed"] for r in rows)
            for row in rows:
                failures.update(row["step_protocol_failures"])
                failures.update("transport_" + s for s in row["step_transport_statuses"] if s != "returned")
                if row["failure_code"] == "substantive_mistake":
                    failures["substantive_mistake"] += 1
        else:
            result["fixed_attempts_expected"] = len(rows)
            result["fixed_attempts_returned"] = sum(r["status"] == "returned" for r in rows)
            # A valid applied patch is stronger than JSON validity, so do not
            # silently substitute it for the unrecorded protocol denominator.
            result["fixed_attempts_protocol_valid"] = None
            result["repair_cases_total"] = len(rows)
            result["repair_cases_passed"] = sum(r["creditable_success"] for r in rows)
            for row in rows:
                if row["status"] != "returned":
                    failures["transport_" + row["status"]] += 1
                elif row["patch_error"]:
                    failures[row["patch_error"]] += 1
                elif not row["creditable_success"]:
                    grade = row.get("grader")
                    failures["grader_" + grade["status"] if isinstance(grade, dict) else "grader_unavailable"] += 1
        arms.append(result)
    overall = {field: sum(a[field] for a in arms) if all(a[field] is not None for a in arms) else None for field in FIELDS}
    if overall["fixed_attempts_expected"] != plan["declared_attempts"]:
        raise ValueError("outcome denominator differs from preregistered attempts")
    overall["failure_categories"] = [{"code": code, "count": count} for code, count in sorted(failures.items()) if count]
    return overall, arms


def read_bound(path: Path, expected_sha256: str | None, *, lines: bool = False, with_hash: bool = False):
    """Parse the same bounded bytes whose hash matches the replayed receipt."""
    if path.resolve() != path:
        raise ValueError("redirected evaluation artifact")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        raw = stream.read(16_000_001)
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > 16_000_000 or (expected_sha256 is not None and digest != expected_sha256):
        raise ValueError("evaluation bytes changed after replay or exceed bound")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate evaluation field")
            value[key] = item
        return value
    def invalid_constant(value):
        raise ValueError("non-finite evaluation value")
    def parse(data):
        value = json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)
        if not isinstance(value, dict):
            raise TypeError("evaluation object required")
        return value
    if not lines:
        parsed = parse(raw)
        return (parsed, digest) if with_hash else parsed
    if raw and not raw.endswith(b"\n"):
        raise ValueError("partial evaluation JSONL")
    return [parse(line) for line in raw.splitlines()]


def record(repo: Path, trial_id: str):
    from orchestrator.weekly_upgrade_trial import _read, evaluation_receipt
    if not re.fullmatch(r"\d{4}-W\d{2}-[0-9a-f]{24}", trial_id):
        raise ValueError("invalid trial ID")
    repo = repo.absolute()
    if repo.resolve() != repo:
        raise ValueError("redirected repository")
    journal_path = repo / "run_state/weekly_upgrade/trials" / (trial_id + ".json")
    if journal_path.resolve() != journal_path:
        raise ValueError("redirected trial journal")
    journal, journal_sha256 = read_bound(journal_path, None, with_hash=True)
    if journal.get("phase") != "finished" or journal.get("plan", {}).get("trial_id") != trial_id:
        raise ValueError("trial is not terminal and identity-bound")
    plan, result = journal["plan"], journal["result"]
    output = Path(journal["output"])
    if output.resolve() != output:
        raise ValueError("redirected trial output")
    result_copy, result_sha256 = read_bound(output / "trial_result.json", None, with_hash=True)
    expected_result_sha256 = hashlib.sha256(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    ).hexdigest()
    if result_copy != result or result_sha256 != expected_result_sha256:
        raise ValueError("terminal result differs from journal")
    receipt = evaluation_receipt(plan, output)
    if receipt != result.get("evaluation"):
        raise ValueError("replayed evaluation differs from terminal receipt")
    run = read_bound(output / "evaluation/run.json", receipt["artifact_sha256"]["run.json"])
    raw_path = output / "evaluation/raw_calls.jsonl"
    raw = read_bound(raw_path, receipt["artifact_sha256"]["raw_calls.jsonl"], lines=True) if plan["kind"] == "diversity" else []
    overall, arms = observations(plan, run, raw)
    value = {
        "schema_version": "weekly-upgrade-evaluation-summary/v1", "trial_id": trial_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "provenance": "operator_recorded",
        "trial_journal_sha256": journal_sha256,
        "trial_result_sha256": result_sha256, "transport_evaluation_sha256": receipt["sha256"],
        "summary_artifact_sha256": receipt["sha256"], "annotation_artifacts": [],
        "observations": overall, "arm_observations": arms,
    }
    target = repo / "run_state/weekly_upgrade/evaluations" / (trial_id + ".json")
    if target.resolve() != target:
        raise ValueError("redirected summary destination")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        previous = _read(target)
        if {k: v for k, v in previous.items() if k != "recorded_at"} != {k: v for k, v in value.items() if k != "recorded_at"}:
            raise ValueError("existing summary differs; do not overwrite evidence")
        return target
    with target.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--trial-id", required=True)
    args = parser.parse_args()
    print(record(args.repo, args.trial_id))


if __name__ == "__main__":
    main()
