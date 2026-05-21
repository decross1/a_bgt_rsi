#!/usr/bin/env python3
"""Unit tests for tools/inspect_run.py.

Most tests build a 4-link causal chain as inline JSONL fixtures written
to a per-test temp directory:

    orchestrator_dispatch -> worker_invocation -> wrapper_request
                                              -> wrapper_response

and assert the reconstructed chain. Two tests additionally read the real
read-only logs (logs/day4_e2e.jsonl, logs/day2.jsonl) WITHOUT modifying
them -- they assert the file mtime is unchanged afterwards.

Run standalone:
    python3 tests/test_inspect_run.py
or under pytest:
    pytest tests/test_inspect_run.py
"""
import contextlib
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
sys.path.insert(0, str(REPO))

import inspect_run  # noqa: E402

# Stable uuid4-shaped ids for the 4-link fixture chain.
DISP = "11111111-1111-4111-8111-111111111111"
WORK = "22222222-2222-4222-8222-222222222222"
WREQ = "33333333-3333-4333-8333-333333333333"
WRESP = "44444444-4444-4444-8444-444444444444"
TASK_ID = "summarize-paper-7"


def four_link_chain(task_id=TASK_ID, task_on_wrapper=True, break_at_wreq=False):
    """Return the four records of a full orchestrator->vLLM chain.

    task_on_wrapper: when False the two wrapper records carry no task_id,
        mimicking the real split where logs/orchestrator.jsonl holds the
        task_id'd records and logs/dayN.jsonl holds bare wrapper calls.
    break_at_wreq: when True wrapper_request points at a non-existent
        parent, fragmenting the chain.
    """
    disp = {
        "level": "orchestrator_dispatch", "request_id": DISP,
        "parent_request_id": None, "task_id": task_id,
        "task_type": "summarize_paper",
        "timestamp": "2026-05-21T10:00:00.000000Z", "duration_ms": 12.4,
    }
    work = {
        "level": "worker_invocation", "request_id": WORK,
        "parent_request_id": DISP, "task_id": task_id,
        "task_type": "summarize_paper", "status": "passed",
        "timestamp": "2026-05-21T10:00:00.030000Z", "duration_ms": 910.2,
    }
    wreq = {
        "level": "wrapper_request", "request_id": WREQ,
        "parent_request_id": "deadbeef-0000-4000-8000-000000000000"
        if break_at_wreq else WORK,
        "caller_tag": "summarize_worker",
        "timestamp": "2026-05-21T10:00:00.060000Z", "duration_ms": 3.1,
    }
    wresp = {
        "level": "wrapper_response", "request_id": WRESP,
        "parent_request_id": WREQ, "model": "gemma-4-26b-a4b",
        "caller_tag": "summarize_worker",
        "completion": "This paper introduces a new method for X.",
        "usage": {"input_tokens": 420, "output_tokens": 96},
        "latency_ms": 638.5,
        "timestamp": "2026-05-21T10:00:00.064000Z",
    }
    if task_on_wrapper:
        wreq["task_id"] = task_id
        wresp["task_id"] = task_id
    return [disp, work, wreq, wresp]


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def run_cli(argv):
    """Invoke inspect_run.run(argv) capturing (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = inspect_run.run(argv)
    return code, out.getvalue(), err.getvalue()


def leading_spaces(line):
    return len(line) - len(line.lstrip(" "))


class FourLinkChainTest(unittest.TestCase):
    """Single-file 4-link chain rooted by --task-id."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = self.dir / "orchestrator.jsonl"
        write_jsonl(self.log, four_link_chain())

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_four_levels_print(self):
        code, out, err = run_cli(
            ["--task-id", TASK_ID, "--log", str(self.log), "--no-discover"])
        self.assertEqual(code, 0, err)
        for level in ("orchestrator_dispatch", "worker_invocation",
                      "wrapper_request", "wrapper_response"):
            self.assertIn(level, out)
        self.assertIn("4 record(s)", out)
        self.assertEqual(err, "")  # a clean chain produces no warnings

    def test_all_four_request_ids_print(self):
        _, out, _ = run_cli(
            ["--task-id", TASK_ID, "--log", str(self.log), "--no-discover"])
        for rid in (DISP, WORK, WREQ, WRESP):
            self.assertIn(rid, out)

    def test_indentation_increases_with_depth(self):
        _, out, _ = run_cli(
            ["--task-id", TASK_ID, "--log", str(self.log), "--no-discover"])
        lines = out.splitlines()

        def level_line(name):
            return next(ln for ln in lines if f"[{name}]" in ln)

        indents = [leading_spaces(level_line(n)) for n in (
            "orchestrator_dispatch", "worker_invocation",
            "wrapper_request", "wrapper_response")]
        self.assertEqual(indents, sorted(indents))
        self.assertEqual(len(set(indents)), 4, "each level must be deeper")

    def test_timestamps_and_durations_present(self):
        _, out, _ = run_cli(
            ["--task-id", TASK_ID, "--log", str(self.log), "--no-discover"])
        lines = out.splitlines()
        dispatch = next(ln for ln in lines if "[orchestrator_dispatch]" in ln)
        self.assertIn("2026-05-21T10:00:00.000000Z", dispatch)
        self.assertIn("dur=12.4ms", dispatch)
        response = next(ln for ln in lines if "[wrapper_response]" in ln)
        self.assertIn("dur=638.5ms", response)  # falls back to latency_ms

    def test_completion_preview_in_summary(self):
        _, out, _ = run_cli(
            ["--task-id", TASK_ID, "--log", str(self.log), "--no-discover"])
        self.assertIn("introduces a new method", out)


