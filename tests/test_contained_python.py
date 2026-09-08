"""Real finite qualification on the declared local Linux profile.

These parent assertions execute known synthetic candidate fixtures only in
the contained child. They make no model, remote, service or policy calls.
"""
import json
import hashlib
import os
import signal
import tempfile
import time
from pathlib import Path

import pytest

from tools import contained_python as controller
from tools.contained_python import run_python, runtime_identity


@pytest.fixture
def tmp_path():
    # Preserve private evidence; do not change workspace/host permissions.
    return Path(tempfile.mkdtemp(prefix="lab-contained-test-", dir="/tmp"))


def call(tmp_path, source, arguments=(), **kwargs):
    receipt = run_python(source.encode(), "probe", list(arguments),
                         evidence_dir=tmp_path, approved_runtime=runtime_identity(), **kwargs)
    assert receipt["launched"] and receipt["input_bytes_unchanged"]
    return receipt


def returned(receipt):
    assert receipt.get("returncode") == 0, receipt
    assert not receipt["timed_out"] and not receipt["output_exceeded"], receipt
    assert receipt["stderr"] == "", receipt
    output = json.loads(receipt["stdout"])
    assert output["status"] == "returned", output
    return output["value"]


def test_positive_call_and_explicit_error(tmp_path):
    good = call(tmp_path, "def probe(a, b):\n    return a + b\n", [2, 3])
    assert returned(good) == 5
    assert good["pass_fds"] == [] and good["close_fds"] is True
    assert good["writable_mounts"] == []
    assert len(good["libseccomp_sha256"]) == 64
    error = call(tmp_path, "def probe():\n    raise ValueError('expected')\n")
    assert error["returncode"] == 0
    assert json.loads(error["stdout"]) == {
        "status": "error", "error_type": "ValueError", "error_message": "expected"}


def test_filesystem_fd_and_namespace_boundaries(tmp_path):
    canary = tmp_path / "host-canary.txt"
    canary.write_text("private synthetic canary")
    descriptor = os.open(canary, os.O_RDONLY)
    os.set_inheritable(descriptor, True)
    info = os.fstat(descriptor)
    source = '''
import os
from pathlib import Path
def probe(canary, fd, device, inode, host_net):
    denied = []
    for path in [canary, '/home', '/input/candidate.py', '/input/request.json', '/created']:
        try:
            if path in [canary, '/home']:
                Path(path).read_bytes()
            else:
                Path(path).write_bytes(b'forbidden')
        except OSError:
            denied.append(path)
    try:
        info = os.fstat(fd)
        leaked = (info.st_dev, info.st_ino) == (device, inode)
    except OSError:
        leaked = False
    try:
        os.symlink(canary, '/input/link')
        link_denied = False
    except OSError:
        link_denied = True
    return {'denied': denied, 'leaked': leaked, 'link_denied': link_denied,
            'net_isolated': os.readlink('/proc/self/ns/net') != host_net,
            'nnp': 'NoNewPrivs:\\t1' in Path('/proc/self/status').read_text()}
'''
    try:
        result = returned(call(tmp_path, source,
            [str(canary), descriptor, info.st_dev, info.st_ino,
             os.readlink("/proc/self/ns/net")]))
    finally:
        os.close(descriptor)
    assert result == {"denied": [str(canary), "/home", "/input/candidate.py",
                                 "/input/request.json", "/created"],
                      "leaked": False, "link_denied": True,
                      "net_isolated": True, "nnp": True}
    assert canary.read_text() == "private synthetic canary"


