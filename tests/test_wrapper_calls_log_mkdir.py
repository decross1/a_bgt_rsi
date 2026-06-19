"""Regression: agent_wrapper.wrapper._emit creates the call-log directory if it
is missing.

Root cause of the 2026-06-19 experiment-grounded chain stalls: the experiment
`loop_bridge.py` / `replication_driver.py` modules set
`LOOP_V0_CALLS_LOG = <exp>/runs/calls.jsonl` at IMPORT time but only `mkdir` that
dir inside their `main()`. When `autoresearch` imports them (e.g. `replication_driver`
under `--replicate` -> `experiments/runs/`), the env var leaks process-wide and the
dir does not exist, so the wrapper's `open(log_path, "a")` raised `FileNotFoundError`
on EVERY `call_sync` (hypothesize / novelty_classify / critic_loop_v0 all failed ->
the chain looped to max_depth and never vetted the finding). The wrapper now ensures
the log dir exists before writing.
"""
import json
from pathlib import Path

from agent_wrapper.wrapper import _emit


def _valid_record() -> dict:
    with open(Path(__file__).parent / "example_call.jsonl") as fh:
        return json.loads(fh.readline())


def test_emit_creates_missing_log_dir(tmp_path):
    log_path = tmp_path / "does" / "not" / "exist" / "calls.jsonl"
    assert not log_path.parent.exists()
    _emit(_valid_record(), str(log_path))
    assert log_path.is_file()
    assert log_path.read_text().strip(), "the record should have been appended"


def test_emit_appends_to_existing_dir(tmp_path):
    log_path = tmp_path / "calls.jsonl"
    rec = _valid_record()
    _emit(rec, str(log_path))
    _emit(rec, str(log_path))
    assert len(log_path.read_text().splitlines()) == 2
