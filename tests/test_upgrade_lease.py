"""Process-boundary tests for the cooperative local-inference lease."""
from __future__ import annotations

import asyncio
import fcntl
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_wrapper import upgrade_lease
from agent_wrapper import wrapper as W
from agent_wrapper.backends.vllm_openai import VLLMBackend
from orchestrator.weekly_upgrade_trial import TrialError, resource_lease

# Captured during test collection, before the autouse isolation fixture points
# mutable lease operations at each test's tmp_path.
ORIGINAL_CANONICAL_ROOT = upgrade_lease._canonical_repo()
ORIGINAL_LOCK_PATH = upgrade_lease.LOCK_PATH
WORKTREE_ROOT = Path(__file__).resolve().parent.parent


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "canonical"
    (root / "run_state").mkdir(parents=True)
    return root


def _gpu_lock(root: Path) -> Path:
    return root / "run_state" / ".weekly-upgrade-gpu.lock"


def _exclusive_is_blocked(path: Path) -> None:
    with path.open("a+") as contender, pytest.raises(BlockingIOError):
        fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _exclusive_is_available(path: Path) -> None:
    with path.open("a+") as contender:
        fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(contender.fileno(), fcntl.LOCK_UN)


def _ordinary_holder(path: Path) -> subprocess.Popen:
    script = r"""
import pathlib
import sys
from agent_wrapper import upgrade_lease

upgrade_lease.LOCK_PATH = pathlib.Path(sys.argv[1])
with upgrade_lease.local_inference():
    print("READY", flush=True)
    sys.stdin.buffer.read(1)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        cwd=WORKTREE_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    ready, _, _ = select.select([proc.stdout], [], [], 3)
    if not ready:
        proc.kill()
        _, stderr = proc.communicate(timeout=3)
        pytest.fail(f"ordinary lease holder did not start: {stderr.decode(errors='replace')}")
    assert proc.stdout.readline() == b"READY\n"
    return proc


def _release_holder(proc: subprocess.Popen) -> None:
    assert proc.stdin is not None
    proc.stdin.write(b"x")
    proc.stdin.flush()
    proc.stdin.close()
    assert proc.wait(timeout=3) == 0


def _response():
    return SimpleNamespace(
        model=W.MODEL,
        choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content="pong", tool_calls=None, reasoning=None),
        )],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def test_real_process_shared_ordinary_lock_blocks_exclusive_maintenance(
    tmp_path: Path, monkeypatch,
):
    root = _root(tmp_path)
    lock_path = _gpu_lock(root)
    monkeypatch.setattr(upgrade_lease, "LOCK_PATH", lock_path)
    holder = _ordinary_holder(lock_path)
    try:
        # Ordinary inference remains concurrent under shared locking.
        with upgrade_lease.local_inference():
            _exclusive_is_blocked(lock_path)
        with pytest.raises(TrialError, match="weekly-upgrade-gpu.lock"), resource_lease(root):
            pytest.fail("exclusive maintenance must not overlap ordinary inference")
    finally:
        _release_holder(holder)

    with resource_lease(root):
        _exclusive_is_blocked(lock_path)
    _exclusive_is_available(lock_path)


def test_exclusive_maintenance_accepts_only_its_inherited_descriptor(
    tmp_path: Path, monkeypatch,
):
    root = _root(tmp_path)
    lock_path = _gpu_lock(root)
    monkeypatch.setattr(upgrade_lease, "LOCK_PATH", lock_path)

    with resource_lease(root) as descriptors:
        with pytest.raises(upgrade_lease.InferenceLeaseBusy), upgrade_lease.local_inference():
            pytest.fail("a newly opened shared descriptor must contend")

        monkeypatch.setenv("WEEKLY_UPGRADE_GPU_LEASE_FD", str(descriptors[-1]))
        expected = os.stat(lock_path)
        supplied = os.fstat(descriptors[-1])
        assert (supplied.st_dev, supplied.st_ino) == (expected.st_dev, expected.st_ino)
        with upgrade_lease.local_inference():
            _exclusive_is_blocked(lock_path)

        child = r"""
import pathlib
import sys
from agent_wrapper import upgrade_lease

upgrade_lease.LOCK_PATH = pathlib.Path(sys.argv[1])
with upgrade_lease.local_inference():
    print("INHERITED_OK")
