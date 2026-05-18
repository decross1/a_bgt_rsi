"""Incremental tailer: reads only new complete lines, survives truncation."""
import json

from backend.tailer import JsonlTailer


def test_reads_only_new_complete_lines(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n" + json.dumps({"n": 2}) + "\n")
    tailer = JsonlTailer(path)
    assert [r["n"] for r in tailer.read_new()] == [1, 2]
    assert tailer.read_new() == []                       # nothing new

    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"n": 3}) + "\n")
    assert [r["n"] for r in tailer.read_new()] == [3]


def test_partial_line_held_back(tmp_path):
    path = tmp_path / "b.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n")
    tailer = JsonlTailer(path)
    assert [r["n"] for r in tailer.read_new()] == [1]

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
    tailer.read_new()
    path.write_text(json.dumps({"n": 99}) + "\n")        # shorter -> looks truncated
    assert [r["n"] for r in tailer.read_new()] == [99]


def test_missing_file_is_empty(tmp_path):
    assert JsonlTailer(tmp_path / "nope.jsonl").read_new() == []


def test_malformed_line_skipped(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text(json.dumps({"n": 1}) + "\n" + "{not json}\n"
                    + json.dumps({"n": 2}) + "\n")
    assert [r["n"] for r in JsonlTailer(path).read_new()] == [1, 2]
