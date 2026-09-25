"""Dormant, unintegrated low-level storage for synthetic D-087 rows.

There is no default/live root, role or time authentication, selection,
calibration, kill, CLI, or runtime integration.  Recovery is deliberately
conservative: it never discards a first incomplete row, only a malformed final
tail following an already complete valid prefix.
An ambiguous fsync failure is reconciled only by retrying the identical encoded
row, which is idempotent; a torn or corrupt result remains fail-closed.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import stat
from pathlib import Path
from typing import Any


DIR = "run_state"
NAME = "thesis_convictions.jsonl"
LEDGER = Path(DIR) / NAME
MAX_LEDGER_BYTES = 1 << 20
MAX_ROW_BYTES = 8192
REQUIRED = {"thesis", "forecaster", "at", "p_pass_T", "p_pass_S", "p_pass_A",
            "p_dead_end", "interest_0_10", "reasons", "trigger"}
ALLOWED = REQUIRED | {"untrusted_extensions"}
FORECASTERS = {"nara", "oracle", "claude"}
PROBABILITIES = {"p_pass_T", "p_pass_S", "p_pass_A", "p_dead_end"}


class ConvictionLedgerError(ValueError):
    """Storage input or on-disk prefix is invalid."""


def _error(exc: OSError) -> ConvictionLedgerError:
    return ConvictionLedgerError(f"unsafe ledger filesystem object: {exc.strerror}")


def _open(path: str | Path, flags: int, *, dir_fd: int | None = None) -> int:
    try:
        return os.open(path, flags | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    except (FileNotFoundError, FileExistsError):
        raise
    except OSError as exc:
        raise _error(exc) from exc


def _directory(fd: int) -> None:
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        raise ConvictionLedgerError("ledger parent must be a directory")


def _regular(fd: int) -> None:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise ConvictionLedgerError("ledger must be a regular file")


def _root(root: Path) -> int:
    fd = _open(Path(root), os.O_RDONLY | os.O_DIRECTORY)
    _directory(fd)
    return fd


def _run_dir(root_fd: int, create: bool) -> tuple[int | None, bool]:
    made = False
    if create:
        try:
            os.mkdir(DIR, 0o700, dir_fd=root_fd)
            os.fsync(root_fd)  # persist the new directory entry before use
            made = True
        except FileExistsError:
            pass
        except OSError as exc:
            raise _error(exc) from exc
    try:
        fd = _open(DIR, os.O_RDONLY | os.O_DIRECTORY, dir_fd=root_fd)
    except FileNotFoundError:
        if not create:
            return None, False
        raise ConvictionLedgerError("new ledger directory disappeared")
    _directory(fd)
    return fd, made


def _number(value: Any, name: str, upper: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConvictionLedgerError(f"{name} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError as exc:
        raise ConvictionLedgerError(f"{name} must be a finite number") from exc
    if not finite or not 0 <= value <= upper:
        raise ConvictionLedgerError(f"{name} must be within 0..{upper:g}")


def _native(value: Any) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(value)
        except OverflowError as exc:
            raise ConvictionLedgerError("untrusted extension must be finite") from exc
        if not finite:
            raise ConvictionLedgerError("untrusted extension must be finite")
        return
    if isinstance(value, list):
        for item in value:
            _native(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _native(item)
        return
    raise ConvictionLedgerError("untrusted_extensions must be JSON-native")


def _validate(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict) or REQUIRED - set(row) or set(row) - ALLOWED:
        raise ConvictionLedgerError("row fields are not storage-canonical")
    if not isinstance(row["forecaster"], str) or row["forecaster"] not in FORECASTERS:
        raise ConvictionLedgerError("forecaster must be nara, oracle, or claude")
    for name in ("thesis", "at", "reasons", "trigger"):
        if not isinstance(row[name], str) or not row[name]:
            raise ConvictionLedgerError(f"{name} must be a nonempty string")
    for name in PROBABILITIES:
        _number(row[name], name, 1)
    _number(row["interest_0_10"], "interest_0_10", 10)
    if "untrusted_extensions" in row:
        if not isinstance(row["untrusted_extensions"], dict):
            raise ConvictionLedgerError("untrusted_extensions must be a mapping")
        _native(row["untrusted_extensions"])
    return row


def _encode(row: Any) -> bytes:
    try:
        return (json.dumps(_validate(row), allow_nan=False, separators=(",", ":"),
                           sort_keys=True) + "\n").encode()
    except ConvictionLedgerError:
        raise
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError) as exc:
        raise ConvictionLedgerError("row is not serializable JSON") from exc


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConvictionLedgerError("duplicate JSON key")
        result[key] = value
    return result


def _parse(raw: bytes) -> list[dict[str, Any]]:
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise ConvictionLedgerError("unterminated tail")
    rows = []
    if b"\r" in raw:
        raise ConvictionLedgerError("physical lines must use LF only")
    for line in raw[:-1].split(b"\n"):
        if len(line) + 1 > MAX_ROW_BYTES:
            raise ConvictionLedgerError("physical line exceeds storage bound")
        try:
            rows.append(_validate(json.loads(line, object_pairs_hook=_pairs,
                                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
            raise ConvictionLedgerError("malformed JSONL") from exc
    return rows


def _read(fd: int) -> bytes:
    if os.fstat(fd).st_size > MAX_LEDGER_BYTES:
        raise ConvictionLedgerError("ledger exceeds storage bound")
    os.lseek(fd, 0, os.SEEK_SET)
    chunks, size = [], 0
    while part := os.read(fd, 65536):
        size += len(part)
        if size > MAX_LEDGER_BYTES:
            raise ConvictionLedgerError("ledger exceeds storage bound")
        chunks.append(part)
    return b"".join(chunks)


def _unlock_close(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _append_fd(dir_fd: int) -> tuple[int, bool]:
    flags = os.O_RDWR | os.O_APPEND
    try:
        return _open(NAME, flags, dir_fd=dir_fd), False
    except FileNotFoundError:
        pass
    try:
        return _open(NAME, flags | os.O_CREAT | os.O_EXCL, dir_fd=dir_fd), True
    except FileExistsError:
        return _open(NAME, flags, dir_fd=dir_fd), False


def append(root: Path, row: dict[str, Any]) -> None:
    """Append idempotently by exact encoded row, or fail closed on ambiguity."""
    payload = _encode(row)
    if len(payload) > MAX_ROW_BYTES:
        raise ConvictionLedgerError("row exceeds storage bound")
    root_fd = _root(root)
    dir_fd = fd = None
    try:
        dir_fd, _ = _run_dir(root_fd, True)
        fd, _ = _append_fd(dir_fd)
        _regular(fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        prefix = _read(fd)
        _parse(prefix)
        duplicate = payload[:-1] in prefix[:-1].split(b"\n")
        if not duplicate and len(prefix) + len(payload) > MAX_LEDGER_BYTES:
            raise ConvictionLedgerError("append exceeds storage bound")
        if not duplicate:
            view = memoryview(payload)
            try:
                while view:
                    count = os.write(fd, view)
                    if not count:
                        raise ConvictionLedgerError("short append write")
                    view = view[count:]
            except OSError as exc:
                raise _error(exc) from exc
        try:
            os.fsync(fd)
            os.fsync(dir_fd)
            os.fsync(root_fd)
        except OSError as exc:
            raise _error(exc) from exc
    finally:
        if fd is not None:
            _unlock_close(fd)
        if dir_fd is not None:
            os.close(dir_fd)
        os.close(root_fd)


def read(root: Path) -> list[dict[str, Any]]:
    """Take a bounded snapshot under a shared lock on one no-follow fd."""
    root_fd = _root(root)
    dir_fd = fd = None
    try:
        dir_fd, _ = _run_dir(root_fd, False)
        if dir_fd is None:
            return []
        try:
            fd = _open(NAME, os.O_RDONLY, dir_fd=dir_fd)
        except FileNotFoundError:
            return []
        _regular(fd)
        fcntl.flock(fd, fcntl.LOCK_SH)
        return _parse(_read(fd))
    finally:
        if fd is not None:
            _unlock_close(fd)
        if dir_fd is not None:
            os.close(dir_fd)
        os.close(root_fd)


def recover_torn_tail(root: Path) -> None:
    """Drop only malformed final bytes after a complete valid prefix, under lock."""
    root_fd = _root(root)
    dir_fd = fd = None
    try:
        dir_fd, _ = _run_dir(root_fd, False)
        if dir_fd is None:
            return
        try:
            fd = _open(NAME, os.O_RDWR, dir_fd=dir_fd)
        except FileNotFoundError:
            return
        _regular(fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        raw = _read(fd)
        if b"\r" in raw:
            raise ConvictionLedgerError("physical lines must use LF only")
        if not raw or raw.endswith(b"\n"):
            _parse(raw)
            return
        cut = raw.rfind(b"\n") + 1
        if not cut:
            raise ConvictionLedgerError("no complete prefix to recover")
        try:
            json.loads(raw[cut:], object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except RecursionError as exc:
            raise ConvictionLedgerError("tail exceeds storage recursion bound") from exc
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            pass
        else:
            raise ConvictionLedgerError("valid JSON tail must not be discarded")
        _parse(raw[:cut])
        os.ftruncate(fd, cut)
        os.fsync(fd)
    finally:
        if fd is not None:
            _unlock_close(fd)
        if dir_fd is not None:
            os.close(dir_fd)
        os.close(root_fd)
