"""Tests for orchestrator/packet_dispatcher.py (LOOP_V1 P4 stage-(ii)).

Hermetic: every dispatch runs in a tmp_path git repo with an injected shell
"agent" script and an injected ledger + run-log — no network, no real model,
no writes to run_state/. The real tools/premerge_check.sh is executed (bash,
git-only) against the tmp worktree.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from orchestrator import packet_dispatcher as pd

REPO_ROOT = Path(__file__).resolve().parent.parent


def _mk_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (
        "git init -q",
        "git config user.email pkt@test.local",
        "git config user.name pkt-test",
    ):
        subprocess.run(cmd, shell=True, cwd=repo, check=True, capture_output=True)
    # Acceptance test: green only once fixed.txt exists.
    (repo / "check.sh").write_text("test -f fixed.txt\n")
    subprocess.run(
        "git add -A && git commit -qm init", shell=True, cwd=repo,
        check=True, capture_output=True,
    )
    return repo


def _mk_agent(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "agent.sh"
    script.write_text("#!/usr/bin/env bash\nset -e\n" + body)
    script.chmod(0o755)
    return ["bash", str(script)]


def _packet(**over) -> dict:
    base = {
        "task_id": "PKT-t1",
        "objective": "make check.sh pass by creating fixed.txt",
        "files_in_scope": ["fixed.txt"],
        "files_out_of_scope": ["run_state/"],
        "preconditions": ["git rev-parse HEAD"],
        "acceptance_criteria": {"test_cmd": "bash check.sh", "must_fail_before": True},
        "budgets": {"max_attempts": 1, "wall_clock_minutes": 1, "max_diff_lines": 50},
        "forbidden_actions": ["git push"],
        "rollback": {"branch_delete": True, "notes": ""},
    }
    base.update(over)
    return base


class _LogSink:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def __call__(self, event: dict, *, agent: str | None = None) -> None:
        self.rows.append({"agent": agent, **event})


def _dispatch(repo, tmp_path, agent_cmd, packet):
    sink = _LogSink()
    ledger = tmp_path / "packets.jsonl"
    report = pd.dispatch_packet(
        packet, agent_cmd=agent_cmd, ledger_path=ledger,
        repo_root=repo, run_log=sink,
    )
    lines = []
    if ledger.exists():
        lines = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    return report, lines, sink


# --- schema coverage: every required schema property appears in the source --

def _required_names(schema: dict) -> set[str]:
    names = set(schema.get("required", []))
    for sub in (schema.get("properties") or {}).values():
        if isinstance(sub, dict):
            names |= _required_names(sub)
    return names


def test_schema_required_fields_are_read_by_dispatcher():
    """'A field the dispatcher doesn't read is documentation, not control.'"""
    schema = json.loads((REPO_ROOT / "schema" / "task_packet.schema.json").read_text())
    source = (REPO_ROOT / "orchestrator" / "packet_dispatcher.py").read_text()
    missing = sorted(n for n in _required_names(schema) if n not in source)
    assert not missing, f"schema fields absent from dispatcher source: {missing}"


# --- e2e: injected agent fixes the failing test -> done ---------------------

def test_agent_fixes_failing_test_reaches_done(tmp_path):
    repo = _mk_repo(tmp_path)
    agent = _mk_agent(
        tmp_path, "echo done > fixed.txt\ngit add fixed.txt\ngit commit -qm fix\n"
    )
    report, lines, sink = _dispatch(repo, tmp_path, agent, _packet())
    assert report["status"] == "done"
    assert report["branch"] == "pkt/PKT-t1"
    assert report["merged"] is False
    assert report["premerge_ok"] is True
    assert len(report["test_output_digest"]) == 64
    assert [l["status"] for l in lines] == ["dispatched", "done"]
    assert lines[1]["decided_by"] == "dispatcher"
    assert lines[1]["test_output_digest"] == report["test_output_digest"]
    assert sink.rows and sink.rows[-1]["agent"] == "packet_dispatcher"
    # The branch exists but was NOT merged into the base branch.
    merged = subprocess.run(
        "git branch --merged HEAD", shell=True, cwd=repo,
        capture_output=True, text=True,
    ).stdout
    assert "pkt/PKT-t1" not in merged


# --- refusals ---------------------------------------------------------------

def test_already_green_is_refused_without_burning_an_attempt(tmp_path):
    repo = _mk_repo(tmp_path)
    (repo / "fixed.txt").write_text("already\n")
    report, lines, _ = _dispatch(repo, tmp_path, _mk_agent(tmp_path, "true\n"), _packet())
    assert report["status"] == "refused"
    assert report["refusal_reason"] == "nothing_to_do"
    assert report["attempts_used"] == 0
    assert lines == []


