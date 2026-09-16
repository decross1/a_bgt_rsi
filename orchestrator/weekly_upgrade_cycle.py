"""Default-off owner for one bounded weekly review and admitted trial.

The existing frontier-agenda cron may invoke this module only behind its
explicit enable flag.  A cycle refreshes an allowlisted source packet, runs
the two-provider subscription review, and optionally executes one exact
registered manifest when that manifest matches the validated review card.
It never selects a change, promotes a result, retries a reserved frontier
call, or creates a schedule.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from orchestrator import weekly_upgrade as review
from orchestrator import weekly_upgrade_trial as trial
from orchestrator.weekly_upgrade_budget import BudgetLedger
from orchestrator.weekly_stable_benchmark_report import (
    build_weekly_benchmark_snapshot,
    inspect_weekly_review_context,
)

SCHEMA_VERSION = "weekly-upgrade-cycle/v1"
PLAN_VERSION = "weekly-upgrade-cycle-plan/v1"
SOURCE_VERSION = "weekly-upgrade-cycle-source/v1"
DEFAULT_REVIEW_DEADLINE_S = 600
DEFAULT_CALL_TIMEOUT_S = 300
DEFAULT_CYCLE_DEADLINE_S = 3_300
DEFAULT_FETCH_DEADLINE_S = 60
DEFAULT_MAX_GPU_MINUTES = 120
MAX_CYCLE_DEADLINE_S = 7_200
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_JSONL_BYTES = 16 * 1024 * 1024
MAX_JSONL_ROWS = 20_000
FRONTIER_CALL_BUDGET = 2
NORMAL_REVIEW_STATUSES = frozenset({
    "NO_CHANGE", "REVISION_REQUIRED", "CONTINUE_TRIAL",
})


class CycleError(RuntimeError):
    """The weekly cycle cannot proceed without weakening a declared gate."""


@contextmanager
def _termination_cleanup() -> Iterator[None]:
    """Turn the cron backstop's TERM into unwinding so child groups are killed."""
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        raise CycleError("weekly cycle termination requested")

    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _week(value: datetime) -> tuple[str, datetime, datetime]:
    moment = value.astimezone(timezone.utc)
    start = datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc)
    start -= timedelta(days=start.weekday())
    iso_year, iso_week, _ = moment.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}", start, start + timedelta(days=7)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CycleError(f"value is not canonical JSON: {exc}") from exc


