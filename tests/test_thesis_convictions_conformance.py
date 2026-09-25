"""Bounded synthetic D-087 storage conformance."""
from __future__ import annotations

import importlib
import inspect
import json
import math
import multiprocessing as mp
import os
import sys
import threading
import time
from collections import Counter

import pytest


ACTORS = ("nara", "oracle", "claude")
NUMBERS = ("p_pass_T", "p_pass_S", "p_pass_A", "p_dead_end", "interest_0_10")


@pytest.fixture
def api():
    return importlib.import_module("tools.thesis_convictions")


def row(actor="oracle", thesis="synthetic"):
    return {"thesis": thesis, "forecaster": actor, "at": "2026-09-25T00:00:00Z",
            "p_pass_T": .2, "p_pass_S": .1, "p_pass_A": .05, "p_dead_end": .75,
            "interest_0_10": 1, "reasons": "Synthetic storage row.", "trigger": "selection"}


def _events(path, action):
    seen = []
    def hook(event, args):
        if args and any(str(item) in (str(path), path.name) for item in args[:2]):
            seen.append((event, args))
    sys.addaudithook(hook)
    action()
    return seen


def _no_replace(events):
    bad = [(event, args) for event, args in events if event in ("os.rename", "os.remove", "os.unlink")
           or event == "open" and len(args) > 2 and isinstance(args[2], int) and args[2] & os.O_TRUNC]
    assert not bad, f"replace/truncate event: {bad}"


def _child(root, payload, gate):
    if not gate.wait(3):
        raise RuntimeError("start timeout")
    importlib.import_module("tools.thesis_convictions").append(root, payload)


def _round(root, rows):
    ctx = mp.get_context("spawn")
    gate = ctx.Event()
    children, deadline = [ctx.Process(target=_child, args=(str(root), r, gate)) for r in rows], time.monotonic() + 6
    try:
        for child in children: child.start()
        gate.set()
        for child in children: child.join(max(0, deadline - time.monotonic()))
    finally:
        for child in children:
            if child.is_alive(): child.terminate()
        for child in children:
            child.join(.5)
            if child.is_alive(): child.kill(); child.join(.5)
    assert all(child.exitcode == 0 for child in children)


def test_append_flags(tmp_path, api):
    ledger = tmp_path / api.LEDGER
    first = _events(ledger, lambda: api.append(tmp_path, row("nara")))
    writes = [a[2] for e, a in first if e == "open" and len(a) > 2 and a[2] & (os.O_WRONLY | os.O_RDWR)]
    assert writes and all(flags & os.O_APPEND for flags in writes)
    source = inspect.getsource(api)
    assert "os.O_APPEND" in source and "O_TRUNC" not in source
    _no_replace(first)
    old = ledger.read_text()
    fake = _events(ledger, lambda: ledger.write_text(old + json.dumps(row()) + "\n"))
    with pytest.raises(AssertionError, match="replace"):
        _no_replace(fake)


def test_contention(tmp_path, api):
    api.append(tmp_path, row("oracle", "prefix"))
    ledger, prefix, expected = tmp_path / api.LEDGER, (tmp_path / api.LEDGER).read_bytes(), [row("oracle", "prefix")]
    stale = api.read(tmp_path)
    for number in range(2):
        batch = [row(actor, f"round-{number}") for actor in ACTORS]
        _round(tmp_path, batch); expected += batch
    api.append(tmp_path, row("nara", "after-stale")); expected.append(row("nara", "after-stale"))
    actual = [json.loads(line) for line in ledger.read_bytes().splitlines()]
    canon = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"))
    assert stale == [row("oracle", "prefix")] and ledger.read_bytes().startswith(prefix)
    assert Counter(map(canon, actual)) == Counter(map(canon, expected)) == Counter(map(canon, api.read(tmp_path)))


