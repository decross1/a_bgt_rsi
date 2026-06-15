"""orchestrator/authorize_fix.py — outcome-4 spawn-contract enqueue (seams 3+4).

Mirrors test discipline from test_todo_cli.py / gate_cli: validate-then-append,
rejections exit nonzero and write NOTHING, append-only. The extra invariant
here is the SHAPE: a valid row must carry the FULL spawn-contract block so a
future stage-(ii) dispatcher consumes it with no schema migration.
"""
import json

import pytest

from orchestrator import authorize_fix

# Every field the spawn-contract skill / CLAUDE.md Dynamic Workflow rule 3
# requires inside contract{}. Option-(ii) readiness == all present.
SPAWN_CONTRACT_FIELDS = {
    "task_statement", "done_condition", "skill_subset", "authority_cap",
    "self_gating_rules", "reporting_format", "escalation_path", "budget",
    "state_basis",
}


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _surface(tmp_path):
    """A surfaced_findings.jsonl with one resolvable finding id."""
    p = tmp_path / "surfaced.jsonl"
    p.write_text(json.dumps({"finding_id": "F-1", "claim": "x"}) + "\n")
    return p


def _call(tmp_path, ref_id="F-1", task="fix the over-gate", note="why",
          **overrides):
    """authorize_fix with a tmp queue + a one-finding surface, by default
    resolvable. Tests override pieces as needed."""
    kw = dict(
        path=tmp_path / "queue.jsonl",
        surfaced_path=_surface(tmp_path),
        defer_path=tmp_path / "defer.jsonl",      # absent -> no rows
        bubbles_path=tmp_path / "bubbles.jsonl",  # absent -> no rows
    )
    kw.update(overrides)
    return authorize_fix.authorize_fix(ref_id, task, note, "human:ui", **kw)


# ----------------------------------------------------------- happy path

def test_valid_enqueue_writes_full_contract_row(tmp_path):
    queue = tmp_path / "queue.jsonl"
    row = _call(tmp_path, path=queue)
    assert _rows(queue) == [row]
    assert row["ref_id"] == "F-1"
    assert row["outcome"] == "authorize_fix"
    assert row["status"] == "enqueued"
    assert row["authorized_by"] == "human:ui"
    assert row["note"] == "why"
    assert "authorized_at" in row


def test_row_is_option_ii_ready_every_spawn_contract_field(tmp_path):
    row = _call(tmp_path)
    contract = row["contract"]
    # Exactly the spawn-contract block, every field non-empty.
    assert set(contract) == SPAWN_CONTRACT_FIELDS
    assert contract["task_statement"] == "fix the over-gate"
    assert isinstance(contract["skill_subset"], list) and contract["skill_subset"]
    assert isinstance(contract["budget"], dict)
    # A real wall-time cap (spawn-contract: a spawn with no budget is forbidden).
    assert contract["budget"]["wall_time_seconds"] > 0
    for field in SPAWN_CONTRACT_FIELDS:
        assert contract[field] not in (None, "", [], {}), field


def test_enqueue_writes_queue_file_not_spawn_ledger(tmp_path):
    # The enqueue is NOT the live run_state/spawn.jsonl ledger.
    queue = tmp_path / "queue.jsonl"
    _call(tmp_path, path=queue)
    assert queue.exists()
    assert "spawn.jsonl" not in queue.name


def test_contract_encodes_merge_gate_and_firewall(tmp_path):
    # The autonomy boundary lives in the row: no merge by the child; dev-time
    # dispatch only (D-014). A future dispatcher inherits these from the row.
    row = _call(tmp_path)
    cap = row["contract"]["authority_cap"].lower()
    gating = row["contract"]["self_gating_rules"].lower()
    assert "merge" in cap and "do not merge" in cap
    assert "dispatch is dev-time" in gating


# ----------------------------------------------------- rejection / rule 4

def test_unknown_ref_rejected_writes_nothing(tmp_path):
    queue = tmp_path / "queue.jsonl"
    with pytest.raises(ValueError, match="resolves to no known"):
        _call(tmp_path, ref_id="F-NOPE", path=queue)
    assert not queue.exists()


def test_empty_ref_rejected(tmp_path):
    queue = tmp_path / "queue.jsonl"
    with pytest.raises(ValueError, match="ref_id"):
        _call(tmp_path, ref_id="   ", path=queue)
    assert not queue.exists()


