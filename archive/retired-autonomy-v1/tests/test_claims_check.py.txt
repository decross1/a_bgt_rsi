#!/usr/bin/env python3
"""Unit tests for tools/claims_check.py.

Exercises each subcommand of the claim-log sweeper:
  --dry-run, --check, --validate-ownership, --gc, --weekly-summary.

All tests build inline JSONL claim fixtures in a per-test temp directory
and monkey-patch the module-level CLAIMS_FILE / OWNERSHIP_FILE / _now so
no test ever touches run_state/claims.jsonl on disk.

Run standalone:
    python3 tests/test_claims_check.py
or under pytest:
    pytest tests/test_claims_check.py
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

import claims_check  # noqa: E402


T0 = _dt.datetime(2026, 5, 23, 12, 0, 0, tzinfo=_dt.timezone.utc)


def iso(dt: _dt.datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def write_claim(agent_id, paths, *, claim_ts=T0, ttl_hours=2, zone="tests-shared"):
    return {
        "timestamp": iso(claim_ts),
        "agent_id": agent_id,
        "zone": zone,
        "paths": list(paths),
        "intent": "write",
        "expires_at": iso(claim_ts + _dt.timedelta(hours=ttl_hours)),
    }


def release_entry(claim_ts, agent_id, *, ts=None):
    return {
        "timestamp": iso(ts or (claim_ts + _dt.timedelta(minutes=5))),
        "agent_id": agent_id,
        "intent": "release",
        "claim_timestamp": iso(claim_ts),
    }


def dump_claims(path: Path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


@contextlib.contextmanager
def patched(claims_path: Path, *, now: _dt.datetime = T0,
            ownership_path: Path | None = None):
    """Redirect claims_check at a tmp claims.jsonl + frozen clock."""
    saved_claims = claims_check.CLAIMS_FILE
    saved_ownership = claims_check.OWNERSHIP_FILE
    saved_now = claims_check._now
    claims_check.CLAIMS_FILE = claims_path
    if ownership_path is not None:
        claims_check.OWNERSHIP_FILE = ownership_path
    claims_check._now = lambda: now
    try:
        yield
    finally:
        claims_check.CLAIMS_FILE = saved_claims
        claims_check.OWNERSHIP_FILE = saved_ownership
        claims_check._now = saved_now


def run_cli(argv):
    """Call claims_check.main() via argv shim; return (exit, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    saved_argv = sys.argv
    sys.argv = ["claims_check.py", *argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = claims_check.main()
    finally:
        sys.argv = saved_argv
    return code, out.getvalue(), err.getvalue()


class DryRunTest(unittest.TestCase):
    """`--dry-run` (default): lists actives and exits 1 only on overlaps."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.claims = Path(self.tmp.name) / "claims.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_log_is_clean(self):
        dump_claims(self.claims, [])
        with patched(self.claims):
            code, out, err = run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("Active claims: 0", out)
        self.assertIn("No overlapping active claims", out)
        self.assertEqual(err, "")

    def test_released_claim_is_not_active(self):
        claim = write_claim("agent-a", ["tests/foo.py"])
        rel = release_entry(T0, "agent-a")
        dump_claims(self.claims, [claim, rel])
        with patched(self.claims):
            code, out, _ = run_cli(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("Active claims: 0", out)

    def test_expired_claim_is_not_active(self):
        # Claim created 5h before "now"; default ttl 2h => expired.
        old = T0 - _dt.timedelta(hours=5)
        claim = write_claim("agent-a", ["tests/foo.py"], claim_ts=old)
        dump_claims(self.claims, [claim])
        with patched(self.claims):
            code, out, _ = run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("Active claims: 0", out)

    def test_overlapping_claims_exit_1(self):
        a = write_claim("agent-a", ["tests/shared.py"])
        b = write_claim("agent-b", ["tests/shared.py"],
                        claim_ts=T0 + _dt.timedelta(minutes=1))
        dump_claims(self.claims, [a, b])
        with patched(self.claims):
            code, out, _ = run_cli([])
        self.assertEqual(code, 1)
        self.assertIn("Overlapping claims: 1", out)
        self.assertIn("agent-a", out)
        self.assertIn("agent-b", out)
        self.assertIn("tests/shared.py", out)

    def test_same_agent_two_claims_no_overlap(self):
        # An agent reclaiming its own paths is not an overlap.
        a = write_claim("agent-a", ["tests/x.py"])
        a2 = write_claim("agent-a", ["tests/x.py"],
                         claim_ts=T0 + _dt.timedelta(minutes=10))
        dump_claims(self.claims, [a, a2])
        with patched(self.claims):
            code, _, _ = run_cli(["--dry-run"])
        self.assertEqual(code, 0)

    def test_disjoint_paths_no_overlap(self):
        a = write_claim("agent-a", ["tests/a.py"])
        b = write_claim("agent-b", ["tests/b.py"])
        dump_claims(self.claims, [a, b])
        with patched(self.claims):
            code, _, _ = run_cli([])
        self.assertEqual(code, 0)

    def test_malformed_line_skipped(self):
        a = write_claim("agent-a", ["tests/a.py"])
        body = json.dumps(a) + "\n"
        body += "{ not valid json\n"
        body += "# a comment line\n"
        self.claims.write_text(body)
        with patched(self.claims):
            code, out, _ = run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("Active claims: 1", out)

    def test_schema_comment_line_skipped(self):
        sc = {"_schema_comment": "header"}
        a = write_claim("agent-a", ["tests/a.py"])
        dump_claims(self.claims, [sc, a])
        with patched(self.claims):
            code, out, _ = run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("Active claims: 1", out)


class CheckPathTest(unittest.TestCase):
    """`--check <path>`: 0 free, 1 held, 2 held-but-expired."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.claims = Path(self.tmp.name) / "claims.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_free_path_exits_0(self):
        dump_claims(self.claims, [write_claim("agent-a", ["tests/a.py"])])
        with patched(self.claims):
            code, _, _ = run_cli(["--check", "tests/b.py"])
        self.assertEqual(code, 0)

    def test_held_path_exits_1(self):
        dump_claims(self.claims, [write_claim("agent-a", ["tests/a.py"])])
        with patched(self.claims):
            code, out, _ = run_cli(["--check", "tests/a.py"])
        self.assertEqual(code, 1)
        self.assertIn("agent-a", out)

    def test_held_but_expired_exits_2(self):
        old = T0 - _dt.timedelta(hours=5)
        dump_claims(self.claims, [write_claim("agent-a", ["tests/a.py"],
                                              claim_ts=old)])
        with patched(self.claims):
            code, out, _ = run_cli(["--check", "tests/a.py"])
        self.assertEqual(code, 2)
        self.assertIn("safe to claim", out)

    def test_released_path_exits_0(self):
        claim = write_claim("agent-a", ["tests/a.py"])
        rel = release_entry(T0, "agent-a")
        dump_claims(self.claims, [claim, rel])
        with patched(self.claims):
            code, _, _ = run_cli(["--check", "tests/a.py"])
        self.assertEqual(code, 0)

    def test_latest_claim_wins_when_multiple(self):
        # Older expired claim; newer active claim on the same path.
        old = write_claim("agent-old", ["tests/a.py"],
                          claim_ts=T0 - _dt.timedelta(hours=5))
        new = write_claim("agent-new", ["tests/a.py"],
                          claim_ts=T0 - _dt.timedelta(minutes=10))
        dump_claims(self.claims, [old, new])
        with patched(self.claims):
            code, out, _ = run_cli(["--check", "tests/a.py"])
        self.assertEqual(code, 1)
        self.assertIn("agent-new", out)


class GcTest(unittest.TestCase):
    """`--gc`: surfaces write claims whose expiry is > 24h in the past."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.claims = Path(self.tmp.name) / "claims.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_just_expired_is_not_stale(self):
        # Claimed 3h ago with 2h ttl => expired 1h ago; below 24h threshold.
        recent = write_claim("agent-a", ["tests/a.py"],
                             claim_ts=T0 - _dt.timedelta(hours=3))
        dump_claims(self.claims, [recent])
        with patched(self.claims):
            code, out, _ = run_cli(["--gc"])
        self.assertEqual(code, 0)
        self.assertIn("Stale (expired > 24h ago) write claims: 0", out)

    def test_more_than_24h_expired_is_stale(self):
        # Claimed 30h ago with 2h ttl => expired 28h ago; above 24h threshold.
        stale = write_claim("agent-a", ["tests/a.py"],
                            claim_ts=T0 - _dt.timedelta(hours=30))
        dump_claims(self.claims, [stale])
        with patched(self.claims):
            code, out, _ = run_cli(["--gc"])
        self.assertEqual(code, 0)  # gc never fails; it only reports
        self.assertIn("Stale (expired > 24h ago) write claims: 1", out)
        self.assertIn("agent-a", out)
        self.assertIn("tests/a.py", out)

    def test_release_entries_are_not_gc_candidates(self):
        # A release record should never be reported as a stale write.
        rel = release_entry(T0 - _dt.timedelta(hours=30),
                            "agent-a", ts=T0 - _dt.timedelta(hours=29))
        dump_claims(self.claims, [rel])
        with patched(self.claims):
            code, out, _ = run_cli(["--gc"])
        self.assertEqual(code, 0)
        self.assertIn("Stale (expired > 24h ago) write claims: 0", out)

    def test_boundary_at_24h_is_not_stale(self):
        # Exactly 24h-since-expiry should be reported as NOT stale (> 24h).
        boundary = write_claim("agent-a", ["tests/a.py"],
                               claim_ts=T0 - _dt.timedelta(hours=26),
                               ttl_hours=2)
        dump_claims(self.claims, [boundary])
        with patched(self.claims):
            code, out, _ = run_cli(["--gc"])
        self.assertEqual(code, 0)
        # 26h ago + 2h ttl => expired exactly 24h ago; threshold is strictly >.
        self.assertIn("Stale (expired > 24h ago) write claims: 0", out)


class WeeklySummaryTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.claims = Path(self.tmp.name) / "claims.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_summary(self):
        dump_claims(self.claims, [])
        with patched(self.claims):
            code, out, _ = run_cli(["--weekly-summary"])
        self.assertEqual(code, 0)
        self.assertIn("overlapping_claims_now: 0", out)
        self.assertIn("expired_unreleased_total: 0", out)
        self.assertIn("active_now: 0", out)

    def test_overlaps_and_expired_unreleased_counted(self):
        # Two active overlapping claims + one expired-and-never-released claim.
        a = write_claim("agent-a", ["tests/x.py"])
        b = write_claim("agent-b", ["tests/x.py"],
                        claim_ts=T0 + _dt.timedelta(minutes=1))
        expired = write_claim("agent-c", ["tests/y.py"],
                              claim_ts=T0 - _dt.timedelta(hours=30))
        dump_claims(self.claims, [a, b, expired])
        with patched(self.claims):
            code, out, _ = run_cli(["--weekly-summary"])
        self.assertEqual(code, 0)
        self.assertIn("overlapping_claims_now: 1", out)
        self.assertIn("expired_unreleased_total: 1", out)
        self.assertIn("active_now: 2", out)

    def test_released_claim_not_counted_as_expired_unreleased(self):
        old = write_claim("agent-a", ["tests/a.py"],
                          claim_ts=T0 - _dt.timedelta(hours=30))
        rel = release_entry(T0 - _dt.timedelta(hours=30), "agent-a",
                            ts=T0 - _dt.timedelta(hours=29))
        dump_claims(self.claims, [old, rel])
        with patched(self.claims):
            code, out, _ = run_cli(["--weekly-summary"])
        self.assertEqual(code, 0)
        self.assertIn("expired_unreleased_total: 0", out)


class ValidateOwnershipTest(unittest.TestCase):
    """`--validate-ownership`: glob conflicts fail (exit 1); unassigned is a
    warning (exit 0). git ls-files is monkey-patched so the test owns the
    file list rather than the surrounding worktree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.claims = self.dir / "claims.jsonl"
        self.ownership = self.dir / "ownership.yaml"
        dump_claims(self.claims, [])
        self._saved_check_output = subprocess.check_output

    def tearDown(self):
        subprocess.check_output = self._saved_check_output
        self.tmp.cleanup()

    def _fake_git_ls_files(self, files):
        def fake(cmd, *args, **kwargs):
            if cmd[:2] == ["git", "ls-files"]:
                return "\n".join(files) + "\n"
            return self._saved_check_output(cmd, *args, **kwargs)
        subprocess.check_output = fake

    def test_clean_ownership_exits_0(self):
        self.ownership.write_text(
            "zones:\n"
            "  - id: tests\n"
            "    paths: ['tests/test_*.py']\n"
            "  - id: tools\n"
            "    paths: ['tools/*.py']\n"
        )
        self._fake_git_ls_files(["tests/test_a.py", "tools/foo.py"])
        with patched(self.claims, ownership_path=self.ownership):
            code, out, _ = run_cli(["--validate-ownership"])
        self.assertEqual(code, 0)
        self.assertIn("Multi-assigned (in >1 zone): 0", out)

    def test_overlapping_globs_exit_1(self):
        # Two zones both claim tests/test_*.py — that's a planning bug.
        self.ownership.write_text(
            "zones:\n"
            "  - id: zone-one\n"
            "    paths: ['tests/test_*.py']\n"
            "  - id: zone-two\n"
            "    paths: ['tests/test_*.py']\n"
        )
        self._fake_git_ls_files(["tests/test_a.py"])
        with patched(self.claims, ownership_path=self.ownership):
            code, out, _ = run_cli(["--validate-ownership"])
        self.assertEqual(code, 1)
        self.assertIn("Multi-assigned (in >1 zone): 1", out)
        self.assertIn("zone-one", out)
        self.assertIn("zone-two", out)

    def test_unassigned_file_is_warning_not_error(self):
        self.ownership.write_text(
            "zones:\n"
            "  - id: tests\n"
            "    paths: ['tests/test_*.py']\n"
        )
        self._fake_git_ls_files(["tests/test_a.py", "README.md"])
        with patched(self.claims, ownership_path=self.ownership):
            code, out, _ = run_cli(["--validate-ownership"])
        self.assertEqual(code, 0)
        self.assertIn("Unassigned (in 0 zones): 1", out)
        self.assertIn("README.md", out)


class CliSubprocessTest(unittest.TestCase):
    """One real-process smoke test against the committed repo state.

    Uses an empty per-test claims.jsonl via env-var indirection? No — the
    tool reads CLAIMS_FILE relative to its own location, so subprocess
    mode necessarily reads the real run_state/claims.jsonl. We only assert
    the tool exits cleanly and prints the expected header — never the
    claim count, which depends on live state.
    """

    def test_cli_dry_run_smoke(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "tools" / "claims_check.py"),
             "--dry-run"],
            capture_output=True, text=True,
            env={**os.environ, "MOCK_LLM": "1"})
        # Exit may be 0 or 1 depending on whether anyone holds overlapping
        # claims right now. Both are valid CLI outcomes.
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        self.assertIn("Active claims:", proc.stdout)

    def test_cli_help_lists_all_subcommands(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "tools" / "claims_check.py"), "--help"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        for flag in ("--dry-run", "--check", "--validate-ownership",
                     "--gc", "--weekly-summary"):
            self.assertIn(flag, proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
