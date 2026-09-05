"""Finite read-only Python RPC using the existing local Bubblewrap binary.

No candidate code is imported into this controller. Caller-supplied bytes are
copied into a fresh private directory; namespace mounts expose only that copy
and the system interpreter. The caller owns trusted ancestry/lifecycle of the
evidence directory. This is a narrow Linux profile, not a general worker.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sysconfig
import stat
import threading
import uuid
import time


BWRAP = Path("/usr/bin/bwrap")
PYTHON = Path("/usr/bin/python3")
BOOTSTRAP = Path(__file__).with_name("contained_worker.py")
SECCOMP_LIB = Path("/usr/lib") / sysconfig.get_config_var("MULTIARCH") / "libseccomp.so.2"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _stop(process):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            process.send_signal(sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
            return
        except subprocess.TimeoutExpired:
            continue
    raise RuntimeError("contained process did not terminate")


def _validate(candidate, function, arguments, wall_seconds, output_limit):
    """Run one JSON-compatible function and retain exact bounded observations.

    A zero exit or a returned value is not acceptance; the parent owns tests.
    No model endpoint, credentials, host repository or writable mount is passed.
    """
    if type(candidate) is not bytes or not 0 < len(candidate) <= 32768:
        raise ValueError("candidate must be 1..32768 bytes")
    if not isinstance(function, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", function):
        raise ValueError("invalid function name")
    if type(arguments) is not list or type(output_limit) is not int \
            or not 128 <= output_limit <= 65536:
        raise ValueError("invalid arguments or output limit")
    if type(wall_seconds) not in (int, float) or not 0.1 <= wall_seconds <= 15:
        raise ValueError("wall time must be within 0.1..15 seconds")
    request = json.dumps({"function": function, "arguments": arguments},
                         ensure_ascii=True, allow_nan=False).encode()
    if len(request) > 32768:
        raise ValueError("request exceeds 32768 bytes")
    return request


def _private_directory(path):
    """Admit static ancestry, retaining an fd; equal-UID interference excluded."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("evidence directory must be an absolute trusted path")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in (0, os.geteuid()) or (info.st_mode & 0o022 and not sticky_root):
                raise ValueError("untrusted evidence ancestry ownership/mode")
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("evidence leaf must be caller-owned mode 0700")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _persist(descriptor, name, data):
    temporary = "." + name + "-" + uuid.uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=descriptor)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
    os.fsync(descriptor)


def _checkpoint(descriptor, receipt):
    _persist(descriptor, "receipt.json", (json.dumps(receipt, indent=2) + "\n").encode())