def _sha(value: Any) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path, *, maximum: int = MAX_JSON_BYTES) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CycleError(f"artifact is absent or redirected: {path}")
    raw = path.read_bytes()
    if len(raw) > maximum:
        raise CycleError(f"artifact exceeds {maximum} bytes: {path}")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CycleError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CycleError(f"artifact root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(value) + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSONL_BYTES:
        raise CycleError(f"JSONL artifact is oversized or redirected: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, start=1):
            if number > MAX_JSONL_ROWS:
                raise CycleError(f"JSONL artifact has too many rows: {path}")
            try:
                row = json.loads(
                    raw,
                    object_pairs_hook=_unique_object,
                    parse_constant=lambda token: (_ for _ in ()).throw(
                        ValueError(f"non-finite JSON number {token}")
                    ),
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise CycleError(f"invalid JSONL row {path}:{number}: {exc}") from exc
            if not isinstance(row, dict):
                raise CycleError(f"non-object JSONL row {path}:{number}")
            rows.append(row)
    return rows


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _load_bounded_source_packet(path: Path) -> dict[str, Any]:
    packet = _read_json(path, maximum=2_000_000)
    review._validate("source_packet", packet)
    urls = [source["url"] for source in packet["sources"]]
    if len(urls) != len(set(urls)):
        raise CycleError("source packet contains a duplicate URL")
    return packet


def _check_output_root(repo_root: Path, canonical_root: Path, output_root: Path) -> None:
    lexical = output_root.expanduser().absolute()
    resolved = output_root.expanduser().resolve()
    if lexical != resolved:
        raise CycleError("output root cannot traverse symlinks")
    for repository in {repo_root.resolve(), canonical_root.resolve()}:
        if resolved == repository or repository in resolved.parents:
            raise CycleError("output root must be outside canonical and execution checkouts")
    if resolved.exists() and (resolved.is_symlink() or not resolved.is_dir()):
        raise CycleError("output root must be a real directory when it exists")


def _weekly_claim_path(canonical_root: Path, week_id: str) -> Path:
    run_state = canonical_root / "run_state"
    if run_state.is_symlink() or not run_state.is_dir():
        raise CycleError("canonical run_state directory is absent or redirected")
    parent = run_state
    for name in ("weekly_upgrade", "cycles"):
        parent = parent / name
        if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
            raise CycleError("canonical weekly cycle directory is redirected")
    return parent / f"{week_id}.json"


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=repo_root, text=True, timeout=10,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.SubprocessError as exc:
        raise CycleError("weekly cycle requires a readable Git checkout") from exc


def _source_spec(
    *, source_packet: Path | None, fetch_config: Path | None,
) -> dict[str, Any]:
    if (source_packet is None) == (fetch_config is None):
        raise CycleError("choose exactly one fresh source packet or fetch config")
    lexical = (source_packet or fetch_config).expanduser().absolute()  # type: ignore[union-attr]
    if lexical.is_symlink():
        raise CycleError("source input is absent or redirected")
    path = lexical.resolve()
    if lexical != path or not path.is_file():
        raise CycleError("source input is absent or redirected")
    if source_packet is not None:
        _load_bounded_source_packet(path)
        mode = "packet"
    else:
        value = _read_json(path)
        review._validate("fetch_config", value)
        mode = "fetch"
    return {"mode": mode, "path": str(path), "sha256": _file_sha(path)}


def _packet_is_fresh(
    packet: dict[str, Any], start: datetime, end: datetime, observed_at: datetime,
) -> bool:
    sources = packet.get("sources")
    if not isinstance(sources, list) or not sources:
        return False
    for source in sources:
        accessed = _parse_time(source.get("accessed_at")) if isinstance(source, dict) else None
        if accessed is None or not start <= accessed < end or accessed > observed_at:
            return False
    return True


def _default_subscription_probe(vendor: str) -> tuple[bool, str]:
    """Check CLI and subscription auth without making a model request."""
    from agent_wrapper import maintenance_frontier as transport

    try:
        with tempfile.TemporaryDirectory(prefix="weekly-cycle-ready-") as directory:
            env = transport._environment()
            deadline = time.monotonic() + 10
            binary, _, _ = transport._preflight(vendor, env, directory, deadline)
            if vendor == "codex":
                transport._codex_auth()
            else:
                result = transport._run(
                    [binary, "auth", "status"], env=env, cwd=directory,
                    deadline=deadline,
                )
                payload = json.loads(result.stdout)
                if (
                    result.returncode
                    or not payload.get("loggedIn")
                    or payload.get("authMethod") != "claude.ai"
                    or payload.get("apiProvider") != "firstParty"
                ):
                    raise ValueError("not subscription authenticated")
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return False, "subscription CLI/auth preflight failed"
    return True, "subscription CLI/auth available"


def _frontier_invoke(canonical_root: Path) -> Callable[..., dict[str, Any]]:
    from agent_wrapper.maintenance_frontier import invoke_maintenance_frontier

    cancel_paths = (
        canonical_root / "run_state" / "pause_frontier",
        canonical_root / "run_state" / "pause_weekly_upgrade",
    )

    def invoke(vendor, prompt, **kwargs):
        return invoke_maintenance_frontier(
            vendor, prompt, cancel_paths=cancel_paths, **kwargs,
        )

    return invoke


def _check(
    checks: list[dict[str, Any]], name: str, ok: bool, detail: str,
) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def readiness_report(
    repo_root: str | Path,
    output_root: str | Path,
    *,
    source_packet: str | Path | None = None,
    fetch_config: str | Path | None = None,
    trial_manifest: str | None = None,
    frontier_call_budget: int = FRONTIER_CALL_BUDGET,
    review_deadline_s: int = DEFAULT_REVIEW_DEADLINE_S,
    call_timeout_s: int = DEFAULT_CALL_TIMEOUT_S,
    cycle_deadline_s: int = DEFAULT_CYCLE_DEADLINE_S,
    fetch_deadline_s: int = DEFAULT_FETCH_DEADLINE_S,
    max_gpu_minutes: int = DEFAULT_MAX_GPU_MINUTES,
    now: datetime | None = None,
    environment: dict[str, str] | None = None,
    subscription_probe: Callable[[str], tuple[bool, str]] = _default_subscription_probe,
    trial_planner: Callable[..., dict[str, Any]] = trial.plan_trial,
) -> dict[str, Any]:
    """Return bounded readiness evidence; never fetch, call a model, or write."""
    root = Path(repo_root).expanduser().resolve()
    output = Path(output_root).expanduser()
    moment = now or _utcnow()
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise CycleError("readiness time must be timezone aware")
    moment = moment.astimezone(timezone.utc)
    week_id, _, _ = _week(moment)
    env = os.environ if environment is None else environment
    checks: list[dict[str, Any]] = []
    canonical = root
    try:
        canonical = trial.canonical_root(root)
        _check(checks, "canonical_checkout", True, "canonical checkout resolved")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        _check(checks, "canonical_checkout", False, "canonical checkout unavailable")

    try:
        top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
        _check(checks, "git_checkout", top == root, "execution checkout is exact")
    except CycleError:
        _check(checks, "git_checkout", False, "Git checkout unavailable")

    sentinel = canonical / "run_state" / "frontier_tos_ratified"
    _check(
        checks, "frontier_tos", sentinel.is_file() and not sentinel.is_symlink(),
        "frontier ToS sentinel present" if sentinel.is_file() else "frontier ToS sentinel absent",
    )
    pauses = [
        name for name in ("pause_frontier", "pause_weekly_upgrade")
        if (canonical / "run_state" / name).exists()
    ]
    if trial_manifest and (canonical / "run_state" / "pause_coordinator").exists():
        pauses.append("pause_coordinator")
    _check(
        checks, "pause_controls", not pauses,
        "no applicable pause control" if not pauses else f"active: {','.join(pauses)}",
    )
    _check(
        checks, "mock_mode", not env.get("MOCK_LLM"),
        "real transport required" if not env.get("MOCK_LLM") else "MOCK_LLM is set",
    )

    budget_ok = (
        type(frontier_call_budget) is int and frontier_call_budget == 2
        and type(review_deadline_s) is int and 0 < review_deadline_s <= 1_800
        and type(call_timeout_s) is int and 180 < call_timeout_s <= review_deadline_s
        and type(fetch_deadline_s) is int and 0 < fetch_deadline_s <= 120
        and type(cycle_deadline_s) is int and 0 < cycle_deadline_s <= MAX_CYCLE_DEADLINE_S
        and type(max_gpu_minutes) is int and 0 <= max_gpu_minutes <= 120
    )
    _check(checks, "declared_budgets", budget_ok, "bounded subscription/GPU budgets")

    try:
        _check_output_root(root, canonical, output)
        _check(checks, "output_root", True, "isolated output root")
    except CycleError as exc:
        _check(checks, "output_root", False, str(exc))

    source: dict[str, Any] | None = None
    try:
        source = _source_spec(
            source_packet=Path(source_packet) if source_packet is not None else None,
            fetch_config=Path(fetch_config) if fetch_config is not None else None,
        )
        fresh = True
        if source["mode"] == "packet":
            packet = _load_bounded_source_packet(Path(source["path"]))
            _, week_start, week_end = _week(moment)
            fresh = _packet_is_fresh(packet, week_start, week_end, moment)
        _check(
            checks, "source_input", fresh,
            (f"validated {source['mode']} input" if fresh
             else "explicit source packet is not current for this ISO week"),
        )
    except (
        CycleError, review.WeeklyUpgradeError, ValidationError, OSError,
        json.JSONDecodeError,
    ) as exc:
        _check(checks, "source_input", False, f"invalid source input: {type(exc).__name__}")

    required_s = (
        (fetch_deadline_s if source and source.get("mode") == "fetch" else 0)
        + review_deadline_s + 15
    )
    planned_trial: dict[str, Any] | None = None
    if trial_manifest is not None:
        try:
            if trial_manifest not in trial.TRIALS:
                raise CycleError("trial manifest is not in the fixed registry")
            planned_trial = trial_planner(trial_manifest, worktree=root, now=moment)
            if planned_trial["reservation_s"] > max_gpu_minutes * 60:
                raise CycleError("registered trial exceeds the declared weekly GPU cap")
            budget = review._budget_history(canonical, moment)
            if planned_trial["reservation_s"] > budget["remaining_s"]:
                raise CycleError("registered trial exceeds remaining weekly Spark budget")
            paths = [trial_manifest, *trial.DEPENDENCY_PATHS]
            clean = not _git(root, "status", "--porcelain", "--untracked-files=all", "--", *paths)
            if not clean:
                raise CycleError("registered trial dependencies are dirty")
            required_s += int(planned_trial["reservation_s"]) + 15
            _check(checks, "trial_registration", True, "fixed manifest is clean and registered")
        except (CycleError, trial.TrialError, ValidationError, OSError, ValueError):
            _check(checks, "trial_registration", False, "trial registration/readiness failed")
    else:
        _check(checks, "trial_registration", True, "review-only; trial activation absent")
    _check(
        checks, "cycle_deadline", budget_ok and cycle_deadline_s >= required_s,
        f"requires at least {required_s}s for declared worst case",
    )
    _, _, week_end = _week(moment)
    _check(
        checks, "week_boundary",
        budget_ok and moment + timedelta(seconds=cycle_deadline_s) <= week_end,
        "declared cycle remains inside one UTC ISO week",
    )

    try:
        claim_path = _weekly_claim_path(canonical, week_id)
        claim_ok = True
        if claim_path.exists():
            claim = _read_json(claim_path)
            claim_ok = (
                set(claim) == {
                    "schema_version", "week_id", "output_root", "cycle_dir",
                    "cycle_plan_sha256", "production_change_authorized",
                }
                and claim.get("schema_version") == "weekly-upgrade-cycle-claim/v1"
                and claim.get("week_id") == week_id
                and claim.get("output_root") == str(output.expanduser().resolve())
                and claim.get("production_change_authorized") is False
            )
        _check(
            checks, "weekly_owner", claim_ok,
            ("weekly output owner is available" if claim_ok
             else "this ISO week is bound to another output root"),
        )
    except (CycleError, OSError, ValueError):
        _check(checks, "weekly_owner", False, "canonical weekly owner claim is invalid")

    prerequisites_ok = all(item["ok"] for item in checks)
    for vendor in ("codex", "claude"):
        if not prerequisites_ok:
            ok, detail = False, "deferred because an earlier readiness gate failed"
        else:
            try:
                ok, detail = subscription_probe(vendor)
            except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError):
                ok, detail = False, "subscription CLI/auth preflight failed"
        _check(checks, f"subscription_{vendor}", ok, detail)

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "readiness",
        "week_id": week_id,
        "ready": all(item["ok"] for item in checks),
        "checks": checks,
        "source": source,
        "trial": ({
            "manifest": trial_manifest,
            "trial_id": planned_trial.get("trial_id"),
            "reservation_s": planned_trial.get("reservation_s"),
        } if planned_trial is not None else None),
        "production_change_authorized": False,
    }


@contextmanager
def owner_lock(canonical_root: Path, inherited_fd: int | None = None) -> Iterator[None]:
    """Share the agenda owner's lock; validate an inherited cron descriptor."""
    path = canonical_root / "run_state" / ".frontier-agenda-cron.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise CycleError("weekly frontier owner lock is redirected")
    if inherited_fd is not None:
        try:
            descriptor = os.fstat(inherited_fd)
            target = path.stat()
        except OSError as exc:
            raise CycleError("inherited agenda lock descriptor is unavailable") from exc
        if not stat.S_ISREG(descriptor.st_mode) or (
            descriptor.st_dev, descriptor.st_ino
        ) != (target.st_dev, target.st_ino):
            raise CycleError("inherited agenda lock descriptor has the wrong inode")
        try:
            fcntl.flock(inherited_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CycleError("inherited agenda lock is not owned by this cycle") from exc
        yield
        return

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "a+") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise CycleError("weekly frontier owner lock is not a regular file")
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CycleError("weekly frontier owner lock is already held") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _fresh_source(
    cycle_dir: Path,
    source: dict[str, Any],
    *,
    week_start: datetime,
    week_end: datetime,
    fetch_deadline_s: int,
    fetch_fn: Callable[..., dict[str, Any]],
    now_fn: Callable[[], datetime],
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_path = cycle_dir / "source_evidence.json"
    attempt_path = cycle_dir / "source_fetch_receipt.json"
    if _file_sha(Path(source["path"])) != source["sha256"]:
        raise CycleError("source input changed after readiness")
    if artifact_path.exists():
        artifact = _read_json(artifact_path)
        if (
            artifact.get("schema_version") != SOURCE_VERSION
            or artifact.get("source_input") != source
            or not isinstance(artifact.get("source_packet"), dict)
        ):
            raise CycleError("stored source evidence differs from the frozen source input")
        packet = artifact["source_packet"]
        review._validate("source_packet", packet)
        observed = now_fn()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise CycleError("source observation time must be timezone aware")
        if not _packet_is_fresh(
            packet, week_start, week_end, observed.astimezone(timezone.utc),
        ):
            raise CycleError("stored source evidence is empty or stale")
        if source["mode"] == "fetch":
            if not attempt_path.exists():
                raise CycleError("fetched evidence has no durable attempt receipt")
            attempt = _read_json(attempt_path)
            if attempt.get("status") == "reserved":
                _write_json(attempt_path, {
                    **attempt, "status": "completed",
                    "source_evidence_sha256": _file_sha(artifact_path),
                })
            elif (
                attempt.get("status") != "completed"
                or attempt.get("source_evidence_sha256") != _file_sha(artifact_path)
            ):
                raise CycleError("source-fetch receipt does not bind stored evidence")
        return packet, artifact

    if source["mode"] == "fetch":
        if attempt_path.exists():
            raise CycleError("source fetch was reserved but produced no durable evidence; no retry")
        _write_json(attempt_path, {
            "schema_version": "weekly-upgrade-source-fetch-receipt/v1",
            "status": "reserved", "source_input": source,
            "source_evidence_sha256": None,
        })
        result = fetch_fn(
            source["path"], total_deadline_s=fetch_deadline_s,
        )
        if _file_sha(Path(source["path"])) != source["sha256"]:
            raise CycleError("fetch config changed during source refresh")
        review._validate("fetch_result", result)
        packet = result["source_packet"]
        receipts = result["receipts"]
        summary = {
            "attempted": len(receipts),
            "fetched": sum(row.get("status") == "FETCHED_UNVERIFIED" for row in receipts),
            "failure_categories": dict(sorted(Counter(
                row.get("error_category") for row in receipts if row.get("error_category")
            ).items())),
            "fetch_result_sha256": _sha(result),
        }
    else:
        packet = _load_bounded_source_packet(Path(source["path"]))
        if _file_sha(Path(source["path"])) != source["sha256"]:
            raise CycleError("source packet changed while it was loaded")
        result = None
        summary = {
            "attempted": len(packet["sources"]),
            "fetched": len(packet["sources"]),
            "failure_categories": {},
            "fetch_result_sha256": None,
        }
    observed = now_fn()
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise CycleError("source observation time must be timezone aware")
    if not _packet_is_fresh(
        packet, week_start, week_end, observed.astimezone(timezone.utc),
    ):
        raise CycleError("weekly source refresh produced no current-week evidence")
    artifact = {
        "schema_version": SOURCE_VERSION,
        "source_input": source,
        "source_packet": packet,
        "source_packet_sha256": review._sha(packet),
        "fetch_result": result,
        "summary": summary,
    }
    _write_json(artifact_path, artifact)
    if source["mode"] == "fetch":
        attempt = _read_json(attempt_path)
        _write_json(attempt_path, {
            **attempt, "status": "completed",
            "source_evidence_sha256": _file_sha(artifact_path),
        })
    return packet, artifact


def _frontier_usage(
    canonical_root: Path, review_dir: Path, week_start: datetime, week_end: datetime,
) -> dict[str, Any]:
    canonical_rows = _read_jsonl(canonical_root / "run_state" / "frontier_calls.jsonl")
    weekly_rows = [
        row for row in canonical_rows
        if (timestamp := _parse_time(row.get("timestamp"))) is not None
        and week_start <= timestamp < week_end
    ]
    agenda_rows = [row for row in weekly_rows if row.get("role") == "agenda_synthesist"]
    receipt_rows = []
    receipts = review_dir / "receipts"
    if receipts.is_dir() and not receipts.is_symlink():
        for path in sorted(receipts.glob("*.json"))[:2]:
            receipt_rows.append(_read_json(path))
    review_ledger = _read_jsonl(review_dir / "frontier_calls.jsonl")
    trial_runs, _ = review._trial_history(canonical_root)
    evaluation_receipts, _ = review._evaluation_history(canonical_root, trial_runs)
    weekly_annotations = [
        item
        for receipt in evaluation_receipts
        if (recorded := _parse_time(receipt.get("recorded_at"))) is not None
        and week_start <= recorded < week_end
        for item in receipt.get("annotation_artifacts", [])
    ]

    def by_vendor(rows: list[dict[str, Any]]) -> dict[str, int]:
        return dict(sorted(Counter(
            str(row.get("vendor") or "unknown") for row in rows
        ).items()))

    actual_models: dict[str, set[str]] = {}
    requested_models: dict[str, set[str]] = {}
    for row in receipt_rows:
        vendor = str(row.get("vendor") or "unknown")
        transport = row.get("transport") if isinstance(row.get("transport"), dict) else {}
        actual_models.setdefault(vendor, set()).update(
            model for model in transport.get("model_ids", []) if isinstance(model, str)
        )
        requested = transport.get("requested_model")
        if isinstance(requested, str) and requested:
            requested_models.setdefault(vendor, set()).add(requested)

    agenda_ms = sum(
        float(row["duration_ms"]) for row in agenda_rows
        if isinstance(row.get("duration_ms"), (int, float))
        and not isinstance(row.get("duration_ms"), bool)
        and math.isfinite(float(row["duration_ms"]))
        and row["duration_ms"] >= 0
    )
    review_ms = sum(
        float(row["duration_ms"]) for row in review_ledger
        if isinstance(row.get("duration_ms"), (int, float))
        and not isinstance(row.get("duration_ms"), bool)
        and math.isfinite(float(row["duration_ms"]))
        and row["duration_ms"] >= 0
    )
    return {
        "week_subscription_attempts": {
            "agenda_observed": len(agenda_rows),
            "review_reserved": len(receipt_rows),
            "operator_claimed_annotation_artifacts": len(weekly_annotations),
            "agenda_review_observed": len(agenda_rows) + len(receipt_rows),
            "all_canonical_frontier_observed": len(weekly_rows),
        },
        "agenda_by_vendor": by_vendor(agenda_rows),
        "review_by_vendor": by_vendor(receipt_rows),
        "review_receipt_statuses": dict(sorted(Counter(
            str(row.get("status") or "unknown") for row in receipt_rows
        ).items())),
        "review_requested_models": {
            vendor: sorted(models) for vendor, models in sorted(requested_models.items())
        },
        "review_actual_model_ids": {
            vendor: sorted(models) for vendor, models in sorted(actual_models.items())
        },
        "observed_frontier_minutes": round((agenda_ms + review_ms) / 60_000, 6),
        "frontier_cost_usd": None,
        "note": (
            "Agenda/review attempt counts are receipt-based where available. "
            "Claimed annotation counts are separately operator-recorded and "
            "have no duration in this summary. "
            "the legacy agenda has no pre-call reservation, so interrupted "
            "unrecorded attempts cannot be reconstructed."
        ),
    }


def _agenda_outcomes(canonical_root: Path) -> dict[str, Any]:
    path = canonical_root / "memory" / "frontier_agenda.jsonl"
    rows = _read_jsonl(path)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        proposal_id = row.get("proposal_id")
        if isinstance(proposal_id, str):
            latest[proposal_id] = row
    return {
        "total": len(latest),
        "by_status": dict(sorted(Counter(
            str(row.get("status") or "unknown") for row in latest.values()
        ).items())),
    }


def _budget_usage(canonical_root: Path, now: datetime) -> dict[str, Any]:
    path = canonical_root / "run_state" / "weekly_upgrade_budget.jsonl"
    if not path.exists():
        return {
            "schema_version": "weekly-upgrade-budget-v1",
            "week_id": _week(now)[0],
            "limit_s": 7_200.0,
            "charged_s": 0.0,
            "remaining_s": 7_200.0,
            "status": "not_initialized",
        }
    snapshot = BudgetLedger(path).snapshot(now)
    return {**snapshot, "status": "validated"}


def _frontier_selection(environment: dict[str, str]) -> dict[str, Any]:
    """Freeze requested aliases without claiming that an alias is current/latest."""
    return {
        "codex": {
            "requested_model": environment.get("FRONTIER_CODEX_MODEL") or None,
            "requested_effort": environment.get("FRONTIER_CODEX_EFFORT") or None,
        },
        "claude": {
            "requested_model": environment.get("FRONTIER_CLAUDE_MODEL") or None,
            "requested_effort": None,
        },
        "selection_provenance": (
            "process_environment_explicit"
            if any(environment.get(key) for key in (
                "FRONTIER_CODEX_MODEL", "FRONTIER_CODEX_EFFORT", "FRONTIER_CLAUDE_MODEL",
            )) else "transport_default"
        ),
        "latest_model_claimed": False,
    }


def _cycle_plan(
    *, week_id: str, repo_root: Path, source: dict[str, Any], review_deadline_s: int,
    call_timeout_s: int, cycle_deadline_s: int, fetch_deadline_s: int,
    max_gpu_minutes: int, frontier_selection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": PLAN_VERSION,
        "week_id": week_id,
        "repo_root": str(repo_root),
        "repo_head": _git(repo_root, "rev-parse", "HEAD"),
        "source": source,
        "frontier_selection": frontier_selection,
        "review_budget": {
            "frontier_calls": FRONTIER_CALL_BUDGET,
            "total_deadline_s": review_deadline_s,
            "call_timeout_s": call_timeout_s,
            "max_gpu_minutes": max_gpu_minutes,
        },
        "cycle_deadline_s": cycle_deadline_s,
        "fetch_deadline_s": fetch_deadline_s,
        "production_change_authorized": False,
    }


def _load_or_create(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        observed = _read_json(path)
        if observed != expected:
            raise CycleError("existing weekly cycle plan differs; no call repeated")
        return observed
    _write_json(path, expected)
    return expected


def _pause_reason(canonical_root: Path, *, trial_enabled: bool) -> str | None:
    names = ["pause_frontier", "pause_weekly_upgrade"]
    if trial_enabled:
        names.append("pause_coordinator")
    active = [name for name in names if (canonical_root / "run_state" / name).exists()]
    return f"pause control active: {','.join(active)}" if active else None


def _trial_summary(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    evaluation = result.get("evaluation") if isinstance(result.get("evaluation"), dict) else None
    budget = result.get("budget_receipt") if isinstance(result.get("budget_receipt"), dict) else None
    return {
        "trial_id": result.get("trial_id"),
        "status": result.get("status"),
        "elapsed_s": result.get("elapsed_s"),
        "evaluation_sha256": evaluation.get("sha256") if evaluation else None,
        "execution_complete": evaluation.get("execution_complete") if evaluation else False,
        "charged_s": budget.get("charged_s") if budget else None,
        "semantic_benefit_measured": result.get("semantic_benefit_measured") is True,
        "production_change_authorized": False,
    }


def _report(
    *, cycle_dir: Path, plan: dict[str, Any], status: str,
    review_report: dict[str, Any] | None, trial_result: dict[str, Any] | None,
    source_artifact: dict[str, Any] | None, canonical_root: Path,
    now: datetime, reason: str,
) -> dict[str, Any]:
    _, week_start, week_end = _week(now)
    usage = _frontier_usage(canonical_root, cycle_dir / "review", week_start, week_end)
    result = {
        "schema_version": SCHEMA_VERSION,
        "mode": "cycle",
        "week_id": plan["week_id"],
        "cycle_plan_sha256": _sha(plan),
        "status": status,
        "reason": reason,
        "source": ({
            "source_packet_sha256": source_artifact.get("source_packet_sha256"),
            "summary": source_artifact.get("summary"),
        } if source_artifact else None),
        "review": ({
            "status": review_report.get("status"),
            "run_id": review_report.get("run_id"),
            "snapshot_sha256": review_report.get("snapshot_sha256"),
            "proposal_sha256": review_report.get("proposal_sha256"),
            "frontier_calls_used": review_report.get("frontier_calls_used"),
            "experiment_card_sha256": (
                _sha(review_report["experiment_card"])
                if review_report.get("experiment_card") is not None else None
            ),
        } if review_report else None),
        "trial": _trial_summary(trial_result),
        "usage": {
            "frontier": usage,
            "spark": _budget_usage(canonical_root, now),
        },
        "recommendation_outcomes": {
            "agenda": _agenda_outcomes(canonical_root),
            "weekly_review": review_report.get("status") if review_report else None,
            "trial": trial_result.get("status") if trial_result else None,
        },
        # This observation is refreshed even when the provider review is an
        # immutable same-week receipt. It performs no inference or runtime
        # inspection and does not alter the review/trial no-replay contract.
        "stable_benchmark": build_weekly_benchmark_snapshot(
            repo=canonical_root, observed_at=now,
        ),
        "production_change_authorized": False,
        "promotion_authorized": False,
        "recorded_at": _iso(now),
    }
    _write_json(cycle_dir / "cycle_report.json", result)
    return result


def _immutable_week_noop(
    *, canonical_root: Path, output_root: Path, repo_root: Path,
    week_id: str, now: datetime,
) -> dict[str, Any] | None:
    """Return a no-call status for a verified terminal review from another context."""
    lexical_output = output_root.expanduser().absolute()
    if (not lexical_output.exists() or lexical_output.is_symlink()
            or not lexical_output.is_dir() or lexical_output.resolve() != lexical_output):
        return None
    cycle_dir = lexical_output / week_id
    context = inspect_weekly_review_context(cycle_dir, week_id=week_id)
    if context["status"] != "terminal_immutable_review":
        return None
    claim_path = _weekly_claim_path(canonical_root, week_id)
    if not claim_path.exists():
        return None
    claim = _read_json(claim_path)
    expected_claim = {
        "schema_version": "weekly-upgrade-cycle-claim/v1",
        "week_id": week_id,
        "output_root": str(lexical_output),
        "cycle_dir": str(cycle_dir),
        "cycle_plan_sha256": context["cycle_plan_sha256"],
        "production_change_authorized": False,
    }
    if claim != expected_claim:
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "cycle",
        "week_id": week_id,
        "status": "IMMUTABLE_WEEK_REVIEWED",
        "reason": (
            "This UTC ISO week already has a verified terminal provider review under "
            "its original repository context. No source fetch, provider call, trial, "
            "or receipt rewrite was attempted."
        ),
        "weekly_review_context": context,
        "stable_benchmark": build_weekly_benchmark_snapshot(
            repo=repo_root, observed_at=now,
        ),
        "automatic_execution": False,
        "frontier_calls_repeated": False,
        "production_change_authorized": False,
        "promotion_authorized": False,
        "recorded_at": _iso(now),
    }


def _existing_trial_is_recoverable(
    canonical_root: Path, plan: dict[str, Any], output: Path,
) -> tuple[bool, dict[str, Any] | None]:
    ledger_path = canonical_root / "run_state" / "weekly_upgrade_budget.jsonl"
    if not ledger_path.exists():
        return True, None
    prior = BudgetLedger(ledger_path).existing(plan["trial_id"])
    if prior is None:
        return True, None
    journal_path = (
        canonical_root / "run_state" / "weekly_upgrade" / "trials"
        / f"{plan['trial_id']}.json"
    )
    if journal_path.is_file() and not journal_path.is_symlink():
        journal = _read_json(journal_path)
        if journal.get("plan") == plan and journal.get("output") == str(output.resolve()):
            return True, prior
    return False, prior


def run_cycle(
    repo_root: str | Path,
    output_root: str | Path,
    *,
    source_packet: str | Path | None = None,
    fetch_config: str | Path | None = None,
    trial_manifest: str | None = None,
    frontier_call_budget: int = FRONTIER_CALL_BUDGET,
    review_deadline_s: int = DEFAULT_REVIEW_DEADLINE_S,
    call_timeout_s: int = DEFAULT_CALL_TIMEOUT_S,
    cycle_deadline_s: int = DEFAULT_CYCLE_DEADLINE_S,
    fetch_deadline_s: int = DEFAULT_FETCH_DEADLINE_S,
    max_gpu_minutes: int = DEFAULT_MAX_GPU_MINUTES,
    inherited_lock_fd: int | None = None,
    now_fn: Callable[[], datetime] = _utcnow,
    monotonic_fn: Callable[[], float] = time.monotonic,
    subscription_probe: Callable[[str], tuple[bool, str]] = _default_subscription_probe,
    fetch_fn: Callable[..., dict[str, Any]] = review.fetch_sources_from_config,
    review_fn: Callable[..., dict[str, Any]] = review.run_review,
    frontier_invoke: Callable[..., dict[str, Any]] | None = None,
    trial_planner: Callable[..., dict[str, Any]] = trial.plan_trial,
    trial_executor: Callable[..., dict[str, Any]] = trial.execute_trial,
) -> dict[str, Any]:
    """Run or resume one weekly cycle. Reserved calls/trials are never replayed."""
    root = Path(repo_root).expanduser().resolve()
    output_input = Path(output_root).expanduser()
    canonical_root = trial.canonical_root(root)
    start = monotonic_fn()
    with owner_lock(canonical_root, inherited_lock_fd):
        initial_moment = now_fn()
        if initial_moment.tzinfo is None or initial_moment.utcoffset() is None:
            raise CycleError("cycle clock must be timezone aware")
        initial_moment = initial_moment.astimezone(timezone.utc)
        initial_week_id, _, _ = _week(initial_moment)
        immutable = _immutable_week_noop(
            canonical_root=canonical_root, output_root=output_input,
            repo_root=root, week_id=initial_week_id, now=initial_moment,
        )
        if immutable is not None:
            return immutable
        ready = readiness_report(
            root, output_input, source_packet=source_packet, fetch_config=fetch_config,
            trial_manifest=trial_manifest, frontier_call_budget=frontier_call_budget,
            review_deadline_s=review_deadline_s, call_timeout_s=call_timeout_s,
            cycle_deadline_s=cycle_deadline_s, fetch_deadline_s=fetch_deadline_s,
            max_gpu_minutes=max_gpu_minutes, now=now_fn(),
            subscription_probe=subscription_probe, trial_planner=trial_planner,
        )
        if not ready["ready"]:
            return {
                **ready, "mode": "cycle", "status": "READINESS_BLOCKED",
                "reason": "one or more readiness gates failed",
                "promotion_authorized": False,
            }

        output = output_input.resolve()
        moment = now_fn().astimezone(timezone.utc)
        week_id, week_start, week_end = _week(moment)
        cycle_dir = output / week_id
        source = ready["source"]
        assert isinstance(source, dict)
        plan = _cycle_plan(
            week_id=week_id, repo_root=root, source=source,
            review_deadline_s=review_deadline_s, call_timeout_s=call_timeout_s,
            cycle_deadline_s=cycle_deadline_s, fetch_deadline_s=fetch_deadline_s,
            max_gpu_minutes=max_gpu_minutes,
            frontier_selection=_frontier_selection(dict(os.environ)),
        )
        plan_path = cycle_dir / "cycle_plan.json"
        if plan_path.exists() and _read_json(plan_path) != plan:
            context = inspect_weekly_review_context(cycle_dir, week_id=week_id)
            recovery = context.get("recovery")
            detail = (
                recovery if isinstance(recovery, str)
                else "Use the original cycle_plan repository context or wait for the next UTC ISO week."
            )
            raise CycleError(
                "existing weekly cycle plan differs and is not a verified terminal "
                f"review; no call repeated. {detail}"
            )
        _load_or_create(plan_path, plan)
        _load_or_create(
            _weekly_claim_path(canonical_root, week_id),
            {
                "schema_version": "weekly-upgrade-cycle-claim/v1",
                "week_id": week_id,
                "output_root": str(output),
                "cycle_dir": str(cycle_dir),
                "cycle_plan_sha256": _sha(plan),
                "production_change_authorized": False,
            },
        )

        packet, source_artifact = _fresh_source(
            cycle_dir, source, week_start=week_start, week_end=week_end,
            fetch_deadline_s=fetch_deadline_s, fetch_fn=fetch_fn, now_fn=now_fn,
        )
        pause = _pause_reason(canonical_root, trial_enabled=trial_manifest is not None)
        if pause:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="PAUSED",
                review_report=None, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=now_fn(), reason=pause,
            )
        remaining = cycle_deadline_s - (monotonic_fn() - start)
        if remaining < review_deadline_s + 5:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="DEADLINE_BLOCKED",
                review_report=None, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=now_fn(), reason="cycle deadline cannot fund the frozen review budget",
            )

        before_review = now_fn()
        if before_review.tzinfo is None or before_review.utcoffset() is None:
            raise CycleError("cycle clock must remain timezone aware")
        if _week(before_review)[0] != week_id:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="WEEK_BOUNDARY_BLOCKED",
                review_report=None, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=before_review, reason="cycle crossed its frozen UTC ISO week",
            )

        review_dir = cycle_dir / "review"
        report = review_fn(
            root, review_dir, frontier_call_budget=frontier_call_budget,
            total_deadline_s=review_deadline_s, max_gpu_minutes=max_gpu_minutes,
            call_timeout_s=call_timeout_s, source_packet=packet,
            operational_history_root=output,
            review_target_manifest=trial_manifest,
            invoke_fn=frontier_invoke or _frontier_invoke(canonical_root),
        )
        if report.get("status") not in NORMAL_REVIEW_STATUSES:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="REVIEW_INCONCLUSIVE",
                review_report=report, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=now_fn(), reason="weekly review did not produce an actionable terminal result",
            )
        if report["status"] != "CONTINUE_TRIAL":
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="REVIEW_COMPLETE",
                review_report=report, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=now_fn(), reason="weekly review completed without an admitted trial",
            )
        if trial_manifest is None:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="AWAITING_TRIAL_ACTIVATION",
                review_report=report, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=now_fn(), reason="review admitted a card; explicit fixed-manifest activation is absent",
            )

        before_trial = now_fn()
        if before_trial.tzinfo is None or before_trial.utcoffset() is None:
            raise CycleError("cycle clock must remain timezone aware")
        if _week(before_trial)[0] != week_id:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="WEEK_BOUNDARY_BLOCKED",
                review_report=report, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=before_trial, reason="trial activation crossed the frozen UTC ISO week",
            )

        pause = _pause_reason(canonical_root, trial_enabled=True)
        if pause:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="PAUSED",
                review_report=report, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=now_fn(), reason=pause,
            )
        card = report.get("experiment_card")
        if not isinstance(card, dict) or card.get("fixture_manifest_path") != trial_manifest:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="TRIAL_BINDING_REJECTED",
                review_report=report, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=now_fn(), reason="activated manifest does not exactly match the admitted card",
            )
        planned = trial_planner(
            trial_manifest, worktree=root, review_dir=review_dir, now=now_fn(),
        )
        activation = {
            "schema_version": "weekly-upgrade-trial-activation/v1",
            "trial_manifest": trial_manifest,
            "trial_id": planned["trial_id"],
            "review_report_sha256": _file_sha(review_dir / "weekly_report.json"),
            "production_change_authorized": False,
        }
        _load_or_create(cycle_dir / "trial_activation.json", activation)
        remaining = cycle_deadline_s - (monotonic_fn() - start)
        needed = planned["reservation_s"] + trial.KILL_GRACE_S + trial.SUPERVISION_MARGIN_S + 5
        if remaining < needed:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="DEADLINE_BLOCKED",
                review_report=report, trial_result=None,
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=now_fn(), reason="remaining cycle deadline cannot fund the entire fixed trial",
            )

        trial_dir = cycle_dir / f"trial-{planned['trial_id']}"
        recoverable, prior = _existing_trial_is_recoverable(
            canonical_root, planned, trial_dir,
        )
        if not recoverable:
            return _report(
                cycle_dir=cycle_dir, plan=plan, status="TRIAL_ALREADY_ACCOUNTED",
                review_report=report, trial_result={
                    "trial_id": planned["trial_id"],
                    "status": prior.get("status") if prior else "unknown",
                    "elapsed_s": prior.get("elapsed_s") if prior else None,
                    "budget_receipt": prior,
                    "evaluation": None,
                    "semantic_benefit_measured": False,
                },
                source_artifact=source_artifact, canonical_root=canonical_root,
                now=now_fn(), reason="same-week trial id already belongs to another execution; no replay",
            )
        result = trial_executor(
            planned, trial_dir, worktree=root, review_dir=review_dir,
        )
        status = "TRIAL_COMPLETE" if result.get("status") == "completed" else "TRIAL_INCOMPLETE"
        return _report(
            cycle_dir=cycle_dir, plan=plan, status=status,
            review_report=report, trial_result=result,
            source_artifact=source_artifact, canonical_root=canonical_root,
            now=now_fn(), reason="registered trial returned a terminal controller receipt",
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="read-only readiness report")
    mode.add_argument("--run", action="store_true", help="run or resume one weekly cycle")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-packet", type=Path)
    source.add_argument("--fetch-config", type=Path)
    parser.add_argument("--trial-manifest")
    parser.add_argument("--frontier-call-budget", type=int, default=FRONTIER_CALL_BUDGET)
    parser.add_argument("--review-deadline-s", type=int, default=DEFAULT_REVIEW_DEADLINE_S)
    parser.add_argument("--call-timeout-s", type=int, default=DEFAULT_CALL_TIMEOUT_S)
    parser.add_argument("--cycle-deadline-s", type=int, default=DEFAULT_CYCLE_DEADLINE_S)
    parser.add_argument("--fetch-deadline-s", type=int, default=DEFAULT_FETCH_DEADLINE_S)
    parser.add_argument("--max-gpu-minutes", type=int, default=DEFAULT_MAX_GPU_MINUTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    inherited = os.environ.get("WEEKLY_UPGRADE_OWNER_LOCK_FD")
    try:
        inherited_fd = int(inherited) if inherited is not None else None
    except ValueError:
        print("weekly-upgrade-cycle: invalid inherited lock descriptor", file=sys.stderr)
        return 2
    kwargs = {
        "source_packet": args.source_packet,
        "fetch_config": args.fetch_config,
        "trial_manifest": args.trial_manifest,
        "frontier_call_budget": args.frontier_call_budget,
        "review_deadline_s": args.review_deadline_s,
        "call_timeout_s": args.call_timeout_s,
        "cycle_deadline_s": args.cycle_deadline_s,
        "fetch_deadline_s": args.fetch_deadline_s,
        "max_gpu_minutes": args.max_gpu_minutes,
    }
    try:
        if args.check:
            result = readiness_report(args.repo_root, args.output_root, **kwargs)
        else:
            with _termination_cleanup():
                result = run_cycle(
                    args.repo_root, args.output_root,
                    inherited_lock_fd=inherited_fd, **kwargs,
                )
        assert result is not None
        print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
        if result.get("status") in {
            "READINESS_BLOCKED", "PAUSED", "DEADLINE_BLOCKED",
            "REVIEW_INCONCLUSIVE", "TRIAL_BINDING_REJECTED",
            "TRIAL_ALREADY_ACCOUNTED", "TRIAL_INCOMPLETE",
            "WEEK_BOUNDARY_BLOCKED",
        } or result.get("ready") is False:
            return 3
        return 0
    except (
        CycleError, review.WeeklyUpgradeError, trial.TrialError, ValidationError, OSError,
        json.JSONDecodeError, ValueError,
    ) as exc:
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "production_change_authorized": False,
        }, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