class RootingTest(unittest.TestCase):
    """Root selection by --request-id and not-found handling."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = self.dir / "orchestrator.jsonl"
        write_jsonl(self.log, four_link_chain())

    def tearDown(self):
        self.tmp.cleanup()

    def test_request_id_roots_midchain(self):
        # Rooting at the worker invocation drops the dispatch above it.
        code, out, err = run_cli(
            ["--request-id", WORK, "--log", str(self.log), "--no-discover"])
        self.assertEqual(code, 0, err)
        # The dispatch is not a node in the tree (it may still be named as
        # the rooted worker's parent= field, which is correct).
        self.assertNotIn("[orchestrator_dispatch]", out)
        for level in ("worker_invocation", "wrapper_request",
                      "wrapper_response"):
            self.assertIn(f"[{level}]", out)
        self.assertIn("3 record(s)", out)

    def test_task_id_not_found_exits_1(self):
        code, out, err = run_cli(
            ["--task-id", "no-such-task", "--log", str(self.log),
             "--no-discover"])
        self.assertEqual(code, 1)
        self.assertIn("no record with task_id", err)

    def test_request_id_not_found_exits_1(self):
        code, _, err = run_cli(
            ["--request-id", "00000000-0000-4000-8000-000000000000",
             "--log", str(self.log), "--no-discover"])
        self.assertEqual(code, 1)
        self.assertIn("no record with request_id", err)

    def test_missing_log_file_exits_1(self):
        code, _, err = run_cli(
            ["--task-id", TASK_ID, "--log", str(self.dir / "nope.jsonl"),
             "--no-discover"])
        self.assertEqual(code, 1)
        self.assertIn("no usable log records", err)


class CrossFileTest(unittest.TestCase):
    """The chain spans two files: orchestrator records carry task_id,
    bare wrapper records do not -- they attach via parent_request_id."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        chain = four_link_chain(task_on_wrapper=False)
        self.orch = self.dir / "orchestrator.jsonl"
        self.wrap = self.dir / "day6.jsonl"
        write_jsonl(self.orch, chain[:2])   # dispatch + worker
        write_jsonl(self.wrap, chain[2:])   # wrapper request + response

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_logs_join_the_chain(self):
        code, out, err = run_cli(
            ["--task-id", TASK_ID, "--log", str(self.orch),
             "--log", str(self.wrap), "--no-discover"])
        self.assertEqual(code, 0, err)
        for level in ("orchestrator_dispatch", "worker_invocation",
                      "wrapper_request", "wrapper_response"):
            self.assertIn(level, out)
        self.assertIn("4 record(s)", out)

    def test_sibling_discovery_finds_wrapper_log(self):
        # Only the orchestrator log is named; discovery pulls in day6.jsonl.
        code, out, err = run_cli(
            ["--task-id", TASK_ID, "--log", str(self.orch)])
        self.assertEqual(code, 0, err)
        self.assertIn("wrapper_response", out)
        self.assertIn("4 record(s)", out)

    def test_no_discover_leaves_chain_short(self):
        # Without discovery and without --log day6.jsonl, only 2 levels.
        code, out, _ = run_cli(
            ["--task-id", TASK_ID, "--log", str(self.orch), "--no-discover"])
        self.assertEqual(code, 0)
        self.assertIn("worker_invocation", out)
        self.assertNotIn("wrapper_response", out)
        self.assertIn("2 record(s)", out)


