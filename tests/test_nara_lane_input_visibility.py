"""Input visibility: a plan item may not name an input file its builder cannot read.

Meta-oracle finding, review claude-e347ce59ca643116 (seq 165), severity material.
Plan 2026-09-24 d1 was posted with `notes/research/2026-09-24-g11-candidates/
READING_LIST.md` in `allowed_write_paths` and an objective telling the builder to
copy 19 paper titles from that file. The file exists nowhere: `implement()` creates
the worktree as checkout HEAD plus the acceptance test, and `builder()` reports
`current_contents` only for writable paths. So the builder was instructed to copy
titles from a path it saw as `None` - the invented-citation failure mode dressed up
as an instruction, and the item was posted knowing it (my seq 163 raised the objection).

Two rules close it:

1. `admission()` refuses an item that declares `input_paths` - paths it names as
   inputs to read - unless each one is readable by the builder: present at the
   checkout HEAD, or writable and present in the worktree. The lane holds the item
   before it draws a worktree, so no attempt is burned and no receipt is mislabelled.
2. `builder()` states the verdict in the prompt. A declared input that is absent is
   reported as `NOT PRESENT ... do not copy, quote or invent content for it`, and the
   system prompt carries the rule. Absent today: the builder just gets `None`, which
   a model reads as an empty file.

An item that declares no `input_paths` is admitted and prompted exactly as before.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator import nara_lane as lane

WRITABLE = "notes/research/2026-09-24-g11-candidates/CANDIDATES.md"
ABSENT_INPUT = "notes/research/2026-09-24-g11-candidates/READING_LIST.md"
TRACKED_INPUT = "notes/existing_inputs.md"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


@pytest.fixture
def repo(tmp_path):
    """A checkout whose HEAD tracks one readable input file."""
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "Test")
    tracked = root / TRACKED_INPUT
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("iter-2026-09-23-035 - a stored claim\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root

def _item(**body_over) -> dict:
    body = {
        "title": "d1: draft thesis candidates",
        "objective": "Write CANDIDATES.md; copy the 19 titles from the reading list verbatim.",
        "task_class": "documentation",
        "allowed_write_paths": [WRITABLE],
        "acceptance": {
            "test_path": "tests/test_g11_candidates_shape.py",
            "test_content": "def test_shape():\n    assert False\n",
            "test_argv": ["python", "-m", "pytest", "-q", "tests/test_g11_candidates_shape.py"]},
        "budget": {"attempts": 3, "wall_clock_minutes": 30},
    }
    body.update(body_over)
    return {"msg_id": "oracle-d1-test", "actor": "oracle", "body": body}


# --- rule 1: admission() refuses an item whose declared input is unreadable ----------


def test_item_declaring_no_inputs_is_admitted_as_before(repo, monkeypatch, tmp_path) -> None:
    """No regression: today's posting style (readable content inline in the objective)
    still passes admission, so the new rule only bites items that name a file."""
    monkeypatch.setattr(lane, "ROOT", tmp_path)  # receipts resolve under the redirected ROOT
    sha = lane.test_sha256(_item()["body"]["acceptance"]["test_content"])
    receipt = lane.receipt_path(sha)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({"state": "green", "test_sha256": sha}))
    assert lane.admission(_item()) == []


def test_admission_refuses_an_input_path_that_is_not_at_head(repo) -> None:
    """The seq-165 shape: input_paths names a file that is not committed at HEAD and is
    not writable. `notes/...` is inside the lane fence, so the path fence cannot catch
    this; only a visibility check can."""
    item = _item(input_paths=[ABSENT_INPUT])
    reasons = lane.admission(item, repo_root=repo)
    assert any(ABSENT_INPUT in r and "read" in r.lower() for r in reasons), reasons


def test_admission_accepts_an_input_path_tracked_at_head(repo) -> None:
    reasons = lane.admission(_item(input_paths=[TRACKED_INPUT]), repo_root=repo)
    assert not any("input" in r and TRACKED_INPUT in r for r in reasons), reasons


def test_admission_accepts_a_writable_input_path_that_exists(repo) -> None:
    """An input the builder may also write is visible when it is at HEAD: builder()
    shows current contents for writable paths."""
    (repo / "notes/writable_note.md").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "note")
    item = _item(allowed_write_paths=[WRITABLE, "notes/writable_note.md"],
                 input_paths=["notes/writable_note.md"])
    reasons = lane.admission(item, repo_root=repo)
    assert not any("input" in r and "writable_note" in r for r in reasons), reasons


def test_admission_refuses_an_input_path_outside_the_fence(repo) -> None:
    """A path the lane fence denies is never readable by the sandboxed builder."""
    reasons = lane.admission(_item(input_paths=["run_state/secrets.json"]), repo_root=repo)
    assert any("run_state/secrets.json" in r for r in reasons), reasons


def test_admission_still_refuses_a_non_regular_input(repo) -> None:
    """A declared input that is not a regular file at HEAD (here, a directory) is not
    something builder() can hand over."""
    (repo / "notes/dir_input").mkdir(parents=True, exist_ok=True)
    (repo / "notes/dir_input/inner.md").write_text("inner\n", encoding="utf-8")
    _git(repo, "add", "notes/dir_input/inner.md")
    _git(repo, "commit", "-q", "-m", "directory input")
    reasons = lane.admission(_item(input_paths=["notes/dir_input"]), repo_root=repo)
    assert any("notes/dir_input" in r for r in reasons), reasons


# --- rule 2: builder() tells the model which declared inputs it cannot read ---------


def _call_builder(monkeypatch, body, worktree):
    captured: dict = {}

    def fake_call_sync(messages, **kw):
        captured["messages"] = messages
        return {"completion": json.dumps({"files": {WRITABLE: "# candidates\n"}})}

    import agent_wrapper.wrapper as wrapper

    monkeypatch.setattr(wrapper, "call_sync", fake_call_sync)
    files = lane.builder(body, worktree, "test output", timeout=5)
    return captured, files


def _body(**over) -> dict:
    body = {
        "title": "d1", "objective": "copy the titles from the reading list verbatim",
        "allowed_write_paths": [WRITABLE], "input_paths": [ABSENT_INPUT],
        "acceptance": {"test_path": "tests/test_g11_candidates_shape.py",
                       "test_content": "def test_shape():\n    assert False\n"},
    }
    body.update(over)
    return body


def test_builder_prompt_reports_a_missing_input_as_missing(monkeypatch, tmp_path) -> None:
    captured, files = _call_builder(monkeypatch, _body(), tmp_path)
    assert files == {WRITABLE: "# candidates\n"}
    user = json.loads(captured["messages"][1]["content"])
    verdict = user["input_visibility"][ABSENT_INPUT]
    assert verdict.startswith("NOT PRESENT")
    assert "invent" in verdict, "the verdict must forbid inventing content for a missing input"
    assert "NOT PRESENT" in captured["messages"][0]["content"], (
        "the builder system prompt never states the input-visibility rule")


def test_builder_prompt_marks_a_readable_input_and_shows_it(monkeypatch, tmp_path) -> None:
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "reading.md").write_text("2609.16270 - a stored title\n", encoding="utf-8")
    body = _body(input_paths=["notes/reading.md"], allowed_write_paths=[WRITABLE, "notes/reading.md"])
    captured, _ = _call_builder(monkeypatch, body, tmp_path)
    user = json.loads(captured["messages"][1]["content"])
    assert user["input_visibility"]["notes/reading.md"] == "PRESENT"
    assert user["current_contents"]["notes/reading.md"] == "2609.16270 - a stored title\n"


def test_builder_prompt_unchanged_when_no_inputs_declared(monkeypatch, tmp_path) -> None:
    """Backward compatibility: existing items carry no input_paths, and their prompt,
    including the system message, is byte-for-byte what it is today."""
    captured, files = _call_builder(monkeypatch, _body(input_paths=[]), tmp_path)
    assert files == {WRITABLE: "# candidates\n"}
    assert "input_visibility" not in json.loads(captured["messages"][1]["content"])
    assert captured["messages"][0]["content"] == (
        "You are Nara's builder for the lab. Make the acceptance test pass by writing complete file "
        "contents. Reply with ONLY a JSON object {\"files\": {\"<path>\": \"<full content>\"}} using only "
        "the writable_paths. Never modify the acceptance test. Standard library only unless the file "
        "already imports something else.")


def test_builder_prompt_reports_a_missing_input_that_is_also_writable(monkeypatch, tmp_path) -> None:
    """A writable path the builder must not write blind: a declared input that is absent
    is reported missing even when it is in allowed_write_paths - the seq-165 posting
    asked for exactly this combination."""
    body = _body(allowed_write_paths=[WRITABLE, ABSENT_INPUT])
    captured, _ = _call_builder(monkeypatch, body, tmp_path)
    user = json.loads(captured["messages"][1]["content"])
    assert user["current_contents"][ABSENT_INPUT] is None
    assert user["input_visibility"][ABSENT_INPUT].startswith("NOT PRESENT")