def test_syscall_denials_and_hard_limits(tmp_path):
    source = '''
import ctypes
import os
import resource
import socket
def probe():
    denied = []
    for name, action in [('socket', lambda: socket.socket()),
                         ('fork', os.fork),
                         ('exec', lambda: os.execl('/usr/bin/true', 'true'))]:
        try:
            action()
        except OSError:
            denied.append(name)
    libc = ctypes.CDLL(None, use_errno=True)
    blocked_unshare = libc.unshare(0x10000000) == -1
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (100, 100))
        raise_denied = False
    except (ValueError, OSError):
        raise_denied = True
    limits = {name: list(resource.getrlimit(getattr(resource, name))) for name in
              ['RLIMIT_CPU', 'RLIMIT_AS', 'RLIMIT_NOFILE', 'RLIMIT_NPROC', 'RLIMIT_CORE', 'RLIMIT_FSIZE']}
    return {'denied': denied, 'unshare': blocked_unshare, 'raise': raise_denied,
            'limits': limits}
'''
    result = returned(call(tmp_path, source))
    assert result["denied"] == ["socket", "fork", "exec"]
    assert result["unshare"] and result["raise"]
    assert result["limits"] == {"RLIMIT_CPU": [2, 2],
        "RLIMIT_AS": [268435456, 268435456], "RLIMIT_NOFILE": [32, 32],
        "RLIMIT_NPROC": [0, 0], "RLIMIT_CORE": [0, 0], "RLIMIT_FSIZE": [0, 0]}


def test_memory_allocation_is_bounded(tmp_path):
    result = returned(call(tmp_path, '''
def probe():
    try:
        allocation = bytearray(512 * 1024 * 1024)
    except MemoryError:
        return 'denied'
    return len(allocation)
'''))
    assert result == "denied"


def test_invalid_utf8_remains_exact_raw_evidence(tmp_path):
    receipt = call(tmp_path, "import os\ndef probe():\n    os.write(1, bytes([255]))\n    return 1\n")
    raw = Path(receipt["stdout_raw_path"]).read_bytes()
    assert raw.startswith(bytes([255]))
    assert hashlib.sha256(raw).hexdigest() == receipt["stdout_sha256"]
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8", errors="strict")


def test_output_flood_is_bounded_and_reaped(tmp_path):
    receipt = call(tmp_path, '''
import os
def probe():
    while True:
        os.write(1, b'x' * 8192)
''', output_limit=1024)
    assert receipt["output_exceeded"] is True
    assert len(receipt["stdout"].encode()) + len(receipt["stderr"].encode()) <= 1024
    assert receipt["duration_seconds"] < 4
    with pytest.raises(ProcessLookupError):
        os.kill(receipt["pid"], 0)


@pytest.mark.parametrize("close_streams", [False, True])
def test_wall_timeout_reaps_even_after_output_closes(tmp_path, close_streams):
    source = "import os, time\ndef probe():\n"
    if close_streams:
        source += "    os.close(1)\n    os.close(2)\n"
    source += "    time.sleep(8)\n"
    receipt = call(tmp_path, source, wall_seconds=0.3)
    assert receipt["timed_out"] is True
    assert receipt["duration_seconds"] < 3
    with pytest.raises(ProcessLookupError):
        os.kill(receipt["pid"], 0)


def test_cpu_limit_precedes_longer_wall_cap(tmp_path):
    receipt = call(tmp_path, "def probe():\n    while True:\n        pass\n", wall_seconds=6)
    assert receipt["returncode"] != 0
    assert not receipt["timed_out"] and receipt["duration_seconds"] < 5


