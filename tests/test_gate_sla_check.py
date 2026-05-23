#!/usr/bin/env python3
"""Unit tests for tools/gate_sla_check.py.

Two SLA tracks are exercised:
  - 4h soft-gate auto-clear (writes a `no_objection` attestation when an
    open `request` attestation crosses its sla_hours threshold).
  - 48h hard-gate escalation (appends an entry to escalations.jsonl when
    a state.human_gates_pending entry crosses 48h).

All tests use a per-test temp directory; the module-level STATE_FILE,
ATTESTATIONS, ESCALATIONS, and _now are monkey-patched. No test ever
touches run_state/ on disk.

Run standalone:
    python3 tests/test_gate_sla_check.py
or under pytest:
    pytest tests/test_gate_sla_check.py
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import gate_sla_check  # noqa: E402


T0 = _dt.datetime(2026, 5, 23, 12, 0, 0, tzinfo=_dt.timezone.utc)


def iso(dt: _dt.datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def soft_request(task_id, *, ts: _dt.datetime, sla_hours: int | None = None):
    rec = {"kind": "request", "task_id": task_id, "ts": iso(ts)}
    if sla_hours is not None:
        rec["sla_hours"] = sla_hours
    return rec


def soft_outcome(task_id, kind, *, ts: _dt.datetime):
    return {"kind": kind, "task_id": task_id, "ts": iso(ts)}


def write_jsonl(path: Path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def write_state(path: Path, *, human_gates_pending):
    path.write_text(json.dumps({"human_gates_pending": human_gates_pending}))


@contextlib.contextmanager
def patched(dir_: Path, *, now: _dt.datetime = T0):
    saved = {
        "STATE_FILE": gate_sla_check.STATE_FILE,
        "ATTESTATIONS": gate_sla_check.ATTESTATIONS,
        "ESCALATIONS": gate_sla_check.ESCALATIONS,
        "_now": gate_sla_check._now,
    }
    gate_sla_check.STATE_FILE = dir_ / "week1.state.json"
    gate_sla_check.ATTESTATIONS = dir_ / "attestations.jsonl"
    gate_sla_check.ESCALATIONS = dir_ / "escalations.jsonl"
    gate_sla_check._now = lambda: now
    try:
        yield (gate_sla_check.STATE_FILE, gate_sla_check.ATTESTATIONS,
               gate_sla_check.ESCALATIONS)
    finally:
        gate_sla_check.STATE_FILE = saved["STATE_FILE"]
        gate_sla_check.ATTESTATIONS = saved["ATTESTATIONS"]
        gate_sla_check.ESCALATIONS = saved["ESCALATIONS"]
        gate_sla_check._now = saved["_now"]


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    saved = sys.argv
    sys.argv = ["gate_sla_check.py", *argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate_sla_check.main()
    finally:
        sys.argv = saved
    return code, out.getvalue(), err.getvalue()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


class SoftGateExpiryTest(unittest.TestCase):
    """find_expired_soft_gates + the no_objection auto-clear path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_request_under_4h_not_expired(self):
        # 3h 59min old — under the 4h SLA.
        req = soft_request("task-A", ts=T0 - _dt.timedelta(hours=3, minutes=59))
        write_jsonl(self.dir / "attestations.jsonl", [req])
        with patched(self.dir):
            expired = gate_sla_check.find_expired_soft_gates(
                gate_sla_check._read_jsonl(gate_sla_check.ATTESTATIONS), T0)
        self.assertEqual(expired, [])

    def test_open_request_past_4h_is_expired(self):
        # 4h 1min old — past SLA.
        req = soft_request("task-A", ts=T0 - _dt.timedelta(hours=4, minutes=1))
        write_jsonl(self.dir / "attestations.jsonl", [req])
        with patched(self.dir):
            expired = gate_sla_check.find_expired_soft_gates(
                gate_sla_check._read_jsonl(gate_sla_check.ATTESTATIONS), T0)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["task_id"], "task-A")

    def test_request_with_outcome_is_not_expired(self):
        # 5h ago request, then approved 1h later — must NOT be flagged.
        req = soft_request("task-A", ts=T0 - _dt.timedelta(hours=5))
        ok = soft_outcome("task-A", "approved", ts=T0 - _dt.timedelta(hours=4))
        write_jsonl(self.dir / "attestations.jsonl", [req, ok])
        with patched(self.dir):
            expired = gate_sla_check.find_expired_soft_gates(
                gate_sla_check._read_jsonl(gate_sla_check.ATTESTATIONS), T0)
        self.assertEqual(expired, [])

    def test_custom_sla_hours_honored(self):
        # Custom 1h SLA, request 2h old => expired.
        req = soft_request("task-B", ts=T0 - _dt.timedelta(hours=2),
                           sla_hours=1)
        write_jsonl(self.dir / "attestations.jsonl", [req])
        with patched(self.dir):
            expired = gate_sla_check.find_expired_soft_gates(
                gate_sla_check._read_jsonl(gate_sla_check.ATTESTATIONS), T0)
        self.assertEqual(len(expired), 1)

    def test_no_objection_clears_request(self):
        # Even a prior no_objection counts as a closing outcome.
        req = soft_request("task-A", ts=T0 - _dt.timedelta(hours=10))
        clear = soft_outcome("task-A", "no_objection",
                             ts=T0 - _dt.timedelta(hours=6))
        write_jsonl(self.dir / "attestations.jsonl", [req, clear])
        with patched(self.dir):
            expired = gate_sla_check.find_expired_soft_gates(
                gate_sla_check._read_jsonl(gate_sla_check.ATTESTATIONS), T0)
        self.assertEqual(expired, [])

    def test_main_appends_no_objection_when_sla_expires(self):
        req = soft_request("task-A", ts=T0 - _dt.timedelta(hours=5))
        write_jsonl(self.dir / "attestations.jsonl", [req])
        with patched(self.dir) as (_, attestations, _esc):
            code, out, _ = run_main([])
        self.assertEqual(code, 0)
        self.assertIn("Soft-gate SLA-expired requests: 1", out)
        recs = read_jsonl(attestations)
        # Original request + newly-appended no_objection.
        self.assertEqual(len(recs), 2)
        no_obj = recs[-1]
        self.assertEqual(no_obj["kind"], "no_objection")
        self.assertEqual(no_obj["task_id"], "task-A")
        self.assertEqual(no_obj["original_request_ts"], iso(
            T0 - _dt.timedelta(hours=5)))
        self.assertIn("SLA", no_obj["reason"])

    def test_dry_run_does_not_write(self):
        req = soft_request("task-A", ts=T0 - _dt.timedelta(hours=5))
        write_jsonl(self.dir / "attestations.jsonl", [req])
        with patched(self.dir) as (_, attestations, _esc):
            code, out, _ = run_main(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("[dry-run]", out)
        # File is untouched — still one record.
        self.assertEqual(len(read_jsonl(attestations)), 1)


class HardGateEscalationTest(unittest.TestCase):
    """find_expired_hard_gates + the escalations.jsonl auto-append path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_gate_under_48h_is_not_expired(self):
        pending = [{"task_id": "gate-X",
                    "ts": iso(T0 - _dt.timedelta(hours=47, minutes=59))}]
        write_state(self.dir / "week1.state.json", human_gates_pending=pending)
        with patched(self.dir):
            state = json.loads(gate_sla_check.STATE_FILE.read_text())
            expired = gate_sla_check.find_expired_hard_gates(state, T0)
        self.assertEqual(expired, [])

    def test_gate_past_48h_is_expired(self):
        pending = [{"task_id": "gate-X",
                    "ts": iso(T0 - _dt.timedelta(hours=49))}]
        write_state(self.dir / "week1.state.json", human_gates_pending=pending)
        with patched(self.dir):
            state = json.loads(gate_sla_check.STATE_FILE.read_text())
            expired = gate_sla_check.find_expired_hard_gates(state, T0)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["task_id"], "gate-X")

    def test_undated_string_gates_are_reported_undated(self):
        # Older state format: pending is a bare list of task IDs.
        write_state(self.dir / "week1.state.json",
                    human_gates_pending=["gate-Y"])
        with patched(self.dir):
            state = json.loads(gate_sla_check.STATE_FILE.read_text())
            expired = gate_sla_check.find_expired_hard_gates(state, T0)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0],
                         {"task_id": "gate-Y", "undated": True})

    def test_main_appends_escalation_when_48h_passes(self):
        pending = [{"task_id": "gate-X",
                    "ts": iso(T0 - _dt.timedelta(hours=49))}]
        write_state(self.dir / "week1.state.json", human_gates_pending=pending)
        # Need attestations.jsonl to exist (empty) so soft-gate scan is clean.
        write_jsonl(self.dir / "attestations.jsonl", [])
        with patched(self.dir) as (_, _att, escalations):
            code, out, _ = run_main([])
        self.assertEqual(code, 0)
        self.assertIn("Hard-gate SLA-expired entries: 1", out)
        recs = read_jsonl(escalations)
        self.assertEqual(len(recs), 1)
        esc = recs[0]
        self.assertEqual(esc["kind"], "hard_gate_sla_expired")
        self.assertEqual(esc["task_id"], "gate-X")
        self.assertEqual(esc["gate_ts"], iso(T0 - _dt.timedelta(hours=49)))
        self.assertFalse(esc["notification_sent"])

    def test_undated_gate_does_not_escalate(self):
        # Undated gates must be printed but never written to escalations.jsonl
        # because we can't prove the SLA expired.
        write_state(self.dir / "week1.state.json",
                    human_gates_pending=["gate-Y"])
        write_jsonl(self.dir / "attestations.jsonl", [])
        with patched(self.dir) as (_, _att, escalations):
            code, out, _ = run_main([])
        self.assertEqual(code, 0)
        self.assertIn("undated hard-gate", out)
        self.assertEqual(read_jsonl(escalations), [])

    def test_dry_run_does_not_write_escalations(self):
        pending = [{"task_id": "gate-X",
                    "ts": iso(T0 - _dt.timedelta(hours=49))}]
        write_state(self.dir / "week1.state.json", human_gates_pending=pending)
        write_jsonl(self.dir / "attestations.jsonl", [])
        with patched(self.dir) as (_, _att, escalations):
            code, out, _ = run_main(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("[dry-run] would append escalation", out)
        self.assertEqual(read_jsonl(escalations), [])

    def test_missing_state_file_is_tolerated(self):
        # No state file written => no hard-gate sweep, no crash.
        write_jsonl(self.dir / "attestations.jsonl", [])
        with patched(self.dir):
            code, out, _ = run_main([])
        self.assertEqual(code, 0)
        self.assertIn("Hard-gate SLA-expired entries: 0", out)

    def test_corrupt_state_file_emits_warning(self):
        (self.dir / "week1.state.json").write_text("{ not json")
        write_jsonl(self.dir / "attestations.jsonl", [])
        with patched(self.dir):
            code, _, err = run_main([])
        self.assertEqual(code, 0)
        self.assertIn("not valid JSON", err)


class CliSubprocessTest(unittest.TestCase):
    """Smoke test against the real entry point in dry-run mode.

    Runs against the live run_state/ in this worktree — only asserts the
    process exits cleanly and produces the expected headers, never the
    actual count, which depends on live state.
    """

    def test_cli_dry_run_smoke(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "tools" / "gate_sla_check.py"),
             "--dry-run"],
            capture_output=True, text=True,
            env={**os.environ, "MOCK_LLM": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Soft-gate SLA-expired requests:", proc.stdout)
        self.assertIn("Hard-gate SLA-expired entries:", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