class BrokenChainTest(unittest.TestCase):
    """Malformed, fragmented and cyclic logs are reported, never coerced."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_malformed_line_skipped_with_warning(self):
        log = self.dir / "orchestrator.jsonl"
        chain = four_link_chain()
        body = json.dumps(chain[0]) + "\n"
        body += "{ this is not valid json\n"
        body += "".join(json.dumps(r) + "\n" for r in chain[1:])
        log.write_text(body)
        code, out, err = run_cli(
            ["--task-id", TASK_ID, "--log", str(log), "--no-discover"])
        self.assertEqual(code, 0, err)
        self.assertIn("malformed JSON", err)
        # The valid records still reconstruct.
        self.assertIn("orchestrator_dispatch", out)
        self.assertIn("worker_invocation", out)

    def test_fragmented_chain_reported(self):
        log = self.dir / "orchestrator.jsonl"
        write_jsonl(log, four_link_chain(break_at_wreq=True))
        code, out, err = run_cli(
            ["--task-id", TASK_ID, "--log", str(log), "--no-discover"])
        self.assertEqual(code, 0, err)
        self.assertIn("fragmented", err)
        self.assertIn("chain break", err)
        self.assertIn("chain fragment 1 of 2", out)
        # All four levels still surface, just in two fragments.
        for level in ("orchestrator_dispatch", "wrapper_request"):
            self.assertIn(level, out)

    def test_cycle_detected_without_hang(self):
        log = self.dir / "orchestrator.jsonl"
        a = {"level": "a", "request_id": DISP, "parent_request_id": WORK,
             "task_id": TASK_ID, "timestamp": "2026-05-21T10:00:00Z"}
        b = {"level": "b", "request_id": WORK, "parent_request_id": DISP,
             "task_id": TASK_ID, "timestamp": "2026-05-21T10:00:01Z"}
        write_jsonl(log, [a, b])
        code, _, err = run_cli(
            ["--task-id", TASK_ID, "--log", str(log), "--no-discover"])
        self.assertEqual(code, 0)
        self.assertIn("cycle", err)

    def test_duplicate_request_id_reported(self):
        log = self.dir / "orchestrator.jsonl"
        chain = four_link_chain()
        write_jsonl(log, chain + [chain[1]])  # worker record twice
        code, _, err = run_cli(
            ["--task-id", TASK_ID, "--log", str(log), "--no-discover"])
        self.assertEqual(code, 0)
        self.assertIn("duplicate request_id", err)


class RealLogReadOnlyTest(unittest.TestCase):
    """Reads the committed read-only logs and asserts they are untouched."""

    def test_day4_e2e_two_link_chain(self):
        log = REPO / "logs" / "day4_e2e.jsonl"
        if not log.is_file():
            self.skipTest("logs/day4_e2e.jsonl absent")
        before = log.stat().st_mtime_ns
        records = [json.loads(ln) for ln in
                   log.read_text().splitlines() if ln.strip()]
        root_id = records[0]["request_id"]
        child_id = records[1]["request_id"]
        self.assertEqual(records[1]["parent_request_id"], root_id,
                         "fixture assumption: day4_e2e is a 2-link chain")
        code, out, err = run_cli(
            ["--request-id", root_id, "--log", str(log), "--no-discover"])
        self.assertEqual(code, 0, err)
        self.assertIn(root_id, out)
        self.assertIn(child_id, out)
        self.assertIn("2 record(s)", out)
        self.assertEqual(log.stat().st_mtime_ns, before,
                         "inspect_run must not modify the real log")

    def test_day2_singleton_chain(self):
        log = REPO / "logs" / "day2.jsonl"
        if not log.is_file():
            self.skipTest("logs/day2.jsonl absent")
        before = log.stat().st_mtime_ns
        first = json.loads(log.read_text().splitlines()[0])
        # day2 predates call chains: every parent_request_id is null.
        code, out, err = run_cli(
            ["--request-id", first["request_id"], "--log", str(log),
             "--no-discover"])
        self.assertEqual(code, 0, err)
        self.assertIn("1 record(s)", out)
        self.assertEqual(log.stat().st_mtime_ns, before)


class CliSubprocessTest(unittest.TestCase):
    """Exercises the actual `python3 tools/inspect_run.py` entry point."""

    def test_cli_runs_and_reconstructs_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "orchestrator.jsonl"
            write_jsonl(log, four_link_chain())
            proc = subprocess.run(
                [sys.executable, str(REPO / "tools" / "inspect_run.py"),
                 "--task-id", TASK_ID, "--log", str(log), "--no-discover"],
                capture_output=True, text=True, env={**os.environ,
                                                     "MOCK_LLM": "1"})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("wrapper_response", proc.stdout)
            self.assertIn("4 record(s)", proc.stdout)

    def test_cli_requires_a_selector(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "tools" / "inspect_run.py")],
            capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
