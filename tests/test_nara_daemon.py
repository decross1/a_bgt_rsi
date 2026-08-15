"""D-063 Stage-2 daemon tests — hermetic (tmp_path everywhere, MOCK_LLM=1,
stubbed cycle/dispatch seams; the conftest autouse fixture keeps the run log
and coordinator ledgers off the live tree).

Covers: the work_exists truth table (human-only gaps False; ladder gap /
agenda / armed packets True; packets without the flag False), wake-on-mtime,
heartbeat backoff arithmetic, gate order (flock, sentinel, pause before any
cycle; preflight refusal), the packet-dark pin (env unset -> dispatch never
called), --once / --dry-run, honest idle, hygiene re-render trigger, budget
refusal as a designed exit, and crash backoff.
"""
from __future__ import annotations

import fcntl
import json
import os

import pytest

from orchestrator import nara_daemon as nd


def _arm(tmp_path, monkeypatch, *, ratified=True, gaps=None, agenda=None,
         packets=None):
    """Point every daemon path at tmp, pass the preflight, stub the work
    seams + the cycle/dispatch seams with recorders. Returns the recorders."""
    calls = {"cycle": [], "dispatch": [], "gaps_reads": 0, "rerender": 0}
    for attr, name in [
        ("LOCK_PATH", "coordinator-cron.lock"),
        ("RATIFIED_PATH", "d049_ratified"),
        ("PAUSE_PATH", "pause_coordinator"),
        ("SECRETS_ENV", "secrets.env"),
        ("DAEMON_LOG_PATH", "nara-daemon.log"),
        ("LAB_CHANNEL_PATH", "lab_channel.jsonl"),
        ("FOLLOWUPS_PATH", "finding_followups.jsonl"),
        ("IDEA_LEDGER_PATH", "idea_ledger.jsonl"),
        ("FIX_QUEUE_PATH", "authorize_fix_queue.jsonl"),
        ("PACKETS_PATH", "packets.jsonl"),
        ("IDEAS_MD_PATH", "ideas.md"),
    ]:
        monkeypatch.setattr(nd, attr, tmp_path / name)
    if ratified:
        nd.RATIFIED_PATH.write_text("")
    monkeypatch.setattr(nd, "_preflight_ok", lambda: True)

    def _gaps():
        calls["gaps_reads"] += 1
        return list(gaps or [])

    monkeypatch.setattr(nd, "_gaps", _gaps)
    monkeypatch.setattr(nd, "_agenda", lambda: list(agenda or []))
    monkeypatch.setattr(nd, "_queued_packets", lambda: list(packets or []))

    def _cycle(budget):
        calls["cycle"].append(budget)
        return {"status": "executed"}

    monkeypatch.setattr(nd, "_run_cycle", _cycle)

    def _dispatch(packet, *, agent_cmd):
        calls["dispatch"].append((packet, agent_cmd))
        return {"status": "done"}

    monkeypatch.setattr(nd, "_dispatch_packet", _dispatch)
    monkeypatch.delenv("NARA_PACKET_DISPATCH", raising=False)
    monkeypatch.delenv("NARA_PACKET_AGENT_CMD", raising=False)
    return calls


def _log_text(tmp_path):
    p = tmp_path / "nara-daemon.log"
    return p.read_text() if p.exists() else ""


# ── work_exists truth table ──────────────────────────────────────────────

HUMAN_ONLY_GAPS = [
    "2 recent iteration(s) await a human gate verdict",
    "3 surfaced finding(s) await human review",
]
LADDER_GAP = ("3 open cluster(s) at L3 awaiting adversarial battery "
              "(vote survived + redteam proceed) for L4")
STALE_GAP = ("loop has not iterated in 3 days (last iteration it_x at "
             "2026-08-12T00:00:00+00:00; bar STALE_DAYS=2)")


def test_agent_actionable_gaps_filters_human_shapes():
    got = nd.agent_actionable_gaps(HUMAN_ONLY_GAPS + [LADDER_GAP, STALE_GAP])
    assert got == [LADDER_GAP, STALE_GAP]


def test_work_exists_human_only_gaps_is_false(tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch, gaps=HUMAN_ONLY_GAPS)
    assert nd.work_exists() == {"work": False, "reasons": []}


def test_work_exists_ladder_gap_is_true(tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch, gaps=HUMAN_ONLY_GAPS + [LADDER_GAP])
    verdict = nd.work_exists()
    assert verdict["work"] is True
    assert verdict["reasons"] == ["gaps:1"]


def test_work_exists_staleness_gap_is_true(tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch, gaps=[STALE_GAP])
    assert nd.work_exists()["work"] is True


