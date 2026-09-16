"""Read bounded, hash-bound benchmark receipts without executing their contents.

The API may inspect the artifacts of a supervised run; it must never replay a
model response, import generated code, or manufacture a missing admission.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_DOCUMENT_BYTES = 2_000_000
MAX_RUNS = 32
SAFE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,159}\Z")


def read_document(path: Path, limit: int = MAX_DOCUMENT_BYTES) -> tuple[dict, str]:
    from bench.stable_benchmark.manifest import _unique_object
    from .iteration_journey import _encoder_safe

    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("artifact path redirected")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError("artifact is not a bounded regular file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("artifact changed during open")
        raw = stream.read(limit + 1)
    if len(raw) != before.st_size or len(raw) > limit:
        raise ValueError("artifact changed size or exceeded bound")
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or not _encoder_safe(value):
        raise ValueError("artifact is not a safely representable object")
    return value, hashlib.sha256(raw).hexdigest()


def _directories(path: Path) -> list[Path]:
    if not path.exists() and not path.is_symlink():
        return []
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("run directory redirected")
    result = []
    with os.scandir(path) as entries:
        for entry in entries:
            if not SAFE_ID.fullmatch(entry.name) or not entry.is_dir(follow_symlinks=False):
                raise ValueError("unexpected run directory entry")
            result.append(Path(entry.path))
            if len(result) > MAX_RUNS:
                raise ValueError("run directory exceeds registered read bound")
    return sorted(result)


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid receipt timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("receipt timestamp lacks timezone")
    return value


def _number(value: Any) -> float | None:
    return (float(value) if isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value <= 10**9 else None)


def _instant(value: str | None) -> datetime:
    return (datetime.fromisoformat(value.replace("Z", "+00:00")) if value
            else datetime.min.replace(tzinfo=timezone.utc))


def _registered_arms(repo: Path, root: Path, definition, current: datetime) -> dict:
    from bench.stable_benchmark.receipt_verification import load_registration

    directory = repo / "docs/benchmarks/registrations"
    if not directory.exists() and not directory.is_symlink():
        return {}
    if directory.is_symlink() or directory.resolve() != directory.absolute():
        raise ValueError("registration directory redirected")
    entries = []
    with os.scandir(directory) as source:
        for entry in source:
            if not entry.name.endswith(".json") or not SAFE_ID.fullmatch(entry.name[:-5]):
                raise ValueError("unexpected registration entry")
            entries.append(Path(entry.path))
            if len(entries) > MAX_RUNS:
                raise ValueError("registration read bound exceeded")
    arms = {}
    for path in sorted(entries):
        registration = load_registration(path)
        document = registration.document
        if document["definition"]["sha256"] != definition.raw_sha256:
            continue  # Other releases keep their own comparison series.
        registration = load_registration(path, definition)
        if document["comparison_id"] != path.stem:
            raise ValueError("registration filename differs from comparison")
        if datetime.fromisoformat(document["registered_at"].replace("Z", "+00:00")) > current:
            raise ValueError("comparison registration is in the future")
        if Path(document["definition"]["path"]) != root / "definition.published.json":
            raise ValueError("registered definition path differs")
        for arm in document["arms"]:
            expected = root / "runs" / document["comparison_id"] / arm["arm_id"]
            if Path(arm["run_receipt_directory"]) != expected:
                raise ValueError("registered run directory differs")
            expected_manifest = root / "manifests" / f"{document['comparison_id']}.{arm['arm_id']}.json"
            if Path(arm["manifest"]["path"]) != expected_manifest:
                raise ValueError("registered manifest path differs")
            arms[expected] = (registration, arm)
    return arms


def _construct_results(outcomes: list[dict], tasks: dict) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in outcomes:
        grouped[_family(tasks[row["task_id"]])].append(row)
    return [{
        "construct": construct,
        "domain": tasks[rows[0]["task_id"]]["domain"],
        "panel": tasks[rows[0]["task_id"]]["panel"],
        "successful_units": sum(row["score_credit"] is True for row in rows),
        "planned_units": len(rows),
        "metric": "objective_success", "unit": "percent",
        "value": 100 * sum(row["score_credit"] is True for row in rows) / len(rows),
    } for construct, rows in sorted(grouped.items())]


def _family(task: dict) -> str:
    return task["construct"] if task["domain"] == "strategic_behavior" else task["domain"]


def load_history(root: Path, definition, *, repo: Path, now: datetime | None = None) -> dict[str, Any]:
    from bench.stable_benchmark.manifest import validate_run_manifest
    from bench.stable_benchmark.receipt_verification import verify_registered_arm
    from bench.stable_benchmark.projection import program_projection

    tasks = {task["id"]: task for task in definition.document["tasks"]}
    current = now or datetime.now(timezone.utc)
    rows, warnings, eligible = [], [], []
    registered = _registered_arms(repo, root, definition, current)
    directories = []
    for cohort in _directories(root / "runs"):
        directories.extend(_directories(cohort))
        if len(directories) > MAX_RUNS:
            raise ValueError("run history exceeds registered read bound")
    directories = sorted(set(directories) | set(registered))
    if len(directories) > MAX_RUNS:
        raise ValueError("registered history exceeds read bound")
    for directory in directories:
        row = {"comparison_id": directory.parent.name, "arm_id": directory.name,
               "label": directory.name, "admission_status": "not_evaluated",
               "observed_terminal_status": "pending_receipt", "results": [],
               "started_at": None, "finished_at": None, "week": None,
               "wall_seconds": None, "model_calls": None, "policy": None, "role": None,
               "registered_at": None}
        rows.append(row)
        try:
            if directory not in registered:
                row["admission_status"] = "withheld_unregistered"
                warnings.append(f"{directory.parent.name}/{directory.name}: no source-controlled registration; scores withheld.")
                continue
            registration, registered_arm = registered[directory]
            row["role"] = registered_arm["role"]
            row["registered_at"] = registration.document["registered_at"]
            run, run_sha = read_document(directory / "run.json")
            if (run.get("comparison_id") != directory.parent.name or
                    run.get("arm_id") != directory.name or
                    run.get("definition_sha256") != definition.raw_sha256):
                raise ValueError("run identity differs from registered path or release")
            row.update(started_at=_timestamp(run.get("started_at")),
                       finished_at=_timestamp(run.get("finished_at")))
            if row["finished_at"] is None:
                raise ValueError("terminal run receipt has no finish time")
            finished = datetime.fromisoformat(row["finished_at"].replace("Z", "+00:00"))
            if finished > current:
                raise ValueError("run receipt is in the future")
            if row["started_at"]:
                started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
                published = datetime.fromisoformat(definition.document["freeze"]["published_at"].replace("Z", "+00:00"))
                expires = datetime.fromisoformat(definition.document["freeze"]["review_at"].replace("Z", "+00:00"))
                if started < published or started >= expires or finished < started:
                    raise ValueError("run timing differs from the frozen execution window")
            stamp = row["started_at"] or row["finished_at"]
            if stamp:
                iso = datetime.fromisoformat(stamp.replace("Z", "+00:00")).isocalendar()
                row["week"] = f"{iso.year}-W{iso.week:02}"
            manifest_path = directory / "run-manifest.snapshot.json"
            if not manifest_path.exists():
                # An unissued arm has no execution snapshot. Its original
                # preregistered manifest still identifies the intended route.
                manifest_path = root / "manifests" / f"{directory.parent.name}.{directory.name}.json"
            manifest, manifest_sha = read_document(manifest_path)
            validate_run_manifest(manifest, definition)
            if (manifest_sha != run.get("run_manifest_sha256") or
                    manifest["comparison_id"] != directory.parent.name or
                    manifest["arm"]["id"] != directory.name):
                raise ValueError("run manifest identity differs")
            verified = verify_registered_arm(registration, directory.name, definition=definition)
            if verified.manifest_sha256 != manifest_sha or verified.run_sha256 != run_sha:
                raise ValueError("receipt changed during registered verification")
            row["label"] = manifest["arm"]["label"]
            row["policy"] = {
                "role_map": manifest["arm"]["role_map"],
                "routes": {key: {field: route[field] for field in
                                 ("backend", "model", "profile", "expected_policy", "runtime_identity")}
                           for key, route in manifest["arm"]["routes"].items()},
                "harness_source_sha256": manifest["harness_identity"]["source_sha256"],
            }
            replays = ([(verified.replay, verified.replay_sha256)] if verified.replay else [])
            admissions = ([(verified.admission, verified.admission_sha256)] if verified.admission else [])
            projected = program_projection(definition, run_receipts=[(run, run_sha)],
                                           replay_receipts=replays, admission_receipts=admissions)
            if len(projected["runs"]) != 1:
                raise ValueError("run receipt schema is invalid")
            public = projected["runs"][0]
            row.update({key: public[key] for key in (
                "run_id", "observed_terminal_status", "replay_status", "admission_status")})
            if (row["observed_terminal_status"] == "unissued" and
                    isinstance(run.get("outcomes"), list) and
                    len(run["outcomes"]) == len(tasks) and
                    all(isinstance(item, dict) and item.get("cell_status") == "unissued"
                        and type(item.get("model_calls")) is int and item["model_calls"] == 0
                        for item in run["outcomes"])):
                row["model_calls"] = 0
            if (public["admission_status"] == "admitted" and
                    public["replay_status"] == "verified" and
                    len(public["task_outcomes"]) == len(tasks) and
                    not (public.get("summary") or {}).get("error")):
                row["results"] = _construct_results(public["task_outcomes"], tasks)
                row["wall_seconds"] = _number(run.get("elapsed_s"))
                row["model_calls"] = sum(item["model_calls"] for item in public["task_outcomes"])
                row["completed_units"] = len(public["task_outcomes"])
                row["definition_sha256"] = definition.raw_sha256
                row["receipt_sha256"] = run_sha
                eligible.append((row, public["task_outcomes"]))
            elif row["admission_status"] == "admitted":
                row["admission_status"] = "withheld_invalid_replay"
        except FileNotFoundError:
            row["admission_status"] = "awaiting_artifacts"
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            row["admission_status"] = "withheld_invalid_artifacts"
            row["results"] = []
            warnings.append(f"{directory.parent.name}/{directory.name}: evidence is incomplete or invalid; scores withheld.")
    rows.sort(key=lambda row: (_instant(row["registered_at"]),
                              _instant(row["finished_at"] or row["started_at"]),
                              row["comparison_id"], row["arm_id"]))
    eligible.sort(key=lambda pair: (_instant(pair[0]["finished_at"]), pair[0]["arm_id"]))
    return {"history": rows, "eligible": eligible, "warnings": warnings}


def matched_results(eligible: list[tuple[dict, list[dict]]], tasks: dict) -> list[dict]:
    """Report observed paired deltas. A tiny fixed canary is not a population CI."""
    cohorts: dict[str, list] = defaultdict(list)
    for item in eligible:
        cohorts[item[0]["comparison_id"]].append(item)
    results = []
    for cohort, arms in sorted(cohorts.items()):
        if len(arms) != 2:
            continue
        # Reference and challenger are preregistered, never inferred from timing or score.
        if {pair[0].get("role") for pair in arms} != {"reference", "candidate"}:
            continue
        arms.sort(key=lambda pair: pair[0]["role"] != "reference")
        (left, left_rows), (right, right_rows) = arms
        right_by_id = {row["task_id"]: row for row in right_rows}
        constructs: dict[str, list] = defaultdict(list)
        for row in left_rows:
            constructs[_family(tasks[row["task_id"]])].append((row, right_by_id[row["task_id"]]))
        for construct, pairs in sorted(constructs.items()):
            lc = sum(l["score_credit"] for l, _ in pairs)
            rc = sum(r["score_credit"] for _, r in pairs)
            task = tasks[pairs[0][0]["task_id"]]
            results.append({
                "comparison_id": cohort, "domain": task["domain"], "mechanism": construct,
                "panel": task["panel"], "baseline_arm": left["label"], "candidate_arm": right["label"],
                "baseline_value": 100 * lc / len(pairs), "candidate_value": 100 * rc / len(pairs),
                "delta": 100 * (rc - lc) / len(pairs), "metric": "objective_success",
                "unit": "percent", "n_pairs": len(pairs),
                "discordant_counts": {
                    "baseline_only": sum(l["score_credit"] and not r["score_credit"] for l, r in pairs),
                    "candidate_only": sum(r["score_credit"] and not l["score_credit"] for l, r in pairs)},
                "uncertainty": {"method": "fixed_panel_descriptive_no_population_interval", "lower": None, "upper": None},
                "window": {"started_at": min(left["started_at"], right["started_at"], key=_instant),
                           "ended_at": max(left["finished_at"], right["finished_at"], key=_instant)},
                "status": "admitted_descriptive_canary",
            })
    return results
