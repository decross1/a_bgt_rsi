"""Dispatcher policy/receipt unit tests with a deterministic inert adapter.

No shell, Git, model, endpoint, generated candidate or builder executes. The
real schema/control/ledger code runs against private files; scripted external
observations exercise refusal, budget, scope and receipt behavior. This is not
qualification of actual Git/worktrees, builders or premerge integration.
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
    return repo


def _mk_agent(tmp_path: Path, result: str) -> list[str]:
    return ["inert-agent", result]


class _Effects:
    """Strict scripted observations; unknown commands fail rather than succeed."""
    def __init__(self, private):
        self.private, self.green, self.gate_rc = private, False, 0
        self.commands, self.agents, self.gates = [], [], []
        self.base = "a" * 40

    def shell(self, command, cwd, timeout=None):
        self.commands.append(command)
        if command == "git rev-parse HEAD":
            return subprocess.CompletedProcess(command, 0, self.base + "\n", "")
        if command == "test -f does_not_exist":
            return subprocess.CompletedProcess(command, 1, "", "missing prerequisite")
        if command == "bash check.sh":
            green = self.green or (Path(cwd) / "fixed.txt").exists()
            return subprocess.CompletedProcess(command, 0 if green else 1,
                                                "fixture green" if green else "fixture red", "")
        if command == "git status --porcelain":
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == "git merge-base HEAD " + self.base:
            return subprocess.CompletedProcess(command, 0, self.base, "")
        raise AssertionError("unplanned shell effect: " + command)

    def worktree(self, repo_root, packet_id):
        target = self.private / "inert-worktree"
        target.mkdir(exist_ok=True)
        return target

    def run(self, argv, **kwargs):
        if argv[:2] == ["bash", str(pd.PREMERGE_SCRIPT)]:
            assert len(argv) == 4 and argv[2] == self.base
            self.gates.append({"argv": argv, **kwargs})
            return subprocess.CompletedProcess(argv, self.gate_rc, "scripted premerge", "")
        if argv == ["/nonexistent/agent-binary"]:
            raise FileNotFoundError("scripted agent launch failure")
        assert len(argv) == 2 and argv[0] == "inert-agent", "unplanned process effect"
        assert argv[1] in {"success", "noop", "bloat", "refused"}
        # The real append must precede any external attempt observation.
        latest = json.loads((self.private / "packets.jsonl").read_text().splitlines()[-1])
        assert latest["status"] == "dispatched"
        self.agents.append({"argv": argv, **kwargs})
        self.green = argv[1] in {"success", "bloat"}
        self.gate_rc = 1 if argv[1] == "bloat" else 0
        refused = argv[1] == "refused"
        return subprocess.CompletedProcess(argv, 3 if refused else 0,
            "REFUSED: scripted out-of-scope write" if refused else "scripted agent result", "")


@pytest.fixture(autouse=True)
def inert_effects(tmp_path, monkeypatch):
    effects = _Effects(tmp_path)
    monkeypatch.setattr(pd, "_sh", effects.shell)
    monkeypatch.setattr(pd, "_ensure_worktree", effects.worktree)
    monkeypatch.setattr(pd.subprocess, "run", effects.run)
    return effects


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


# --- policy: scripted successful agent observation -> done ----------------

def test_agent_fixes_failing_test_reaches_done(tmp_path, inert_effects, monkeypatch):
    repo = _mk_repo(tmp_path)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY",
                 "SEMANTIC_SCHOLAR_API_KEY"):
        monkeypatch.setenv(name, "synthetic-test-value")
    agent = _mk_agent(tmp_path, "success")
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
    assert not any(command.startswith("git merge ") for command in inert_effects.commands)
    assert len(inert_effects.agents) == 1
    passed = inert_effects.agents[0]["env"]
    packet = _packet()
    assert passed["PKT_TASK_ID"] == packet["task_id"]
    assert passed["PKT_OBJECTIVE"] == packet["objective"]
    for key, field in [("PKT_FILES_IN_SCOPE", "files_in_scope"),
                       ("PKT_FILES_OUT_OF_SCOPE", "files_out_of_scope"),
                       ("PKT_FORBIDDEN_ACTIONS", "forbidden_actions")]:
        assert json.loads(passed[key]) == packet[field]
    assert not set(passed) & {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                              "OPENAI_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"}


# --- refusals ---------------------------------------------------------------

def test_already_green_is_refused_without_burning_an_attempt(tmp_path, inert_effects):
    repo = _mk_repo(tmp_path)
    (repo / "fixed.txt").write_text("already\n")
    report, lines, _ = _dispatch(repo, tmp_path, _mk_agent(tmp_path, "noop"), _packet())
    assert report["status"] == "refused"
    assert report["refusal_reason"] == "nothing_to_do"
    assert report["attempts_used"] == 0
    assert lines == []
    assert inert_effects.agents == []


def test_failed_precondition_is_refused_without_burning_an_attempt(tmp_path, inert_effects):
    repo = _mk_repo(tmp_path)
    packet = _packet(preconditions=["test -f does_not_exist"])
    report, lines, _ = _dispatch(repo, tmp_path, _mk_agent(tmp_path, "noop"), packet)
    assert report["status"] == "refused"
    assert report["refusal_reason"] == "precondition_failed"
    assert lines == []
    assert inert_effects.agents == []


# --- budgets ----------------------------------------------------------------

def test_useless_agent_exhausts_budget(tmp_path):
    repo = _mk_repo(tmp_path)
    packet = _packet(budgets={"max_attempts": 2, "wall_clock_minutes": 1,
                              "max_diff_lines": 50})
    report, lines, _ = _dispatch(repo, tmp_path, _mk_agent(tmp_path, "noop"), packet)
    assert report["status"] == "budget_exhausted"
    assert report["attempts_used"] == 2
    assert [l["status"] for l in lines] == [
        "dispatched", "failed", "dispatched", "budget_exhausted"]
    assert "rollback_hint" in report and "git branch -D pkt/PKT-t1" in report["rollback_hint"]


# --- premerge gate ----------------------------------------------------------

def test_green_test_but_premerge_violation_is_terminal_failed(tmp_path, inert_effects):
    repo = _mk_repo(tmp_path)
    # Scripted gate refusal, without executing a candidate or the shell gate.
    agent = _mk_agent(tmp_path, "bloat")
    packet = _packet(budgets={"max_attempts": 3, "wall_clock_minutes": 1,
                              "max_diff_lines": 2})
    report, lines, _ = _dispatch(repo, tmp_path, agent, packet)
    assert report["status"] == "failed"
    assert report["premerge_ok"] is False
    assert inert_effects.gates[0]["argv"][-1] == "2"
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


def test_agent_output_is_captured_on_a_failed_attempt(tmp_path):
    """2026-08-15: the dispatcher discarded the agent's stdout, so a builder
    that REFUSED an out-of-scope write (qwen_builder does exactly that,
    loudly) left no trace in packets.jsonl — the failure was invisible. A
    non-done attempt now carries agent_rc + an agent_tail excerpt."""
    repo = _mk_repo(tmp_path)
    agent = _mk_agent(tmp_path, "refused")
    report, lines, sink = _dispatch(repo, tmp_path, agent, _packet())
    assert report["status"] != "done"
    closes = [l for l in lines if l["status"] in ("failed", "budget_exhausted")]
    assert closes, "a refused attempt must close the ledger line"
    last = closes[-1]
    assert last["agent_rc"] == 3
    assert "REFUSED" in last["agent_tail"]



def test_inert_adapter_refuses_unplanned_commands(inert_effects, tmp_path):
    with pytest.raises(AssertionError, match="unplanned"):
        inert_effects.shell("git merge forbidden", tmp_path)
    with pytest.raises(AssertionError, match="unplanned"):
        inert_effects.run(["unexpected-command"])