"""
        env = dict(os.environ)
        env["WEEKLY_UPGRADE_GPU_LEASE_FD"] = str(descriptors[-1])
        completed = subprocess.run(
            [sys.executable, "-c", child, str(lock_path)],
            cwd=WORKTREE_ROOT,
            env=env,
            pass_fds=(descriptors[-1],),
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
        assert completed.stdout == "INHERITED_OK\n"

    monkeypatch.delenv("WEEKLY_UPGRADE_GPU_LEASE_FD")
    _exclusive_is_available(lock_path)


def test_inherited_descriptor_with_wrong_inode_fails_closed(tmp_path: Path, monkeypatch):
    root = _root(tmp_path)
    lock_path = _gpu_lock(root)
    lock_path.touch()
    wrong = tmp_path / "wrong.lock"
    monkeypatch.setattr(upgrade_lease, "LOCK_PATH", lock_path)
    with wrong.open("a+") as stream:
        monkeypatch.setenv("WEEKLY_UPGRADE_GPU_LEASE_FD", str(stream.fileno()))
        with pytest.raises(
            upgrade_lease.InferenceLeaseBusy,
            match="invalid inherited weekly inference lease",
        ), upgrade_lease.local_inference():
            pytest.fail("wrong-inode descriptor must never bypass maintenance")


def test_linked_worktree_resolves_the_canonical_checkout_lock_inode(tmp_path: Path, monkeypatch):
    # Verify the real checkout first: this module lives in a linked worktree,
    # while the import-time lock path resolves through Git's common directory.
    common = subprocess.check_output(
        [
            "git",
            "-C",
            str(WORKTREE_ROOT),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        text=True,
    ).strip()
    expected_real_root = Path(common).resolve().parent
    assert ORIGINAL_CANONICAL_ROOT == expected_real_root
    assert ORIGINAL_LOCK_PATH == expected_real_root / "run_state" / ".weekly-upgrade-gpu.lock"

    # Exercise the same commondir resolution with two actual distinct inodes,
    # without creating a lock in the live canonical checkout.
    canonical = tmp_path / "repo"
    gitdir = canonical / ".git" / "worktrees" / "linked"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n")
    linked = tmp_path / "linked"
    (linked / "agent_wrapper").mkdir(parents=True)
    (linked / ".git").write_text(f"gitdir: {gitdir}\n")
    (canonical / "run_state").mkdir()
    (linked / "run_state").mkdir()
    canonical_lock = canonical / "run_state" / ".weekly-upgrade-gpu.lock"
    worktree_lock = linked / "run_state" / ".weekly-upgrade-gpu.lock"
    canonical_lock.touch()
    worktree_lock.touch()
    canonical_inode = (canonical_lock.stat().st_dev, canonical_lock.stat().st_ino)
    worktree_inode = (worktree_lock.stat().st_dev, worktree_lock.stat().st_ino)
    assert canonical_inode != worktree_inode

    monkeypatch.setattr(
        upgrade_lease,
        "__file__",
        str(linked / "agent_wrapper" / "upgrade_lease.py"),
    )
    derived = upgrade_lease._canonical_repo() / "run_state" / canonical_lock.name
    assert derived.samefile(canonical_lock)
    assert not derived.samefile(worktree_lock)


def test_sync_and_async_wrapper_hold_shared_lease_through_transport(
    tmp_path: Path, monkeypatch,
):
    lock_path = tmp_path / "inference.lock"
    monkeypatch.setattr(upgrade_lease, "LOCK_PATH", lock_path)
    backend = VLLMBackend()
    monkeypatch.setattr(W, "get_backend", lambda _name: backend)

    class SyncCompletions:
        def create(self, **_kwargs):
            _exclusive_is_blocked(lock_path)
            return _response()

    class AsyncCompletions:
        async def create(self, **_kwargs):
            _exclusive_is_blocked(lock_path)
            await asyncio.sleep(0)
            _exclusive_is_blocked(lock_path)
            return _response()

    monkeypatch.setattr(
        W,
        "_sync_client",
        SimpleNamespace(chat=SimpleNamespace(completions=SyncCompletions())),
    )
    monkeypatch.setattr(
        W,
        "_async_client",
        SimpleNamespace(chat=SimpleNamespace(completions=AsyncCompletions())),
    )
    messages = [{"role": "user", "content": "lease fixture"}]

    assert W.call_sync(messages, log_path=None)["completion"] == "pong"
    _exclusive_is_available(lock_path)
    assert asyncio.run(W.call_async(messages, log_path=None))["completion"] == "pong"
    _exclusive_is_available(lock_path)


def test_gnu_timeout_keeps_inherited_lease_after_controller_exit_until_deadline(
    tmp_path: Path,
):
    timeout = shutil.which("timeout")
    if timeout is None:
        pytest.skip("GNU timeout is unavailable")
    version = subprocess.check_output([timeout, "--version"], text=True).splitlines()[0]
    if "GNU coreutils" not in version:
        pytest.skip("timeout is not GNU coreutils")

    root = _root(tmp_path)
    controller = r"""
import subprocess
import sys
from pathlib import Path
from orchestrator.weekly_upgrade_trial import resource_lease

root, timeout = Path(sys.argv[1]), sys.argv[2]
with resource_lease(root) as descriptors:
    subprocess.Popen(
        [timeout, "--signal=TERM", "--kill-after=0.2s", "0.8s",
         sys.executable, "-c", "import time; time.sleep(30)"],
        pass_fds=descriptors,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
"""
    subprocess.run(
        [sys.executable, "-c", controller, str(root), timeout],
        cwd=WORKTREE_ROOT,
        check=True,
        timeout=3,
    )
    controller_returned = time.monotonic()

    # The controller has exited and closed its copies. GNU timeout still owns
    # the inherited open-file descriptions while supervising its child.
    with pytest.raises(TrialError, match="resource is occupied"), resource_lease(root):
        pytest.fail("the inherited deadline supervisor must retain the lock")

    deadline = controller_returned + 2
    while True:
        try:
            with resource_lease(root):
                break
        except TrialError:
            if time.monotonic() >= deadline:
                pytest.fail("GNU timeout did not release inherited lease by deadline")
            time.sleep(0.03)
    assert time.monotonic() - controller_returned >= 0.65