@pytest.mark.parametrize("kwargs", [
    {"candidate": b""}, {"candidate": b"x" * 32769},
    {"function": "../bad"}, {"arguments": {}},
    {"wall_seconds": 0}, {"wall_seconds": float("nan")},
    {"output_limit": 65537}, {"arguments": [float("inf")]},
])
def test_bad_requests_refused_before_launch(tmp_path, kwargs):
    values = {"candidate": b"def probe(): return 1", "function": "probe", "arguments": []}
    values.update(kwargs)
    with pytest.raises(ValueError):
        run_python(**values, evidence_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("key", ["bwrap", "python", "libseccomp", "controller", "bootstrap"])
def test_every_approved_identity_is_enforced(tmp_path, key):
    approved = runtime_identity()
    approved[key + "_sha256"] = "0" * 64
    receipt = run_python(b"raise RuntimeError('must not import')", "probe", [],
                         evidence_dir=tmp_path, approved_runtime=approved)
    assert not receipt["launched"] and receipt["phase"] == "failed"
    assert "identity" in receipt["launch_error"]
    assert json.loads(Path(receipt["receipt_path"]).read_text()) == receipt


def test_missing_approval_is_durable_refusal(tmp_path):
    receipt = run_python(b"def probe(): return 1", "probe", [], evidence_dir=tmp_path)
    assert not receipt["launched"] and receipt["phase"] == "failed"
    assert Path(receipt["receipt_path"]).is_file()


@pytest.mark.parametrize("failure", ["runtime_read", "inner_launch", "supervisor_fork"])
def test_prelaunch_failures_have_receipts(tmp_path, monkeypatch, failure):
    approved = runtime_identity()
    def fail(*args, **kwargs):
        raise OSError("synthetic prelaunch failure")
    if failure == "runtime_read":
        monkeypatch.setattr(controller, "runtime_identity", fail)
    elif failure == "inner_launch":
        monkeypatch.setattr(controller.subprocess, "Popen", fail)
    else:
        monkeypatch.setattr(controller.os, "fork", fail)
    receipt = run_python(b"def probe(): return 1", "probe", [],
                         evidence_dir=tmp_path, approved_runtime=approved)
    assert not receipt["launched"] and receipt["phase"] == "failed"
    assert "synthetic" in receipt["launch_error"]
    assert json.loads(Path(receipt["receipt_path"]).read_text()) == receipt


@pytest.mark.parametrize("phase", ["preflight", "inner_popen"])
def test_deadline_covers_delayed_prelaunch(tmp_path, monkeypatch, phase):
    approved = runtime_identity()
    def delay(*args, **kwargs):
        time.sleep(5)
        raise RuntimeError("delay should not finish")
    if phase == "preflight":
        monkeypatch.setattr(controller, "verify_runtime", delay)
    else:
        monkeypatch.setattr(controller.subprocess, "Popen", delay)
    receipt = run_python(b"def probe(): return 1", "probe", [],
        evidence_dir=tmp_path, approved_runtime=approved, wall_seconds=0.1)
    assert receipt["timed_out"] and receipt["supervisor_reaped"]
    assert not receipt["launched"] and receipt["duration_seconds"] < 2
    assert json.loads(Path(receipt["receipt_path"]).read_text()) == receipt
    with pytest.raises(ProcessLookupError):
        os.kill(receipt["supervisor_pid"], 0)


@pytest.mark.parametrize("mode", ["ancestor_link", "writable_ancestor", "public_leaf"])
def test_untrusted_evidence_paths_refused(tmp_path, mode):
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    leaf = parent / "leaf"
    leaf.mkdir(mode=0o700)
    if mode == "ancestor_link":
        (tmp_path / "link").symlink_to(parent, target_is_directory=True)
        leaf = tmp_path / "link" / "leaf"
    elif mode == "writable_ancestor":
        parent.chmod(0o777)
    else:
        leaf.chmod(0o755)
    with pytest.raises((ValueError, OSError)):
        run_python(b"def probe(): return 1", "probe", [], evidence_dir=leaf)
    assert list(leaf.iterdir()) == []


def test_small_sysv_and_object_factory_refusals(tmp_path):
    source = """
import ctypes, errno, os
def probe():
    libc = ctypes.CDLL(None, use_errno=True)
    results = {}
    # IPC_PRIVATE, one byte/one semaphore: never pressure or exhaust resources.
    for name, args in [('shmget', (0, 1, 0o600)), ('semget', (0, 1, 0o600)),
                       ('msgget', (0, 0o600)), ('memfd_create', (b'probe', 0)),
                       ('eventfd', (0, 0)), ('inotify_init1', (0,)),
                       ('setsid', ()), ('setpgid', (0, 0))]:
        ctypes.set_errno(0)
        value = getattr(libc, name)(*args)
        results[name] = [value, ctypes.get_errno()]
        if value >= 0:
            if name == 'shmget': libc.shmctl(value, 0, None)
            elif name == 'semget': libc.semctl(value, 0, 0)
            elif name == 'msgget': libc.msgctl(value, 0, None)
            elif name not in ('setsid', 'setpgid'): os.close(value)
    return results
"""
    values = returned(call(tmp_path, source))
    import errno
    assert values and all(value == [-1, errno.EPERM] for value in values.values())



def test_malformed_runtime_approval_is_durable(tmp_path):
    receipt = run_python(b"def probe(): return 1", "probe", [],
                         evidence_dir=tmp_path, approved_runtime={1: object()})
    assert not receipt["launched"] and receipt["failure_phase"] == "preflight"
    assert json.loads(Path(receipt["receipt_path"]).read_text()) == receipt


def test_failed_terminal_write_preserves_initial_receipt(tmp_path, monkeypatch):
    original = controller._persist
    writes = 0
    def fail_after_initial(*args, **kwargs):
        nonlocal writes
        writes += 1
        if writes > 1:
            raise OSError("synthetic unavailable evidence storage")
        return original(*args, **kwargs)
    monkeypatch.setattr(controller, "_persist", fail_after_initial)
    with pytest.raises(OSError, match="unavailable evidence storage"):
        run_python(b"def probe(): return 1", "probe", [], evidence_dir=tmp_path)
    saved = list(tmp_path.glob("contained-*/receipt.json"))
    assert len(saved) == 1
    initial = json.loads(saved[0].read_text())
    assert initial["phase"] == "supervisor_start" and not initial["launched"]


@pytest.mark.parametrize("interrupted", ["stdout.bin", "stderr.bin"])
def test_parent_finishes_evidence_when_child_raw_publisher_is_interrupted(tmp_path, monkeypatch, interrupted):
    parent = os.getpid()
    persist = controller._persist
    def stop_child(descriptor, name, data):
        if os.getpid() != parent and name == interrupted:
            persist(descriptor, ".interrupted-" + name, b"temporary fragment")
            # Deterministic: the child cannot finish; parent must time out/reap.
            os.kill(os.getpid(), signal.SIGSTOP)
        return persist(descriptor, name, data)
    monkeypatch.setattr(controller, "_persist", stop_child)
    receipt = run_python(b"def probe(): return 42", "probe", [],
        evidence_dir=tmp_path, approved_runtime=runtime_identity(), wall_seconds=0.3)
    assert receipt["timed_out"] and receipt["supervisor_reaped"]
    assert receipt["phase"] == "timed_out" and receipt["duration_seconds"] < 3
    assert receipt["parent_finalized"] and receipt["input_bytes_unchanged"]
    assert not receipt["terminal_evidence_complete"]
    assert receipt["raw_streams"]["stderr"]["status"] == "unavailable"
    assert "stderr" not in receipt and "stderr_sha256" not in receipt
    if interrupted == "stdout.bin":
        assert receipt["raw_streams"]["stdout"]["status"] == "unavailable"
        assert "stdout" not in receipt and "stdout_sha256" not in receipt
    else:
        assert receipt["raw_streams"]["stdout"]["status"] == "partial"
        assert hashlib.sha256(Path(receipt["stdout_raw_path"]).read_bytes()).hexdigest() == receipt["stdout_sha256"]
    assert "returncode" not in receipt  # finalizer never checkpointed its value
    assert json.loads(Path(receipt["receipt_path"]).read_text()) == receipt
    with pytest.raises(ProcessLookupError):
        os.kill(receipt["supervisor_pid"], 0)


@pytest.mark.parametrize("name,remove", [("candidate.py", False), ("request.json", False),
                                        ("bootstrap.py", False), ("request.json", True)])
def test_parent_detects_input_change_after_child_checkpoint(tmp_path, monkeypatch, name, remove):
    attempt = controller._attempt
    def changed(candidate, request, private, *args):
        attempt(candidate, request, private, *args)
        path = private / "input" / name
        if remove:
            path.unlink()
        else:
            path.write_bytes(b"changed after child verification")
    monkeypatch.setattr(controller, "_attempt", changed)
    receipt = run_python(b"def probe(): return 1", "probe", [],
        evidence_dir=tmp_path, approved_runtime=runtime_identity())
    assert receipt["supervisor_reaped"] and receipt["parent_finalized"]
    assert not receipt["input_bytes_unchanged"] and not receipt["terminal_evidence_complete"]
    assert receipt["phase"] == "failed"
    assert json.loads(Path(receipt["receipt_path"]).read_text()) == receipt


def test_unreaped_supervisor_cannot_claim_final_evidence(tmp_path, monkeypatch):
    # Synthetic process observations only: never signal a real unowned process.
    monkeypatch.setattr(controller.os, "fork", lambda: 2147483647)
    monkeypatch.setattr(controller.os, "waitpid", lambda *args: (0, 0))
    monkeypatch.setattr(controller.os, "killpg", lambda *args: None)
    monkeypatch.setattr(controller.os, "kill", lambda *args: None)
    receipt = run_python(b"def probe(): return 1", "probe", [],
        evidence_dir=tmp_path, approved_runtime=runtime_identity(), wall_seconds=0.1)
    assert receipt["phase"] == "teardown_incomplete" and not receipt["supervisor_reaped"]
    assert not receipt["parent_finalized"] and not receipt["terminal_evidence_complete"]
    assert not receipt["input_bytes_unchanged"]
    assert all(item["status"] == "unavailable" for item in receipt["raw_streams"].values())


def test_parent_pins_published_normal_stream_bytes(tmp_path):
    receipt = call(tmp_path, "import os\ndef probe():\n    os.write(2, b'known stderr')\n    return 9\n")
    assert receipt["parent_finalized"] and receipt["terminal_evidence_complete"]
    for name in ("stdout", "stderr"):
        raw = Path(receipt[name + "_raw_path"]).read_bytes()
        assert receipt["raw_streams"][name]["status"] == "complete"
        assert receipt[name + "_sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["stderr"] == "known stderr"


@pytest.mark.parametrize("name", ["stdout.bin", "stderr.bin"])
def test_parent_rejects_changed_raw_bytes_after_complete_checkpoint(tmp_path, monkeypatch, name):
    attempt = controller._attempt
    def changed(candidate, request, private, *args):
        attempt(candidate, request, private, *args)
        (private / name).write_bytes(b"different published bytes")
    monkeypatch.setattr(controller, "_attempt", changed)
    receipt = run_python(b"def probe(): return 1", "probe", [],
        evidence_dir=tmp_path, approved_runtime=runtime_identity())
    assert receipt["supervisor_reaped"] and receipt["input_bytes_unchanged"]
    assert receipt["phase"] == "failed" and not receipt["terminal_evidence_complete"]
    stream = name.removesuffix(".bin")
    assert receipt["raw_streams"][stream]["status"] == "invalid"
    assert receipt[stream + "_sha256"] == hashlib.sha256(b"different published bytes").hexdigest()


def test_parent_final_storage_failure_does_not_publish_parent_success(tmp_path, monkeypatch):
    parent = os.getpid()
    persist = controller._persist
    writes = 0
    def fail_parent(descriptor, name, data):
        nonlocal writes
        if os.getpid() == parent and name == "receipt.json":
            writes += 1
            if writes > 1:
                raise OSError("synthetic parent final storage failure")
        return persist(descriptor, name, data)
    monkeypatch.setattr(controller, "_persist", fail_parent)
    with pytest.raises(OSError, match="parent final storage failure"):
        run_python(b"def probe(): return 1", "probe", [],
            evidence_dir=tmp_path, approved_runtime=runtime_identity())
    saved = json.loads(next(tmp_path.glob("contained-*/receipt.json")).read_text())
    assert saved["inner_finalized"] and not saved.get("parent_finalized", False)
