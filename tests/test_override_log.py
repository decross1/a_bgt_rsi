"""Tests for orchestrator/override_log.py — the human-override ledger."""
import json
import subprocess
import sys

import pytest

from orchestrator.override_log import record_override


def test_append_shape(tmp_path):
    path = tmp_path / "overrides.jsonl"
    row = record_override(
        actor="human:derrick",
        packet_id="pkt-001",
        action="force_promote",
        rationale="finding is sound; skeptic mis-scored register",
        path=path,
    )
    assert set(row) == {"timestamp", "actor", "packet_id", "action", "rationale"}
    assert row["actor"] == "human:derrick"
    assert row["packet_id"] == "pkt-001"
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == row


def test_packet_id_may_be_none(tmp_path):
    path = tmp_path / "overrides.jsonl"
    row = record_override(
        actor="human:derrick",
        packet_id=None,
        action="halt_run",
        rationale="stopping for the day",
        path=path,
    )
    assert row["packet_id"] is None


@pytest.mark.parametrize("actor", ["", "nara", "workflow:wf1/build", "derrick"])
def test_non_human_actor_raises_and_writes_nothing(tmp_path, actor):
    path = tmp_path / "overrides.jsonl"
    with pytest.raises(ValueError, match="human-only"):
        record_override(
            actor=actor,
            packet_id=None,
            action="force_promote",
            rationale="why",
            path=path,
        )
    assert not path.exists()


@pytest.mark.parametrize("field", ["action", "rationale"])
def test_empty_action_or_rationale_raises(tmp_path, field):
    path = tmp_path / "overrides.jsonl"
    kwargs = {"action": "force_promote", "rationale": "why", field: ""}
    with pytest.raises(ValueError):
        record_override(
            actor="human:derrick", packet_id=None, path=path, **kwargs
        )
    assert not path.exists()


def test_cli_roundtrip(tmp_path):
    path = tmp_path / "overrides.jsonl"
    proc = subprocess.run(
        [
            sys.executable, "-m", "orchestrator.override_log",
            "--actor", "human:derrick",
            "--action", "skip_gate",
            "--rationale", "gate already covered by manual review",
            "--packet-id", "pkt-002",
            "--path", str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    row = json.loads(proc.stdout)
    assert row == json.loads(path.read_text().splitlines()[0])
    assert row["action"] == "skip_gate"


def test_cli_rejects_non_human(tmp_path):
    path = tmp_path / "overrides.jsonl"
    proc = subprocess.run(
        [
            sys.executable, "-m", "orchestrator.override_log",
            "--actor", "nara",
            "--action", "x",
            "--rationale", "y",
            "--path", str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "REJECTED" in proc.stderr
    assert not path.exists()
