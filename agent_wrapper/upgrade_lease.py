"""Cooperative local inference lease shared by canonical and linked checkouts.

Ordinary calls take shared locks, retaining normal production concurrency.
Weekly experiments hold the exclusive lock for their entire reservation.
Their children inherit that same open descriptor rather than reacquiring it.
No busy wait, service action or provider fallback is performed here.
"""
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


def _canonical_repo() -> Path:
    root = Path(__file__).resolve().parents[1]
    dotgit = root / ".git"
    if dotgit.is_file():
        gitdir = Path(dotgit.read_text().strip().removeprefix("gitdir: "))
        if not gitdir.is_absolute():
            gitdir = root / gitdir
        common = gitdir / "commondir"
        if common.is_file():
            return (gitdir / common.read_text().strip()).resolve().parent
    return root


LOCK_PATH = _canonical_repo() / "run_state" / ".weekly-upgrade-gpu.lock"


class InferenceLeaseBusy(RuntimeError):
    """An exclusive weekly experiment currently owns the resident endpoints."""


@contextmanager
def local_inference():
    inherited = os.environ.get("WEEKLY_UPGRADE_GPU_LEASE_FD")
    if inherited is not None:
        try:
            fd = int(inherited)
            supplied, expected = os.fstat(fd), LOCK_PATH.stat()
            if (supplied.st_dev, supplied.st_ino) != (expected.st_dev, expected.st_ino):
                raise ValueError("descriptor belongs to another file")
            # Reassert ownership on the inherited open-file description; a new
            # descriptor cannot evade another process's exclusive lease.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ValueError) as exc:
            raise InferenceLeaseBusy("invalid inherited weekly inference lease") from exc
        yield
        return
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InferenceLeaseBusy("weekly experiment owns local inference; retry after it finishes") from exc
        yield