def test_empty_task_rejected(tmp_path):
    queue = tmp_path / "queue.jsonl"
    with pytest.raises(ValueError, match="task"):
        _call(tmp_path, task="   ", path=queue)
    assert not queue.exists()


def test_empty_note_rejected(tmp_path):
    queue = tmp_path / "queue.jsonl"
    with pytest.raises(ValueError, match="note"):
        _call(tmp_path, note="   ", path=queue)
    assert not queue.exists()


# ------------------------------------------------- resolution surfaces

def test_resolves_via_dev_session_deferral(tmp_path):
    # A ref-id that is a deferral ref_id (not a finding) still resolves.
    defer = tmp_path / "defer.jsonl"
    defer.write_text(json.dumps({"ref_id": "D-7", "status": "open"}) + "\n")
    queue = tmp_path / "queue.jsonl"
    row = _call(tmp_path, ref_id="D-7", path=queue, defer_path=defer)
    assert row["ref_id"] == "D-7"
    assert _rows(queue) == [row]


def test_resolves_via_coordinator_bubble_finding_id(tmp_path):
    # A coordinator bubble carrying the id inside finding_ids resolves it.
    bubbles = tmp_path / "bubbles.jsonl"
    bubbles.write_text(
        json.dumps({"run_id": "r1", "finding_ids": ["B-9"], "note": "n"}) + "\n")
    queue = tmp_path / "queue.jsonl"
    row = _call(tmp_path, ref_id="B-9", path=queue, bubbles_path=bubbles)
    assert row["ref_id"] == "B-9"
    assert _rows(queue) == [row]


# ----------------------------------------------------------------- CLI

def test_cli_enqueue_prints_row(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(authorize_fix, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(authorize_fix, "SURFACED_PATH", _surface(tmp_path))
    monkeypatch.setattr(authorize_fix, "DEFER_PATH", tmp_path / "defer.jsonl")
    monkeypatch.setattr(authorize_fix, "BUBBLES_PATH", tmp_path / "bubbles.jsonl")
    rc = authorize_fix.main([
        "authorize-fix",
        "--ref-id", "F-1", "--task", "fix it", "--note", "because",
        "--by", "human:ui",
    ])
    assert rc == 0
    row = json.loads(capsys.readouterr().out)
    assert row["ref_id"] == "F-1"
    assert set(row["contract"]) == SPAWN_CONTRACT_FIELDS


def test_cli_unknown_ref_nonzero_writes_nothing(tmp_path, monkeypatch, capsys):
    queue = tmp_path / "queue.jsonl"
    monkeypatch.setattr(authorize_fix, "QUEUE_PATH", queue)
    monkeypatch.setattr(authorize_fix, "SURFACED_PATH", _surface(tmp_path))
    monkeypatch.setattr(authorize_fix, "DEFER_PATH", tmp_path / "defer.jsonl")
    monkeypatch.setattr(authorize_fix, "BUBBLES_PATH", tmp_path / "bubbles.jsonl")
    rc = authorize_fix.main([
        "authorize-fix",
        "--ref-id", "F-NOPE", "--task", "fix it", "--note", "because",
    ])
    assert rc == 1
    assert "rejected" in capsys.readouterr().err
    assert not queue.exists()


def test_cli_missing_required_arg_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(authorize_fix, "QUEUE_PATH", tmp_path / "queue.jsonl")
    with pytest.raises(SystemExit) as exc:
        # argparse required= rejects before our validation: exits 2.
        authorize_fix.main(["authorize-fix", "--ref-id", "F-1", "--note", "because"])
    assert exc.value.code not in (0, None)
    assert not (tmp_path / "queue.jsonl").exists()


def test_cli_requires_authorize_fix_subcommand_token(tmp_path, monkeypatch):
    # The documented argv (seam plan / D-046, what the UI execs) carries the
    # `authorize-fix` subcommand token. The bare flat form must be rejected
    # so a UI built against the contract is not silently wrong.
    monkeypatch.setattr(authorize_fix, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(authorize_fix, "SURFACED_PATH", _surface(tmp_path))
    monkeypatch.setattr(authorize_fix, "DEFER_PATH", tmp_path / "defer.jsonl")
    monkeypatch.setattr(authorize_fix, "BUBBLES_PATH", tmp_path / "bubbles.jsonl")
    with pytest.raises(SystemExit) as exc:
        authorize_fix.main(["--ref-id", "F-1", "--task", "t", "--note", "n"])
    assert exc.value.code not in (0, None)
    assert not (tmp_path / "queue.jsonl").exists()