def _read_bounded(descriptor, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("evidence is not a bounded regular file")
        raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("evidence exceeds byte bound")
        return raw


def _finalize_evidence(descriptor, private, receipt, candidate, request, approved, reaped):
    """Parent observation after reap; cannot reconstruct uncheckpointed events."""
    checkpoint_hashes = {name: receipt.get(name + "_sha256") for name in ("stdout", "stderr")}
    receipt.update(parent_finalized=False, input_bytes_unchanged=False,
                   terminal_evidence_complete=False, input_verification={}, raw_streams={})
    for name in ("stdout", "stderr"):
        for key in (name, name + "_raw_path", name + "_sha256"):
            receipt.pop(key, None)
        receipt["raw_streams"][name] = {"status": "unavailable", "reason": "supervisor not reaped"}
    if not reaped:
        return  # a writer may still exist; no final integrity claim
    receipt["parent_finalized"] = True
    inputs = None
    try:
        inputs = os.open("input", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=descriptor)
        for name, expected in (("candidate.py", candidate), ("request.json", request),
                               ("bootstrap.py", (approved or {}).get("bootstrap_sha256"))):
            try:
                raw = _read_bounded(inputs, name, 32768)
                matches = raw == expected if type(expected) is bytes else _sha(raw) == expected
                receipt["input_verification"][name] = {
                    "status": "verified" if matches else "mismatch", "sha256": _sha(raw)}
            except (OSError, ValueError) as error:
                receipt["input_verification"][name] = {
                    "status": "missing" if isinstance(error, FileNotFoundError) else "unreadable",
                    "error": type(error).__name__ + ": " + str(error)}
        receipt["input_bytes_unchanged"] = all(
            item["status"] == "verified" for item in receipt["input_verification"].values())
    except OSError as error:
        receipt["input_verification"]["directory"] = {"status": "unavailable", "error": str(error)}
    finally:
        if inputs is not None:
            os.close(inputs)
    complete = receipt.get("inner_finalized", False) and not (
        receipt["timed_out"] or receipt["output_exceeded"] or receipt.get("launch_error"))
    remaining = receipt["output_limit"]
    for name in ("stdout", "stderr"):
        try:
            raw = _read_bounded(descriptor, name + ".bin", remaining)
            remaining -= len(raw)
            receipt[name + "_raw_path"] = str(private / (name + ".bin"))
            receipt[name + "_sha256"] = _sha(raw)
            receipt[name] = raw.decode("utf-8", errors="replace")
            receipt["raw_streams"][name] = {"status": "complete" if complete else "partial",
                                             "bytes": len(raw)}
            if complete and _sha(raw) != checkpoint_hashes[name]:
                receipt["raw_streams"][name].update(
                    status="invalid", reason="published bytes differ from child checkpoint")
        except (OSError, ValueError) as error:
            receipt["raw_streams"][name] = {
                "status": "invalid" if isinstance(error, ValueError) else "unavailable",
                "reason": type(error).__name__ + ": " + str(error)}
    receipt["terminal_evidence_complete"] = receipt["input_bytes_unchanged"] and all(
        item["status"] == "complete" for item in receipt["raw_streams"].values())
    if receipt["phase"] == "exited" and not receipt["terminal_evidence_complete"]:
        receipt.update(phase="failed", evidence_error="parent could not verify complete terminal evidence")


def runtime_identity():
    """Measure only. A caller must independently approve/freeze these values."""
    result = {}
    for name, path in {"bwrap": BWRAP, "python": PYTHON, "libseccomp": SECCOMP_LIB,
                       "controller": Path(__file__), "bootstrap": BOOTSTRAP}.items():
        resolved = path.resolve(strict=True)
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 \
                or (name in {"bwrap", "python", "libseccomp"} and info.st_uid != 0):
            raise ValueError("untrusted runtime file: " + name)
        result[name + "_sha256"] = _sha(resolved.read_bytes())
    return result


def verify_runtime(approved):
    observed = runtime_identity()
    if type(approved) is not dict or approved != observed:
        raise ValueError("approved runtime identity missing or differs from observed files")
    return observed


def _attempt(candidate, request, private, descriptor, receipt, approved, started):
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    inputs = private / "input"
    bootstrap = None
    wall_seconds, output_limit = receipt["wall_seconds"], receipt["output_limit"]
    try:
        receipt["phase"] = "preflight"
        _checkpoint(descriptor, receipt)
        receipt.update(verify_runtime(approved))
        bootstrap = BOOTSTRAP.read_bytes()
        if _sha(bootstrap) != approved["bootstrap_sha256"]:
            raise ValueError("bootstrap changed after runtime admission")
        _execute(candidate, request, bootstrap, inputs, private, descriptor,
                 receipt, streams, started, wall_seconds, output_limit)
    except BaseException as error:
        receipt["launch_error"] = type(error).__name__ + ": " + str(error)
        receipt["failure_phase"] = receipt["phase"]
        receipt["phase"] = "failed"
    finally:
        receipt["duration_seconds"] = time.monotonic() - started
        for name, data in streams.items():
            _persist(descriptor, name + ".bin", bytes(data))
            receipt[name + "_raw_path"] = str(private / (name + ".bin"))
            receipt[name] = data.decode("utf-8", errors="replace")
            receipt[name + "_sha256"] = _sha(data)
        receipt["input_bytes_unchanged"] = bootstrap is not None and all(
            (inputs / name).is_file() and (inputs / name).read_bytes() == data
            for name, data in (("candidate.py", candidate), ("request.json", request),
                               ("bootstrap.py", bootstrap)))
        receipt["inner_finalized"] = True
        _checkpoint(descriptor, receipt)


def _execute(candidate, request, bootstrap, inputs, private, descriptor,
             receipt, streams, started, wall_seconds, output_limit):
    inputs.mkdir(mode=0o700)
    for name, data in (("candidate.py", candidate), ("request.json", request),
                       ("bootstrap.py", bootstrap)):
        with (inputs / name).open("xb") as handle:
            handle.write(data)
    argv = [str(BWRAP), "--unshare-user", "--unshare-ipc", "--unshare-pid",
            "--unshare-net", "--unshare-uts", "--unshare-cgroup",
            "--disable-userns", "--die-with-parent",
            "--cap-drop", "ALL", "--clearenv", "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
            "--proc", "/proc", "--remount-ro", "/proc",
            "--ro-bind", str(inputs), "/input", "--chdir", "/input",
            "--remount-ro", "/", "--", str(PYTHON), "-I", "-S", "-B",
            "/input/bootstrap.py"]
    receipt.update(argv=argv, phase="launch")
    _checkpoint(descriptor, receipt)
    process = None
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, close_fds=True, pass_fds=(),
                                   start_new_session=False, env=receipt["environment"])
        receipt["launched"] = True
        receipt["pid"] = process.pid
        receipt["phase"] = "execution"
        _checkpoint(descriptor, receipt)
        with selectors.DefaultSelector() as poller:
            for name in streams:
                poller.register(getattr(process, name), selectors.EVENT_READ, name)
            while poller.get_map():
                remaining = wall_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    receipt["timed_out"] = True
                    break
                for key, _ in poller.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        poller.unregister(key.fileobj)
                    else:
                        available = output_limit - sum(map(len, streams.values()))
                        streams[key.data].extend(chunk[:available])
                        if len(chunk) > available:
                            receipt["output_exceeded"] = True
                            break
                if receipt["output_exceeded"]:
                    break
        if receipt["timed_out"] or receipt["output_exceeded"]:
            _stop(process)
        else:
            try:
                process.wait(timeout=max(0.01, wall_seconds - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                receipt["timed_out"] = True
                _stop(process)
        receipt["returncode"] = process.returncode
    finally:
        if process is not None:
            if process.poll() is None:
                _stop(process)
            for name in streams:
                getattr(process, name).close()


def _terminate(signum, frame):
    raise TimeoutError("whole-attempt deadline reached")


def run_python(candidate: bytes, function: str, arguments: list, *,
               evidence_dir: Path, approved_runtime: dict = None,
               wall_seconds: float = 3, output_limit: int = 65536) -> dict:
    """Finite attempt after trusted sink admission; see profile for OS limits.

    No caller bytes execute on the host. Missing/drifting runtime approval
    returns a durable prelaunch failure. Invalid arguments/no trusted sink raise.
    """
    request = _validate(candidate, function, arguments, wall_seconds, output_limit)
    if threading.current_thread() is not threading.main_thread() or threading.active_count() != 1:
        raise ValueError("trusted supervisor requires a single-threaded caller")
    if type(approved_runtime) is not dict or any(
            type(key) is not str or type(value) is not str
            for key, value in approved_runtime.items()):
        approved_runtime = None  # malformed pins are a durable admission refusal
    root = _private_directory(evidence_dir)
    name = "contained-" + uuid.uuid4().hex
    try:
        os.mkdir(name, 0o700, dir_fd=root)
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        os.fsync(root)
    finally:
        os.close(root)
    private = Path(evidence_dir) / name
    started = time.monotonic()
    receipt = {"started_at": datetime.now(timezone.utc).isoformat(),
        "candidate_sha256": _sha(candidate), "request_sha256": _sha(request),
        "approved_runtime": approved_runtime, "phase": "supervisor_start",
        "environment": {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        "close_fds": True, "pass_fds": [], "writable_mounts": [],
        "wall_seconds": wall_seconds, "output_limit": output_limit,
        "timed_out": False, "output_exceeded": False, "launched": False,
        "receipt_path": str(private / "receipt.json")}
    pid = None
    reaped = False
    try:
        _checkpoint(descriptor, receipt)  # survives fork/preflight failures
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()  # before any inner launch; descendants retain this PGID
                signal.signal(signal.SIGTERM, _terminate)
                _attempt(candidate, request, private, descriptor, receipt,
                         approved_runtime, started)
            finally:
                os._exit(0)
        receipt["supervisor_pid"] = pid
        while time.monotonic() - started < wall_seconds:
            observed, status = os.waitpid(pid, os.WNOHANG)
            if observed:
                reaped = True
                break
            time.sleep(0.005)
        if not reaped:
            receipt["timed_out"] = True
            for sig, grace in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 0.5)):
                try:
                    os.killpg(pid, sig)
                except ProcessLookupError:
                    try:
                        os.kill(pid, sig)  # child may not have reached setsid
                    except ProcessLookupError:
                        pass
                until = time.monotonic() + grace
                while time.monotonic() < until:
                    if os.waitpid(pid, os.WNOHANG)[0]:
                        reaped = True
                        break
                    time.sleep(0.005)
                if reaped:
                    break
        fd = os.open("receipt.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
        with os.fdopen(fd, "r") as handle:
            latest = json.load(handle)
        latest.update(supervisor_pid=pid, supervisor_reaped=reaped,
                      timed_out=receipt["timed_out"] or latest["timed_out"],
                      duration_seconds=time.monotonic() - started)
        if not reaped:
            latest["phase"] = "teardown_incomplete"
        elif latest["timed_out"]:
            latest["phase"] = "timed_out"
        elif not latest.get("inner_finalized"):
            latest["phase"] = "failed"
            latest["launch_error"] = "supervisor exited without terminal receipt"
        elif latest["phase"] == "execution":
            latest["phase"] = "exited"
        elif latest["phase"] != "failed":
            latest["launch_error"] = "supervisor exited without terminal receipt"
            latest["phase"] = "failed"
        receipt = latest
    except OSError as error:
        receipt.update(failure_phase=receipt["phase"], phase="failed",
                       launch_error=type(error).__name__ + ": " + str(error))
    finally:
        try:
            receipt["supervisor_reaped"] = reaped
            _finalize_evidence(descriptor, private, receipt, candidate, request,
                               approved_runtime, reaped)
            receipt["duration_seconds"] = time.monotonic() - started
            _checkpoint(descriptor, receipt)
        finally:
            os.close(descriptor)
    return receipt
