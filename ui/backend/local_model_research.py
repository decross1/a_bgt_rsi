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


def _datetime(value):
    normalized = _time(value)
    return datetime.fromisoformat(normalized) if normalized is not None else None


def _registered_mia_spec(run_id: str):
    from bench.flash_next_ab.candidate_registry import MIA
    if run_id.startswith("qfn-mia-c0-"):
        return MIA
    from bench.flash_next_ab.followon_projection import spec_for_run_name
    return spec_for_run_name(run_id)


def _startup_evidence(reader: Reader, run_id: str, result: dict):
    """Record observed server start to first valid models response, if bound.

    This is a stage measurement, so a later probe/serialization failure can
    leave qualification failed while its earlier startup duration remains
    measurable. It never says anything about request TTFT or decode speed.
    """
    absent = {"startup_seconds": None, "startup_source_sha256": None,
              "startup_status": "not_recorded"}
    if result.get("schema") not in {
        "qwen-flash-next-qualification-result/v3",
        "qwen-flash-next-qualification-result/v4",
        "qwen-flash-next-qualification-result/v5",
    }:
        return absent
    relative = f"qualification-runs/{run_id}/readiness.json"
    try:
        ready, digest = reader.read(relative)
    except FileNotFoundError:
        return absent
    except SourceError:
        return dict(absent, startup_status="unavailable")
    try:
        if result["schema"].endswith(("/v4", "/v5")):
            spec = _registered_mia_spec(run_id)
            if spec is None:
                return dict(absent, startup_status="unavailable")
            expected = (spec.container_name, spec.image_id, spec.served_name,
                        spec.docker_memory_limit_bytes)
        else:
            from bench.flash_next_ab import qualification as q
            expected = (q.CONTAINER_NAME, q.IMAGE_ID, q.SERVED_MODEL,
                        q.DOCKER_MEMORY_LIMIT_BYTES)
    except (ImportError, AttributeError):
        return dict(absent, startup_status="unavailable")
    container = ready.get("container")
    if not isinstance(container, dict):
        return dict(absent, startup_status="unavailable")
    identifier = container.get("id")
    started = _datetime(container.get("started_at"))
    ready_at = _datetime(ready.get("ready_at"))
    run_started = _datetime(result.get("started_at"))
    run_finished = _datetime(result.get("finished_at"))
    quiet_started = _datetime(result.get("ready_quiescence_started_at"))
    elapsed = _number(result.get("elapsed_seconds"))
    if (
        not isinstance(identifier, str) or not SHA.fullmatch(identifier)
        or container.get("name") != expected[0]
        or container.get("image") != expected[1]
        or ready.get("models") != [expected[2]]
        or container.get("running") is not True
        or container.get("oom_killed") is not False
        or type(container.get("restart_count")) is not int
        or container["restart_count"] != 0
        or type(container.get("pid")) is not int
        or container["pid"] <= 0
        or container["pid"] != result.get("candidate_cgroup_pid")
        or result.get("candidate_cgroup_path")
           != f"/system.slice/docker-{identifier}.scope"
        or container.get("memory_limit_bytes") != expected[3]
        or container.get("memory_swap_total_bytes") != expected[3]
        or any(time is None for time in
               (started, ready_at, run_started, run_finished, quiet_started))
        or elapsed is None
    ):
        return dict(absent, startup_status="unavailable")
    duration = (ready_at - started).total_seconds()
    if (
        not run_started <= started <= ready_at <= quiet_started <= run_finished
        or (quiet_started - ready_at).total_seconds() > 10
        or not 0 < duration <= elapsed + 1
    ):
        return dict(absent, startup_status="unavailable")
    return {"startup_seconds": duration, "startup_source_sha256": digest,
            "startup_status": "recorded"}


