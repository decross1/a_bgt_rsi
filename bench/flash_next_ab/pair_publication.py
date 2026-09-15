"""Publish only a fully admitted, content-free Flash pair.

No production pair is published by importing this module. The caller must
explicitly invoke ``publish_pair`` after reviewing the frozen source contract.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REGISTERED_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research"
)
PAIR = re.compile(r"qfn-ab-[a-z0-9][a-z0-9._-]{0,63}\Z")
ENTRY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
INDEX_SCHEMA = "flash-next-dashboard-index/v1"
AGGREGATE_SCHEMA = "flash-next-content-free-aggregate/v1"
PROOF_SCHEMA = "flash-next-recorded-pair-admission/v1"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_INDEX_BYTES = 1 * 1024 * 1024
MAX_INDEX_ENTRIES = 32


class PublicationError(ValueError):
    pass


@dataclass(frozen=True)
class Prepared:
    pair_id: str
    aggregate_path: str
    aggregate_raw: bytes
    proof_path: str
    proof_raw: bytes
    index_entry: dict


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationError(message)


def _canonical(value: dict) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PublicationError("aggregate contains invalid JSON") from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_all(fd: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(fd, raw[offset:])
        _require(written > 0, "artifact write made no progress")
        offset += written


def _relative(root: Path, path: Path) -> str:
    _require(path.is_absolute() and not path.is_symlink(), "source path is not regular")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PublicationError("source is outside registered research root") from exc
    _require(
        relative.parts and all(part not in {".", ".."} for part in relative.parts),
        "source path is invalid",
    )
    return str(relative)


def _read(root: Path, relative: str, *, maximum: int = MAX_SOURCE_BYTES) -> bytes:
    """Open each path component without following links; reject growth."""
    path = Path(relative)
    _require(not path.is_absolute() and str(path) == relative and path.parts,
             "relative source path is invalid")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fds: list[int] = []
    try:
        fd = os.open(root, flags | os.O_DIRECTORY)
        fds.append(fd)
        for part in path.parts[:-1]:
            _require(part not in {".", ".."}, "relative source path is invalid")
            fd = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
            fds.append(fd)
        fd = os.open(path.name, flags, dir_fd=fd)
        fds.append(fd)
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum,
                 "source exceeds bounded regular-file limit")
        chunks = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        _require(
            len(raw) == before.st_size and len(raw) <= maximum
            and before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns,
            "source changed during bounded read",
        )
        return raw
    except OSError as exc:
        raise PublicationError("source is unavailable or redirected") from exc
    finally:
        for fd in reversed(fds):
            os.close(fd)


def _object(raw: bytes, label: str) -> dict:
    def unique(pairs):
        found = {}
        for key, value in pairs:
            _require(key not in found, f"{label} repeats a JSON key")
            found[key] = value
        return found

    try:
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError) as exc:
        raise PublicationError(f"{label} is malformed") from exc
    _require(isinstance(value, dict), f"{label} is not an object")
    return value


def _source(root: Path, path: Path, *, expected_sha: str | None = None) -> tuple[dict, dict]:
    relative = _relative(root, path)
    raw = _read(root, relative)
    digest = _sha(raw)
    if expected_sha is not None:
        _require(SHA.fullmatch(str(expected_sha)) is not None and digest == expected_sha,
                 "completed gate source hash changed")
    return {"path": relative, "sha256": digest}, _object(raw, relative)


def _qualification_refs(root: Path, window: dict, cohort: str) -> tuple[dict, dict]:
    source = window.get("qualification")
    _require(isinstance(source, dict), "qualification binding is unavailable")
    wanted = (
        {"receipt": "receipt", "plan": "qualification_plan",
         "contract": "contract_snapshot"}
        if cohort == "flash"
        else {"receipt": "receipt", "artifacts": "resident_artifacts"}
    )
    public = {}
    proof = {}
    for key, source_key in wanted.items():
        ref = source.get(source_key)
        _require(isinstance(ref, dict) and set(ref) == {"path", "sha256"},
                 "qualification reference is incomplete")
        source_ref, _ = _source(root, Path(ref["path"]), expected_sha=ref["sha256"])
        public[key] = source_ref["path"]
        proof[key] = source_ref
    if cohort == "flash":
        raw_contract = source.get("contract_raw")
        _require(isinstance(raw_contract, dict)
                 and set(raw_contract) == {"path", "sha256"},
                 "raw Flash contract reference is incomplete")
        proof["contract_raw"], _ = _source(
            root, Path(raw_contract["path"]), expected_sha=raw_contract["sha256"]
        )
    return public, proof


def _aggregate(summary: dict, pair_id: str, gate: dict, source_refs: dict,
               extended_plan: dict) -> dict:
    _require(
        summary.get("schema_version") == "flash-next-ab-comparison/v1"
        and summary.get("status") == "complete"
        and summary.get("comparison_eligible") is True
        and summary.get("promotion_authorized") is False
        and summary.get("causal_attribution") is None,
        "paired summary is incomplete or overclaims",
    )
    families = {}
    for name, row in summary["families"].items():
        _require(re.fullmatch(r"[a-z_]{1,40}", name) is not None,
                 "summary family is invalid")
        arms = {}
        for cohort in ("resident", "flash"):
            arm = row["cohorts"][cohort]
            arms[cohort] = {key: arm[key] for key in (
                "declared", "attempted", "passed", "success_rate",
                "wall_s_including_failures", "successful_task_runs_per_hour",
            )}
        families[name] = {
            "cohorts": arms,
            "task_runs": row["task_runs"],
            "resampling_units": row["resampling_units"],
            "paired_success_delta": row["paired_success_delta"],
            "equal_source_task_success_delta": row["equal_source_task_success_delta"],
            "source_task_interval_95": row[
                "source_task_cluster_resampling_95_interval"
            ],
            "paired_outcomes": {key: row[key] for key in (
                "both_passed_task_runs", "resident_only_passed_task_runs",
                "flash_only_passed_task_runs", "neither_passed_task_runs",
            )},
        }
    return {
        "schema_version": AGGREGATE_SCHEMA,
        "pair_id": pair_id,
        "admission_class": "RECORDED_COMPLETED_PAIR_ADMISSION",
        "status": "descriptive_complete",
        "comparison_eligible_at_recording": True,
        "manifest_sha256": summary["manifest_sha256"],
        "benchmark_plan_file_sha256": gate["flash"]["benchmark_plan_file_sha256"],
        "controller_source_bundle_sha256": extended_plan[
            "controller_source_bundle_sha256"
        ],
        "candidate_variant_id": extended_plan["candidate_variant_id"],
        "candidate_spec_sha256": extended_plan["candidate_spec_sha256"],
        "model_artifact_sha256": extended_plan["model_artifact_sha256"],
        "families": families,
        "harness_elapsed_s_excluding_candidate_startup_and_restoration": summary[
            "elapsed_s"
        ],
        "run_sha256": {
            cohort: source_refs[cohort]["run"]["sha256"]
            for cohort in ("resident", "flash")
        },
        "bootstrap_samples": summary["bootstrap_samples"],
        "bootstrap_seed": summary["bootstrap_seed"],
        "causal_attribution": None,
        "promotion_authorized": False,
        "limitations": [
            "Development-panel tasks, not hidden-set confirmation.",
            "Bundle contrast can mix model, quantization, runtime, policy and cache.",
            "Source-task resampling units are not a random population sample.",
            "Per-family wall includes failures and grading; harness elapsed includes its own setup and persistence.",
            "Harness elapsed excludes candidate cold startup and final window restoration.",
        ],
    }


def prepare_pair(
    root: Path,
    pair_id: str,
    *,
    gate_fn: Callable | None = None,
    summarize_fn: Callable | None = None,
) -> Prepared:
    """Validate and build deterministic bytes; does not mutate the root."""
    _require(PAIR.fullmatch(pair_id) is not None, "pair ID is invalid")
    root = root.absolute()
    _require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
             "research root is not a fixed regular directory")
    if gate_fn is None:
        from bench.flash_next_ab.extended_admission import validate_completed_pair

        gate_fn = validate_completed_pair
    if summarize_fn is None:
        from bench.flash_next_ab.compare import summarize_pair

        summarize_fn = summarize_pair
    plan_root = root / "evaluation/window-plans"
    run_root = root / "evaluation/runs"
    windows = {
        cohort: plan_root / f"{pair_id}.{cohort}.window.json"
        for cohort in ("resident", "flash")
    }
    outputs = {cohort: run_root / f"{pair_id}.{cohort}"
               for cohort in ("resident", "flash")}
    gate = gate_fn(windows["flash"], outputs["flash"],
                   windows["resident"], outputs["resident"])
    _require(
        isinstance(gate, dict) and gate.get("schema")
        == "flash-next-supervised-pair-validation/v1"
        and gate.get("pair_id") == pair_id
        and gate.get("promotion_authorized") is False
        and all(gate.get(cohort, {}).get("cohort") == cohort
                and gate[cohort].get("restoration_verified") is True
                and gate[cohort].get("benchmark_plan_file_sha256")
                == gate["flash"]["benchmark_plan_file_sha256"]
                for cohort in ("resident", "flash")),
        "completed-pair gate is not admitted",
    )
    refs = {}
    runs = {}
    qualifications = {}
    for cohort in ("resident", "flash"):
        receipt = gate[cohort]
        window_ref, window = _source(
            root, windows[cohort],
            expected_sha=(receipt["window_plan_sha256"] if cohort == "flash" else None),
        )
        _require(window.get("pair_id") == pair_id and window.get("cohort") == cohort,
                 "window identity differs from admitted pair")
        result_ref, result = _source(
            root, outputs[cohort] / "result.json",
            expected_sha=receipt["result_sha256"],
        )
        run_ref, run = _source(
            root, outputs[cohort] / "harness/run.json",
            expected_sha=receipt["harness_run_sha256"],
        )
        _require(result.get("window_plan_sha256") == window_ref["sha256"],
                 "saved result and frozen window differ")
        _require(result.get("status") == "complete" and run.get("status") == "complete",
                 "saved cohort is not complete")
        qualification, qualifier_refs = _qualification_refs(root, window, cohort)
        qualifications[cohort] = qualification
        refs[cohort] = {
            "window": window_ref, "result": result_ref, "run": run_ref,
            "qualifications": qualifier_refs,
        }
        runs[cohort] = run
    extended_ref, extended_plan = _source(
        root, outputs["flash"] / "extended-plan.json"
    )
    _require(
        extended_plan.get("pair_id") == pair_id
        and SHA.fullmatch(str(extended_plan.get("controller_source_bundle_sha256")))
        is not None,
        "frozen producer source bundle is unavailable",
    )
    refs["flash"]["extended_plan"] = extended_ref
    summary = summarize_fn(runs["resident"], runs["flash"])
    aggregate = _aggregate(summary, pair_id, gate, refs, extended_plan)
    aggregate_raw = _canonical(aggregate)
    aggregate_path = f"evaluation/aggregate-summaries/{pair_id}.json"
    proof = {
        "schema_version": PROOF_SCHEMA,
        "pair_id": pair_id,
        "admission_at_recording": gate,
        "sources": refs,
        "aggregate": {"path": aggregate_path, "sha256": _sha(aggregate_raw)},
        "controller_source_bundle_sha256": extended_plan[
            "controller_source_bundle_sha256"
        ],
        "source_replay_status": "verified_when_recorded_not_a_future_replay_claim",
        "promotion_authorized": False,
    }
    proof_raw = _canonical(proof)
    proof_path = f"evaluation/pair-proofs/{pair_id}.json"
    entry = {
        "id": pair_id,
        "resident": refs["resident"]["run"],
        "flash": refs["flash"]["run"],
        "qualifications": qualifications,
        "admission": {"path": proof_path, "sha256": _sha(proof_raw)},
        "aggregate": {"path": aggregate_path, "sha256": _sha(aggregate_raw)},
        "comparison_eligible_at_recording": True,
        "promotion_authorized": False,
    }
    return Prepared(pair_id, aggregate_path, aggregate_raw, proof_path, proof_raw, entry)


def _directory(root: Path, relative: str) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parts = Path(relative).parts
    _require(parts and all(part not in {".", ".."} for part in parts),
             "artifact directory is invalid")
    fd = os.open(root, flags)
    try:
        for part in parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _immutable(root: Path, relative: str, raw: bytes) -> None:
    parent = str(Path(relative).parent)
    leaf = Path(relative).name
    fd = _directory(root, parent)
    try:
        try:
            existing = _read(root, relative, maximum=MAX_INDEX_BYTES)
        except PublicationError as exc:
            if not isinstance(exc.__cause__, FileNotFoundError):
                raise
        else:
            _require(existing == raw, "immutable pair artifact already differs")
            return
        file_fd = os.open(
            leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=fd,
        )
        try:
            _write_all(file_fd, raw)
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
        os.fsync(fd)
    finally:
        os.close(fd)


def _index(root: Path) -> dict:
    try:
        raw = _read(root, "evaluation/dashboard-index.json", maximum=MAX_INDEX_BYTES)
    except PublicationError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return {"schema_version": INDEX_SCHEMA, "comparisons": []}
        raise
    value = _object(raw, "dashboard index")
    entries = value.get("comparisons")
    _require(
        value.get("schema_version") == INDEX_SCHEMA
        and isinstance(entries, list) and len(entries) <= MAX_INDEX_ENTRIES
        and all(isinstance(entry, dict)
                and ENTRY_ID.fullmatch(str(entry.get("id", ""))) is not None
                for entry in entries)
        and len({entry["id"] for entry in entries}) == len(entries),
        "existing dashboard index is invalid",
    )
    return value


def _reverify_before_index(root: Path, prepared: Prepared, gate_fn: Callable | None) -> None:
    """Recheck admission and raw references after artifact writes."""
    proof = _object(prepared.proof_raw, "pair proof")
    if gate_fn is None:
        from bench.flash_next_ab.extended_admission import validate_completed_pair

        gate_fn = validate_completed_pair
    pair_id = prepared.pair_id
    plans = root / "evaluation/window-plans"
    outputs = root / "evaluation/runs"
    current = gate_fn(
        plans / f"{pair_id}.flash.window.json", outputs / f"{pair_id}.flash",
        plans / f"{pair_id}.resident.window.json", outputs / f"{pair_id}.resident",
    )
    _require(current == proof["admission_at_recording"],
             "completed-pair gate changed before index publication")
    for cohort in ("resident", "flash"):
        source = proof["sources"][cohort]
        references = [source[key] for key in ("window", "result", "run")]
        references.extend(source["qualifications"].values())
        if cohort == "flash":
            references.append(source["extended_plan"])
        for reference in references:
            _require(
                _sha(_read(root, reference["path"])) == reference["sha256"],
                "recorded pair source changed before index publication",
            )


def publish_pair(
    root: Path,
    pair_id: str,
    *,
    gate_fn: Callable | None = None,
    summarize_fn: Callable | None = None,
    test_root_allowed: bool = False,
) -> Prepared:
    """Explicit append after completion; never evict or rewrite an old entry."""
    root = root.absolute()
    _require(test_root_allowed or root == REGISTERED_ROOT,
             "publication root is not registered")
    _require(root != REGISTERED_ROOT or (gate_fn is None and summarize_fn is None),
             "registered publication may not replace the completed-pair gate")
    _require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
             "research root is not a fixed regular directory")
    lock_dir = _directory(root, "evaluation")
    try:
        lock_fd = os.open(
            ".dashboard-publish.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=lock_dir,
        )
        try:
            _require(stat.S_ISREG(os.fstat(lock_fd).st_mode),
                     "dashboard publication lock is invalid")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            prepared = prepare_pair(root, pair_id, gate_fn=gate_fn,
                                    summarize_fn=summarize_fn)
            index = _index(root)
            matches = [entry for entry in index["comparisons"]
                       if entry["id"] == pair_id]
            if matches:
                _require(matches[0] == prepared.index_entry,
                         "published pair ID already has different source hashes")
                _immutable(root, prepared.aggregate_path, prepared.aggregate_raw)
                _immutable(root, prepared.proof_path, prepared.proof_raw)
                _reverify_before_index(root, prepared, gate_fn)
                return prepared
            _require(len(index["comparisons"]) < MAX_INDEX_ENTRIES,
                     "dashboard index is full; no historical entry may be evicted")
            _immutable(root, prepared.aggregate_path, prepared.aggregate_raw)
            _immutable(root, prepared.proof_path, prepared.proof_raw)
            _reverify_before_index(root, prepared, gate_fn)
            index = dict(index, comparisons=[*index["comparisons"],
                                             prepared.index_entry])
            encoded = _canonical(index)
            _require(len(encoded) <= MAX_INDEX_BYTES,
                     "dashboard index exceeds its read bound")
            temporary = ".dashboard-index." + uuid.uuid4().hex + ".tmp"
            temporary_fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=lock_dir,
            )
            try:
                _write_all(temporary_fd, encoded)
                os.fsync(temporary_fd)
            finally:
                os.close(temporary_fd)
            os.replace(temporary, "dashboard-index.json",
                       src_dir_fd=lock_dir, dst_dir_fd=lock_dir)
            os.fsync(lock_dir)
            return prepared
        finally:
            os.close(lock_fd)
    finally:
        os.close(lock_dir)