def test_failed_precondition_is_refused_without_burning_an_attempt(tmp_path):
    repo = _mk_repo(tmp_path)
    packet = _packet(preconditions=["test -f does_not_exist"])
    report, lines, _ = _dispatch(repo, tmp_path, _mk_agent(tmp_path, "true\n"), packet)
    assert report["status"] == "refused"
    assert report["refusal_reason"] == "precondition_failed"
    assert lines == []


# --- budgets ----------------------------------------------------------------

def test_useless_agent_exhausts_budget(tmp_path):
    repo = _mk_repo(tmp_path)
    packet = _packet(budgets={"max_attempts": 2, "wall_clock_minutes": 1,
                              "max_diff_lines": 50})
    report, lines, _ = _dispatch(repo, tmp_path, _mk_agent(tmp_path, "true\n"), packet)
    assert report["status"] == "budget_exhausted"
    assert report["attempts_used"] == 2
    assert [l["status"] for l in lines] == [
        "dispatched", "failed", "dispatched", "budget_exhausted"]
    assert "rollback_hint" in report and "git branch -D pkt/PKT-t1" in report["rollback_hint"]


# --- premerge gate ----------------------------------------------------------

def test_green_test_but_premerge_violation_is_terminal_failed(tmp_path):
    repo = _mk_repo(tmp_path)
    # Agent fixes the test but blows the 2-line diff budget.
    agent = _mk_agent(tmp_path, (
        "echo done > fixed.txt\nseq 50 > bloat.txt\n"
        "git add -A\ngit commit -qm fix\n"
    ))
    packet = _packet(budgets={"max_attempts": 3, "wall_clock_minutes": 1,
                              "max_diff_lines": 2})
    report, lines, _ = _dispatch(repo, tmp_path, agent, packet)
    assert report["status"] == "failed"
    assert report["premerge_ok"] is False
    assert report["attempts_used"] == 1  # terminal: retry cannot un-commit
    assert [l["status"] for l in lines] == ["dispatched", "failed"]


# --- attempt-before-invoke pin ----------------------------------------------

def test_dispatched_line_precedes_agent_crash(tmp_path):
    repo = _mk_repo(tmp_path)
    report, lines, _ = _dispatch(
        repo, tmp_path, ["/nonexistent/agent-binary"], _packet())
    assert lines[0]["status"] == "dispatched"
    assert lines[0]["attempt"] == 1
    assert report["status"] == "budget_exhausted"


# --- seams + validation -----------------------------------------------------

def test_missing_agent_seam_raises(tmp_path):
    repo = _mk_repo(tmp_path)
    with pytest.raises(pd.PacketDispatchError, match="no agent seam"):
        pd.dispatch_packet(
            _packet(), agent_cmd=None, ledger_path=tmp_path / "packets.jsonl",
            repo_root=repo, run_log=_LogSink(),
        )


def test_invalid_packet_raises_before_any_side_effect(tmp_path):
    bad = _packet()
    del bad["budgets"]
    with pytest.raises(pd.PacketDispatchError, match="schema validation"):
        pd.dispatch_packet(
            bad, agent_cmd=["true"], ledger_path=tmp_path / "packets.jsonl",
            repo_root=tmp_path, run_log=_LogSink(),
        )
    assert not (tmp_path / "packets.jsonl").exists()


# --- authorize-fix queue mapping --------------------------------------------

def test_consume_authorize_fix_queue_maps_enqueued_rows(tmp_path):
    queue = tmp_path / "authorize_fix_queue.jsonl"
    rows = [
        {"ref_id": "F-001", "outcome": "authorize_fix", "status": "enqueued",
         "contract": {"task_statement": "fix the flaky parser"}},
        {"ref_id": "F-002", "outcome": "authorize_fix", "status": "done",
         "contract": {"task_statement": "already handled"}},
        {"ref_id": "F-003", "outcome": "authorize_fix", "status": "enqueued",
         "packet": _packet(task_id="PKT-explicit")},
    ]
    queue.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    packets = pd.consume_authorize_fix_queue(queue)
    assert len(packets) == 2
    assert packets[0]["task_id"] == "PKT-fix-F-001"
    assert packets[0]["objective"] == "fix the flaky parser"
    assert packets[0]["acceptance_criteria"]["must_fail_before"] is True
    assert packets[1]["task_id"] == "PKT-explicit"
    # Skeleton without a real test_cmd fails validation at dispatch time.
    with pytest.raises(pd.PacketDispatchError):
        pd.dispatch_packet(
            packets[0], agent_cmd=["true"],
            ledger_path=tmp_path / "packets.jsonl", repo_root=tmp_path,
            run_log=_LogSink(),
        )


def test_consume_authorize_fix_queue_missing_file_is_empty(tmp_path):
    assert pd.consume_authorize_fix_queue(tmp_path / "absent.jsonl") == []
