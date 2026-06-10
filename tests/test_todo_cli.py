"""orchestrator/todo_cli.py — bubble acks + dev-session deferrals (D-046).

Mirrors test discipline from gate_cli: validate-then-append, rejections
exit nonzero and write NOTHING, append-only fold semantics.
"""
import json

import pytest

from orchestrator import todo_cli


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


# ---------------------------------------------------------------- ack

def test_ack_appends_join_key_row(tmp_path):
    path = tmp_path / "acks.jsonl"
    row = todo_cli.ack("bubble-42", "seen it", "human:ui", path=path)
    assert _rows(path) == [row]
    # The exact join key ui/backend/human_todo.py reads.
    assert row["bubble_run_id"] == "bubble-42"
    assert row["ack_by"] == "human:ui"
    assert row["note"] == "seen it"
    assert "acked_at" in row


def test_ack_rejects_empty_id(tmp_path):
    path = tmp_path / "acks.jsonl"
    with pytest.raises(ValueError):
        todo_cli.ack("  ", path=path)
    assert not path.exists()


# -------------------------------------------------------------- defer

def test_defer_appends_open_row(tmp_path):
    path = tmp_path / "queue.jsonl"
    row = todo_cli.defer(
        "stale_active_run", "active_run", "needs a process autopsy",
        "human:ui", path=path,
    )
    assert row["status"] == "open"
    assert row["kind"] == "stale_active_run"
    assert row["attested_by"] == "human:ui"
    assert _rows(path) == [row]


def test_defer_rejects_out_of_enum_kind(tmp_path):
    path = tmp_path / "queue.jsonl"
    with pytest.raises(ValueError, match="kind"):
        todo_cli.defer("nonsense_kind", "x", "why", path=path)
    assert not path.exists()


def test_defer_requires_note(tmp_path):
    path = tmp_path / "queue.jsonl"
    with pytest.raises(ValueError, match="note"):
        todo_cli.defer("gate_verdict", "iter-2026-06-05-002", "   ", path=path)
    assert not path.exists()


# ------------------------------------------------- list-deferred / close

def test_fold_last_status_wins(tmp_path):
    path = tmp_path / "queue.jsonl"
    todo_cli.defer("gate_verdict", "iter-A", "review me", path=path)
    todo_cli.defer("bubble_ack", "bubble-B", "needs discussion", path=path)
    assert [r["ref_id"] for r in todo_cli.list_deferred(path=path)] == [
        "iter-A", "bubble-B",
    ]

    todo_cli.close("iter-A", "handled in session", "human", path=path)
    assert [r["ref_id"] for r in todo_cli.list_deferred(path=path)] == [
        "bubble-B",
    ]
    # Append-only: 3 rows on disk, open row untouched.
    assert len(_rows(path)) == 3


def test_close_unknown_ref_rejected(tmp_path):
    path = tmp_path / "queue.jsonl"
    todo_cli.defer("gate_verdict", "iter-A", "review me", path=path)
    with pytest.raises(ValueError, match="no open deferral"):
        todo_cli.close("iter-ZZZ", path=path)
    assert len(_rows(path)) == 1  # nothing written


def test_reopen_after_close(tmp_path):
    path = tmp_path / "queue.jsonl"
    todo_cli.defer("gate_verdict", "iter-A", "review me", path=path)
    todo_cli.close("iter-A", path=path)
    todo_cli.defer("gate_verdict", "iter-A", "regressed; review again",
                   path=path)
    open_rows = todo_cli.list_deferred(path=path)
    assert len(open_rows) == 1
    assert open_rows[0]["note"] == "regressed; review again"


# ----------------------------------------------------------------- CLI

def test_cli_defer_and_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(todo_cli, "QUEUE_PATH", tmp_path / "queue.jsonl")
    rc = todo_cli.main([
        "defer", "--kind", "gate_verdict", "--ref-id", "iter-X",
        "--note", "deep journal read needed", "--by", "human:ui",
    ])
    assert rc == 0
    row = json.loads(capsys.readouterr().out)
    assert row["ref_id"] == "iter-X"

    rc = todo_cli.main(["list-deferred"])
    assert rc == 0
    listed = json.loads(capsys.readouterr().out)
    assert [r["ref_id"] for r in listed] == ["iter-X"]


def test_cli_rejects_bad_kind_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(todo_cli, "QUEUE_PATH", tmp_path / "queue.jsonl")
    with pytest.raises(SystemExit) as exc:
        # argparse choices= rejects before our validation: exits 2.
        todo_cli.main([
            "defer", "--kind", "bogus", "--ref-id", "x", "--note", "y",
        ])
    assert exc.value.code not in (0, None)
    assert not (tmp_path / "queue.jsonl").exists()


def test_cli_ack(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(todo_cli, "ACKS_PATH", tmp_path / "acks.jsonl")
    rc = todo_cli.main([
        "ack", "--bubble-run-id", "bubble-7", "--by", "human:ui",
    ])
    assert rc == 0
    row = json.loads(capsys.readouterr().out)
    assert row["bubble_run_id"] == "bubble-7"
