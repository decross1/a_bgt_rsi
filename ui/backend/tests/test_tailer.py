"""Incremental tailer: forward-only by default (first attach = EOF, never a
replay of a giant pre-existing file — the 6.5GB /api/health hang fix,
2026-08-15), with an explicit replay=True opt-in for index-building consumers
(chain.LogStore). Survives truncation; holds back partial lines."""
import json

from backend.tailer import JsonlTailer


# ─── first-attach regression (the 2026-08-15 /api/health hang) ───────────


def test_first_attach_skips_preexisting_content(tmp_path):
    # A big pre-existing file must NOT be parsed on first read — the first
    # read_new attaches at EOF and returns []; only lines appended AFTER the
    # attach come back. (Before the fix, a restart re-parsed the whole file —
    # 6.5GB of telemetry hung /api/health.)
    path = tmp_path / "big.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for n in range(10_000):                       # stands in for the 6.5GB
            fh.write(json.dumps({"n": n}) + "\n")
    tailer = JsonlTailer(path)
    assert tailer.read_new() == []                    # attach only — no replay

    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"n": "fresh"}) + "\n")
    assert [r["n"] for r in tailer.read_new()] == ["fresh"]


def test_first_attach_on_missing_file_then_created(tmp_path):
    # Attaching before the file exists: everything later written IS new.
    path = tmp_path / "later.jsonl"
    tailer = JsonlTailer(path)
    assert tailer.read_new() == []                    # attach at offset 0
    path.write_text(json.dumps({"n": 1}) + "\n")
    assert [r["n"] for r in tailer.read_new()] == [1]


def test_replay_opt_in_reads_history_first(tmp_path):
    # chain.LogStore's contract: replay=True keeps the from-byte-0 first read
    # (its in-memory index IS the file history).
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n" + json.dumps({"n": 2}) + "\n")
    tailer = JsonlTailer(path, replay=True)
    assert [r["n"] for r in tailer.read_new()] == [1, 2]
    assert tailer.read_new() == []                       # nothing new

    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"n": 3}) + "\n")
    assert [r["n"] for r in tailer.read_new()] == [3]


# ─── incremental semantics (post-attach) ─────────────────────────────────


def test_reads_only_new_complete_lines_after_attach(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n")
    tailer = JsonlTailer(path)
    assert tailer.read_new() == []                       # attach
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"n": 2}) + "\n" + json.dumps({"n": 3}) + "\n")
    assert [r["n"] for r in tailer.read_new()] == [2, 3]
    assert tailer.read_new() == []                       # nothing new


def test_partial_line_held_back(tmp_path):
    path = tmp_path / "b.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n")
    tailer = JsonlTailer(path)
    tailer.read_new()                                    # attach at EOF

    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"n": 2')                              # no newline yet
    assert tailer.read_new() == []                       # held back
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("}\n")                                  # completes the line
    assert [r["n"] for r in tailer.read_new()] == [2]


def test_truncation_resets(tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n" + json.dumps({"n": 2}) + "\n")
    tailer = JsonlTailer(path)
    tailer.read_new()                                    # attach at EOF
    path.write_text(json.dumps({"n": 99}) + "\n")        # shorter -> looks truncated
    assert [r["n"] for r in tailer.read_new()] == [99]


def test_missing_file_is_empty(tmp_path):
    assert JsonlTailer(tmp_path / "nope.jsonl").read_new() == []


def test_malformed_line_skipped(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n" + "{not json}\n"
                    + json.dumps({"n": 2}) + "\n")
    assert [r["n"] for r in JsonlTailer(path, replay=True).read_new()] == [1, 2]


def test_seek_to_end_still_attaches_explicitly(tmp_path):
    # The websocket path calls seek_to_end() up front; it must keep working
    # (and now simply performs the attach the default read would do anyway).
    path = tmp_path / "e.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n")
    tailer = JsonlTailer(path)
    tailer.seek_to_end()
    assert tailer.read_new() == []
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"n": 2}) + "\n")
    assert [r["n"] for r in tailer.read_new()] == [2]


def test_reset_replays_from_start(tmp_path):
    path = tmp_path / "f.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n")
    tailer = JsonlTailer(path)
    tailer.read_new()                                    # attach at EOF
    tailer.reset()                                       # explicit replay
    assert [r["n"] for r in tailer.read_new()] == [1]