def test_work_exists_agenda_item_is_true(tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch,
         agenda=[{"topic": "t", "source": "human", "cluster_id": "c1"}])
    verdict = nd.work_exists()
    assert verdict["work"] is True
    assert verdict["reasons"] == ["agenda:1"]


def test_work_exists_packets_with_flag_is_true(tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch, packets=[{"task_id": "PKT-1"}])
    monkeypatch.setenv("NARA_PACKET_DISPATCH", "1")
    verdict = nd.work_exists()
    assert verdict["work"] is True
    assert verdict["reasons"] == ["packets:1"]


def test_work_exists_packets_without_flag_is_false(tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch, packets=[{"task_id": "PKT-1"}])
    assert nd.work_exists()["work"] is False


# ── wake + heartbeat ─────────────────────────────────────────────────────

def test_wake_on_mtime_change(tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch)
    monkeypatch.setattr(
        nd, "_sleep", lambda s: nd.LAB_CHANNEL_PATH.write_text("turn\n"))
    assert nd.wait_for_wake(3600, poll_s=0.01) == "event:lab_channel"


def test_wake_heartbeat_floor(tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch)
    monkeypatch.setattr(nd, "_sleep", lambda s: None)
    assert nd.wait_for_wake(0) == "heartbeat"


def test_heartbeat_backoff_arithmetic():
    kw = dict(had_event=False, had_work=False, base_s=1800)
    assert nd.next_heartbeat_s(1800, **kw) == 3600
    assert nd.next_heartbeat_s(3600, **kw) == 7200
    assert nd.next_heartbeat_s(7200, **kw) == 7200          # 2 h ceiling
    assert nd.next_heartbeat_s(
        7200, had_event=True, had_work=False, base_s=1800) == 1800
    assert nd.next_heartbeat_s(
        7200, had_event=False, had_work=True, base_s=1800) == 1800


# ── gate ladder ──────────────────────────────────────────────────────────

def test_pause_file_blocks_before_any_cycle(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP])
    nd.PAUSE_PATH.write_text("")
    outcome = nd.run_pass(wake_reason="test")
    assert outcome["action"] == "refused:pause"
    assert calls["cycle"] == []
    assert calls["gaps_reads"] == 0  # gates precede any work evaluation
    assert "action=refused:pause" in _log_text(tmp_path)


def test_missing_d049_sentinel_refuses(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch, ratified=False, gaps=[LADDER_GAP])
    outcome = nd.run_pass(wake_reason="test")
    assert outcome["action"] == "refused:d049_sentinel"
    assert calls["cycle"] == []


def test_flock_respected(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP])
    holder = open(nd.LOCK_PATH, "w")
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        outcome = nd.run_pass(wake_reason="test")
    finally:
        holder.close()
    assert outcome["action"] == "skipped:flock"
    assert calls["cycle"] == []
    # Released lock -> the next pass proceeds to a cycle.
    outcome = nd.run_pass(wake_reason="test")
    assert outcome["action"].startswith("cycle:executed")
    assert calls["cycle"] == [6]


def test_preflight_refusal_blocks_cycle(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP])
    monkeypatch.setattr(nd, "_preflight_ok", lambda: False)
    outcome = nd.run_pass(wake_reason="test")
    assert outcome["action"] == "refused:preflight"
    assert calls["cycle"] == []


def test_preflight_subprocess_reads_injected_meminfo(tmp_path, monkeypatch):
    plenty = tmp_path / "meminfo.plenty"
    plenty.write_text("MemAvailable:  999999999 kB\n")
    scarce = tmp_path / "meminfo.scarce"
    scarce.write_text("MemAvailable:  1024 kB\n")
    monkeypatch.setenv("PREFLIGHT_MEMINFO", str(plenty))
    assert nd._preflight_ok() is True
    monkeypatch.setenv("PREFLIGHT_MEMINFO", str(scarce))
    assert nd._preflight_ok() is False


def test_budget_refusal_is_designed_exit(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP])
    monkeypatch.setattr(nd, "_budget_remaining", lambda b: False)
    outcome = nd.run_pass(wake_reason="test")
    assert outcome["action"] == "refused:daily_budget"
    assert outcome["worked"] is False
    assert calls["cycle"] == []


# ── honest idle + hygiene ────────────────────────────────────────────────

def test_no_work_is_honest_idle(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch)
    outcome = nd.run_pass(wake_reason="heartbeat")
    assert outcome == {"wake": "heartbeat", "work": "no", "action": "idle",
                       "worked": False}
    assert calls["cycle"] == []
    assert "work=no action=idle" in _log_text(tmp_path)


