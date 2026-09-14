"""Execute one restricted generated function in a bounded bubblewrap process.

Expected answers never enter the sandbox.  The child returns only the function
value, exception type, and post-call arguments; the trusted parent grades them.
There is deliberately no host-execution fallback.
"""

from __future__ import annotations

import ast
import json
import math
import os
import resource
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BWRAP = "/usr/bin/bwrap"
DEFAULT_PYTHON = "/usr/bin/python3"
SANDBOX_CONTRACT_VERSION = "bubblewrap-python-function/v1"
_ALLOWED_CALLS = {
    "ValueError",
    "NotImplementedError",
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "float",
    "int",
    "isinstance",
    "len",
    "list",
    "max",
    "min",
    "range",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
}
_ALLOWED_METHODS = {"add", "append", "get", "items", "keys", "startswith", "values"}
_BANNED_NODES = (
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
    ast.Global,
    ast.Import,
    ast.ImportFrom,
    ast.Lambda,
    ast.Nonlocal,
    ast.Try,
    ast.With,
    ast.Yield,
    ast.YieldFrom,
)


@dataclass(frozen=True)
class SandboxResult:
    status: str
    value: Any = None
    exception_type: str | None = None
    input_mutated: bool | None = None
    detail: str | None = None


class SandboxUnavailable(RuntimeError):
    """The declared isolation boundary is unavailable."""


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sandbox_runtime_identity(
    *,
    bwrap_path: str = DEFAULT_BWRAP,
    python_path: str = DEFAULT_PYTHON,
) -> dict[str, str]:
    """Return content-addressed identity for the trusted sandbox executables."""
    bwrap = shutil.which(bwrap_path)
    if bwrap is None:
        raise SandboxUnavailable(f"bubblewrap is unavailable at {bwrap_path!r}")
    bwrap_file = Path(bwrap).resolve()
    python_file = Path(python_path).resolve()
    if not bwrap_file.is_file() or not os.access(bwrap_file, os.X_OK):
        raise SandboxUnavailable(f"bubblewrap is not executable at {str(bwrap_file)!r}")
    if not python_file.is_file() or not os.access(python_file, os.X_OK):
        raise SandboxUnavailable(f"Python is not executable at {str(python_file)!r}")
    try:
        bwrap_version = subprocess.run(
            [str(bwrap_file), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=2,
            check=True,
        ).stdout.strip()
        python_version = subprocess.run(
            [str(python_file), "-I", "-c", "import platform;print(platform.python_version())"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=2,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxUnavailable(f"cannot identify sandbox runtime: {exc}") from exc
    return {
        "contract": SANDBOX_CONTRACT_VERSION,
        "bubblewrap_path": str(bwrap_file),
        "bubblewrap_sha256": _sha256_file(bwrap_file),
        "bubblewrap_version": bwrap_version,
        "python_path": str(python_file),
        "python_sha256": _sha256_file(python_file),
        "python_version": python_version,
    }


def validate_candidate_source(source: Any, function_name: str) -> None:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("candidate source must be a non-empty string")
    if len(source.encode("utf-8")) > 65536:
        raise ValueError("candidate source exceeds 65536 bytes")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"candidate source is invalid Python: {exc.msg}") from exc

    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    permitted_top_level = all(
        isinstance(node, ast.FunctionDef)
        or (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        for node in tree.body
    )
    if not permitted_top_level or len(functions) != 1 or functions[0].name != function_name:
        raise ValueError(f"source must define only the function {function_name!r}")
    if functions[0].decorator_list:
        raise ValueError("candidate function decorators are forbidden")

    for node in ast.walk(tree):
        if isinstance(node, _BANNED_NODES):
            # Candidate validation intentionally presents one closed refusal
            # surface regardless of whether the rejected syntax is type-like.
            raise ValueError(  # noqa: TRY004
                f"forbidden syntax in candidate source: {type(node).__name__}"
            )
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("private/dunder names are forbidden in candidate source")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("_") or node.attr not in _ALLOWED_METHODS
        ):
            raise ValueError(f"candidate method is forbidden: {node.attr!r}")
        if isinstance(node, ast.Call):
            safe_name = isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_CALLS
            safe_method = (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in _ALLOWED_METHODS
            )
            if not safe_name and not safe_method:
                raise ValueError("candidate calls are limited to safe builtins")


def _set_limits(timeout_s: float, max_output_bytes: int) -> None:
    cpu = max(1, math.ceil(timeout_s))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_output_bytes, max_output_bytes))