@pytest.mark.parametrize("target", ("run_state", "root"))
def test_parent_sync(tmp_path, api, monkeypatch, target):
    api.append(tmp_path, row("oracle", "seed")); inode = (tmp_path / target).stat().st_ino if target == "run_state" else tmp_path.stat().st_ino
    entered, release, done, errors, real = threading.Event(), threading.Event(), threading.Event(), [], api.os.fsync
    def paused(fd):
        if api.os.fstat(fd).st_ino == inode and not entered.is_set(): entered.set(); assert release.wait(2)
        return real(fd)
    monkeypatch.setattr(api.os, "fsync", paused)
    writer = threading.Thread(target=lambda: _call(errors, api.append, tmp_path, row("nara", target)))
    follower = threading.Thread(target=lambda: (_call(errors, api.append, tmp_path, row("claude", "follower")), done.set()))
    writer.start(); assert entered.wait(2); follower.start(); time.sleep(.1); assert not done.is_set()
    release.set(); writer.join(3); follower.join(3)
    assert not errors and done.is_set() and {r["thesis"] for r in api.read(tmp_path)} == {"seed", target, "follower"}


def _call(errors, fn, *args):
    try: fn(*args)
    except Exception as exc: errors.append(exc)


def test_denials(tmp_path, api, monkeypatch):
    api.append(tmp_path, row()); ledger, prefix = tmp_path / api.LEDGER, (tmp_path / api.LEDGER).read_bytes()
    cases = [None, [], "x", {"forecaster": "nara"}]
    for key in NUMBERS:
        missing = row(); missing.pop(key); cases.append(missing)
        for value in (True, "x", math.nan, math.inf, -1, 11 if key == "interest_0_10" else 2):
            bad = row(); bad[key] = value; cases.append(bad)
    extra, too_big, nested = row(), row(), row(); extra["authority"] = "owner"; too_big["reasons"] = "x" * api.MAX_ROW_BYTES; nested["untrusted_extensions"] = {"x": [math.nan]}
    for bad in cases + [extra, too_big, nested]:
        with pytest.raises(api.ConvictionLedgerError): api.append(tmp_path, bad)
        assert ledger.read_bytes() == prefix
    monkeypatch.setattr(api, "MAX_LEDGER_BYTES", len(prefix))
    calls, real = [], api.os.fsync
    monkeypatch.setattr(api.os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    api.append(tmp_path, row())
    assert ledger.read_bytes() == prefix and len(calls) == 3
    with pytest.raises(api.ConvictionLedgerError): api.append(tmp_path, row("claude"))
    assert ledger.read_bytes() == prefix
    monkeypatch.setattr(api.os, "fsync", real)
    monkeypatch.setattr(api, "MAX_LEDGER_BYTES", 1 << 20)
    long = row(); long["reasons"] = "x" * api.MAX_ROW_BYTES; wire = json.dumps(long).encode() + b"\n"
    ledger.write_bytes(wire)
    for fn in (api.read, api.recover_torn_tail, lambda _: api.append(tmp_path, row())):
        with pytest.raises(api.ConvictionLedgerError): fn(tmp_path)
    assert ledger.read_bytes() == wire
    ledger.write_bytes(prefix)
    for wire in (json.dumps(row()).encode() + b"\r", json.dumps(long).encode() + b"\r\n"):
        ledger.write_bytes(wire)
        for fn in (api.read, api.recover_torn_tail, lambda _: api.append(tmp_path, row())):
            with pytest.raises(api.ConvictionLedgerError): fn(tmp_path)
        assert ledger.read_bytes() == wire
    ledger.write_bytes(prefix)
    ledger.write_bytes(prefix + b'{"bad":true}\n')
    with pytest.raises(api.ConvictionLedgerError): api.append(tmp_path, row())
    assert ledger.read_bytes() == prefix + b'{"bad":true}\n'
    victim = tmp_path / "victim"; victim.write_text("unchanged"); ledger.unlink(); ledger.symlink_to(victim)
    with pytest.raises(api.ConvictionLedgerError): api.append(tmp_path, row())
    assert victim.read_text() == "unchanged"
    ledger.unlink(); ledger.symlink_to(tmp_path / "missing")
    with pytest.raises(api.ConvictionLedgerError): api.read(tmp_path)
    with pytest.raises(api.ConvictionLedgerError): api.recover_torn_tail(tmp_path)
    escaped, root = tmp_path / "escaped", tmp_path / "root"; escaped.mkdir(); root.mkdir(); (root / "run_state").symlink_to(escaped, target_is_directory=True)
    with pytest.raises(api.ConvictionLedgerError): api.append(root, row())
    assert not (escaped / "thesis_convictions.jsonl").exists()


def test_retry(tmp_path, api, monkeypatch):
    api.append(tmp_path, row("oracle", "seed")); ledger, real, tripped = tmp_path / api.LEDGER, api.os.fsync, []
    def fail_once(fd):
        if api.os.fstat(fd).st_ino == ledger.stat().st_ino and not tripped: tripped.append(1); raise OSError("disk")
        return real(fd)
    payload = row("nara", "retry"); monkeypatch.setattr(api.os, "fsync", fail_once)
    with pytest.raises(api.ConvictionLedgerError): api.append(tmp_path, payload)
    monkeypatch.setattr(api.os, "fsync", real); api.append(tmp_path, payload)
    assert [r for r in api.read(tmp_path) if r == payload] == [payload]


def test_extensions_reject_recursion_and_allow_finite_negative(tmp_path, api):
    api.append(tmp_path, row()); ledger, prefix = tmp_path / api.LEDGER, (tmp_path / api.LEDGER).read_bytes()
    good = row("nara"); good["untrusted_extensions"] = {"x": [-1, {"y": -.5}]}; api.append(tmp_path, good)
    cyclic = row(); value = []; value.append(value); cyclic["untrusted_extensions"] = {"x": value}
    with pytest.raises(api.ConvictionLedgerError): api.append(tmp_path, cyclic)
    assert good in api.read(tmp_path)
    deep = (json.dumps(row())[:-1] + ',"untrusted_extensions":{"x":' + "[" * 1100 + "0" + "]" * 1100 + "}}\n").encode()
    ledger.write_bytes(prefix + deep)
    for fn in (api.read, api.recover_torn_tail):
        with pytest.raises(api.ConvictionLedgerError): fn(tmp_path)
    assert ledger.read_bytes() == prefix + deep


def test_recovery(tmp_path, api):
    api.append(tmp_path, row()); ledger, prefix = tmp_path / api.LEDGER, (tmp_path / api.LEDGER).read_bytes()
    api.recover_torn_tail(tmp_path); assert ledger.read_bytes() == prefix
    for tail in (b'{"bad":true}\n', json.dumps(row("nara")).encode()):
        ledger.write_bytes(prefix + tail)
        with pytest.raises(api.ConvictionLedgerError): api.recover_torn_tail(tmp_path)
        assert ledger.read_bytes() == prefix + tail
    for token in ("NaN", "Infinity"):
        tail = json.dumps(row()).replace("0.2", token).encode() + b"\n"
        ledger.write_bytes(prefix + tail)
        for fn in (api.read, api.recover_torn_tail, lambda _: api.append(tmp_path, row("nara"))):
            with pytest.raises(api.ConvictionLedgerError): fn(tmp_path)
        assert ledger.read_bytes() == prefix + tail
    corrupt = prefix + b'{"bad":\n' + json.dumps(row("nara")).encode() + b"\n"
    ledger.write_bytes(corrupt)
    with pytest.raises(api.ConvictionLedgerError): api.read(tmp_path)
    with pytest.raises(api.ConvictionLedgerError): api.recover_torn_tail(tmp_path)
    assert ledger.read_bytes() == corrupt
    ledger.write_bytes(b'{"partial"')
    with pytest.raises(api.ConvictionLedgerError): api.recover_torn_tail(tmp_path)
    assert ledger.read_bytes() == b'{"partial"'
    ledger.write_bytes(prefix + b'{"partial"')
    api.recover_torn_tail(tmp_path); api.recover_torn_tail(tmp_path)
    assert ledger.read_bytes() == prefix