def test_hygiene_rerenders_ideas_md_iff_ledger_changed(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP])

    def rerender():
        calls["rerender"] += 1
        return True

    monkeypatch.setattr(nd, "_rerender_ideas", rerender)
    # Cycle leaves the ledger untouched -> no re-render.
    nd.run_pass(wake_reason="test")
    assert calls["rerender"] == 0

    def cycle_writes_ledger(budget):
        calls["cycle"].append(budget)
        with open(nd.IDEA_LEDGER_PATH, "a") as fh:
            fh.write("{}\n")
        return {"status": "executed"}

    monkeypatch.setattr(nd, "_run_cycle", cycle_writes_ledger)
    outcome = nd.run_pass(wake_reason="test")
    assert calls["rerender"] == 1
    assert outcome["action"] == "cycle:executed+ideas_md"


# ── packet dispatch (DARK) ───────────────────────────────────────────────

def test_packet_dark_env_unset_never_dispatches(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP],
                 packets=[{"task_id": "PKT-1"}])
    monkeypatch.setenv("NARA_PACKET_AGENT_CMD", json.dumps(["true"]))
    outcome = nd.run_pass(wake_reason="test")  # cycle runs; dispatch dark
    assert outcome["action"] == "cycle:executed"
    assert "packet" not in outcome
    assert calls["dispatch"] == []


def test_packet_armed_without_agent_cmd_logs_and_skips(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP],
                 packets=[{"task_id": "PKT-1"}])
    monkeypatch.setenv("NARA_PACKET_DISPATCH", "1")
    outcome = nd.run_pass(wake_reason="test")
    assert calls["dispatch"] == []
    assert outcome["packet"] == "skipped:no_agent_cmd"
    assert ("packet dispatch armed but no agent_cmd configured"
            in _log_text(tmp_path))


def test_packet_armed_dispatches_exactly_one(tmp_path, monkeypatch):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP],
                 packets=[{"task_id": "PKT-1"}, {"task_id": "PKT-2"}])
    monkeypatch.setenv("NARA_PACKET_DISPATCH", "1")
    monkeypatch.setenv("NARA_PACKET_AGENT_CMD", json.dumps(["echo", "agent"]))
    outcome = nd.run_pass(wake_reason="test")
    assert calls["dispatch"] == [({"task_id": "PKT-1"}, ["echo", "agent"])]
    assert outcome["packet"] == "done"
    assert outcome["action"] == "cycle:executed+packet:done"


# ── CLI: --once / --dry-run ──────────────────────────────────────────────

def test_once_runs_single_pass_and_cycles(tmp_path, monkeypatch, capsys):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP])
    rc = nd.main(["--once"])
    assert rc == 0
    assert calls["cycle"] == [6]
    printed = json.loads(capsys.readouterr().out.strip())
    assert printed["action"] == "cycle:executed"
    assert printed["wake"] == "once"


def test_dry_run_evaluates_but_never_cycles(tmp_path, monkeypatch, capsys):
    calls = _arm(tmp_path, monkeypatch, gaps=[LADDER_GAP],
                 agenda=[{"topic": "t", "source": "s", "cluster_id": "c"}])
    rc = nd.main(["--dry-run"])
    assert rc == 0
    assert calls["cycle"] == []
    printed = json.loads(capsys.readouterr().out.strip())
    assert printed["action"] == "dry_run"
    assert printed["work"] == "yes:gaps:1,agenda:1"
    assert "action=dry_run" in _log_text(tmp_path)


# ── crash backoff + secrets ──────────────────────────────────────────────

def test_crash_backoff_never_loop_storms(tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch)
    waits = iter([RuntimeError("boom"), KeyboardInterrupt()])
    monkeypatch.setattr(
        nd, "wait_for_wake", lambda hb, **kw: (_ for _ in ()).throw(next(waits)))
    slept = []
    monkeypatch.setattr(nd, "_sleep", slept.append)
    rc = nd.run_forever()
    assert rc == 0
    assert slept == [nd.CRASH_BACKOFF_S]
    log = _log_text(tmp_path)
    assert "ERROR: RuntimeError: boom" in log
    assert "daemon start" in log and "daemon stop" in log


def test_source_secrets_parses_exports_and_warns_when_absent(
        tmp_path, monkeypatch):
    _arm(tmp_path, monkeypatch)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    nd.SECRETS_ENV.write_text(
        "# comment\nexport NARA_TEST_SECRET='v1'\nPLAIN_TEST_SECRET=v2\n")
    try:
        nd._source_secrets()
        assert os.environ["NARA_TEST_SECRET"] == "v1"
        assert os.environ["PLAIN_TEST_SECRET"] == "v2"
    finally:
        os.environ.pop("NARA_TEST_SECRET", None)
        os.environ.pop("PLAIN_TEST_SECRET", None)
    assert "SEMANTIC_SCHOLAR_API_KEY absent" in _log_text(tmp_path)
