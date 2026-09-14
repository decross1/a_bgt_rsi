"""Workspace construction, locked-path patching, and bounded pytest sandbox."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import resource
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .manifest import REPO_ROOT, grader_source, sha256_json

SANDBOX_CONTRACT_VERSION = "bubblewrap-pytest-repair/v1"
DEFAULT_BWRAP = "/usr/bin/bwrap"
DEFAULT_PYTHON = "/home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python"

AUDIT_GUARD_SOURCE = r'''from __future__ import annotations
import json
import os
import sys

DENIED = {
    "socket.connect", "socket.bind", "socket.getaddrinfo",
    "subprocess.Popen", "os.system", "os.posix_spawn", "os.posix_spawnp",
    "os.fork", "os.forkpty", "os.kill", "os.killpg",
}

_WRITE = os.write
try:
    _AUDIT_FD = int(os.environ.pop("WEEKLY_AUDIT_FD"))
except (KeyError, TypeError, ValueError):
    _AUDIT_FD = None

def audit(event, args):
    if event not in DENIED:
        return
    try:
        if _AUDIT_FD is not None:
            _WRITE(_AUDIT_FD, (json.dumps({"event": event}, sort_keys=True) + "\n").encode())
    finally:
        raise PermissionError("operation denied by repair grader")

sys.addaudithook(audit)
'''

RESULT_PLUGIN_SOURCE = r'''from __future__ import annotations
import json
import os

_WRITE = os.write
_FD = int(os.environ.pop("WEEKLY_RESULT_FD"))
_TOKEN = os.environ.pop("WEEKLY_RESULT_TOKEN")
_REPORTS = []

def pytest_runtest_logreport(report):
    _REPORTS.append({
        "nodeid": report.nodeid,
        "phase": report.when,
        "outcome": report.outcome,
    })

def pytest_sessionfinish(session, exitstatus):
    payload = {
        "token": _TOKEN,
        "exitstatus": int(exitstatus),
        "reports": _REPORTS,
    }
    _WRITE(_FD, (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode())
'''

SUPERVISOR_SOURCE = r'''from __future__ import annotations
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--node", required=True)
parser.add_argument("--expected", type=int, required=True)
parser.add_argument("--max-output", type=int, required=True)
args = parser.parse_args()

result_r, result_w = os.pipe()
audit_r, audit_w = os.pipe()
token = secrets.token_hex(32)
env = dict(os.environ)
env.update({
    "PYTHONPATH": "/guard:/workspace",
    "WEEKLY_RESULT_FD": str(result_w),
    "WEEKLY_RESULT_TOKEN": token,
    "WEEKLY_AUDIT_FD": str(audit_w),
})
output_path = "/tmp/pytest-output.bin"
with open(output_path, "wb") as output:
    child = subprocess.Popen(
        [
            "/venv/bin/python", "-m", "pytest", "-q", args.node,
            "-p", "result_plugin", "-p", "no:cacheprovider",
            "--basetemp", "/tmp/pytest",
        ],
        stdin=subprocess.DEVNULL,
        stdout=output,
        stderr=subprocess.STDOUT,
        env=env,
        pass_fds=(result_w, audit_w),
    )
    child_returncode = child.wait()
os.close(result_w)
os.close(audit_w)

def bounded_read(fd, maximum):
    chunks = []
    total = 0
    while True:
        chunk = os.read(fd, min(65536, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            break
    os.close(fd)
    return b"".join(chunks)

receipt_raw = bounded_read(result_r, 1048576)
audit_raw = bounded_read(audit_r, 1048576)
with open(output_path, "rb") as handle:
    child_output = handle.read(args.max_output + 1)
output_truncated = len(child_output) > args.max_output

receipt = None
receipt_valid = False
try:
    lines = receipt_raw.splitlines()
    if len(lines) == 1:
        receipt = json.loads(lines[0])
        receipt_valid = (
            isinstance(receipt, dict)
            and set(receipt) == {"token", "exitstatus", "reports"}
            and receipt.get("token") == token
            and receipt.get("exitstatus") == child_returncode
            and isinstance(receipt.get("reports"), list)
        )
except (UnicodeDecodeError, json.JSONDecodeError):
    receipt_valid = False

reports = receipt.get("reports", []) if receipt_valid else []
reports_valid = all(
    isinstance(row, dict)
    and set(row) == {"nodeid", "phase", "outcome"}
    and isinstance(row["nodeid"], str)
    and row["phase"] in {"setup", "call", "teardown"}
    and row["outcome"] in {"passed", "failed", "skipped"}
    for row in reports
)
calls = [row for row in reports if row.get("phase") == "call"] if reports_valid else []
counts = {
    "passed": sum(row.get("outcome") == "passed" for row in calls),
    "failed": sum(row.get("outcome") == "failed" for row in calls),
    "errors": 0,
    "skipped": sum(row.get("outcome") == "skipped" for row in calls),
}
if receipt_valid and reports_valid and not calls and child_returncode != 0:
    counts["errors"] = 1
audit_events = len([line for line in audit_raw.splitlines() if line])
passed = (
    receipt_valid and reports_valid and child_returncode == 0
    and len(calls) == args.expected
    and counts == {"passed": args.expected, "failed": 0, "errors": 0, "skipped": 0}
    and audit_events == 0 and not output_truncated
)
payload = {
    "protocol": "trusted-pytest-supervisor/v1",
    "receipt_valid": receipt_valid and reports_valid,
    "child_returncode": child_returncode,
    "counts": counts,
    "passed": passed,
    "audit_event_count": audit_events,
    "output_sha256": hashlib.sha256(child_output).hexdigest(),
    "output_bytes": len(child_output),
    "output_truncated": output_truncated,
}
sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
'''


class SandboxUnavailable(RuntimeError):
    """The declared isolation boundary cannot be constructed."""


@dataclass(frozen=True)
class PatchResult:
    valid: bool
    code: str | None
    patch_sha256: str | None
    patch_bytes: int
    repaired_file_sha256: str | None = None


@dataclass(frozen=True)
class GraderResult:
    status: str
    passed: bool
    returncode: int | None
    timed_out: bool
    counts: dict[str, int]
    duration_s: float
    output_sha256: str
    output_bytes: int
    output_truncated: bool
    guard_event_count: int


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sandbox_runtime_identity(
    *, bwrap_path: str = DEFAULT_BWRAP, python_path: str = DEFAULT_PYTHON,
) -> dict[str, str]:
    executable = shutil.which(bwrap_path)
    python = Path(python_path)
    if executable is None or not Path(executable).is_file():
        raise SandboxUnavailable("bubblewrap is unavailable")
    if not python.is_file() or not os.access(python, os.X_OK):
        raise SandboxUnavailable("the pinned Python environment is unavailable")
    try:
        bwrap_version = subprocess.run(
            [executable, "--version"], capture_output=True, text=True,
            timeout=2, check=True,
        ).stdout.strip()
        versions = subprocess.run(
            [str(python), "-I", "-c", "import platform,pytest;print(platform.python_version());print(pytest.__version__)"],
            capture_output=True, text=True, timeout=3, check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxUnavailable("cannot identify the sandbox runtime") from exc
    if len(versions) != 2:
        raise SandboxUnavailable("Python or pytest version identity is incomplete")
    return {
        "contract": SANDBOX_CONTRACT_VERSION,
        "bubblewrap_path": str(Path(executable).resolve()),
        "bubblewrap_sha256": _sha_file(Path(executable).resolve()),
        "bubblewrap_version": bwrap_version,
        "python_path": str(python),
        "python_sha256": _sha_file(python.resolve()),
        "python_version": versions[0],
        "pytest_version": versions[1],
        "audit_guard_sha256": hashlib.sha256(AUDIT_GUARD_SOURCE.encode()).hexdigest(),
        "result_plugin_sha256": hashlib.sha256(RESULT_PLUGIN_SOURCE.encode()).hexdigest(),
        "supervisor_sha256": hashlib.sha256(SUPERVISOR_SOURCE.encode()).hexdigest(),
    }


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise SandboxUnavailable("Git archive contains an unsafe path")
    return path


def materialize_workspace(
    task: dict[str, Any], destination: Path, *, max_archive_bytes: int, max_files: int,
) -> None:
    """Export only the preregistered public allowlist from the exact base."""
    base = task["base"]
    paths = [*base["workspace_source_allowlist"], *base["workspace_fixture_allowlist"]]
    try:
        process = subprocess.run(
            ["git", "archive", "--format=tar", base["commit"], "--", *paths],
            cwd=REPO_ROOT, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=12, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxUnavailable("cannot export the registered base workspace") from exc
    if process.returncode != 0 or len(process.stdout) > max_archive_bytes:
        raise SandboxUnavailable("registered base workspace export failed or exceeded its bound")

    destination.mkdir(parents=True, exist_ok=False)
    total = 0
    count = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(process.stdout), mode="r:") as archive:
            for member in archive:
                relative = _safe_member(member.name)
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(0o755)
                    continue
                if not member.isfile():
                    raise SandboxUnavailable("Git archive contains a non-regular member")
                count += 1
                total += member.size
                if count > max_files or total > max_archive_bytes:
                    raise SandboxUnavailable("workspace content exceeds its frozen bound")
                stream = archive.extractfile(member)
                if stream is None:
                    raise SandboxUnavailable("cannot read a Git archive member")
                data = stream.read(max_archive_bytes + 1)
                if len(data) != member.size:
                    raise SandboxUnavailable("Git archive member size differs")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o644)
    except (tarfile.TarError, OSError) as exc:
        raise SandboxUnavailable("cannot materialize the bounded Git archive") from exc

    repair = destination / base["repair_path"]
    if not repair.is_file() or repair.is_symlink() or _sha_file(repair) != base["repair_sha256"]:
        raise SandboxUnavailable("materialized repair file differs from the registered base")


def _inventory(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("workspace contains a symlink")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = _sha_file(path)
    return result


def apply_candidate_patch(
    workspace: Path, *, allowed_path: str, patch: Any, max_patch_bytes: int,
) -> PatchResult:
    """Apply one unified diff after a closed path/header check."""
    if not isinstance(patch, str) or not patch:
        return PatchResult(False, "patch_missing", None, 0)
    encoded = patch.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if len(encoded) > max_patch_bytes:
        return PatchResult(False, "patch_too_large", digest, len(encoded))
    if "\x00" in patch or "GIT binary patch" in patch:
        return PatchResult(False, "patch_binary_or_nul", digest, len(encoded))
    forbidden = ("new file mode ", "deleted file mode ", "old mode ", "new mode ", "rename from ", "rename to ", "copy from ", "copy to ")
    if any(line.startswith(forbidden) for line in patch.splitlines()):
        return PatchResult(False, "patch_operation_forbidden", digest, len(encoded))
    expected_diff = f"diff --git a/{allowed_path} b/{allowed_path}"
    diff_headers = [line for line in patch.splitlines() if line.startswith("diff --git ")]
    old_headers = [line for line in patch.splitlines() if line.startswith("--- ")]
    new_headers = [line for line in patch.splitlines() if line.startswith("+++ ")]
    if diff_headers != [expected_diff] or old_headers != [f"--- a/{allowed_path}"] or new_headers != [f"+++ b/{allowed_path}"]:
        return PatchResult(False, "patch_path_or_header", digest, len(encoded))

    before = _inventory(workspace)
    try:
        checked = subprocess.run(
            ["git", "apply", "--check", "--whitespace=nowarn", "--"],
            cwd=workspace, input=encoded, capture_output=True,
            timeout=5, check=False,
        )
        if checked.returncode != 0:
            return PatchResult(False, "patch_does_not_apply", digest, len(encoded))
        applied = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "--"],
            cwd=workspace, input=encoded, capture_output=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return PatchResult(False, "patch_apply_error", digest, len(encoded))
    if applied.returncode != 0:
        return PatchResult(False, "patch_apply_error", digest, len(encoded))
    after = _inventory(workspace)
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    target = workspace / allowed_path
    if changed != {allowed_path} or not target.is_file() or target.is_symlink():
        return PatchResult(False, "patch_scope_violation", digest, len(encoded))
    return PatchResult(
        True, None, digest, len(encoded), repaired_file_sha256=_sha_file(target),
    )


def install_grader(task: dict[str, Any], workspace: Path) -> Path:
    relative = PurePosixPath(task["grader"]["sandbox_path"])
    target = workspace.joinpath(*relative.parts)
    if target.exists() or target.is_symlink():
        raise SandboxUnavailable("grader destination collides with the base workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(grader_source(task))
    target.chmod(0o444)
    return target


def _set_limits(timeout_s: float, max_output_bytes: int) -> None:
    cpu = max(1, math.ceil(timeout_s))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_output_bytes, max_output_bytes))


def run_grader(
    task: dict[str, Any], workspace: Path, *, bwrap_path: str, python_path: str,
    timeout_s: float, max_output_bytes: int, monotonic=time.monotonic,
) -> GraderResult:
    executable = shutil.which(bwrap_path)
    python = Path(python_path)
    if executable is None or not python.is_file():
        raise SandboxUnavailable("pinned grader executables are unavailable")
    with tempfile.TemporaryDirectory(prefix="weekly-historical-guard-") as raw_guard:
        guard = Path(raw_guard)
        (guard / "sitecustomize.py").write_text(AUDIT_GUARD_SOURCE, encoding="utf-8")
        (guard / "result_plugin.py").write_text(RESULT_PLUGIN_SOURCE, encoding="utf-8")
        (guard / "supervise.py").write_text(SUPERVISOR_SOURCE, encoding="utf-8")
        # Historical modules may emit explicitly noncanonical scratch run
        # telemetry during otherwise offline tests. Overlay only this path;
        # source and grader files remain read-only.
        mutable_run_state = guard / "run_state"
        mutable_run_state.mkdir()
        mutable_run_state.chmod(0o777)
        (workspace / "run_state").mkdir(exist_ok=True)
        output_path = guard / "pytest.txt"
        command = [
            executable, "--die-with-parent", "--unshare-all", "--cap-drop", "ALL",
            "--uid", "65534", "--gid", "65534", "--clearenv",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
        ]
        if Path("/lib64").is_dir():
            command += ["--ro-bind", "/lib64", "/lib64"]
        command += [
            "--ro-bind", str(python.parent.parent), "/venv",
            "--ro-bind", str(workspace), "/workspace",
            "--bind", str(mutable_run_state), "/workspace/run_state",
            "--ro-bind", str(guard), "/guard",
            "--dev", "/dev", "--tmpfs", "/tmp",
            "--dir", "/tmp/home", "--chdir", "/workspace",
            "--setenv", "HOME", "/tmp/home", "--setenv", "PATH", "/venv/bin:/usr/bin",
            "--setenv", "LANG", "C.UTF-8", "--setenv", "MOCK_LLM", "1",
            "--setenv", "CUDA_VISIBLE_DEVICES", "", "--setenv", "NVIDIA_VISIBLE_DEVICES", "void",
            "--setenv", "PYTHONPATH", "/guard:/workspace",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "PYTHONNOUSERSITE", "1",
            "--setenv", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1",
            "--", "/venv/bin/python", "-I", "/guard/supervise.py",
            "--node", task["grader"]["test_node"],
            "--expected", str(task["grader"]["expected_cases"]),
            "--max-output", str(max_output_bytes),
        ]
        started = monotonic()
        timed_out = False
        try:
            with output_path.open("wb") as output:
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=output,
                    stderr=subprocess.STDOUT,
                    env={"PATH": "/usr/bin", "LANG": "C.UTF-8"}, start_new_session=True,
                    preexec_fn=lambda: _set_limits(timeout_s, max_output_bytes),  # noqa: PLW1509
                )
                try:
                    process.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
        except OSError as exc:
            raise SandboxUnavailable("cannot start the bounded pytest sandbox") from exc
        duration = max(0.0, monotonic() - started)
        combined = output_path.read_bytes()[: max_output_bytes + 1]
        truncated = len(combined) > max_output_bytes
        display = combined[:max_output_bytes]
        audit_path = guard / "audit-events.jsonl"
        guard_events = len(audit_path.read_bytes().splitlines()) if audit_path.exists() else 0

    try:
        supervised = json.loads(display.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        supervised = None
    protocol_valid = (
        isinstance(supervised, dict)
        and set(supervised) == {
            "protocol", "receipt_valid", "child_returncode", "counts", "passed",
            "audit_event_count", "output_sha256", "output_bytes", "output_truncated",
        }
        and supervised.get("protocol") == "trusted-pytest-supervisor/v1"
        and supervised.get("receipt_valid") is True
    )
    counts = supervised.get("counts") if protocol_valid else {
        "passed": 0, "failed": 0, "errors": 1, "skipped": 0,
    }
    child_returncode = supervised.get("child_returncode") if protocol_valid else process.returncode
    child_truncated = supervised.get("output_truncated") is True if protocol_valid else truncated
    child_output_hash = supervised.get("output_sha256") if protocol_valid else hashlib.sha256(combined).hexdigest()
    child_output_bytes = supervised.get("output_bytes") if protocol_valid else len(combined)
    guard_events = supervised.get("audit_event_count") if protocol_valid else 0
    if timed_out:
        status = "timeout"
    elif truncated or child_truncated:
        status = "output_limit"
    elif guard_events:
        status = "guard_denial"
    elif protocol_valid and supervised.get("passed") is True:
        status = "passed"
    elif protocol_valid and child_returncode in {0, 1, 2, 3, 4, 5}:
        status = "failed"
    else:
        status = "error"
    return GraderResult(
        status=status, passed=status == "passed", returncode=child_returncode,
        timed_out=timed_out, counts=counts, duration_s=duration,
        output_sha256=child_output_hash, output_bytes=child_output_bytes,
        output_truncated=truncated or child_truncated, guard_event_count=guard_events,
    )


def grader_receipt_sha256(
    *, attempt_id: str, input_sha256: str, patch_sha256: str,
    grader_sha256: str, sandbox_identity: dict[str, str], result: GraderResult,
) -> str:
    return sha256_json({
        "attempt_id": attempt_id,
        "input_sha256": input_sha256,
        "patch_sha256": patch_sha256,
        "grader_sha256": grader_sha256,
        "sandbox_runtime_sha256": sha256_json(sandbox_identity),
        "result": {
            "status": result.status, "passed": result.passed,
            "returncode": result.returncode, "timed_out": result.timed_out,
            "counts": result.counts, "duration_s": result.duration_s,
            "output_sha256": result.output_sha256, "output_bytes": result.output_bytes,
            "output_truncated": result.output_truncated,
            "guard_event_count": result.guard_event_count,
        },
    })


__all__ = [
    "AUDIT_GUARD_SOURCE",
    "RESULT_PLUGIN_SOURCE",
    "SANDBOX_CONTRACT_VERSION",
    "SUPERVISOR_SOURCE",
    "GraderResult",
    "PatchResult",
    "SandboxUnavailable",
    "apply_candidate_patch",
    "grader_receipt_sha256",
    "install_grader",
    "materialize_workspace",
    "run_grader",
    "sandbox_runtime_identity",
]