def _mia_variant(reader: Reader, run_id: str, state_or_result: dict):
    """Use the literal v4/v5 registry and exact files, never endpoint text."""
    spec = _registered_mia_spec(run_id)
    if spec is None:
        return None
    try:
        from bench.flash_next_ab import qualification as q
        from bench.flash_next_ab.mia_candidate_integration import read_mia_contract

        prefix = f"qualification-runs/{run_id}"
        plan, _ = reader.read(f"{prefix}/plan.json")
        contract, contract_sha = reader.read(f"{prefix}/launch-contract.raw.json")
        snapshot, _ = reader.read(f"{prefix}/launch-contract.snapshot.json")
        fixed_contract, fixed_sha, _ = read_mia_contract(spec.contract_path, q)
        expected = q.plan_qualification(
            fixed_contract, fixed_sha, reader.root / prefix, spec=spec
        )
        candidate = {"id": spec.spec_id, "spec_sha256": spec.identity_sha256()}
    except Exception as exc:
        raise SourceError("Mia registered variant sources are unavailable.") from exc
    if (
        plan != expected
        or snapshot != contract
        or contract != fixed_contract
        or contract_sha != fixed_sha
        or state_or_result.get("candidate") != candidate
        or state_or_result.get("plan_sha256") != q.sha256(plan)
        or state_or_result.get("contract_sha256") != contract_sha
        or state_or_result.get("model_artifact_sha256") != spec.model_artifact_sha256()
        or plan.get("image_id") != spec.image_id
        or plan.get("served_model") != spec.served_name
        or plan.get("profile") != spec.profile
    ):
        raise SourceError("Mia registered variant sources differ.")
    return {
        "id": spec.spec_id,
        "repository": spec.repository,
        "revision": spec.revision,
        "served_model": spec.served_name,
        "image_id": spec.image_id,
        "model_artifact_sha256": spec.model_artifact_sha256(),
        "spec_sha256": spec.identity_sha256(),
        "qualification_profile": spec.profile,
        "mtp_speculative_tokens": spec.mtp_speculative_tokens,
        "max_model_len": spec.max_model_len,
        "kv_cache_memory_bytes": spec.kv_cache_memory_bytes,
        "evidence_class": "REGISTERED_SOURCE_ONLY",
    }


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
            "qwen-flash-next-qualification-state/v4",
            "qwen-flash-next-qualification-state/v5",
        } or row.get("run_id") != run_id:
            raise SourceError("An in-progress qualification has an invalid identity.")
        phase = row.get("phase")
        if phase not in {"preflight", "model_verification", "setup_quiescence", "sentinel_create", "resident_stop",
                         "candidate_start", "readiness", "ready_stabilization", "probes", "qualification_passed", "restoring",
                         "complete", "supervisor_recovered", "recovery_unknown"}:
            raise SourceError("A qualification phase is not recognized.")
        # A state file can outlive a process. Never label it as currently running.
        variant = _mia_variant(reader, run_id, row)
        if (row.get("schema") in {"qwen-flash-next-qualification-state/v4", "qwen-flash-next-qualification-state/v5"}) != (variant is not None):
            raise SourceError("An unfinished qualification variant differs.")
        return {"id": run_id, "status": "unfinished_receipt", "phase": phase,
                "finished_at": None, "candidate_window_minutes": None, "minimum_memory_gib": None,
                "probe_count": None, "restoration": "unverified", "source_sha256": digest,
                "model_started": None, "variant": variant,
                "failure_class": None, "startup_seconds": None,
                "startup_source_sha256": None, "startup_status": "not_recorded",
                "qualification_elapsed_seconds": None}
    if (row.get("schema") not in {
            "qwen-flash-next-qualification-result/v1",
            "qwen-flash-next-qualification-result/v2",
            "qwen-flash-next-qualification-result/v3",
            "qwen-flash-next-qualification-result/v4",
            "qwen-flash-next-qualification-result/v5",
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
    failure_class = row.get("failure_class")
    if failure_class not in {
        None, "experimental_startup_host_pageout_guardrail_abort",
        "other_qualification_failure", "restoration_unknown",
    }:
        raise SourceError("A qualification failure class is unsupported.")
    variant = _mia_variant(reader, run_id, row)
    if (row.get("schema") in {"qwen-flash-next-qualification-result/v4", "qwen-flash-next-qualification-result/v5"}) != (variant is not None):
        raise SourceError("A terminal qualification variant differs.")
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
        if variant is not None:
            if validation.get("variant_id") != variant["id"]:
                raise SourceError("Mia source validator selected another variant.")
            if row["status"] == "passed" and validation.get("admission_eligible") is not True:
                raise SourceError("Mia passing qualification was not admitted.")
            if validation.get("admission_eligible") is True:
                variant = dict(variant, evidence_class="QUALIFICATION_ADMITTED")
    except HarnessError as exc:
        raise SourceError("A qualification failed source validation.") from exc
    gpu_s = _number(row.get("challenger_gpu_seconds"))
    total_s = _number(row.get("elapsed_seconds"))
    startup = _startup_evidence(reader, run_id, row)
    return {"id": run_id, "status": row["status"], "phase": "complete",
            "finished_at": _time(row.get("finished_at")),
            "candidate_window_minutes": gpu_s / 60 if gpu_s is not None else None,
            "minimum_memory_gib": _number(row.get("min_mem_available_gib")),
            "probe_count": _number(row.get("probe_count")), "restoration": restoration,
            "model_started": False if row.get("challenger_gpu_seconds_basis") == "not_started" and gpu_s == 0 else True if gpu_s is not None and gpu_s > 0 else None,
            "source_sha256": digest, "variant": variant,
            "failure_class": failure_class,
            "qualification_elapsed_seconds": total_s, **startup}


def _comparison(reader, entry):
    from .local_model_pair_proof import project_proof_aware_pair

    return project_proof_aware_pair(reader, entry)


def _receipt_recorded_mtime(path: Path) -> int:
    """Order variants by receipt publication, not their differing prefixes.

    Metadata is used only for display order. Reader.read still performs the
    bounded nofollow admission for every receipt that reaches the projection.
    """
    try:
        directory = path.stat(follow_symlinks=False)
    except OSError:
        return 0
    if not stat.S_ISDIR(directory.st_mode):
        return directory.st_mtime_ns
    times = [directory.st_mtime_ns]
    for leaf in ("result.json", "state.json"):
        try:
            receipt = (path / leaf).stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(receipt.st_mode):
            times.append(receipt.st_mtime_ns)
    return max(times)


def project_local_research(root: Path | None = None):
    result = {"schema_version": SCHEMA, "status": "unavailable", "candidate": "Qwen3.8 Flash-Next candidates",
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
            children.sort(
                key=lambda p: (_receipt_recorded_mtime(p), p.name), reverse=True
            )
            for child in children:
                if not ID.fullmatch(child.name) or not (child.name.startswith(("qfn-c0-", "qfn-mia-c0-")) or _registered_mia_spec(child.name) is not None):
                    continue
                try:
                    result["qualification_runs"].append(_qualification(reader, child.name))
                except (ValueError, FileNotFoundError, TypeError, AttributeError):
                    result["warnings"].append("A qualification receipt is unavailable or invalid; its result is withheld.")
                if len(result["qualification_runs"]) == 12:
                    result["warnings"].append("Showing the 12 most recently recorded qualification receipts.")
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