_CHILD = r'''import builtins
import copy
import json
import sys

safe_builtins = {
    name: getattr(builtins, name)
    for name in (
        "ValueError", "NotImplementedError", "abs", "all", "any", "bool",
        "dict", "enumerate", "float", "int", "isinstance", "len", "list",
        "max", "min", "range", "set", "sorted", "str", "sum", "tuple", "zip",
    )
}
namespace = {"__builtins__": safe_builtins}
with open("/task/candidate.py", "r", encoding="utf-8") as handle:
    source = handle.read()
exec(compile(source, "/task/candidate.py", "exec"), namespace, namespace)
function = namespace["FUNCTION"]

request = json.load(sys.stdin)
arguments = request["arguments"]
before = copy.deepcopy(arguments)
try:
    value = function(*arguments)
except Exception as exc:
    payload = {
        "status": "exception",
        "exception_type": type(exc).__name__,
        "arguments_after": arguments,
        "input_mutated": arguments != before,
    }
else:
    payload = {
        "status": "returned",
        "value": value,
        "arguments_after": arguments,
        "input_mutated": arguments != before,
    }
json.dump(payload, sys.stdout, allow_nan=False, sort_keys=True)
'''


def run_case(
    source: str,
    function_name: str,
    arguments: list[Any],
    *,
    timeout_s: float = 3.0,
    max_output_bytes: int = 131072,
    bwrap_path: str = DEFAULT_BWRAP,
    python_path: str = DEFAULT_PYTHON,
) -> SandboxResult:
    """Run one case. Expected output stays in the trusted parent."""
    validate_candidate_source(source, function_name)
    if not isinstance(arguments, list):
        raise ValueError("arguments must be a JSON array")  # noqa: TRY004
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int):
        raise ValueError("max_output_bytes must be a positive integer")  # noqa: TRY004
    if max_output_bytes <= 0 or max_output_bytes > 1024 * 1024:
        raise ValueError("max_output_bytes must be between 1 and 1048576")
    try:
        request_bytes = json.dumps(
            {"arguments": arguments},
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"arguments are not finite JSON data: {exc}") from exc
    if len(request_bytes) > 131072:
        raise ValueError("encoded arguments exceed 131072 bytes")
    executable = shutil.which(bwrap_path)
    if executable is None:
        raise SandboxUnavailable(f"bubblewrap is unavailable at {bwrap_path!r}")
    python = Path(python_path).resolve()
    if not python.is_file() or not Path("/lib").is_dir():
        raise SandboxUnavailable("minimal Python runtime paths are unavailable")

    with tempfile.TemporaryDirectory(prefix="weekly-portfolio-code-") as raw_temp:
        temp = Path(raw_temp)
        (temp / "candidate.py").write_text(source, encoding="utf-8")
        (temp / "invoke.py").write_text(
            _CHILD.replace("FUNCTION", function_name), encoding="utf-8"
        )
        stdout_path = temp / "stdout.json"
        stderr_path = temp / "stderr.txt"
        command = [
            executable,
            "--die-with-parent",
            "--unshare-all",
            "--cap-drop",
            "ALL",
            "--uid",
            "65534",
            "--gid",
            "65534",
            "--clearenv",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/task",
            "--ro-bind",
            str(temp),
            "/task",
            "--chdir",
            "/task",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "PATH",
            "/usr/bin",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--",
            str(python),
            "-I",
            "/task/invoke.py",
        ]
        timed_out = False
        try:
            with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env={"PATH": "/usr/bin", "LANG": "C.UTF-8"},
                    start_new_session=True,
                    # The bounded runner is serial; this child hook contains
                    # only setrlimit syscalls and runs before untrusted code.
                    preexec_fn=lambda: _set_limits(  # noqa: PLW1509
                        timeout_s, max_output_bytes
                    ),
                )
                try:
                    process.communicate(input=request_bytes, timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
        except OSError as exc:
            raise SandboxUnavailable(f"cannot start bubblewrap: {exc}") from exc
        stdout = stdout_path.read_bytes()[: max_output_bytes + 1]
        stderr = stderr_path.read_bytes()[: max_output_bytes + 1]
        returncode = process.returncode

    if timed_out:
        return SandboxResult("timeout", detail="case exceeded wall-clock limit")
    if len(stdout) > max_output_bytes or len(stderr) > max_output_bytes:
        return SandboxResult("protocol_error", detail="sandbox output exceeded limit")
    if returncode != 0:
        diagnostic = stderr.decode("utf-8", errors="replace").strip()[:512]
        return SandboxResult(
            "process_error",
            detail=(
                f"sandbox return code {returncode}: {diagnostic}"
                if diagnostic
                else f"sandbox return code {returncode}"
            ),
        )
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return SandboxResult("protocol_error", detail="sandbox output is not one JSON value")
    if not isinstance(payload, dict) or payload.get("status") not in {
        "returned",
        "exception",
    }:
        return SandboxResult("protocol_error", detail="sandbox response schema is invalid")
    if not isinstance(payload.get("input_mutated"), bool):
        return SandboxResult("protocol_error", detail="sandbox mutation receipt is missing")
    if payload["status"] == "exception":
        exception_type = payload.get("exception_type")
        if not isinstance(exception_type, str):
            return SandboxResult("protocol_error", detail="exception type is missing")
        return SandboxResult(
            "exception",
            exception_type=exception_type,
            input_mutated=payload["input_mutated"],
        )
    return SandboxResult(
        "returned",
        value=payload.get("value"),
        input_mutated=payload["input_mutated"],
    )
