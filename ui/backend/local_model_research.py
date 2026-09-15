"""Bounded, read-only local R&D receipts, separate from weekly maintenance.

The projection reports recorded qualification state and computes descriptive
counts from hash-bound, validated paired runs. It never launches a model,
consumes weekly budget, publishes model text, or authorizes promotion.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RESEARCH_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research"
)
SCHEMA = "local-model-research-progress/v1"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_READ_BYTES = 32 * 1024 * 1024
FAMILIES = {"objective", "topic", "context", "portfolio", "diversity", "role_effort", "historical"}


class SourceError(ValueError):
    pass


class Reader:
    def __init__(self, root: Path):
        self.root = root.absolute()
        self.remaining = MAX_READ_BYTES
        if (not self.root.is_dir() or self.root.is_symlink()
                or self.root.resolve() != self.root):
            raise SourceError("Research receipt directory is unavailable.")

    def read(self, relative: str, *, digest: str | None = None):
        path = Path(relative)
        if (path.is_absolute() or not path.parts or str(path) != relative
                or any(part in {".", ".."} for part in path.parts)):
            raise SourceError("A receipt has an invalid relative path.")
        fds = []
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            fd = os.open(self.root, flags | os.O_DIRECTORY)
            fds.append(fd)
            for part in path.parts[:-1]:
                fd = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
                fds.append(fd)
            fd = os.open(path.name, flags, dir_fd=fd)
            fds.append(fd)
            before = os.fstat(fd)
            limit = min(8 * 1024 * 1024, self.remaining)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise SourceError("A receipt exceeds the regular-file read bound.")
            chunks = []
            left = limit + 1
            while left:
                chunk = os.read(fd, min(left, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                left -= len(chunk)
            raw = b"".join(chunks)
            self.remaining -= len(raw)
            after = os.fstat(fd)
            if (len(raw) > limit or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns):
                raise SourceError("A receipt changed while it was read.")
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise SourceError("A receipt is unreadable or redirected.") from exc
        finally:
            for fd in reversed(fds):
                os.close(fd)
        actual = hashlib.sha256(raw).hexdigest()
        if digest is not None and (not SHA.fullmatch(str(digest)) or digest != actual):
            raise SourceError("A paired-run source hash does not match its index.")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise SourceError("A receipt contains duplicate JSON keys.")
                result[key] = value
            return result

        def nonfinite(_):
            raise SourceError("A receipt contains a non-finite number.")

        try:
            value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
        except (UnicodeError, ValueError) as exc:
            raise SourceError("A receipt is not valid JSON.") from exc
        if not isinstance(value, dict):
            raise SourceError("A receipt is not a JSON object.")
        return value, actual


def _number(value):
    if type(value) not in {float, int} or not math.isfinite(value) or value < 0:
        return None
    return value


def _time(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def _qualification(reader, run_id):
    prefix = f"qualification-runs/{run_id}"
    try:
        row, digest = reader.read(f"{prefix}/result.json")
    except FileNotFoundError:
        row, digest = reader.read(f"{prefix}/state.json")
        if row.get("schema") not in {
            "qwen-flash-next-qualification-state/v1",
            "qwen-flash-next-qualification-state/v2",
            "qwen-flash-next-qualification-state/v3",
        } or row.get("run_id") != run_id:
            raise SourceError("An in-progress qualification has an invalid identity.")
        phase = row.get("phase")
        if phase not in {"preflight", "model_verification", "setup_quiescence", "sentinel_create", "resident_stop",
                         "candidate_start", "readiness", "ready_stabilization", "probes", "qualification_passed", "restoring",
                         "complete", "supervisor_recovered", "recovery_unknown"}:
            raise SourceError("A qualification phase is not recognized.")
        # A state file can outlive a process. Never label it as currently running.
        return {"id": run_id, "status": "unfinished_receipt", "phase": phase,
                "finished_at": None, "candidate_window_minutes": None, "minimum_memory_gib": None,
                "probe_count": None, "restoration": "unverified", "source_sha256": digest,
                "model_started": None}
    if (row.get("schema") not in {
            "qwen-flash-next-qualification-result/v1",
            "qwen-flash-next-qualification-result/v2",
            "qwen-flash-next-qualification-result/v3",
        }
            or row.get("run_id") != run_id or row.get("status") not in {"passed", "failed", "unknown"}
            or row.get("weekly_budget_debit") is not False
            or row.get("production_change_authorized") is not False):
        raise SourceError("A qualification result has an invalid contract.")
    restoration = row.get("restoration", {}).get("status")
    if restoration not in {"verified", "unknown"}:
        raise SourceError("Qualification restoration is not recorded.")
    if row["status"] == "passed" and (restoration != "verified" or row.get("probe_count") != 3):
        raise SourceError("A passing qualification lacks verified restoration.")
    from bench.flash_next_ab.harness import (
        HarnessError,
        validate_flash_qualification_files,
    )

    # Bind failed history to its original source plan too. Only a passing
    # result must satisfy current C0 admission, including all fixed probes.
    for name in ("plan.json", "launch-contract.snapshot.json"):
        reader.read(f"{prefix}/{name}")
    try:
        validation = validate_flash_qualification_files(
            receipt_path=reader.root / prefix / "result.json",
            qualification_plan_path=reader.root / prefix / "plan.json",
            contract_snapshot_path=reader.root / prefix / "launch-contract.snapshot.json",
            require_passed=row["status"] == "passed",
        )
        if validation["qualification_receipt_sha256"] != digest:
            raise SourceError("A qualification changed during source validation.")
    except HarnessError as exc:
        raise SourceError("A qualification failed source validation.") from exc
    gpu_s = _number(row.get("challenger_gpu_seconds"))
    return {"id": run_id, "status": row["status"], "phase": "complete",
            "finished_at": _time(row.get("finished_at")),
            "candidate_window_minutes": gpu_s / 60 if gpu_s is not None else None,
            "minimum_memory_gib": _number(row.get("min_mem_available_gib")),
            "probe_count": _number(row.get("probe_count")), "restoration": restoration,
            "model_started": False if row.get("challenger_gpu_seconds_basis") == "not_started" and gpu_s == 0 else True if gpu_s is not None and gpu_s > 0 else None,
            "source_sha256": digest}


def _comparison(reader, entry):
    from bench.flash_next_ab.compare import summarize_pair, validate_run
    from bench.flash_next_ab.harness import HarnessError, validate_qualification_receipt

    if not isinstance(entry, dict) or not ID.fullmatch(str(entry.get("id", ""))):
        raise SourceError("A comparison index entry has an invalid identity.")
    runs = {}
    indexed = {}
    hashes = {}
    for cohort in ("resident", "flash"):
        ref = entry.get(cohort)
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise SourceError("A comparison source reference is incomplete.")
        if not isinstance(ref["path"], str) or not ref["path"].startswith("evaluation/"):
            raise SourceError("A comparison source is outside the evaluation directory.")
        run, digest = reader.read(ref["path"], digest=ref["sha256"])
        if not isinstance(run.get("outcomes"), list) or len(run["outcomes"]) > 2048:
            raise SourceError("A comparison exceeds the task-run bound.")
        indexed[cohort] = validate_run(run, cohort)
        if any(row["family"] not in FAMILIES for row in indexed[cohort].values()):
            raise SourceError("A comparison contains an unregistered public family.")
        runs[cohort], hashes[cohort] = run, digest
        qualification = entry.get("qualifications", {}).get(cohort)
        expected = {"receipt", "artifacts"} if cohort == "resident" else {"receipt", "plan", "contract"}
        if not isinstance(qualification, dict) or set(qualification) != expected:
            raise SourceError("A comparison lacks bound qualification sources.")
        for path in qualification.values():
            if not isinstance(path, str):
                raise SourceError("A qualification reference is invalid.")
            reader.read(path)
        kwargs = {"receipt_path": reader.root / qualification["receipt"]}
        if cohort == "resident":
            kwargs["resident_artifacts_path"] = reader.root / qualification["artifacts"]
        else:
            kwargs.update(qualification_plan_path=reader.root / qualification["plan"],
                          contract_snapshot_path=reader.root / qualification["contract"])
        try:
            validate_qualification_receipt(run["plan"], cohort, **kwargs)
        except HarnessError as exc:
            raise SourceError("A comparison failed qualification source validation.") from exc
    summary = summarize_pair(runs["resident"], runs["flash"])
    families = []
    for family, row in summary["families"].items():
        arms = {cohort: {key: row["cohorts"][cohort][key] for key in (
            "declared", "attempted", "passed", "success_rate", "successful_task_runs_per_hour"
        )} for cohort in ("resident", "flash")}
        families.append({"family": family, "cohorts": arms, "comparison_eligible": row["comparison_eligible"],
                         "paired_success_delta": row["paired_success_delta"],
                         "equal_source_task_success_delta": row["equal_source_task_success_delta"],
                         "source_task_interval_95": row["source_task_cluster_resampling_95_interval"]})
    return {"id": entry["id"], "status": summary["status"], "comparison_eligible": summary["comparison_eligible"],
            "manifest_sha256": summary["manifest_sha256"], "run_sha256": hashes,
            "families": families, "promotion_authorized": False}


def project_local_research(root: Path | None = None):
    result = {"schema_version": SCHEMA, "status": "unavailable", "candidate": "Qwen3.8 Flash-Next",
              "accounting": "Local model R&D is outside the weekly maintenance allowance. Usage is recorded separately.",
              "qualification_runs": [], "comparisons": [], "warnings": [], "promotion_authorized": False,
              "evidence_note": "Recorded runtime qualification and public development fixtures. These do not establish scientific validity or authorize a production change."}
    if root is None:
        return result
    try:
        reader = Reader(root)
        directory = root / "qualification-runs"
        if directory.exists():
            if directory.is_symlink() or directory.resolve() != directory:
                raise SourceError("Qualification history is redirected.")
            children = []
            for child in directory.iterdir():
                children.append(child)
                if len(children) > 128:
                    raise SourceError("Qualification history exceeds the scan bound.")
            children.sort(key=lambda p: p.name, reverse=True)
            for child in children:
                if not ID.fullmatch(child.name) or not child.name.startswith("qfn-c0-"):
                    continue
                try:
                    result["qualification_runs"].append(_qualification(reader, child.name))
                except (ValueError, FileNotFoundError, TypeError, AttributeError):
                    result["warnings"].append("A qualification receipt is unavailable or invalid; its result is withheld.")
                if len(result["qualification_runs"]) == 12:
                    result["warnings"].append("Showing the 12 latest qualification receipts.")
                    break
        try:
            index, _ = reader.read("evaluation/dashboard-index.json")
        except FileNotFoundError:
            index = {"schema_version": "flash-next-dashboard-index/v1", "comparisons": []}
        entries = index.get("comparisons")
        if (index.get("schema_version") != "flash-next-dashboard-index/v1" or not isinstance(entries, list)
                or len(entries) > 32 or len({row.get("id") for row in entries if isinstance(row, dict)}) != len(entries)):
            raise SourceError("The comparison index is invalid.")
        for entry in entries[-4:]:
            try:
                result["comparisons"].append(_comparison(reader, entry))
            except (SourceError, ValueError, KeyError, TypeError, FileNotFoundError):
                result["warnings"].append("A paired comparison failed source validation; its scores are withheld.")
        if len(entries) > 4:
            result["warnings"].append("Showing the four latest paired comparisons.")
        result["status"] = "partial" if result["warnings"] else "available"
    except (SourceError, OSError, ValueError, TypeError):
        result["warnings"].append("Local model research sources are unavailable or invalid.")
    return result
